"""
Local development settings. Run with:
    DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py runserver
(manage.py already defaults to this module — see manage.py)
"""
from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1']
