"""Fresh-process production admission. No dotenv loading or service probes.

Configuration validity does not establish deployment/operational readiness.
Database TLS, proxy trust, HSTS rollout and infrastructure remain separate gates.
"""
import base64
import binascii
import ipaddress
import os
import re
import unicodedata

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403


def _invalid(name):
    raise ImproperlyConfigured(f"Production configuration has invalid {name}.") from None


def _controlled(value):
    return any(unicodedata.category(char) == "Cc" for char in value)


def _required(name, *, opaque=False):
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ImproperlyConfigured(f"Production configuration requires {name}.") from None
    if _controlled(value) or not opaque and value != value.strip():
        _invalid(name)
    return value


def _unsupported(name):
    if os.environ.get(name, ""):
        raise ImproperlyConfigured(f"Production configuration does not support {name}.") from None


def _host(value, *, web=False):
    # Web IPv6 requires brackets; libpq takes a bare IPv6 address.
    if any(char in value for char in ("%", "@", "/", "\\", "?", "#")):
        raise ValueError()
    if web and value.startswith("[") and value.endswith("]"):
        ipaddress.IPv6Address(value[1:-1])
        # Django matches the literal Host spelling, not compressed IP equivalence.
        return value.lower()
    if ":" in value:
        if web:
            raise ValueError()
        return str(ipaddress.IPv6Address(value))
    if re.fullmatch(r"[0-9.]+", value):
        return str(ipaddress.IPv4Address(value))
    if not value.isascii() or len(value) > 253:
        raise ValueError()
    label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    if not all(re.fullmatch(label, part) for part in value.split(".")):
        raise ValueError()
    return value.lower()


_unsupported("DATABASE_URL")
_unsupported("DJANGO_DB_ENGINE")
_db_name = _required("DJANGO_DB_NAME")
_db_user = _required("DJANGO_DB_USER")
_db_password = _required("DJANGO_DB_PASSWORD", opaque=True)
_db_host = _required("DJANGO_DB_HOST")
try:
    _db_host = _host(_db_host)
except ValueError:
    _db_host = None
if _db_host is None:
    _invalid("DJANGO_DB_HOST")
_db_port = _required("DJANGO_DB_PORT")
if not re.fullmatch(r"[0-9]{1,5}", _db_port) or not 1 <= int(_db_port) <= 65535:
    _invalid("DJANGO_DB_PORT")
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql", "NAME": _db_name,
    "USER": _db_user, "PASSWORD": _db_password, "HOST": _db_host,
    "PORT": int(_db_port),
}}

SECRET_KEY = _required("DJANGO_SECRET_KEY", opaque=True)
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured("Production configuration requires a valid DJANGO_SECRET_KEY.") from None
SECRET_KEY_FALLBACKS = []

# These are compromised development defaults already committed in base.py,
# never production secrets. Reject any of them in any provider position.
_development_keys = {
    "fXjaJnCzcqV7qdtv8krT14nLUD6QBFScd6jZf5hzVGg=",
    "Pkn_45gin4M7zHTs1htox81DGuwAV7ADpMKtZpQqd-4=",
    "FKMi8JI8yo6UB7lC3PoLor_kuv2SAWF5l_rrD0WsoiA=",
    "677OQZpNhrBbieGggrHUIRBlQwXRQNE0PeRbby0pcQ8=",
}


def _provider_key(name):
    value = _required(name, opaque=True)
    decoded = None
    try:
        encoded = value.encode("ascii")
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if len(decoded) != 32 or base64.urlsafe_b64encode(decoded) != encoded or value in _development_keys:
            decoded = None
        else:
            Fernet(encoded)
    except (ValueError, UnicodeError, binascii.Error):
        decoded = None
    # Raise outside parsing handlers so even exception context contains no input.
    if decoded is None:
        _invalid(name)
    return value, decoded


GMAIL_TOKEN_ENCRYPTION_KEY, _gmail_bytes = _provider_key("GMAIL_TOKEN_ENCRYPTION_KEY")
MICROSOFT_TOKEN_ENCRYPTION_KEY, _microsoft_bytes = _provider_key("MICROSOFT_TOKEN_ENCRYPTION_KEY")
IMAP_TOKEN_ENCRYPTION_KEY, _imap_bytes = _provider_key("IMAP_TOKEN_ENCRYPTION_KEY")
MFA_ENCRYPTION_KEY, _mfa_bytes = _provider_key("MFA_ENCRYPTION_KEY")
if len({_gmail_bytes, _microsoft_bytes, _imap_bytes, _mfa_bytes}) != 4:
    raise ImproperlyConfigured("Production configuration requires distinct provider encryption keys.") from None

_hosts = _required("DJANGO_ALLOWED_HOSTS", opaque=True)
ALLOWED_HOSTS = []
_hosts_valid = True
try:
    for _entry in _hosts.split(","):
        _entry = _entry.strip()
        if not _entry:
            raise ValueError()
        _entry = _host(_entry, web=True)
        if _entry not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(_entry)
