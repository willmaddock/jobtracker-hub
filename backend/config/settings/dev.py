"""
Local development settings. Run with:
    DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py runserver
(manage.py already defaults to this module — see manage.py)
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Development only, before base reads environment-backed values. Never overwrite
# values supplied by the process. Production must start in a fresh process.
load_dotenv(Path(__file__).resolve().parent.parent.parent / '.env', override=False)

from .base import *  # noqa: E402,F401,F403

DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# Uploaded Documents land under backend/media/ locally -- base.py's
# FileSystemStorage default is kept as-is, this just gives it
# somewhere real to write. Not used in prod; see prod.py's S3
# STORAGES override.
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'


# --- Account sign-up / MFA switches for local use ---------------------------------------
# All optional; set them in backend/.env (see backend/.env.example). With none set, behaviour
# is exactly as before: only administrator-created accounts, MFA optional.
def _flag(name, default=False):
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() == "true"


# Sign up / sign in with an emailed code. Mail goes to the runserver console (MAILERS default
# in base.py is the console backend), so nothing is actually sent.
EMAIL_SIGNIN_ENABLED = _flag("EMAIL_SIGNIN_ENABLED")
EMAIL_SIGNUP_OPEN = _flag("EMAIL_SIGNUP_OPEN")
EMAIL_SIGNIN_SATISFIES_MFA = _flag("EMAIL_SIGNIN_SATISFIES_MFA")
MFA_EMAIL_FROM = os.environ.get("MFA_EMAIL_FROM", "")
MFA_EMAIL_CODES_ENABLED = _flag("MFA_EMAIL_CODES_ENABLED")
# Force every account to enrol an authenticator app (as production does).
MFA_REQUIRED = _flag("MFA_REQUIRED")
