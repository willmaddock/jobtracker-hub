"""Passwordless sign-in and sign-up with an emailed one-time code. See docs/MFA_DESIGN.md (stage 8).

This is the *primary* way in (it replaces the password), unlike ``email_codes`` which is an optional
second step. Rules, all deliberate:

* Off unless ``EMAIL_SIGNIN_ENABLED`` and a sender (``MFA_EMAIL_FROM``) are configured.
* The answer to "send me a code" is identical whether or not an account exists, and the resend
  cooldown behaves identically too, so the form cannot be used to discover who has an account.
* An account that already has an authenticator app still has to pass it: a mailbox alone never
  downgrades an enrolled account (``email_signin_views`` starts the usual pending-MFA step).
* Staff and superuser accounts without an authenticator cannot use it at all.
* Brand-new accounts are created only when ``EMAIL_SIGNUP_OPEN`` is true.
* Codes are six digits, stored as a salted keyed hash, valid 10 minutes, single use, 5 guesses each,
  a 60-second resend cooldown and at most 5 emails an hour per address.
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
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import mfa
from .models import SignInCode, User, Workspace

CODE_TTL = timedelta(minutes=10)
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_SENDS_PER_HOUR = 5
MAX_ATTEMPTS_PER_CODE = 5
KEEP_ROWS_FOR = timedelta(days=1)
MAX_ADDRESS_LENGTH = 150  # the username column is 150 characters and new accounts use the address
DEFAULT_WORKSPACE_NAME = "My job search"


class SignInError(Exception):
    code = "email_signin_error"


class Unavailable(SignInError):
    code = "email_signin_unavailable"


class InvalidAddress(SignInError):
    code = "email_invalid"


class SendFailed(SignInError):
    code = "email_code_send_failed"


class InvalidCode(SignInError):
    code = "email_code_invalid"


class TooSoon(SignInError):
    code = "email_code_wait"

    def __init__(self, retry_after: float):
        super().__init__(retry_after)
        self.retry_after = max(1, int(retry_after))


def available() -> bool:
    return bool(getattr(settings, "EMAIL_SIGNIN_ENABLED", False) and getattr(settings, "MFA_EMAIL_FROM", ""))


def signup_open() -> bool:
    return available() and bool(getattr(settings, "EMAIL_SIGNUP_OPEN", False))


def normalize_address(raw: str) -> str:
    address = str(raw or "").strip().lower()
    try:
        validate_email(address)
    except ValidationError:
        raise InvalidAddress() from None
    if len(address) > MAX_ADDRESS_LENGTH:
        raise InvalidAddress()
    return address


def _digest(salt: str, code: str) -> str:
    key = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(key, f"signin:{salt}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def _normalize_code(code: str) -> str:
    return "".join(str(code).split())


def lookup(address: str):
    """Who this address would sign in as: ("existing", user), ("new", None) or ("blocked", None)."""
    users = list(User.objects.filter(email__iexact=address)[:2])
    if len(users) > 1:
        return "blocked", None  # ambiguous: an operator must sort it out, never guess
    if users:
        user = users[0]
        if not user.is_active:
            return "blocked", None
        if (user.is_staff or user.is_superuser) and not mfa.is_enrolled(user):
            return "blocked", None
        return "existing", user
    if not signup_open():
        return "blocked", None
    if User.objects.filter(username__iexact=address).exists():
        return "blocked", None
    return "new", None


def request_code(address: str) -> None:
    """Email a code if this address may sign in. Silent (and cooldown-identical) if it may not."""
    if not available():
        raise Unavailable()
    address = normalize_address(address)
    state, _user = lookup(address)
    deliverable = state != "blocked"
    now = timezone.now()
    code = f"{secrets.randbelow(10**6):06d}"
    salt = secrets.token_hex(8)
    with transaction.atomic():
        SignInCode.objects.filter(created_at__lt=now - KEEP_ROWS_FOR).delete()
        recent = SignInCode.objects.select_for_update().filter(address=address, created_at__gt=now - timedelta(hours=1))
        rows = list(recent.order_by("-created_at"))
        if rows and now - rows[0].created_at < RESEND_COOLDOWN:
            raise TooSoon((RESEND_COOLDOWN - (now - rows[0].created_at)).total_seconds())
        if len(rows) >= MAX_SENDS_PER_HOUR:
            raise TooSoon((timedelta(hours=1) - (now - rows[-1].created_at)).total_seconds())
        SignInCode.objects.filter(address=address, used_at__isnull=True).update(used_at=now)
        # An address that may not sign in still gets a (used) row, so the cooldown looks the same.
        row = SignInCode.objects.create(
            address=address, code_hash=f"{salt}${_digest(salt, code)}", expires_at=now + CODE_TTL,
            used_at=None if deliverable else now,
        )
    if not deliverable:
        return
    body = (
        f"Your {settings.MFA_ISSUER} sign-in code is {code}.\n\n"
        f"It expires in {int(CODE_TTL.total_seconds() // 60)} minutes and works once.\n\n"
        "If you did not just try to sign in, you can ignore this email. Do not share this code."
    )
    try:
        EmailMessage(f"Your {settings.MFA_ISSUER} sign-in code", body, settings.MFA_EMAIL_FROM, [address]).send()
    except Exception as error:  # SMTP, DNS, misconfiguration: never leave a usable unsent code
        row.delete()
        raise SendFailed() from error


def _check(address: str, code: str) -> bool:
    """Decide and persist atomically. Rejections are returned, not raised, so counters commit."""
    now = timezone.now()
    normalized = _normalize_code(code)
    with transaction.atomic():
        row = (SignInCode.objects.select_for_update()
               .filter(address=address, used_at__isnull=True, expires_at__gt=now)
               .order_by("-created_at").first())
        if row is None:
            return False
        row.attempts += 1
        salt, _, stored = row.code_hash.partition("$")
        matched = (row.attempts <= MAX_ATTEMPTS_PER_CODE and len(normalized) == 6 and normalized.isdigit()
                   and hmac.compare_digest(stored, _digest(salt, normalized)))
        if matched or row.attempts >= MAX_ATTEMPTS_PER_CODE:
            row.used_at = now  # used, or burned: request a new code
        row.save()
        return matched


def verify_code(address: str, code: str):
    """Returns (user, created). Raises Unavailable, InvalidAddress or InvalidCode."""
    if not available():
        raise Unavailable()
    address = normalize_address(address)
    if not _check(address, code):
        raise InvalidCode()
    state, user = lookup(address)
    if state == "blocked":
        raise InvalidCode()
    if state == "existing":
        return user, False
    try:
        with transaction.atomic():
            user = User(username=address, email=address)
            user.set_unusable_password()
            user.save()
            Workspace.objects.create(owner=user, name=DEFAULT_WORKSPACE_NAME)
    except IntegrityError:
        raise InvalidCode() from None
    return user, True
