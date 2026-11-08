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
| beat (exactly one instance) | `celery -A config beat -l info -s /tmp/celerybeat-schedule` |
| migrate (one-off task, not on every web start) | `python manage.py migrate` |

Build from the repository root (the backend serves `_app/frontend/`):
`docker build -t jobtracker-hub .`

## Configuration
See `deploy/env.example`. `prod.py` loads no `.env` file; inject variables from Secrets
Manager/SSM. It rejects `DATABASE_URL`, `DJANGO_DB_ENGINE` and `DJANGO_CSRF_TRUSTED_ORIGINS`.
Use an IAM role for S3 instead of static keys where possible.

## Decisions taken (owner delegated; implemented in `backend/config/settings/prod.py`)
1. **TLS/proxy:** option A, opt-in `DJANGO_BEHIND_TLS_PROXY=true` (see
   `DEPLOYMENT_PROXY_TLS_PROPOSAL.md`). With it on, `X-Forwarded-Proto: https` is trusted and
   `GET`/`HEAD /api/health` is answered before host validation so ALB probes (plain HTTP, task-IP
   Host) get 200. Point the target group health check at `/api/health`. Containers must be
   reachable only from the ALB security group.
2. **Email:** the product sends none. `MAILERS` uses the SMTP backend with no options, which
   clears `mail.E001` and makes any future send fail loudly until a real mail service (e.g. SES)
   is configured.
3. **Admin/static:** admin stays enabled (it is the account-provisioning tool, decision 9).
   WhiteNoise serves `collectstatic` output, which the Dockerfile generates at build.
4. **Celery/Redis pins:** `celery==5.7.0`, `redis==8.1.0`.
5. **Data:** start fresh on the hosted instance; no migration from the macOS app. Revisit later
   if needed.

## Local production-like stack (before AWS)
`docker-compose.yml` runs the same image as AWS against Postgres, Redis and Adobe S3Mock
(S3-compatible mock), with Caddy as a stand-in for the ALB (TLS termination, `X-Forwarded-Proto`).
Run `sh deploy/local/make-env.sh` once (random throwaway credentials, git-ignored), then
`docker compose -f docker-compose.yml up --build -d` and browse to
`https://localhost:8443/` (accept the local certificate warning). Local testing only.
It does not cover: RDS database TLS, IAM-role S3 access, ALB security groups, or real DNS/ACM.

## First-user onboarding (administrator-created accounts, no signup)
Run as one-off tasks using the same image and environment as web:
1. `python manage.py migrate`
2. `python manage.py createsuperuser` (the operator account, used for `/admin/`)
3. Sign in at `/admin/`, create the product user (Users -> Add), set a password; the user then
   signs in at the app root and creates their workspace there.
Keep the superuser separate from product users.

## Still open / not verified
- The Docker image was not built here; nothing was run against RDS, S3, Redis or an ALB.
  Verify in staging: redirect behaviour, CSRF on login, admin CSS, uploads to S3, Celery beat.
- `security.W004` (HSTS) is deliberately deferred in `prod.py`; enable only after HTTPS works
  end to end.
- `DJANGO_MIGRATION_DECISIONS.md` has not been updated to record these decisions.
