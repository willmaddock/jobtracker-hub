"""
Makes the Celery app available as `config.celery_app` so any
`@shared_task`-decorated function elsewhere in the project (currently
email_sync/tasks.py) always binds to *this* app instance without
needing to import config.celery itself -- Celery's own recommended
Django integration pattern (see config/celery.py's own module
docstring for the fuller "why").
"""
from .celery import app as celery_app

__all__ = ("celery_app",)
