"""Isolated regression settings; never opens backend/db.sqlite3."""
import tempfile
from .dev import *  # noqa: F403

_TEST_FILES = tempfile.TemporaryDirectory(prefix="jth-sqlite-tests-")
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
MEDIA_ROOT = _TEST_FILES.name
SECRET_KEY = "isolated-database-validation-only"
