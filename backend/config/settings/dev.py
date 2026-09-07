"""
Local development settings. Run with:
    DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py runserver
(manage.py already defaults to this module — see manage.py)
"""
from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# Uploaded Documents land under backend/media/ locally -- base.py's
# FileSystemStorage default is kept as-is, this just gives it
# somewhere real to write. Not used in prod; see prod.py's S3
# STORAGES override.
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'
