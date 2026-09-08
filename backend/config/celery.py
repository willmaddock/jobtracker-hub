"""
Celery application for this project (Phase 10 background task runner
-- closes the "no background task runner" gap flagged in
docs/DJANGO_MIGRATION_PLAN.md's Phase 9 Known gaps and
docs/DJANGO_BACKEND_HANDOFF.md §4).

Two separate long-running processes run alongside `manage.py
runserver`/gunicorn in any real deployment (docs/DJANGO_MIGRATION_PLAN.md
Phase 10's "background worker process" bullet):

    celery -A config worker -l info
    celery -A config beat -l info

`worker` executes tasks pulled off CELERY_BROKER_URL (Redis); `beat`
is the scheduler that enqueues CELERY_BEAT_SCHEDULE entries
(config/settings/base.py) on their configured interval -- it never
executes a task itself, only enqueues it, the same split as cron vs.
the command cron invokes. Both processes import this same `app`
object via Celery's own `-A`/`--app` autodiscovery of
`config.celery.app` -- this module living at `config/celery.py`,
matching the Django project package name, is what lets `-A config`
find it with no further flags (see Celery's "First steps with
Django" docs).

`app.config_from_object('django.conf:settings', namespace='CELERY')`
means every Celery setting is a `CELERY_`-prefixed Django setting
(CELERY_BROKER_URL, CELERY_BEAT_SCHEDULE, etc., all in
config/settings/base.py) rather than a separate celeryconfig.py --
one settings surface for both, same reasoning as every other
Django-settings-namespaced third-party app already in this project
(REST_FRAMEWORK, STORAGES, etc.).

`app.autodiscover_tasks()` finds every INSTALLED_APPS app's tasks.py
automatically (currently just email_sync/tasks.py) -- a new
`<app>/tasks.py` in a later phase needs no registration here, the
same Django-convention autodiscovery Django itself already uses for
migrations/admin.py.
"""
from __future__ import annotations

import os

from celery import Celery

# Mirrors manage.py's own default -- a real deployment sets
# DJANGO_SETTINGS_MODULE explicitly (config.settings.prod), so
# setdefault here never overrides that; it only lets `celery -A
# config worker` boot with sane settings the same way `manage.py`
# does when nothing else has set the env var yet.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("jobtracker_hub")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
