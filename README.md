# JobTracker Hub (Django)

JobTracker Hub as a hosted, multi-user Django app: create an account, sign in, and protect it
with MFA (authenticator app, recovery codes, optional passkeys). The UI is the same
`_app/frontend` single page you already know; Django serves it and provides the API.

```
backend/      Django project (plus `gateway/`, the sign-in-then-original-app layer) (accounts + MFA, applications, documents, postings, email_sync)
_app/frontend The React single-page UI, served by backend/core/frontend.py
Dockerfile    Image for web / Celery worker / Celery beat
docker-compose.yml   Production-like stack: Postgres, Redis, S3 mock, mail catcher, TLS proxy
deploy/       env.example (production variables) and local helper files
docs/         MFA design, deployment notes, accepted decisions
```

The original FastAPI app (`_app/`, the list/Kanban/dossier UI and your folders of applications) is
included. In **gateway mode** (`JTH_GATEWAY=true`, on in `.env.example`) Django signs you in and
protects the account with MFA, then runs a private copy of that app for each user. See
[docs/GATEWAY.md](docs/GATEWAY.md).

## Quick start (no Docker, SQLite)

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
python manage.py test accounts applications core documents email_sync gateway postings web
```

Name the apps rather than running a bare `manage.py test`: `config/settings/test_postgres.py` is a
harness-only module (see `tests/backend/`) that fails to import during plain test discovery.
Some tests intentionally feed bad PDFs or trigger a 500, so lines like `invalid pdf header` or
`Internal Server Error` in the output are expected.

Gateway tests that exercise the `/` route depend on `JTH_GATEWAY`; if one fails, try
`JTH_GATEWAY=true python manage.py test gateway`.

## Notes

- Production forces MFA on for every account (`config/settings/prod.py`). In production, emailed
  sign-in needs a real SMTP relay; see `deploy/env.example`.
- Rotating `MFA_ENCRYPTION_KEY` forces everyone to re-enrol MFA.
- Data lives in the database and uploaded documents (S3 in production), not in a local folder.
