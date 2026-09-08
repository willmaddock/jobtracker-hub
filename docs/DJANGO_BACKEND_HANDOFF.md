# JobTracker Hub — Living Django Backend Handoff

> **Purpose:** This is the living handoff document for the Django
> migration's `backend/` track (`docs/DJANGO_MIGRATION_PLAN.md`),
> starting from Phase 9 (email sync). It exists because that plan
> document is deliberately a stable, forward-looking *plan* — Phase
> 0-10, why-this-order — not a place to record what's actually been
> built session by session. This file is that record.
>
> This is a sibling to `docs/troubleshooting/CLAUDE_HANDOFF.md`, which
> is the equivalent living doc for the *other*, older codebase in this
> repo: the single-user `_app/` FastAPI app's Email Sync / Job Postings
> redesign. Don't conflate the two — they track different code
> (`backend/` vs `_app/`), different architectures (multi-user Django
> vs single-user desktop), and this doc has no macOS/Mail.app/Safari
> manual-validation requirement, since the Django backend has none of
> that dependency. If a future session isn't sure which doc applies,
> check which directory the change touches.
>
> **Rule:** keep this file current. A new Claude session working on
> `backend/` should read this file first, inspect the actual
> repository (`backend/email_sync/`, `docs/DJANGO_MIGRATION_PLAN.md`'s
> Phase 9 progress summary), and continue from there rather than
> relying on chat history.

---

## 0. Workspace boundary