except ValueError:
    _hosts_valid = False
if not _hosts_valid:
    _invalid("DJANGO_ALLOWED_HOSTS")

_unsupported("DJANGO_CSRF_TRUSTED_ORIGINS")
CSRF_TRUSTED_ORIGINS = []
DEBUG = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_SSL_REDIRECT = True
# TLS-terminating proxy (accepted option A, docs/DEPLOYMENT_PROXY_TLS_PROPOSAL.md).
# Default OFF: the fail-closed behaviour above is unchanged. Only the exact value
# "true" enables it; "" / "false" keep it off; anything else is refused. Enable ONLY
# when containers are reachable solely through the proxy (e.g. an ALB), which must
# set X-Forwarded-Proto itself -- otherwise a client could spoof HTTPS.
_proxy = os.environ.get("DJANGO_BEHIND_TLS_PROXY", "")
if _proxy not in ("", "true", "false"):
    _invalid("DJANGO_BEHIND_TLS_PROXY")
if _proxy == "true":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Answer load-balancer health probes (plain HTTP, task-IP Host) before host
    # validation and the HTTPS redirect. Liveness only; touches no database.
    MIDDLEWARE = ["core.middleware.HealthCheckMiddleware", *MIDDLEWARE]
else:
    SECURE_PROXY_SSL_HEADER = None
USE_X_FORWARDED_HOST = False
USE_X_FORWARDED_PORT = False

# MFA is mandatory in production and cannot be switched off by configuration
# (docs/MFA_DESIGN.md). Sign-in and code-entry attempts are rate limited per client IP;
# behind the trusted proxy the client IP is the last X-Forwarded-For hop.
MFA_REQUIRED = True
AUTH_THROTTLE_RATES = {"auth_login": "10/min", "mfa": "10/min"}
REST_FRAMEWORK = {**REST_FRAMEWORK, "NUM_PROXIES": 1 if _proxy == "true" else 0}

# Passkeys are enabled only when both values are set, and must describe the same site: the
# origin is exactly https://<host>[:port] and its host is the relying-party id or a subdomain.
# Unset (the default) disables passkeys; the base-settings development values never apply here.
_rp_id = os.environ.get("WEBAUTHN_RP_ID", "")
_origin = os.environ.get("WEBAUTHN_ORIGIN", "")
WEBAUTHN_RP_ID = ""
WEBAUTHN_ORIGIN = ""
if _rp_id or _origin:
    from urllib.parse import urlsplit as _urlsplit
    try:
        _parts = _urlsplit(_origin)
        _host_name = _parts.hostname or ""
        _parts.port  # raises ValueError for a malformed port
        _webauthn_valid = bool(
            _rp_id and _origin and not _controlled(_rp_id) and not _controlled(_origin)
            and _rp_id == _rp_id.strip().lower() and not any(c in _rp_id for c in "/:@?# ")
            and _parts.scheme == "https" and not _parts.username and not _parts.password
            and _parts.path == "" and not _parts.query and not _parts.fragment
            and (_host_name == _rp_id or _host_name.endswith("." + _rp_id))
        )
    except ValueError:
        _webauthn_valid = False
    if not _webauthn_valid:
        _invalid("WEBAUTHN_ORIGIN")
    WEBAUTHN_RP_ID, WEBAUTHN_ORIGIN = _rp_id, _origin

# Static files for /admin/ (the operational/onboarding tool): WhiteNoise serves the
# output of `collectstatic` (run at image build). Unhashed storage so the build does
# not need production secrets. Inserted directly after SecurityMiddleware.
MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
                  "whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES["staticfiles"] = {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"}

# The product sends no email today (nothing calls send_mail). The development console
# backend would silently drop mail and fails `check --deploy` (mail.E001). Use SMTP with
# no OPTIONS so any future send fails loudly until a real mail service is configured.
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.smtp.EmailBackend"}}

# File storage — Phase 4. Overrides base.py's plain-filesystem
# STORAGES["default"] with S3 (or any S3-compatible endpoint, e.g.
# MinIO/R2/Spaces — that's what AWS_S3_ENDPOINT_URL is for; leave it
# unset for real AWS S3). Resumes/cover letters/evidence PDFs are
# personal documents, so the bucket is treated as private: no public
# ACL, and URLs handed to the frontend are short-lived signed links
# rather than permanent public ones (AWS_QUERYSTRING_AUTH=True,
# AWS_QUERYSTRING_EXPIRE below). AWS_S3_FILE_OVERWRITE=False so two
# uploads that happen to share a filename get distinct storage keys
# instead of one silently clobbering the other.
STORAGES['default'] = {
    'BACKEND': 'storages.backends.s3.S3Storage',
}

AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', '')
AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', '')
# Only set for non-AWS S3-compatible providers; leave unset for real S3.
AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL') or None
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True
AWS_QUERYSTRING_EXPIRE = 300  # signed download links expire after 5 minutes
