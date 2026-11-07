"""MFA enrolment and verification on top of accounts.totp. See docs/MFA_DESIGN.md.

HTTP, sessions and throttling are not handled here: this module only owns the database
state (encrypted secret, replay step, failure counter, recovery codes) and the rules.
Time is injectable (``now`` is epoch seconds) so tests are deterministic.
"""
from __future__ import annotations

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import totp
from .models import MfaDevice, MfaRecoveryCode


class MfaError(Exception):
    code = "mfa_error"


class AlreadyEnrolled(MfaError):
    code = "mfa_already_enrolled"


class NotEnrolled(MfaError):
    code = "mfa_not_enrolled"


class InvalidCode(MfaError):
    code = "mfa_invalid_code"


class Locked(MfaError):
    code = "mfa_locked"


def _fernet() -> Fernet:
    return Fernet(settings.MFA_ENCRYPTION_KEY.encode("ascii"))


def _secret_of(device: MfaDevice) -> str:
    return _fernet().decrypt(device.secret_encrypted.encode("ascii")).decode("ascii")


def is_enrolled(user) -> bool:
    return MfaDevice.objects.filter(user=user, confirmed_at__isnull=False).exists()


@transaction.atomic
def begin_enrollment(user) -> tuple[str, str]:
    """Start (or restart an unconfirmed) enrolment; returns (secret, otpauth URI).

    The secret is returned to the caller once, to render a QR code, and is otherwise
    only ever stored encrypted. A confirmed enrolment can only be replaced after an
    operator reset, never silently overwritten here.
    """
    device = MfaDevice.objects.select_for_update().filter(user=user).first()
    if device is not None and device.confirmed_at is not None:
        raise AlreadyEnrolled()
    secret = totp.generate_secret()
    if device is None:
        device = MfaDevice(user=user)
    device.secret_encrypted = _fernet().encrypt(secret.encode("ascii")).decode("ascii")
    device.last_used_step = None
    device.failed_attempts = 0
    device.locked_at = None
    device.save()
    return secret, totp.provisioning_uri(secret, user.get_username(), settings.MFA_ISSUER)


def confirm_enrollment(user, code: str, *, now: float | None = None) -> list[str]:
    """Verify the first code from the user's app; returns the recovery codes (shown once)."""
    with transaction.atomic():
        device = MfaDevice.objects.select_for_update().filter(user=user).first()
        if device is None:
            raise NotEnrolled()
        if device.confirmed_at is not None:
            raise AlreadyEnrolled()
        step = totp.verify_totp(_secret_of(device), code, now=now)
        if step is None:
            invalid = True
        else:
            invalid = False
            device.confirmed_at = timezone.now()
            device.last_used_step = step
            device.save()
            plaintext = totp.generate_recovery_codes()
            device.recovery_codes.all().delete()
            MfaRecoveryCode.objects.bulk_create(
                [MfaRecoveryCode(device=device, code_hash=totp.hash_recovery_code(c)) for c in plaintext]
            )
    if invalid:
        raise InvalidCode()
    return plaintext


def _looks_like_recovery_code(code: str) -> bool:
    normalized = totp.normalize_recovery_code(code)
    return len(normalized) == totp.RECOVERY_CODE_LENGTH and all(c in totp.RECOVERY_ALPHABET for c in normalized)


def _attempt(user, code: str, now: float | None) -> str:
    """Decide and persist the outcome atomically; never raises for a rejected code.

    Failure bookkeeping must commit, so rejections are returned as outcomes and raised by
    the caller after this transaction ends (raising inside would roll the counter back).
    """
    with transaction.atomic():
        device = MfaDevice.objects.select_for_update().filter(user=user, confirmed_at__isnull=False).first()
        if device is None:
            return "not_enrolled"
        if device.locked_at is not None:
            return "locked"
        step = totp.verify_totp(_secret_of(device), code, now=now, last_used_step=device.last_used_step)
        if step is not None:
            device.last_used_step = step
            device.failed_attempts = 0
            device.save()
            return "totp"
        if isinstance(code, str) and _looks_like_recovery_code(code):
            for recovery in device.recovery_codes.filter(used_at__isnull=True):
                if totp.check_recovery_code(code, recovery.code_hash):
                    recovery.used_at = timezone.now()
                    recovery.save()
                    device.failed_attempts = 0
                    device.save()
                    return "recovery"
        device.failed_attempts += 1
        if device.failed_attempts >= settings.MFA_LOCKOUT_THRESHOLD:
            device.locked_at = timezone.now()
        device.save()
        return "invalid"


def verify_code(user, code: str, *, now: float | None = None) -> str:
    """Accept an authenticator code or an unused recovery code.

    Returns ``"totp"`` or ``"recovery"``; raises NotEnrolled, Locked or InvalidCode.
    A locked account refuses even correct codes until an operator calls ``reset``.
    """
    outcome = _attempt(user, code, now)
    if outcome in ("totp", "recovery"):
        return outcome
    raise {"not_enrolled": NotEnrolled, "locked": Locked}.get(outcome, InvalidCode)()


def remaining_recovery_codes(user) -> int:
    return MfaRecoveryCode.objects.filter(device__user=user, used_at__isnull=True).count()


def reset(user) -> None:
    """Operator action: remove the enrolment entirely (user must enrol again)."""
    MfaDevice.objects.filter(user=user).delete()