Same physical-handoff model as `CLAUDE_HANDOFF.md` describes for
`_app/` (see that file's §0A) — a Claude sandbox here is a temporary
workspace, not the user's real Git checkout:

- An uploaded zip is a source snapshot, not a live repo. No `git init`,
  no commit, no push from this workspace.
- The returned zip is the physical handoff artifact. A filename printed
  by a shell command is not a handoff — the zip must actually be
  attached via `present_files` so the user can access it.
- The user applies/reviews/commits/pushes changes on their own machine.
- Before running low on context, stop feature work, update this file,
  and return a zip rather than pushing further into a task with no
  room to hand off safely.

## 1. What's different about validating this track

Unlike `_app/`'s Mail.app-dependent code, `backend/` is a normal Django
project: `python manage.py test` runs for real in a Linux sandbox with
PyPI access, with no macOS/Safari/Mail.app dependency anywhere in the
loop. That means — and this matters for how much to trust a given
checkpoint below — "tests pass" here is not a hedge the way it
sometimes had to be for `_app/`'s checkpoints; when a checkpoint below
says the suite passed, it means `manage.py test` was actually invoked
and its output actually read, in-sandbox or on the user's own machine
(noted per checkpoint). The one thing still genuinely unverified by
any of this is real Google OAuth end-to-end (a real consent screen, a
real Gmail account) — every OAuth-facing test mocks
`google_auth_oauthlib`/`googleapiclient` at the seam, by design (see
§4 Known Gaps).

## 2. Current state (as of the last checkpoint below)

- `backend/email_sync/matching.py` — thread-ID matching, sender
  whitelisting, subject classification, ported from `mail_app_store.py`.
- `backend/email_sync/providers.py` — the `EmailProvider`/
  `FetchedMessage` contract + `ProviderAuthError`/`ProviderTemporaryError`
  + provider registry (`register_provider`/`get_provider`).
- `backend/email_sync/sync_service.py` — `sync_account()`: thread
  trust, posting-notice routing, term matching, idempotent
  `get_or_create` upserts, one `@transaction.atomic` block.
- `backend/email_sync/gmail_provider.py` — `GmailProvider`, a real
  Gmail API `EmailProvider` implementation (list/get, pagination,
  401/403/429/5xx error classification). Takes `service_factory` as a
  constructor arg; doesn't know or care where credentials come from.
- `backend/email_sync/oauth.py` — Gmail OAuth: `GmailCredential` model
  (Fernet-encrypted tokens), `build_authorization_url()`,
  `complete_gmail_connection()`, `gmail_service_factory()` (the real
  `service_factory` for `GmailProvider`, with refresh-on-expiry), and
  `@register_provider("gmail")` wiring so `get_provider("gmail")`
  resolves to a working instance.
- `backend/email_sync/views.py` + `urls.py` — `GET
  /api/email-accounts/gmail/connect` and `.../gmail/callback`,
  workspace-ownership-checked, session-based OAuth CSRF state.
- `backend/requirements.txt` — `google-api-python-client`,
  `google-auth`, `google-auth-oauthlib`, `cryptography` added.
- `backend/email_sync/views.py` + `urls.py` — `EmailAccountSyncView`:
  `POST /api/email-accounts/<id>/sync`, the manual "sync now" trigger
  wiring `sync_service.sync_account()` up to something callable at
  all (no scheduling yet — see §4).
- `backend/email_sync/oauth.py` + `views.py`/`urls.py` —
  `disconnect_gmail_account()` + `EmailAccountDisconnectView`: `POST
  /api/email-accounts/<id>/disconnect`. Best-effort revokes the grant
  with Google (`revoke_gmail_token()`, POSTing to Google's
  `/revoke` endpoint) and always deletes the local `GmailCredential`
  row + marks the account `"disconnected"`, even if the revoke call
  itself fails or the stored token can't be decrypted. Non-Gmail
  accounts (no credential model exists for them yet) just get a
  status flip. Idempotent on an already-disconnected account.
- `backend/requirements.txt` — added `requests` explicitly (previously
  only a transitive dependency of the google-* packages;
  `oauth.py`'s revoke call now uses it directly).
- Full backend suite last stood at **450/450 passing — confirmed on
  the user's own machine** (Outlook/IMAP checkpoints; see §3/§4).
- `backend/config/celery.py` + `config/__init__.py` — the Celery
  application (`config.celery.app`), configured from Django settings
  under the `CELERY_` namespace, autodiscovering `<app>/tasks.py`
  across `INSTALLED_APPS`.
- `backend/config/settings/base.py` — `CELERY_BROKER_URL`/
  `CELERY_RESULT_BACKEND` (Redis), serializer settings,
  `CELERY_TASK_ALWAYS_EAGER` (env-controlled, off by default), and
  `CELERY_BEAT_SCHEDULE` (a 15-minute `sync_all_accounts_task` entry).
- `backend/email_sync/tasks.py` — `sync_account_task(account_id)` (the
  per-account background unit, mirroring `EmailAccountSyncView`'s
  provider-resolve-then-`sync_account()` sequence) and
  `sync_all_accounts_task()` (fans out one `sync_account_task.delay()`
  per currently-connected `EmailAccount`; this is both the Beat
  schedule's entry point and what the new bulk endpoint below
  dispatches to).
- `backend/email_sync/views.py` + `urls.py` — `EmailAccountSyncAllView`:
  `POST /api/email-accounts/sync-all`, the "sync all of a workspace's
  accounts" bulk endpoint flagged as missing in §4 below. Scoped to
  `workspace__owner=request.user`; dispatches, doesn't sync inline.
- `backend/requirements.txt` — `celery`/`redis` added, as
  minimum-version bounds rather than exact pins (see that file's own
  comment on this checkpoint for why — no network access this session
  to freeze a real install against, same constraint as every earlier
  checkpoint here).

## 3. Checkpoint history

### Checkpoint — matching.py (slice 1)

Pre-dates this handoff doc's creation; reconstructed from context. The
`matching.py` port + `test_matching.py` existed before the sync-
orchestration work below started. Tests reportedly passing at the
time; not independently re-verified until the slice-2 checkpoint below,
which re-ran the full suite including these tests.

### Checkpoint — sync orchestration layer (slice 2: `providers.py` + `sync_service.py`)

Built `providers.py` (interface) and `sync_service.py` (orchestration)
against the slice-1 `matching.py`, plus `test_sync_service.py` (~20
tests against an in-memory `FakeProvider`). Initially hand-traced
(sandbox had no network to install Django), then **the user ran
`manage.py test` for real on their own machine: 289/289 passing** (19
new + 270 pre-existing).

### Checkpoint — Gmail provider (slice 2b: `gmail_provider.py`)

User supplied `gmail_provider.py` (message-fetching only, no OAuth —
takes `service_factory` as a constructor arg per its own module
docstring). Integrated it into the repo, wrote
`test_gmail_provider.py` (16 tests against a hand-built fake that
duck-types `googleapiclient.discovery`'s Resource surface — no real
Google library needed to run these). Ran for real in-sandbox: 16/16,
full suite **305/305**. **User then ran the same on their own Mac:
305/305**, confirmed matching.

### Checkpoint — Gmail OAuth (slice 2c: `oauth.py` + views)

Built the OAuth connect/callback flow, `GmailCredential` model
(Fernet-encrypted token storage), `gmail_service_factory()` (the real
`service_factory` `GmailProvider` needed), and provider registration.
25 new tests (14 `test_oauth.py` + 11 `test_gmail_oauth_views.py`), all
mocking Google's own libraries at the `Flow`/`build_gmail_client`/
`Credentials` seam. Ran in-sandbox: 25/25, full suite **330/330**,
`makemigrations --check` clean. **Confirmed on the user's own
machine: 330/330 matching the sandbox exactly.**

### Checkpoint — manual "sync now" endpoint (slice 3)

Built `EmailAccountSyncView` (`backend/email_sync/views.py` +
`urls.py`): `POST /api/email-accounts/<id>/sync`, scoped to
`workspace__owner=request.user` (404, not 403, on another user's
account — same pattern as every other per-object action in this
codebase, e.g. `postings/views.py`'s `JobPostingViewSet`). Resolves a
provider via `providers.get_provider(account.provider)` and calls the
already-fully-tested `sync_service.sync_account()` — no new sync
logic, purely the HTTP layer this had been missing since the OAuth
slice's own docstring flagged it as deferred. Handles:

- account not found / not owned → 404
- `status="disconnected"` → 400 (nothing to sync without credentials)
- no provider registered for `account.provider` (e.g. a legacy
  `mail_app` row) → 400, `ProviderError`'s own message surfaced
- a sync that runs but hits `ProviderAuthError` (revoked grant) → 200,
  not an HTTP error — `sync_account()` itself already handles that by
  marking the account `"blocked"`, so the endpoint reports it as a
  normal (if unsuccessful) result rather than treating it as a server
  failure

No model changes, so no new migration — `makemigrations --check`
still reports nothing pending.

**Tests:** 9 new (`test_email_account_sync_view.py`), all mocking
`email_sync.views.get_provider` with `test_sync_service.py`'s existing
`FakeProvider` rather than touching real Gmail machinery. Full suite:
`python manage.py test` → 339/339 passing in-sandbox, **then
confirmed on the user's own Mac (Python 3.14, Django 6.1.1, DRF
3.18.0): 339/339, matching exactly.**

### Checkpoint — disconnect/revoke flow (slice 4)

Closed the gap `oauth.py`'s own module docstring used to flag as
deferred: disconnecting an account now actually revokes the grant
with Google, not just deletes the local row.

- `oauth.revoke_gmail_token(token)` — POSTs to Google's
  `https://oauth2.googleapis.com/revoke` endpoint. Both a 200
  (revoked) and a 400 (token Google no longer recognizes — already
  revoked or expired from disuse) are treated as success; only a
  network failure or a 5xx raises `ProviderError`.
- `oauth.disconnect_gmail_account(account)` — the full flow: recovers
  a token from the stored `GmailCredential` (refresh token first,
  falling back to the access token if the refresh token can't be
  decrypted), best-effort revokes it, then **always** deletes the
  `GmailCredential` row and marks the account `"disconnected"` — even
  if revoke fails outright or no credential row exists at all. Local
  cleanup is unconditional by design; Google-side revoke is
  best-effort on top of it, not a precondition for it.
- `EmailAccountDisconnectView` (`views.py` + `urls.py`) — `POST
  /api/email-accounts/<id>/disconnect`, same `workspace__owner`
  ownership scoping as the sync-now view. Routes to
  `oauth.disconnect_gmail_account()` for `provider="gmail"` accounts;
  for any other provider (no credential model exists yet), just flips
  `status` to `"disconnected"`. Idempotent — calling it again on an
  already-disconnected account is a no-op that still returns 200.
- `backend/requirements.txt` — added `requests` explicitly, since
  `revoke_gmail_token()` now imports and calls it directly rather than
  relying on it only being present transitively via `google-auth`/
  `google-api-core`.

No model changes, so no new migration — `makemigrations --check`
still reports nothing pending.

**Tests:** 14 new — 9 in `test_oauth.py` (`RevokeGmailTokenTests`,
`DisconnectGmailAccountTests`, covering the revoke-endpoint response
handling, the refresh-token→access-token fallback, and every "still
must clean up locally" case: no credential row, an undecryptable
token, and a revoke call that raises) + 5 in
`test_email_account_disconnect_view.py` (ownership, provider routing,
idempotency, and one end-to-end test against a real encrypted
`GmailCredential` row). Full suite: `python manage.py test` →
355/355 passing in-sandbox, **then confirmed on the user's own Mac
(Python 3.14, Django 6.1.1, DRF 3.18.0): 355/355, matching exactly.**

---

### Checkpoint — Outlook / Microsoft Graph, the second provider (commit `75f86c2`)

Second `EmailProvider` implementation, mirroring the Gmail slice's own
split (message-fetching provider / OAuth+credential-storage module /
views+urls) rather than introducing a new shape:

- `backend/email_sync/outlook_provider.py` — `OutlookProvider`, a real
  Microsoft Graph `EmailProvider` implementation: `GET /me/messages`
  with `$search`/`$filter`, `@odata.nextLink` pagination,
  `/messages/{id}/$value` for the raw MIME source, error
  classification off the HTTP status code (401/403 → auth, 429/5xx →
  temporary). Message-fetching only, same as `gmail_provider.py` — no
  OAuth of its own, takes a `session_factory` the same way
  `GmailProvider` takes a `service_factory`.
- `backend/email_sync/outlook_oauth.py` — Microsoft identity platform
  v2.0 authorization-code flow via plain `requests` (no new
  dependency — see that module's own docstring on why not `msal`):
  `OutlookCredential` model (own `MICROSOFT_TOKEN_ENCRYPTION_KEY`
  Fernet key, separate from Gmail's), `build_authorization_url()`,
  `complete_outlook_connection()`, `outlook_session_factory()` (the
  real `session_factory`, with refresh-on-expiry), and
  `@register_provider("outlook")` wiring. Notably: `disconnect_
  outlook_account()` is local-only — unlike Google's v2 revoke
  endpoint, Microsoft's v2.0 flow has no application-callable
  "revoke this refresh token" API for either personal or work/school
  accounts, so disconnect deletes the local credential but can't
  invalidate the grant on Microsoft's side.
- `views.py`/`urls.py` — `OutlookConnectView`/`OutlookOAuthCallbackView`
  (`GET /api/email-accounts/outlook/{connect,callback}`), mirroring
  `GmailConnectView`/`GmailOAuthCallbackView` field-for-field
  (workspace ownership check, session-stashed CSRF state, same 503 on
  missing app-registration config). `EmailAccountDisconnectView` now
  branches three ways: `gmail` → `oauth.disconnect_gmail_account()`,
  `outlook` → `outlook_oauth.disconnect_outlook_account()`, anything
  else → plain status flip.
- `models.py` — `OutlookCredential` (mirrors `GmailCredential` field-
  for-field), migration `0004_outlookcredential.py`. `EmailAccount.
  PROVIDER_CHOICES`'s `"outlook"` label changed from `"Outlook
  (legacy)"` to `"Outlook"` — same meaning-shift `"gmail"` already went
  through when its own OAuth slice landed.
- `config/settings/base.py` — `MICROSOFT_OAUTH_CLIENT_ID`/`_SECRET`/
  `_REDIRECT_URI`, `MICROSOFT_TOKEN_ENCRYPTION_KEY` (own dev-only
  fallback key, same checked-into-source-control caveat as Gmail's).
- `admin.py`/`apps.py` — `OutlookCredential` registered (token fields
  excluded, same redaction as `GmailCredentialAdmin`);
  `email_sync.outlook_oauth` imported in `AppConfig.ready()` alongside
  `oauth` so `get_provider("outlook")` resolves regardless of import
  order.
- `requirements.txt` — comment-only update; no new package.

**Tests:** 45 new — 15 in `test_outlook_provider.py` (query building,
fetch/parse, pagination via `@odata.nextLink`, `since`-filtering,
401/403/429/5xx classification, HTML-only body fallback, missing
Message-ID/Date handling), 18 in `test_outlook_oauth.py` (encryption
round-trip, credential storage/update, authorization URL, connect
flow incl. `mail`-null → `userPrincipalName` fallback and reconnect-
revives-disconnected-row, access-token load/refresh, session factory,
provider registration, disconnect), 10 in `test_outlook_oauth_views.py`
(mirrors `test_gmail_oauth_views.py`'s ownership/session-state/status-
code coverage), + 2 added to `test_email_account_disconnect_view.py`
(outlook routing, end-to-end real-`OutlookCredential`-row deletion).
Full suite: `python manage.py test` → 400/400 passing in-sandbox,
**then confirmed on the user's own Mac (Python 3.14, Django 6.1.1,
DRF 3.18.0): 400/400, matching exactly.**

**Known gaps introduced or closed by this checkpoint:** closes the
"Microsoft Graph / generic IMAP providers — not started" gap for the
Graph half specifically (IMAP is still not started); introduces the
same "never validated against a real account" gap Gmail's OAuth slice
already had, now true for Outlook too (no real Azure AD app
registration has been created or clicked through) — see §4 below.

**Next action:** see §5 below.

---

### Checkpoint — Generic IMAP, the third provider

Third `EmailProvider` implementation, mirroring the Gmail/Outlook
slices' own split (message-fetching provider / credential-storage
module / views+urls) rather than introducing a new shape — but with
one structural difference from both: there is no OAuth authorization
server for generic IMAP to redirect to, so the "connect" step is a
single direct POST carrying a username/password (typically an
app-specific password), verified with a real IMAP login before
anything is stored, rather than a connect/callback pair.

- `backend/email_sync/imap_provider.py` — `ImapProvider`, a real
  IMAP4 (RFC 3501) `EmailProvider` implementation: `SEARCH` built as a
  right-nested binary `OR` chain (IMAP has no native N-way OR the way
  Gmail's/Graph's query strings do) of `SUBJECT`/`BODY` term matches
  plus `FROM` matches against the known ATS sender domains, ANDed with
  a `SINCE` date bound (day-granularity only — IMAP's SINCE has no
  time-of-day component); `FETCH ... (RFC822)` for the raw message
  source; a 500-message safety cap per sync pass. Message-fetching
  only, same as `gmail_provider.py`/`outlook_provider.py` — no
  connection setup of its own, takes a `client_factory` the same way
  `GmailProvider`/`OutlookProvider` take a `service_factory`/
  `session_factory`.
- `backend/email_sync/imap_auth.py` — the whole connect flow in one
  module, since there's no separate callback step: `connect_imap_
  account()` takes host/port/username/password directly, opens a real
  `imaplib.IMAP4_SSL` connection, logs in, and `SELECT`s INBOX —
  *before* storing anything, so a typo'd password never leaves a
  "connected" `EmailAccount` with credentials that don't actually
  work sitting around (unlike the OAuth providers, there's no later
  sync that would discover that and flip the account to "blocked";
  this connect-time check is the only chance to catch it). Rejects
  `outlook.com`/`hotmail.com`/`live.com`/`msn.com` up front, before
  attempting any connection — Microsoft retired IMAP basic-auth for
  those consumer domains, and a LOGIN attempt against them fails in a
  way that looks just like a wrong password, so the rejection message
  points at the Outlook OAuth flow instead of letting that play out.
  `IMAPCredential` model (own `IMAP_TOKEN_ENCRYPTION_KEY` Fernet key,
  separate from Gmail's and Outlook's) stores host/port/username plus
  the encrypted password — no access/refresh token pair the way OAuth
  credentials have, since IMAP basic auth has nothing to refresh.
  `imap_client_factory()` (the real `client_factory`, opening a fresh
  connection + INBOX select per call) and `@register_provider("imap")`
  wiring. `disconnect_imap_account()` is local-only, same reasoning as
  Outlook's: an app password isn't a grant this app can revoke, only
  one the user can change or delete on their provider's side.
- `views.py`/`urls.py` — `ImapConnectView` (`POST /api/email-accounts/
  imap/connect`, body: `workspace`/`email`/`password`/`host`/`port`
  [default 993]/`username` [optional, defaults to `email`]) — one
  view doing what Gmail/Outlook need two for, since there's no
  redirect to come back from. Same workspace-ownership check as the
  OAuth connect views; 503 for an unreachable host, 400 for a
  rejected login or a retired-basic-auth domain. `EmailAccountDisconnectView`
  now branches four ways: `gmail` → `oauth.disconnect_gmail_account()`,
  `outlook` → `outlook_oauth.disconnect_outlook_account()`, `imap` →
  `imap_auth.disconnect_imap_account()`, anything else → plain status
  flip.
- `models.py` — `IMAPCredential` (host/port/username/password fields,
  no token pair), migration `0005_imapcredential.py`.
- `config/settings/base.py` — `IMAP_TOKEN_ENCRYPTION_KEY` (own
  dev-only fallback key, same checked-into-source-control caveat as
  Gmail's/Outlook's).
- `admin.py`/`apps.py` — `IMAPCredential` registered (password field
  excluded, same redaction as `GmailCredentialAdmin`/
  `OutlookCredentialAdmin`; host/port/username shown since they're
  connection details, not secrets); `email_sync.imap_auth` imported
  in `AppConfig.ready()` alongside `oauth`/`outlook_oauth` so
  `get_provider("imap")` resolves regardless of import order.
- `requirements.txt` — comment-only update; no new package (`imaplib`
  is standard library, `cryptography` already pinned for Gmail/
  Outlook's own field-level encryption).

**Tests:** 56 new — 18 in `test_imap_provider.py` (search-criteria
building incl. the binary-OR nesting and ALL/SINCE-only fallbacks,
fetch/parse, the 500-message cap, HTML-only body fallback, missing
Message-ID/Date handling, SEARCH/FETCH failure classification), 24 in
`test_imap_auth.py` (encryption round-trip, blocked-domain rejection
incl. case-insensitivity, connect flow incl. verify-before-store
ordering on every failure path, custom username override, reconnect-
revives-disconnected-row, credential-row overwrite on reconnect,
client factory, provider registration, disconnect), 10 in
`test_imap_connect_view.py` (auth, required-field validation, port
type validation, ownership, success/failure status codes incl. 503
for an unreachable host), + 2 added to
`test_email_account_disconnect_view.py` (imap routing, end-to-end
real-`IMAPCredential`-row deletion). **Confirmed on the user's real
machine: `python manage.py test` → 450/450 passing** (full suite;
this sandbox still has no network access, so this was run outside
it, not sandbox-first-then-confirmed like the Outlook checkpoint's
400/400). `python manage.py test core` → 59/59 passing separately.
One bug surfaced by that real run and fixed before this figure: a
test's hardcoded expectation for `_or_chain` (`"OR a (OR b c)"`)
didn't match the actual right-nesting, which always parenthesizes
the trailing element (`"OR a (OR b (c))"`) — both semantically
identical IMAP SEARCH syntax, but the test string was wrong. Fixed
the test and the two docstring examples that made the same
imprecise claim; the implementation itself was correct and
untouched.

**Known gaps introduced or closed by this checkpoint:** closes the
"generic IMAP provider — not started" gap from §4 below, and — as of
this real 450/450 run — also closes the "never run against a real
interpreter" gap this checkpoint's own Tests section previously
flagged. What remains open is the same gap the OAuth providers still
have: "never validated against a real IMAP mailbox" — no real
app-specific password has been generated and used against a real
mail provider (Fastmail, a self-hosted server, Gmail's own
IMAP-with-app-password path, etc.), the way Gmail/Outlook's OAuth
flows still haven't been validated against real consent screens
either.

**Next action:** see §5 below.

---

### Checkpoint — Celery/Redis background task scheduling

What was built: closes the "no background task runner" gap from §4
below (docs/DJANGO_MIGRATION_PLAN.md Phase 9/10).

- `config/celery.py` — the Celery application (`app = Celery(...)`),
  configured via `app.config_from_object('django.conf:settings',
  namespace='CELERY')` so every Celery setting lives as a
  `CELERY_`-prefixed Django setting rather than a separate
  `celeryconfig.py`, and `app.autodiscover_tasks()` so a future
  `<app>/tasks.py` needs no registration here. `config/__init__.py`
  exposes it as `config.celery_app`, Celery's own documented
  Django-integration pattern — `@shared_task` in `email_sync/tasks.py`
  binds to this app instance without importing `config.celery`
  itself.
- `config/settings/base.py` — `CELERY_BROKER_URL`/
  `CELERY_RESULT_BACKEND` (Redis, both env-overridable, `redis://
  localhost:6379/0` dev default), JSON serializers,
  `CELERY_TASK_ALWAYS_EAGER` (env-controlled, `False` by default —
  real dispatch, not inline execution, is the point), and
  `CELERY_BEAT_SCHEDULE` with one entry: `sync_all_accounts_task`
  every 900 seconds. Deliberately a plain number (seconds), not a
  `celery.schedules.crontab(...)` instance, so this settings module
  still has no top-level `import celery` — consistent with base.py
  not importing any other third-party client library at module level
  either.
- `email_sync/tasks.py` — `sync_account_task(account_id)`: looks up
  the `EmailAccount` by id (ids, not instances, cross the broker —
  Celery arguments are JSON-serialized), resolves its provider, runs
  `sync_service.sync_account()`, and returns a plain dict in the same
  shape `EmailAccountSyncView.post()` already returns as JSON.
  Missing account / disconnected account / unregistered provider are
  all handled as a non-ok result, not a raised exception — Celery's
  default retry-on-exception behavior is the wrong shape for "this
  account will never sync." `sync_all_accounts_task()`: the Beat
  schedule's entry point — looks up every `status="connected"`
  `EmailAccount` across every workspace and fans out one
  `sync_account_task.delay(id)` per account, so one slow/stuck
  account's sync can't block any other account's turn.
- `email_sync/views.py` + `urls.py` — `EmailAccountSyncAllView`:
  `POST /api/email-accounts/sync-all`, the user-triggered counterpart
  to the Beat schedule. Scoped to `workspace__owner=request.user`;
  dispatches one `sync_account_task.delay(id)` per the *authenticated
  user's own* currently-connected accounts and returns immediately
  with the dispatched ids — deliberately a background dispatch, not a
  loop calling `sync_account()` inline, so a user with several slow
  mailboxes doesn't block this one request on all of them in series.
- `requirements.txt` — `celery`/`redis` added as **minimum-version
  bounds** (`celery>=5.4`, `redis>=5.0`), not exact pins — unlike
  every package pinned above this session had no real `pip install`
  to freeze a version against (no network access in this sandbox,
  same constraint every earlier checkpoint here has flagged). Run
  `pip install -r requirements.txt` normally, then replace these two
  lines with an exact `pip freeze` pin the way Django/DRF/the OAuth
  packages already are.

**Tests:** 11 new — 5 in `test_tasks.py` (missing account, disconnected
account, no registered provider, successful sync updates the account
and returns the right dict shape, a `ProviderAuthError` is reported
but the task itself doesn't raise) + 2 in the same file for
`sync_all_accounts_task` (dispatches only `connected` accounts, `.delay`
patched rather than actually run; dispatches nothing when there are
none) + 4 in `test_email_account_sync_all_view.py` (auth required, no
accounts dispatches nothing, only the authenticated user's own
connected accounts are dispatched — not another user's, not a
disconnected one — dispatches every one of several). All new files
pass `py_compile`. **`python manage.py test` has not been run this
session** — same no-network-access constraint as the IMAP checkpoint's
first attempt, except this time there's a second, harder blocker: this
sandbox has neither `celery` nor `redis` installed (nor even `Django`
itself — confirmed by trying `import django` directly, not assumed),
and no network to install them, so nothing Celery-related here has
executed against a real interpreter at all yet, not even a
Celery-broker-free "task called directly as a function" smoke test.
Treat this checkpoint as compiled-but-unexecuted until the user runs
the real suite, same caveat the IMAP checkpoint carried before its own
450/450 confirmation closed it.

**Known gaps introduced or closed by this checkpoint:** closes "no
background task runner" and "no 'sync all of a workspace's accounts'
bulk endpoint" from §4 below. Introduces the same "never run against a
real interpreter" gap every checkpoint here starts with, now the
single biggest unverified piece for this slice specifically — bigger
than the IMAP checkpoint's own unexecuted period, since that one was
still tested against a real Django/DRF install in-sandbox conceptually
possible the whole time (just blocked on network for extra packages);
this one can't even boot `manage.py test` at all without the user's
own machine, because neither Django nor Celery exist in this sandbox.
Also introduces: **no real Redis instance has ever been started
against this code** — every test here calls a task directly as a
function or patches `.delay`, so the actual broker round-trip
(`worker` picking up a message `beat` or a view enqueued) has never
happened, separate from and in addition to the "never run against a
real interpreter" gap above.

**Next action:** see §5 below.

---

## 4. Known gaps / not yet done

- **Real OAuth end-to-end has never actually happened, for either
  OAuth provider.** Every test mocks `google_auth_oauthlib.flow.Flow`/
  `googleapiclient.discovery.build` (Gmail) or `requests.post`/
  `requests.get` against Microsoft's endpoints (Outlook) — nobody has
  registered a real Google Cloud OAuth client or a real Azure AD app
  registration, set `GOOGLE_OAUTH_CLIENT_ID`/`SECRET` or
  `MICROSOFT_OAUTH_CLIENT_ID`/`SECRET` for real, clicked through a
  real consent screen for either provider, or confirmed either
  callback round-trip against the provider's actual token endpoint.
  This is the single biggest unverified piece for those two providers.
  Generic IMAP has no OAuth step to validate this way, but has its own
  equivalent gap — see the IMAP entry below.
- **No disconnect/revoke flow.** ~~Deleting a `GmailCredential` row~~
  — **done.** `EmailAccountDisconnectView` revokes the Gmail grant
  with Google (best-effort) and deletes the local row; for Outlook it
  deletes the local `OutlookCredential` row only — Microsoft's v2.0
  flow has no application-callable revoke API for this app to call
  (see `outlook_oauth.py`'s own module docstring); for IMAP it deletes
  the local `IMAPCredential` row only — an app password isn't a grant
  this app can revoke either (see `imap_auth.py`'s own module
  docstring).
- **No background task runner.** ~~`sync_service.sync_account()` now
  has a manual trigger ... no Celery/Redis or Django-Q wiring at all
  yet, and no "sync all of a workspace's accounts" bulk endpoint
  either.~~ **Done** (see the Celery checkpoint above): `config/
  celery.py` + `email_sync/tasks.py` wire up `sync_account_task`/
  `sync_all_accounts_task`, a 15-minute `CELERY_BEAT_SCHEDULE` entry,
  and `POST /api/email-accounts/sync-all` for a user-triggered bulk
  dispatch. **Compiled-only, never executed** — see that checkpoint's
  own Tests section; this sandbox has neither Celery, Redis, nor
  Django installed, so nothing here has run against a real
  interpreter, let alone a real broker, yet.
- **No frontend.** Every endpoint built so far (`gmail/connect`,
  `gmail/callback`, `outlook/connect`, `outlook/callback`,
  `imap/connect`, `<id>/sync`, `<id>/disconnect`) returns JSON;
  there's no `backend`-served or separate frontend page that calls
  them yet.
- **Generic IMAP provider** — ~~not started~~ ~~done but
  compiled-only, never executed~~ **done and real-machine-confirmed:
  450/450 full suite, 59/59 for `core` alone.** Still never validated
  against a real IMAP mailbox with a real app-specific password.
  `EmailAccountDisconnectView`'s "any other provider" branch (a plain
  status flip, no credential model) now has no real remaining
  provider to matter for — every provider in `PROVIDER_CHOICES`
  except the legacy `mail_app`/`icloud` rows now has a real
  implementation.
- Every checkpoint's test-count claim through the IMAP checkpoint is
  real-machine-confirmed, not just sandbox — matching.py, sync
  orchestration, both OAuth providers, generic IMAP, the sync-now
  endpoint, and the disconnect flow have all had their exact figure
  independently reproduced on the user's own Mac (450/450 as of the
  IMAP checkpoint). The Celery checkpoint above has **not** gone
  through any of that yet — it needs `pip install -r requirements.txt`
  to even get Celery/Redis onto the user's machine before `manage.py
  test` can run at all, a heavier prerequisite than any earlier
  checkpoint here (those only needed already-installed Django/DRF plus
  whatever that checkpoint's own new package was).

## 5. Next action

1. **Run `pip install -r requirements.txt` then `python manage.py
   test` for real, on the user's own machine, before anything else.**
   The Celery checkpoint above is compiled-only and has never
   executed — a heavier ask than any earlier checkpoint's "just run
   the suite," since `celery`/`redis` need to actually land in the
   venv first (they weren't there before this checkpoint), and a real
   `redis-server` needs to be running locally for anything beyond the
   `.delay`-patched unit tests to mean much end-to-end (the unit tests
   themselves don't need a running Redis — only a real worker/beat
   process would).
2. Decide whether real OAuth end-to-end validation (a real Google
   Cloud project + real Azure AD app registration, real client
   id/secret pairs for both, actual consent-screen click-throughs) and
   a real IMAP mailbox validation (a real app-specific password against
   a real provider) happen now or are deferred further — these need the
   user's own accounts/setup, not something a sandbox can do
   unprompted. Doing all three providers' validation in the same pass
   is probably more efficient than three separate sessions, now that
   all three exist.
3. Once item 1 passes, decide whether to actually run `celery -A
   config worker -l info` and `celery -A config beat -l info` locally
   against a real `redis-server` — that's the only way to confirm the
   Beat schedule and `.delay()` dispatch work end-to-end, since no
   test here exercises a real broker. Separately, a frontend for any
   of this is still not started and not yet decided with the user
   either.
4. Separately, worth the user's own attention: the user's `git status`
   (on branch `django-migration`) has historically shown a mix of
   unrelated pre-existing changes alongside this track's work —
   modified `README.md`, `docs/README.md`,
   `docs/troubleshooting/CLAUDE_HANDOFF.md`, several
   `backend/*/admin.py`/`models.py`/`services.py` files, and three
   deleted `tests.py` files (`applications/`, `documents/`,
   `postings/` — likely superseded by the `tests/` *packages* that
   already exist as untracked directories per that same status output,
   not an accidental deletion, but worth the user double-checking).
   Re-check `git status` at the start of the next session rather than
   assuming this is still accurate — it predates the IMAP checkpoint
   and may already be resolved.

## 6. Checkpoint template

Use this for future entries in §3:

```markdown
### Checkpoint — <short description> (<date if known>)

What was built, in the same level of detail as the entries above:
which files, what they do, why (link back to
DJANGO_MIGRATION_PLAN.md's Phase 9 progress bullets where relevant
rather than re-explaining the whole slice boundary).

**Tests:** exact command run, exact result (N/N passing), and whether
that's sandbox-only or confirmed on the user's real machine — always
state which, never leave it ambiguous.

**Known gaps introduced or closed by this checkpoint:** update §4
to match.

**Next action:** update §5 to match.
```
