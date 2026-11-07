"""One-time-code primitives for MFA: TOTP (RFC 6238 over RFC 4226) and recovery codes.

Standard library only, no Django import, no I/O: every function is deterministic given its
inputs (time is passed in), so it is testable in isolation. Storage, encryption at rest,
throttling and the login flow live elsewhere (docs/MFA_DESIGN.md).

Parameters are the authenticator-app defaults (SHA-1, 6 digits, 30 s) because Google
Authenticator, Authy, 1Password, Apple Passwords etc. all support exactly these.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
STEP_SECONDS = 30
WINDOW = 1  # accept the previous, current and next step: tolerates clock drift
SECRET_BYTES = 20  # 160 bits, the RFC 4226 recommendation

RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0 or 1
RECOVERY_CODE_LENGTH = 10  # 10 characters of 32 symbols = 50 bits
RECOVERY_CODE_COUNT = 10
_PBKDF2_ITERATIONS = 120_000


def generate_secret() -> str:
    """A new random TOTP secret as unpadded base32 (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    cleaned = secret.replace(" ", "").upper()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def _hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % (10 ** digits)).zfill(digits)


def totp_at(secret: str, for_time: float, digits: int = DIGITS) -> str:
    return _hotp(_key(secret), int(for_time // STEP_SECONDS), digits)


def verify_totp(secret: str, code: str, *, now: float | None = None,
                last_used_step: int | None = None, window: int = WINDOW) -> int | None:
    """Return the accepted time step, or None.

    Steps at or before ``last_used_step`` are refused, so a code (including one observed
    by an attacker) cannot be used twice. The caller must persist the returned step.
    All candidate steps are compared before returning, so timing does not reveal which
    one matched.
    """
    if not isinstance(code, str):
        return None
    code = code.replace(" ", "")
    if len(code) != DIGITS or not code.isascii() or not code.isdigit():
        return None
    key = _key(secret)
    current = int((time.time() if now is None else now) // STEP_SECONDS)
    accepted = None
    for step in range(current - window, current + window + 1):
        matches = hmac.compare_digest(_hotp(key, step), code)
        if matches and (last_used_step is None or step > last_used_step):
            accepted = step
    return accepted


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    """otpauth:// URI that authenticator apps read from a QR code."""
    label = quote(f"{issuer}:{account}", safe="")
    query = urlencode({"secret": secret, "issuer": issuer, "algorithm": "SHA1",
                       "digits": DIGITS, "period": STEP_SECONDS}, quote_via=quote)
    return f"otpauth://totp/{label}?{query}"


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Human-friendly single-use codes like ``K7QX2-M9PTD``; shown to the user once."""
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def normalize_recovery_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").upper()


def hash_recovery_code(code: str) -> str:
    """Salted PBKDF2 hash for storage: ``pbkdf2_sha256$iterations$salt$hash``."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", normalize_recovery_code(code).encode(),
                                 salt.encode(), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def check_recovery_code(code: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", normalize_recovery_code(code).encode(),
                                     salt.encode(), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)
