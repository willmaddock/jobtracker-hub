# JobTracker Hub (Django)

JobTracker Hub as a hosted, multi-user Django app: create an account, sign in, and protect it
with MFA (authenticator app, recovery codes, optional passkeys). The UI is the same
`_app/frontend` single page you already know; Django serves it and provides the API.

```
backend/      Django project (plus `gateway/`, the sign-in-then-original-app layer) (accounts + MFA, applications, documents, postings, email_sync)
_app/frontend The React single-page UI, served by backend/core/frontend.py
Dockerfile    Image for web / Celery worker / Celery beat
docker-compose.local.yml   Production-like stack: Postgres, Redis, S3 mock, mail catcher, TLS proxy
deploy/       env.example (production variables) and local helper files
docs/         MFA design, deployment notes, accepted decisions
```

The original FastAPI app (`_app/`, the list/Kanban/dossier UI and your folders of applications) is
included. In **gateway mode** (`JTH_GATEWAY=true`, on in `.env.example`) Django signs you in and
protects the account with MFA, then runs a private copy of that app for each user. See
[docs/GATEWAY.md](docs/GATEWAY.md).

## Quick start (no Docker, SQLite)

Get the code (skip if you already have it):

```bash
git clone -b feature/gateway https://github.com/willmaddock/jobtracker-hub.git
cd jobtracker-hub
```

First time only (if another server is already running, stop it with Ctrl+C so port 8000 is free):

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # turns on "create an account" + required MFA
python manage.py migrate
python manage.py runserver
```

Open **http://localhost:8000** (use `localhost`, not `127.0.0.1`, so passkeys work).

1. Enter your email and choose **Continue with email**. A 6-digit code is printed in the
   terminal running `runserver` (nothing is really sent in dev).
2. Enter the code. Because `MFA_REQUIRED=true`, you are asked to set up an authenticator app:
   scan the QR code, enter the code, and save the recovery codes shown once.
3. After the recovery-codes screen you land in the original JobTracker UI (gateway mode). From then on, sign in with email code (or username/password for admin-created accounts)
   plus your authenticator code. Passkeys can be added under Security.

Operator account (for `/admin/`, also needs MFA):

```bash
python manage.py createsuperuser
```

Without `.env`, dev behaves as before: no public signup, accounts are created in `/admin/`.

## Starting it again later

Setup is a one-time job. From then on, just activate the venv and start the server. Do **not**
re-run `cp .env.example .env`: it overwrites your `backend/.env` and any settings you changed
(for example `JTH_MAX_UPLOAD_MB`).

```bash
cd backend
source .venv/bin/activate
python manage.py runserver
```

Settings in `.env` are read at startup, so stop (Ctrl+C) and restart after editing it.

## Try it locally

1. Start the server (steps above) and open **http://localhost:8000**.
2. Enter any email and click **Continue with email**. This creates the account; there is no
   separate registration form.
3. Look in the terminal running `runserver` for a line containing a 6-digit code (nothing is
   emailed in dev), and enter it.
4. Set up an authenticator app (scan the QR code), enter its code, and save the recovery codes.
5. You are now in the JobTracker UI. To get back in later, sign in with the same email.

Need an admin or username/password account instead? Run `python manage.py createsuperuser`.

If you see no sign-up option, you probably skipped `cp .env.example .env`; without it there is
no public signup and accounts are created in `/admin/`.

## Importing an existing tracker

In the JobTracker UI, open the tracker menu and choose **Bring in a Copy**, then **Import a Copy** in the dialog and pick a `.zip`
export of your tracker folder (a zip keeps notes and statuses; a plain folder upload can't).
Imports larger than 512 MB are rejected with `Upload too large`. Raise `JTH_MAX_UPLOAD_MB` in
`backend/.env` (it is 1024 in `.env.example`) and restart `runserver`; the setting is read at startup.
Behind nginx or another proxy, raise its body-size limit to match.

## Docker (production-like, local)

```bash
sh deploy/local/make-env.sh                       # once: random throwaway secrets
docker compose up --build -d
docker compose run --rm web python manage.py createsuperuser
```

Browse to **https://localhost:8443/** (accept the local certificate warning). Sign-up emails are
caught by Mailpit at **http://localhost:8025**. Stop with `docker compose down` (add `-v` to wipe
data). This stack is for local testing only; see `docs/DEPLOYMENT.md` and `deploy/env.example`
for real deployments.

## Tests

```bash
cd backend
python manage.py test accounts applications core documents email_sync postings web
JTH_GATEWAY=true python manage.py test gateway
```

Name the apps rather than running a bare `manage.py test`: `config/settings/test_postgres.py` is a
harness-only module (see `tests/backend/`) that fails to import during plain test discovery.
Some tests intentionally feed bad PDFs or trigger a 500, so lines like `invalid pdf header` or
`Internal Server Error` in the output are expected.

`manage.py test` ignores `backend/.env`, so a `.env` copied from `.env.example` (which turns on
gateway mode, MFA and email sign-in) cannot change the results. Only the gateway tests need the
flag, and values set in the shell are still honoured.

## Checks before you commit

```bash
pip install -r requirements-dev.txt
ruff check .          # lint (config in ruff.toml)
pre-commit install    # optional: runs the same checks on every commit
```

GitHub Actions (`.github/workflows/ci.yml`) runs the Django tests on every push. The lint and
legacy-app test jobs are informational for now. Styling rules are in `docs/CSS_NOTES.md`.

## Notes

- Production forces MFA on for every account (`config/settings/prod.py`). In production, emailed
  sign-in needs a real SMTP relay; see `deploy/env.example`.
- Rotating `MFA_ENCRYPTION_KEY` forces everyone to re-enrol MFA.
- In gateway mode, each user's trackers and uploaded documents live on the server's disk under
  `jth-data/` (gitignored; override with `JTH_DATA_DIR`). In the non-gateway Django app, data lives
  in the database and S3 in production.
