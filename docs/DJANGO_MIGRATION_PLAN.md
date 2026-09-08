# JobTracker Hub → Django Migration Plan

**Goal:** turn the existing JobTracker into a proper multi-user web
application — Django + DRF as the API backend, existing frontend kept
as-is initially, both SQLite databases consolidated into one
Django-managed database. Django replaces the *infrastructure*; the
product behavior is the thing being preserved, not rewritten.

**Ground rule:** don't convert `api.py` line-for-line into Django
views. The point of this migration is to land on
`Django framework → models → domain/services → API`, not to reproduce
the current file shape inside a new framework.

**Status:** for what's actually been built against this plan
phase-by-phase (as opposed to what's planned), see
[`DJANGO_BACKEND_HANDOFF.md`](DJANGO_BACKEND_HANDOFF.md) — the living
checkpoint doc for this track. This file stays the stable plan; that
one is the changing progress record.

---

## Phase 0 — Characterize before touching anything

Before writing a line of Django code, treat the current app as the
**behavioral reference** you're not allowed to silently drift from:

- Keep `main` untouched; all work happens on `django-migration`.
- Run the existing test suite and record the baseline (currently 368
  passing).
- Inventory every current API endpoint and what the frontend actually
  calls — this becomes your DRF surface-area checklist later.
- Identify which behaviors are load-bearing. The fixture-based
  extraction tests are the sharpest example: `test_linkedin_fixture_
  yields_six_postings`, `test_handshake_fixture_yields_at_least_five_
  postings`, the Indeed/Lensa digest counts. These are concrete,
  numeric, and already automated — use them as acceptance tests for
  the migrated posting-extraction path, not just as "tests that
  happen to exist."

## Phase 1 — Django foundation

Stand up the skeleton alongside the existing app; don't rip anything
out yet.

```text
jobtracker/
├── config/
│   ├── settings/ (base.py, dev.py, prod.py)
│   ├── urls.py
│   └── wsgi.py / asgi.py
├── accounts/
├── workspaces/
├── postings/
├── applications/
├── documents/
├── email_sync/
└── core/
```

Start with: Django, DRF, Postgres-ready DB config (dev can still run
SQLite locally, but don't write anything that assumes SQLite-only
semantics), migrations, environment-based settings.

## Phase 2 — Auth and multi-tenancy, designed now

**This has to happen before Phase 3's data models, not after.** Every
model you're about to create needs a `user`/`workspace` FK from the
moment it's created — retrofitting ownership onto models that already
have data and queries built against them is exactly the kind of rework
this phase order is meant to avoid.

- Custom Django `User` model from day one (much easier now than a
  later migration).
- Session or token auth via DRF, decided based on whether the frontend
  stays same-origin.
- Decide the ownership shape now:
  ```text
  User
    └── Workspace
          ├── JobPostings
          ├── Applications
          ├── Documents
          └── EmailMessages
  ```
  Every query later filters through `workspace=request.user.workspace`
  — never an unscoped `SELECT * FROM …` equivalent.

## Phase 3 — Core data models (consolidating both SQLite DBs)

Move both `db.py` (disposable index) and `overrides_store.py`
(durable user data) into Django models, in one database, with
ownership already wired in from Phase 2:

`Workspace`, `Application`, `Override`, `StatusHistory`, `JobPosting`,
`Discovery`, `EmailAccount`, `EmailMessage`, `HubSettings`.

Use Django migrations from the start — no hand-written schema SQL the
way the current stores do it.

## Phase 4 — File storage (folder → per-user storage)

The current app treats a workspace as a literal folder on disk;
`build_index.py` works by walking it. That has no direct equivalent
once files live in per-user cloud storage instead of a shared
filesystem:

- Introduce a `Document` model (file + metadata + owner + workspace)
  backed by `FileField` against S3-compatible storage
  (`django-storages`), not a local path.
- Rewrite "rebuild the index" as "re-derive the index from the
  `Document` rows for this workspace," not a filesystem walk.
- Uploads (resumes, cover letters, evidence PDFs) go through a normal
  upload endpoint instead of being dropped into a folder by hand.

## Phase 5 — Reuse the existing domain logic

The recent extraction into `_app/domain/` and `_app/infrastructure/`
was real prep work for exactly this — don't discard it:

- `domain/applications.py`, `domain/identity.py`, `domain/job_postings.py`,
  `domain/errors.py` have no FastAPI or filesystem dependency and move
  into the Django apps largely unchanged.
- `infrastructure/paths.py` (local path-traversal safety) gets
  replaced by whatever the storage backend provides — it doesn't port
  as-is, since it's solving a local-filesystem problem that no longer
  exists once uploads go through Phase 4's storage layer.
- Swap `HTTPException`-style errors for DRF `APIException` subclasses
  (or a custom `exception_handler`) using the same status codes and
  messages `domain/errors.py` already defines, so behavior doesn't
  silently shift.

## Phase 6 — Job Postings as first-class

Explicit model, not a generic "discovery" blob:

```text
JobPosting
──────────────
workspace, source_email, title, company, location, salary,
employment_type, posting_url, source, received_at, dedupe_key,
status, created_at
```

The LinkedIn/Handshake/Indeed/Lensa fixture tests from Phase 0 are
your acceptance bar here — same counts, same field extraction, on the
new model.

## Phase 7 — Django Admin

Once the models above exist, Django Admin gives you a working internal
management interface for users, workspaces, postings, applications,
and sync state essentially for free — worth wiring up before building
any custom internal tooling by hand.

## Phase 8 — DRF API surface + frontend

Build viewsets/serializers matching the endpoint inventory from
Phase 0, so the existing frontend needs minimal changes. This is the
"first real milestone" — auth + CRUD + overrides + postings, working
end-to-end, **before** email sync exists in the new system. Verify
this is solid before moving on; don't change the DB, auth, extraction,
and frontend all at once — that makes debugging any one issue
ambiguous.

## Phase 9 — Email sync (the hardest rewrite, not a detail)

`mail_app_store.py` currently works by AppleScript-driving the local
macOS Mail.app — that's inherently one desktop, one mailbox, and has
**no server equivalent**. This isn't a pipeline detail to fill in
later; it's the riskiest, most different part of the whole migration:

- Replace Mail.app/osascript with OAuth-based providers: Gmail API
  and/or Microsoft Graph for most job-search email, generic IMAP as a
  fallback.
- Sync runs as a background task per user (Celery + Redis, or
  Django-Q), not inline in a request.
- The matching logic already in `mail_app_store.py` — thread-ID
  matching, sender whitelisting, subject classification — is portable
  once the "how do I get messages" layer is swapped out.
- **Sync must be idempotent.** Running sync four times in a row should
  produce the same posting count each time, not accumulate duplicates.
  Design the dedupe key and upsert logic for this from the start
  rather than discovering the bug after multiple users hit it.

### Phase 9 progress

Slice-by-slice status against the bullets above (see
`DJANGO_BACKEND_HANDOFF.md` for the full checkpoint history — this is
just the current-state summary):

- **Matching logic port** — done. `backend/email_sync/matching.py`
  ports thread-ID matching, sender whitelisting, and subject
  classification from `mail_app_store.py`.
- **Provider-agnostic sync orchestration** — done.
  `backend/email_sync/providers.py` (the `EmailProvider`/
  `FetchedMessage` contract) + `backend/email_sync/sync_service.py`
  (thread trust, posting-notice routing, term matching, idempotent
  upserts via `get_or_create`, one `@transaction.atomic` block).
- **Gmail provider (message-fetching only)** — done.
  `backend/email_sync/gmail_provider.py` implements `EmailProvider`
  against the real Gmail API (list/get, pagination, error
  classification). Fully mock-tested, no OAuth of its own.
- **Gmail OAuth (connect/callback, encrypted token storage, real
  service_factory)** — done. `backend/email_sync/oauth.py` +
  `views.py`/`urls.py`. `GmailCredential` model, Fernet field-level
  encryption, `GET /api/email-accounts/gmail/{connect,callback}`,
  registers `get_provider("gmail")` for real use.
- **Manual "sync now" trigger** — done. `POST
  /api/email-accounts/<id>/sync` (`backend/email_sync/views.py`'s
  `EmailAccountSyncView`) calls `sync_service.sync_account()` for one
  account at a time. No scheduling of any kind yet — see below.
- **Disconnect/revoke flow** — done. `POST
  /api/email-accounts/<id>/disconnect`
  (`EmailAccountDisconnectView`) best-effort revokes the Gmail grant
  with Google (`oauth.revoke_gmail_token()`) and always deletes the
  local `GmailCredential` row, marking the account `"disconnected"`.
- **Outlook / Microsoft Graph provider (message-fetching only)** —
  done. `backend/email_sync/outlook_provider.py` implements
  `EmailProvider` against Graph's `/me/messages` (`$search`/`$filter`
  list + pagination via `@odata.nextLink`, `/messages/{id}/$value`
  for raw MIME, error classification off the HTTP status code).
  Fully mock-tested, no OAuth of its own — same message-fetching-
  only split as the Gmail provider.
