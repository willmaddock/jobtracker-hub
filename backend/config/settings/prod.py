"""
Production settings. Real values (SECRET_KEY, ALLOWED_HOSTS, database
credentials, etc.) should come from environment variables before this
is ever actually deployed — the placeholders below are not safe to
ship as-is. See docs/DJANGO_MIGRATION_PLAN.md Phase 10.
"""
import os

from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',')
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', SECRET_KEY)
