"""Emailed one-time codes as an optional second sign-in step. See docs/MFA_DESIGN.md (stage 7).

Weaker than an authenticator app or passkey: whoever controls the mailbox and knows the password
can sign in. So it is off unless the operator enables it, each user must opt in from Security (after
the authenticator app and recovery codes exist), and it never bypasses the account lockout.

Only the database state and the rules live here; HTTP is in ``email_code_views``. Codes are six
digits, stored as a salted keyed hash, valid 10 minutes, single use, with 5 guesses per code, a
60-second resend cooldown and at most 5 emails an hour per account.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from .models import EmailCode, MfaDevice

CODE_TTL = timedelta(minutes=10)
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_SENDS_PER_HOUR = 5
MAX_ATTEMPTS_PER_CODE = 5


class EmailCodeError(Exception):
    code = "email_code_error"


class Unavailable(EmailCodeError):
    code = "email_codes_unavailable"


class NotEnabled(EmailCodeError):
    code = "email_codes_not_enabled"


class NoAddress(EmailCodeError):
    code = "email_address_missing"


class SendFailed(EmailCodeError):
    code = "email_code_send_failed"


class InvalidCode(EmailCodeError):
    code = "email_code_invalid"


class Locked(EmailCodeError):
    code = "mfa_locked"


class TooSoon(EmailCodeError):
    code = "email_code_wait"

    def __init__(self, retry_after: int):
        super().__init__(retry_after)
        self.retry_after = max(1, int(retry_after))


def available() -> bool:
    return bool(getattr(settings, "MFA_EMAIL_CODES_ENABLED", False) and getattr(settings, "MFA_EMAIL_FROM", ""))


def has_email_codes(user) -> bool:
    return available() and MfaDevice.objects.filter(
        user=user, confirmed_at__isnull=False).exclude(email_codes_address="").exists()


def mask(address: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if local and domain else "***"


def _digest(salt: str, code: str) -> str:
    key = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(key, f"{salt}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def _normalize(code: str) -> str:
    return "".join(str(code).split())


def _send(device: MfaDevice, purpose: str, address: str) -> None:
    """Create a fresh code and email it. Enforces cooldown and the hourly cap per account."""
    now = timezone.now()
    with transaction.atomic():
        MfaDevice.objects.select_for_update().get(pk=device.pk)  # serialises sends per account
        recent = EmailCode.objects.filter(device=device, created_at__gt=now - timedelta(hours=1))
        latest = recent.order_by("-created_at").first()
        if latest is not None and now - latest.created_at < RESEND_COOLDOWN:
            raise TooSoon((RESEND_COOLDOWN - (now - latest.created_at)).total_seconds())
        if recent.count() >= MAX_SENDS_PER_HOUR:
            oldest = recent.order_by("created_at").first()
            raise TooSoon((timedelta(hours=1) - (now - oldest.created_at)).total_seconds())
        EmailCode.objects.filter(device=device, purpose=purpose, used_at__isnull=True).update(used_at=now)
        code = f"{secrets.randbelow(10**6):06d}"
        salt = secrets.token_hex(8)
        row = EmailCode.objects.create(
            device=device, purpose=purpose, address=address,
            code_hash=f"{salt}${_digest(salt, code)}", expires_at=now + CODE_TTL,
        )
    body = (
        f"Your {settings.MFA_ISSUER} verification code is {code}.\n\n"
        f"It expires in {int(CODE_TTL.total_seconds() // 60)} minutes and works once.\n\n"
        "If you did not just try to sign in or change your security settings, someone may know your "
        "password. Do not share this code, and change your password."
    )
    try:
        EmailMessage(f"Your {settings.MFA_ISSUER} verification code", body, settings.MFA_EMAIL_FROM, [address]).send()
    except Exception as error:  # SMTP, DNS, misconfiguration: never leave a usable unsent code
        row.delete()
        raise SendFailed() from error


def _check(device_id: int, purpose: str, code: str, *, lockout: bool):
    """Decide and persist atomically; returns (outcome, row). Rejections are returned, not raised,
    so failure counters commit (raising inside the transaction would roll them back)."""
    now = timezone.now()
    normalized = _normalize(code)
    with transaction.atomic():
        device = MfaDevice.objects.select_for_update().get(pk=device_id)
        if lockout and device.locked_at is not None:
            return "locked", None
        row = (EmailCode.objects.select_for_update()
               .filter(device=device, purpose=purpose, used_at__isnull=True, expires_at__gt=now)
               .order_by("-created_at").first())
        matched = False
        if row is not None:
            row.attempts += 1
            salt, _, stored = row.code_hash.partition("$")
            if (row.attempts <= MAX_ATTEMPTS_PER_CODE and len(normalized) == 6 and normalized.isdigit()
                    and hmac.compare_digest(stored, _digest(salt, normalized))):
                matched = True
                row.used_at = now
            elif row.attempts >= MAX_ATTEMPTS_PER_CODE:
                row.used_at = now  # burned: request a new code
            row.save()
        if matched:
            if lockout and device.failed_attempts:
                device.failed_attempts = 0
                device.save(update_fields=["failed_attempts"])
            return "ok", row
        if lockout:
            device.failed_attempts += 1
            if device.failed_attempts >= settings.MFA_LOCKOUT_THRESHOLD:
                device.locked_at = now
            device.save(update_fields=["failed_attempts", "locked_at"])
        return "invalid", None


# --- turning it on and off (verified session) ----------------------------------------------

def begin_enable(user, device: MfaDevice) -> str:
    """Email a confirmation code to the account's address; returns that address, masked."""
    if not available():
        raise Unavailable()
    address = (user.email or "").strip()
    try:
        validate_email(address)
    except ValidationError:
        raise NoAddress() from None
    _send(device, EmailCode.PURPOSE_ENABLE, address)
    return mask(address)


