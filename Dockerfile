# Django backend image (web, Celery worker, Celery Beat share this image).
# Build from the repository ROOT: the backend serves _app/frontend/ (see
# backend/core/frontend.py), so both trees must be in the image.
#   docker build -t jobtracker-hub .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# psycopg (non-binary, per backend/requirements.txt) needs the libpq runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 app

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend backend
COPY _app _app

# Collect admin/static assets for WhiteNoise (prod.py). Dev settings are used only
# here because they need no production secrets; STATIC_ROOT comes from base.py.
# Runs as root so the output exists before dropping to the unprivileged user.
RUN cd backend && DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py collectstatic --noinput

# Gateway mode keeps each user's private data here; a volume mounted on it inherits this ownership.
RUN mkdir -p /data && chown app:app /data

USER app
WORKDIR /app/backend
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
EXPOSE 8000

# Web by default. Override the command for other roles (see docs/DEPLOYMENT.md):
#   celery -A config worker -l info
#   celery -A config beat -l info -s /tmp/celerybeat-schedule
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "300", "--access-logfile", "-"]
