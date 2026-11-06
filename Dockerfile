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
COPY _app/frontend _app/frontend

USER app
WORKDIR /app/backend
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
EXPOSE 8000

# Web by default. Override the command for other roles (see docs/DEPLOYMENT.md):
#   celery -A config worker -l info
#   celery -A config beat -l info
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