def confirm_enable(device: MfaDevice, code: str) -> str:
    if not available():
        raise Unavailable()
    outcome, row = _check(device.pk, EmailCode.PURPOSE_ENABLE, code, lockout=False)
    if outcome != "ok":
        raise InvalidCode()
    MfaDevice.objects.filter(pk=device.pk).update(email_codes_address=row.address)
    return mask(row.address)


def pending_enable_address(device: MfaDevice) -> str | None:
    """Masked address of an unexpired, unused confirmation code, so a screen reload keeps the step."""
    row = (EmailCode.objects.filter(device=device, purpose=EmailCode.PURPOSE_ENABLE, used_at__isnull=True,
                                    expires_at__gt=timezone.now(), attempts__lt=MAX_ATTEMPTS_PER_CODE)
           .order_by("-created_at").first())
    return mask(row.address) if row else None


def disable(device: MfaDevice) -> None:
    MfaDevice.objects.filter(pk=device.pk).update(email_codes_address="")
    EmailCode.objects.filter(device=device).delete()


# --- second sign-in step (pending login) ----------------------------------------------------

def send_signin_code(device: MfaDevice) -> str:
    if not available():
        raise Unavailable()
    device.refresh_from_db()
    if not device.email_codes_address:
        raise NotEnabled()
    _send(device, EmailCode.PURPOSE_SIGNIN, device.email_codes_address)
    return mask(device.email_codes_address)


def verify_signin_code(device: MfaDevice, code: str) -> None:
    """Raises NotEnabled, Locked or InvalidCode. A wrong code counts toward the account lockout."""
    if not available():
        raise Unavailable()
    device.refresh_from_db()
    if not device.email_codes_address:
        raise NotEnabled()
    outcome, _row = _check(device.pk, EmailCode.PURPOSE_SIGNIN, code, lockout=True)
    if outcome == "locked":
        raise Locked()
    if outcome != "ok":
        raise InvalidCode()
