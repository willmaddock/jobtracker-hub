"""Harness-only PostgreSQL settings; no developer/production DB fallback."""
import sys
from pathlib import Path
from .test_sqlite import *  # noqa: F403

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests" / "backend"))
from run_database_validation import load_manifest, verify_server

_RUN = load_manifest()
verify_server(_RUN)
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "postgres", "USER": _RUN["role"], "PASSWORD": "",
    "HOST": _RUN["socket"], "PORT": "5432", "CONN_MAX_AGE": 0,
    "OPTIONS": {"connect_timeout": 5, "options": "-c lock_timeout=15000 -c statement_timeout=30000"},
    "TEST": {"NAME": _RUN["database"]},
}}
TEST_RUNNER = "run_database_validation.GuardedRunner"