- **Outlook OAuth (connect/callback, encrypted token storage, real
  session_factory)** — done. `backend/email_sync/outlook_oauth.py` +
  `views.py`/`urls.py`. `OutlookCredential` model (its own Fernet
  key, `MICROSOFT_TOKEN_ENCRYPTION_KEY`, separate from Gmail's), `GET
  /api/email-accounts/outlook/{connect,callback}`, registers
  `get_provider("outlook")` for real use. Disconnect
  (`outlook_oauth.disconnect_outlook_account()`) is local-only —
  unlike Google's v2 endpoint, Microsoft's v2.0 flow has no
  application-callable revoke API (see that module's own docstring).
- **Not started:** generic IMAP provider; the background-task runner
  (Celery/Redis or Django-Q) — sync now has a manual per-account
  trigger but nothing scheduled or workspace-wide; any frontend UI
  for connecting an account, triggering a sync, disconnecting one, or
  reviewing Discoveries/AccountMatches.

## Phase 10 — Production deployment

- Postgres in production; media on S3; static files via whitenoise or
  a CDN.
- Background worker process for Celery (or equivalent) running
  alongside the web process.
- One-off management command to migrate your real existing local data
  (from the current SQLite files) into the new schema — not a manual
  process.
- HTTPS, logging, backups, permissions review.

---

## Branch roadmap

```text
django-migration
├── 1. Characterize current application (Phase 0)
├── 2. Django skeleton (Phase 1)
├── 3. Auth + Workspace ownership (Phase 2)
├── 4. Core models (Phase 3)
├── 5. File storage (Phase 4)
├── 6. Migrate domain logic (Phase 5)
├── 7. Job Postings (Phase 6)
├── 8. Django Admin (Phase 7)
├── 9. DRF API + frontend integration (Phase 8)
├── 10. Email sync rewrite (Phase 9)
├── 11. Integration tests against Phase 0 baseline
└── 12. Production configuration + deployment (Phase 10)
```

## Why this order

Auth and ownership (Phase 2) come before the data models they'll be
attached to (Phase 3) — building models first and retrofitting a
`user` FK onto live models and their queries later is the rework this
order exists to avoid. Email sync (Phase 9) comes last among the
functional work because it's a full rewrite, not a port, and you want
everything else — auth, models, storage, the API surface — proven
solid before taking on the riskiest piece.

---

## Appendix — Phase 0 endpoint inventory

67 routes in the current `_app/api.py`, grouped by the Django app
boundary each maps to.

**System / diagnostics** (`core`)
`GET /api/status` · `GET /api/diagnostics` ·
`POST /api/diagnostics/reveal-log` · `GET /api/health`

**Workspaces** (`workspaces`)
`GET/POST /api/workspaces` · `POST /api/workspaces/inspect` ·
`POST /api/workspaces/link` · `POST /api/workspaces/import` ·
`POST /api/workspaces/import-folder` ·
`POST /api/workspaces/import-folder-local` ·
`GET /api/workspaces/{id}/export` · `POST /api/workspaces/switch` ·
`POST /api/workspaces/{id}/rename` · `DELETE /api/workspaces/{id}` ·
`POST /api/rebuild`

**Email accounts & sync** (`email_sync`) — *the whole cluster is the
Phase 9 rewrite target; do not design its DRF shape ahead of Phase 9*
`GET /api/accounts` · `GET /api/accounts/mail-app/available` ·
`POST /api/accounts/mail-app/connect` · `DELETE /api/accounts/{id}` ·
`POST /api/accounts/reset-email-sync` ·
`POST /api/accounts/{id}/sync` · `POST /api/accounts/{id}/discover`

**Discoveries** (`email_sync`)
`GET /api/discoveries` · dismiss / restore / preview / mark-posting /
dismiss-sender / sender-classification / attach / accept (all
`{discovery_id}`-scoped) · `POST /api/discoveries/backfill-email-pdfs`

**Job postings** (`postings`) — Phase 6
`GET /api/job-postings` · dismiss / restore / save / apply (all
`{job_id}`-scoped)

**Applications** (`applications`)
`GET /api/applications` · `GET /api/applications/{id}/documents` ·
`GET /api/applications/{id}/dossier` ·
`POST /api/applications/{id}/documents` · `POST /api/applications/new` ·
override (single + bulk) · delete (single + bulk)

**Categories & documents** (`documents`) — Phase 4, the
folder→storage rewrite; `/api/file` and `/api/preview-docx` change
shape here too (local-path traversal guard → "fetch object the user
owns")
`POST/GET /api/categories/new`, `/api/categories` ·
`POST /api/categories/{folder}/override` ·
`POST /api/categories/{folder}/delete` · `POST /api/documents/delete` ·
`POST /api/documents/rename` · `POST /api/documents/override`

**Cross-cutting views** (`core`)
`GET /api/attention` · `GET /api/insights` · `GET /api/search` ·
`GET /api/browse` · `GET /api/manage` (+ merge/unmerge) ·
`GET/POST /api/hub/settings` · `POST /api/open` ·
`POST /api/open-url` · `GET /api/file` · `GET /api/preview-docx`

**Two things this inventory flags for later phases:**

1. `/api/file` and `/api/preview-docx` currently serve from a local
   path via `infrastructure/paths.py`'s traversal guards. On
   storage-backed `Document` models (Phase 4) they become "fetch this
   object the user owns" — a different and simpler permission check,
   not a like-for-like port.
2. The accounts/discoveries/sync cluster (13 routes) maps one-to-one
   onto Phase 9. Its underlying data model changes once Mail.app is
   gone — real per-provider `EmailAccount` records with OAuth tokens
   replace "is Mail.app available" — so its DRF shape shouldn't be
   locked in before Phase 9 actually starts.
