# Deployment scaffolding (AWS-oriented)

**Status: scaffolding only.** Added at base commit `ad69358`. Verified in a scratch
environment: `config.settings.prod` loads with the variables in `deploy/env.example`,
`gunicorn config.wsgi:application --check-config` passes, and the Celery app imports.
**Not verified:** the Docker image was not built, nothing connected to RDS/S3/Redis, and
no staging deploy was run. This does not close the Status §10 production gates.

## Processes (one image, three roles)

| Role | Command |
|---|---|
| web | image default: `gunicorn config.wsgi:application --bind 0.0.0.0:8000` |
| worker | `celery -A config worker -l info` |
| beat (exactly one instance) | `celery -A config beat -l info` |
| migrate (one-off task, not on every web start) | `python manage.py migrate` |

Build from the repository root (the backend serves `_app/frontend/`):
`docker build -t jobtracker-hub .`

## Configuration
See `deploy/env.example`. `prod.py` loads no `.env` file; inject variables from Secrets
Manager/SSM. It rejects `DATABASE_URL`, `DJANGO_DB_ENGINE` and `DJANGO_CSRF_TRUSTED_ORIGINS`.
Use an IAM role for S3 instead of static keys where possible.

## Known blockers found while building this (not fixed here)
1. **TLS/proxy:** see `DEPLOYMENT_PROXY_TLS_PROPOSAL.md`. Behind an ALB, current prod
   settings will fail (redirect loop / CSRF). Needs a recorded decision.
2. **`manage.py check --deploy` fails with `mail.E001`:** `MAILERS` is the console backend
   in all environments, including prod. Decide whether the product sends email (SES SMTP)
   or the check should be explicitly handled.
3. **Static files:** no `STATIC_ROOT`/static serving, so `/admin/` renders unstyled.
   Decide: add WhiteNoise/`collectstatic`, or disable admin in production.
4. **Celery pins:** `celery>=5.4` / `redis>=5.0` are still minimum bounds. Run
   `pip freeze | grep -iE 'celery|redis'` in `backend/venv` and pin exact versions.
5. **`check --deploy` warning `security.W004` (HSTS):** deliberately deferred in `prod.py`.
