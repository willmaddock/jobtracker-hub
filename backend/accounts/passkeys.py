"""WebAuthn passkeys as a second sign-in step. See docs/MFA_DESIGN.md.

All use of the ``webauthn`` library (py_webauthn) is confined to this module so the rest of the
code never touches it. Challenges live in the server-side session, are single-use and expire
after five minutes. User verification (Face ID, Touch ID, device PIN) is always required, which
is what makes a passkey a real second factor rather than mere possession.
"""
from __future__ import annotations

import json
import time

from django.conf import settings
from django.utils import timezone

from .models import PasskeyCredential

CHALLENGE_KEY = "webauthn_challenge"
CHALLENGE_TTL_SECONDS = 300
MAX_PASSKEYS_PER_DEVICE = 10


class PasskeyError(Exception):
    code = "passkey_error"


class Unavailable(PasskeyError):
    code = "passkeys_unavailable"


class NoPasskeys(PasskeyError):
    code = "passkey_not_registered"


class ChallengeInvalid(PasskeyError):
    code = "passkey_challenge_invalid"


class InvalidCredential(PasskeyError):
    code = "passkey_invalid"


class TooMany(PasskeyError):
    code = "passkey_limit_reached"


def available() -> bool:
    return bool(settings.WEBAUTHN_RP_ID and settings.WEBAUTHN_ORIGIN)


def has_passkeys(user) -> bool:
    return available() and PasskeyCredential.objects.filter(
        device__user=user, device__confirmed_at__isnull=False
    ).exists()


# --- challenge bookkeeping (session, single use) -------------------------------------------

def _store(request, kind: str, challenge: bytes) -> None:
    from webauthn.helpers import bytes_to_base64url

    request.session[CHALLENGE_KEY] = {"kind": kind, "c": bytes_to_base64url(challenge), "ts": int(time.time())}


def _take(request, kind: str) -> bytes:
    """Remove and return the pending challenge of this kind, or refuse. Never reusable."""
    from webauthn.helpers import base64url_to_bytes

    data = request.session.pop(CHALLENGE_KEY, None)
    try:
        if not isinstance(data, dict) or data.get("kind") != kind:
            raise ChallengeInvalid()
        if time.time() - int(data["ts"]) > CHALLENGE_TTL_SECONDS:
            raise ChallengeInvalid()
        return base64url_to_bytes(data["c"])
    except (KeyError, TypeError, ValueError):
        raise ChallengeInvalid() from None


# --- the only functions that call the library ----------------------------------------------

def _library_errors():
    from webauthn.helpers.exceptions import (
        InvalidAuthenticationResponse, InvalidJSONStructure, InvalidRegistrationResponse,
    )
    return (InvalidRegistrationResponse, InvalidAuthenticationResponse, InvalidJSONStructure, ValueError, KeyError)


def _verify_registration(*, credential, challenge):
    from webauthn import verify_registration_response

    try:
        return verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            require_user_verification=True,
        )
    except _library_errors():
        raise InvalidCredential() from None


def _verify_authentication(*, credential, challenge, public_key, sign_count):
    from webauthn import verify_authentication_response

    try:
        return verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=public_key,
            credential_current_sign_count=sign_count,
            require_user_verification=True,
        )
    except _library_errors():
        raise InvalidCredential() from None


# --- public operations ---------------------------------------------------------------------

def registration_options(request, device) -> dict:
    if not available():
        raise Unavailable()
    if device.passkeys.count() >= MAX_PASSKEYS_PER_DEVICE:
        raise TooMany()
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor, ResidentKeyRequirement,
        UserVerificationRequirement,
    )

    user = device.user
    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=f"jth-{user.pk}".encode("ascii"),  # opaque handle, not the username
        user_name=user.get_username(),
        user_display_name=user.get_username(),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id)) for c in device.passkeys.all()
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    _store(request, "register", options.challenge)
    return json.loads(options_to_json(options))


def register(request, device, credential: dict, name: str) -> PasskeyCredential:
    if not available():
        raise Unavailable()
    from webauthn.helpers import bytes_to_base64url

    challenge = _take(request, "register")
    verified = _verify_registration(credential=credential, challenge=challenge)
    credential_id = bytes_to_base64url(verified.credential_id)
    if PasskeyCredential.objects.filter(credential_id=credential_id).exists():
        raise InvalidCredential()
    return PasskeyCredential.objects.create(
        device=device,
        credential_id=credential_id,
        public_key=bytes(verified.credential_public_key),
        sign_count=verified.sign_count,
        name=(name or "").strip()[:80] or "Passkey",
    )


def authentication_options(request, device) -> dict:
    if not available():
        raise Unavailable()
    rows = list(device.passkeys.all())
    if not rows:
        raise NoPasskeys()
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement

    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(r.credential_id)) for r in rows],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _store(request, "authenticate", options.challenge)
    return json.loads(options_to_json(options))


def authenticate(request, device, credential: dict) -> PasskeyCredential:
    if not available():
        raise Unavailable()
    challenge = _take(request, "authenticate")
    credential_id = credential.get("id")
    row = device.passkeys.filter(credential_id=credential_id).first() if isinstance(credential_id, str) else None
    if row is None:
        raise InvalidCredential()
    verified = _verify_authentication(
        credential=credential, challenge=challenge, public_key=bytes(row.public_key), sign_count=row.sign_count,
    )
    row.sign_count = verified.new_sign_count
    row.last_used_at = timezone.now()
    row.save(update_fields=["sign_count", "last_used_at"])
    return row
