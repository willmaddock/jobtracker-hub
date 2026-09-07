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
