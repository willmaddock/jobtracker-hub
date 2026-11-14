# Gateway mode: Django sign-in in front of the original JobTracker app

`JTH_GATEWAY=true` (set in `backend/.env.example`) changes what happens after sign-in.

## DOCX containment and preview cancellation — 2026-11-13

This uncommitted increment follows local security checkpoint `e26ea79`. It supersedes
the historical DOCX/drawer-cancellation caveats in the earlier checkpoint sections below.
Django templates remain the hosted direction; these changes protect the legacy fallback.

`_app/docx_preview.py` converts with `external_file_access=False` and
`include_embedded_style_map=False`, then sanitizes using `nh3==0.3.7`. Both runtime
manifests require Mammoth >=1.12.2. Missing dependencies fail closed with HTTP 501;
conversion failures return a generic error and never rewrite the original document.
The existing `{html, warnings}` response and safe-root path checks are retained.

Only explicit formatting elements/attributes survive. Links become inert text; scripts,
document styles, forms, frames, active content and navigation/resource attributes are
removed. Embedded PNG/JPEG/GIF/WebP images require matching byte signatures; the sanitizer
admits only exact data URIs issued by that conversion's image handler. SVG, unsupported
images and mislabeled content are omitted with a warning. This validates format signatures,
not full image decoding or immunity to browser image-decoder vulnerabilities.

DOCX HTML is never parsed in the parent DOM. `document-preview.js` wraps the sanitized
fragment with a CSP before any content: deny by default, no scripts/connections/frames/
forms/base changes, data images only, and a SHA-256-authorized fixed stylesheet. The iframe
uses `sandbox=""` and `referrerpolicy="no-referrer"`; no script or same-origin permission
is granted. All document hyperlinks, including external and footnote links, are inert.
Sandboxing alone does not prevent every self-navigation, so server sanitization remains
essential. The native PDF embed stays separate. Text previews retain escaped HTML wrapping
and gain the scriptless sandbox; text downloads retain their existing wrapped-HTML semantics.

Each drawer owns cancellable operations, a document identity, generation and blob URLs.
Close/switch/unmount/session invalidation abort owned requests, remove viewers and release
URLs. Late results are discarded even if a transport ignores abort. Gateway `file()` accepts
an AbortSignal; canceled GET/HEAD consumers cannot allocate a late blob or wait indefinitely
for a shared completion check. Other readers keep their authoritative check. Canceled unused
responses discard their idle timer. End listeners can unsubscribe to avoid retaining drawers.
Authentication, lineage, CSRF, MFA and write/replay behavior are unchanged.

DOCX preview fetches conversion only. Its original is fetched on explicit Download, using
authenticated blobs in gateway mode and a genuine native URL in desktop mode. PDF/text blobs
can be reused for download. Previews have a 60-second deadline; intentional downloads retain
the existing ten-minute allowance. Both are canceled on abandonment before browser handoff.
Once handed off, a browser/OS download belongs to that download manager. The upstream proxy
owns a closable iterator, closing response/socket on EOF/error/close even before iteration.

Limits: browser abort does not forcibly terminate synchronous conversion or a blocking read
already running upstream. WSGI disconnect detection can be delayed; the existing socket
timeout remains. Large documents still buffer in browser memory. Converter process isolation,
CPU/ZIP/image-size quotas, production ingress limits and capacity testing remain hosting
requirements. No application models, schema, auth contract or deployment settings changed.

New permanent regressions first failed against the parent: ten Python failures (including
the real OOXML javascript hyperlink), two gateway file-cancellation failures, and stream-close
failures. The new preview module initially failed to load before implementation.

Verification commands (from repository root unless stated otherwise):

```sh
PYTHONDONTWRITEBYTECODE=1 backend/venv/bin/python -B -m pytest \
  tests/test_docx_preview.py tests/test_file_serving.py -q -p no:cacheprovider
node --test tests/frontend/*.test.cjs
backend/venv/bin/python -B tests/frontend/run_gateway_security.py
```

Node is not on this host shell's PATH; verification used the existing Node tool runtime's
`node:test.run({files})` with child-process isolation. Django commands/settings remain in
[Disposable verification](#disposable-verification). PostgreSQL requires a separately created
disposable database; never point those settings at an existing database. The browser fixture
converts actual generated OOXML, drives the real drawer, and uses CDP mouse input in opaque
iframe targets. Request-volume measurements use transport-only fixture tabs to exclude
unrelated React initialization/lifecycle checks; real-tab lifecycle tests remain separate.

macOS/Python 3.14 and Linux/Python 3.12 binary-wheel imports/conversion are verified. The
desktop specification includes the entire frontend folder, so the new JS is included by
that rule. PyInstaller is not installed: a frozen build, bundled nh3 extension loading,
packaged WKWebView and current Safari remain unverified. No packaging files changed.

Approved file inventory (19; four new):

```text
_app/api.py
_app/docx_preview.py (new)
_app/frontend/index.html
_app/frontend/document-preview.js (new)
_app/frontend/gateway-session.js
_app/requirements.txt
backend/requirements.txt
backend/core/frontend.py
backend/gateway/views.py
backend/gateway/tests.py
tests/test_docx_preview.py (new)
tests/test_file_serving.py
tests/frontend/document-preview.test.cjs (new)
tests/frontend/gateway-session.test.cjs
tests/frontend/gateway-security-browser.html
tests/frontend/serve_gateway_security.py
tests/frontend/run_gateway_security.py
docs/GATEWAY.md
docs/DJANGO_MIGRATION_STATUS.md
```

Actual final counts and verification limitations are recorded in the current
[migration status](DJANGO_MIGRATION_STATUS.md). All tests use synthetic/disposable storage;
no real tracker, existing application database, migration, commit or deployment was used.

```
browser ──► Django (sign-in, email code, MFA, sessions)
              │  every /api/* request that is not /api/auth/*, /api/account/*, /api/health
              ▼
        gateway proxy ──► the signed-in user's own uvicorn process (127.0.0.1, random port, secret token)
                              runs _app/api.py unchanged, via _app/gateway_asgi.py
```

* `/` shows Django's sign-in and MFA screens until the session is fully verified, then serves the
  original UI, with account/security/sign-out controls. An uncertain or changed session clears
  the mounted UI and offers a fresh server-verified reload.
* Each user gets `jth-data/users/<id>/` (override with `JTH_DATA_DIR`) holding their own
  `state/` (tracker registry, indexes), `home/` (their tracker folders and uploaded documents)
  and `logs/app.log`. Processes start on first request, are shared by all web workers (file lock),
  and stop after `JTH_IDLE_MINUTES` idle: run `python manage.py jth_stop_backends` from cron, or
  `--all` to stop everything.
* The private process only answers requests carrying a per-process secret token, and starts with a
  minimal environment (no Django secrets or cloud credentials).

## Endpoints blocked on a server

`_app/gateway_policy.py` refuses, in both the proxy and the private process: `/api/open`,
`/api/open-url`, `/api/diagnostics*`, `/api/workspaces/import-folder-local`, everything under
`/api/accounts/` except listing (Mail.app sync needs macOS), and `/api/workspaces/link` + `/inspect`
(they read arbitrary server folders). The last two can be switched on for **superusers only** with
`JTH_ALLOW_LOCAL_LINK=true`, intended for running on your own computer so you can link an existing
JobTracker folder in place instead of uploading it.

## Getting your existing applications in

* On your own Mac: sign in as a superuser (`python manage.py createsuperuser`, then sign in with
  that account) with `JTH_ALLOW_LOCAL_LINK=true`, and use **Link existing folder**.
* On a server, or for any other user: use **Import** (zip of the tracker folder, or folder upload).

## Known limits

* Unix only (uses `fcntl`, process groups). Not for Windows hosting.
* Email sync via Mail.app is unavailable. Documents live on the server's disk, not the user's machine.
* Django's own workspace/applications API and `/app/` pages are not used in this mode.
* The Django data model and the original app's folders are separate stores; nothing syncs between them.
* Behind a TLS proxy set `JTH_MAX_UPLOAD_MB` and the proxy's body-size and timeout limits to match.


## Browser session lineage (protocol v2)

Django templates remain the primary hosted-product direction; this gateway is the reference
and fallback. Restrictions are conditional on `JTH_GATEWAY=true`. Ordinary deployments retain
Django's original session middleware behavior and native authentication flows.

`GatewaySessionLineage` owns a browser lineage: UUID primary key, positive bigint generation,
unique nullable current Django session key, and indexed expiry. A separate signed, host-only,
HttpOnly, SameSite=Lax cookie identifies the lineage. HTTPS uses a Secure `__Host-` cookie;
local development uses a distinct name. Login, MFA, logout and normal replies never reissue
this cookie. The ordinary Django session remains the authentication authority; its mirror of
lineage ID/generation must match the live authority row and incoming session key.

A signed `X-JTH-Context` contains `{v:2,l,g,p,a}`: lineage UUID, decimal-string generation,
authentication phase and decimal-string principal (null for anonymous). It expires after 24
hours; a valid root reload can issue a new context. Contexts never travel in URLs, persistent
browser storage or browser broadcasts. The context never replaces authentication, ownership,
CSRF, MFA or WebAuthn verification, and never chooses a tracker backend.

**Concurrent transitions: first successful server commit wins.** Two login requests using the
same context cannot both succeed. The loser is rejected without setting/deleting session or
lineage cookies, even if the winning response's headers are withheld. To supersede a committed
but undelivered login, explicitly restart that lineage first, then sign in using the resulting
anonymous context. A delayed earlier cookie cannot match the pinned current session and is
rejected with `409 gateway_session_obsolete`; it cannot silently bootstrap a competing login.

Successful primary password/email attempts, logout and explicit restart increment generation.
Primary proof retires the previous authentication/challenges before starting a new attempt,
including same-account sign-in. MFA/recovery/passkey completion and legitimate session-key
rotation preserve the attempt generation while pinning the new session key atomically. The
actual factor-user resolver and completion boundary check the pending principal and expiry;
expired pending MFA never falls back to another authenticated user. Enrollment confirmation is
classified separately: the existing enrollment/verified/mfa policy phases require an exact
current snapshot and the actual authenticated principal matching the enrollment target. This
permits optional setup and authorized reset/re-enrollment from verified sessions, preserving
generation and pinning the rotated key. Pending sign-in completion still uses the strict
pending identity/expiry resolver; a verified actor is not treated as pending. Separate profiles/devices
have separate rows; logging out one does not revoke the others.

### Transaction and enforcement boundary

The outer middleware locks the **stable lineage row before session load**, enclosing the native
view, authentication signals, Django `SessionMiddleware.process_response` save and final lineage
update in one `transaction.atomic(using='default')`. Session and authority persistence use that
same connection. PostgreSQL uses `SELECT FOR UPDATE` with a five-second lock timeout. SQLite
uses a write lock through a no-op authority update. Rejected responses and server failures roll
back the transaction and cannot replace authentication cookies. Unsupported session backends,
save-every-request, database routers and invalid middleware ordering fail configuration checks.
This implementation requires Django's database session backend on the default database.

Proxy requests authorize under a short lineage lock, including any authentication-triggered
session-key rotation and its save. Slow tracker I/O runs after that transaction, using the
captured authenticated principal. Already accepted operations may finish for that original
principal after logout; no operation switches backend to a later identity. Read-only proxy
responses cannot save a stale session snapshot. A delayed legitimate rotation cookie may still
arrive, but the authoritative lineage check rejects it once superseded.

Only GET `/api/health`, HEAD `/api/health`, GET `/api/auth/options`, and GET `/api/auth/csrf` are
public API exceptions. All other gateway APIs require actual live lineage/session/context
validation before native or proxy execution. Partial phases have explicit factor/enrollment
policies. Normal MFA denial responses retain their valid context so enrollment remains usable.
Gateway-mode native unsafe requests require the same authoritative binding. Traditional
HTML POST forms now use `_jth_context` alongside the unchanged Django CSRF field. Only resolved
`web:sign-out`, `web:application-action` and default `admin` namespace routes under their
expected prefixes accept the form transport, and only for urlencoded/multipart POSTs. No
`/api/` route accepts a body context; API requests retain `X-JTH-Context` and proxy uploads are
not eagerly parsed. Missing/forged/expired/obsolete contexts, duplicate fields and differing
header/field values fail closed. A matching header and field are allowed. The hidden value is
not an authentication, permission, workspace or idempotency capability.

Fresh HTML entry visits to `/app[/]` or `/admin[/]` without a live lineage redirect to the
appropriate sign-in/bootstrap page; they do not adopt an old authenticated cookie. A live
lineage with an obsolete session cookie instead receives explicit recovery, including on
admin login. Recognized context query parameters are rejected before redirects. Stale form
errors are accessible HTML 409 responses without the submitted fields or automatic replay.
Normal Django form errors, redirects, permissions, MFA and ownership checks remain intact.
Native Django form behavior with `JTH_GATEWAY=false` is unchanged, including original admin
lookup: gateway admin overrides are enabled only in the gateway deployment configuration.

### Native form processing and template adapters

Middleware order is checked: outer lineage boundary → Django session middleware → CSRF
middleware → authentication → context validation. Django's CSRF `process_request` handles its
cookie before context validation; its `process_view` independently checks CSRF/origin before
the actual native view. The context boundary does not assume that CSRF has already passed.

For supported native form POSTs, a non-locking authority hint rejects missing/expired lineage
and obsolete session cookies before body parsing. This hint never authorizes an operation.
Django parses bounded form data and temporary upload files **before the lineage transaction
and before session load**. Declared body size is capped by `JTH_MAX_UPLOAD_MB`; Django's normal
field/data/file-count limits still apply. The row is then locked and the actual cookie, session
mirror, principal, phase and signed context are revalidated. An identity change during upload
therefore rejects the request. Native view writes and real response session-save remain inside
the original single-database transaction. Parser errors return a bounded error; Django request
cleanup removes temporary files on success and rejection. `_jth_context` is marked sensitive
for Django production exception reports, and no adapter logs its value.

`{% gateway_context %}` is explicit, separate from `{% csrf_token %}` and empty outside gateway
mode. It is inserted only in same-origin POST forms. GET/search forms remain unmodified. No
HTML rewriting, JavaScript submit interception or Django CSRF monkey-patch is used. The ten
small overrides inherit upstream templates; blocks are copied only where no inner insertion
block exists. They target the pinned Django 6.1 templates and need review on upgrades:

| Override below `backend/gateway/templates/` | Why required |
|---|---|
| `admin/base.html` | The global logout form is in `userlinks`. |
| `admin/login.html` | The credential form has no inner insertion block. |
| `admin/change_form.html` | `form_top` inserts the binding in normal add/change forms. |
| `admin/change_list.html` | `result_list` is inside the bulk/list-edit POST form. |
| `admin/delete_confirmation.html` | The individual confirmation form is in `delete_confirm`. |
| `admin/delete_selected_confirmation.html` | Bulk confirmation has no inner insertion block. |
| `admin/auth/user/add_form.html` | Upstream overrides `form_top` without `block.super`. |
| `admin/auth/user/change_password.html` | User password management has its own form. |
| `registration/password_change_form.html` | Own-password and page-specific logout forms need bindings. |
| `registration/password_change_done.html` | The success page replaces the global logout form. |

New native POST routes must explicitly opt into the transport and render the tag. Start Fresh
remains disabled/unimplemented; its later implementation must add the route and persistent
idempotency independently. Already-rendered native HTML in another tab is not erased by a
hidden field. No-store responses remain in force; superseded submissions are rejected even
with a fresh CSRF token. Live native-page concealment is not added in this compatibility slice.
Current native upload handlers are Django's standard memory/temporary handlers. Custom handlers
would need review before adoption; production request-body logging, upload/read time limits,
rate limits and capacity validation remain hosting responsibilities.

A missing/expired lineage on initial root bootstrap creates a fresh **anonymous** session;
it never adopts an old authenticated session cookie. A live lineage with an obsolete session
cookie instead serves a 409 recovery page. Its explicit button posts a five-minute, purpose-bound
signed recovery challenge plus normal CSRF to `POST /api/gateway/session/restart`. Under the
same stable lock, this revokes the currently pinned session and creates an anonymous next
generation. A stale recovery challenge loses the generation comparison. A restart never grants
product access; the user must sign in again. Database unavailability fails closed (503).
Lineage lifetime is fixed at the configured `SESSION_COOKIE_AGE`, with session expiry capped
to it. `prune_expired()` removes expired authority rows only; operational scheduling, Django
expired-session cleanup and anonymous-bootstrap rate limits remain hosting work.

### Frontend behavior and request cost

The modular guard removes `jth_cache_v1` at gateway/login startup and disables gateway data
persistence. Desktop caching is preserved. It conceals root and portal content while checking,
unmounts sensitive UI on invalidation and revokes its document blob URLs. Browser notifications
are revalidation signals, never authentication authority. Focus/visibility revalidate; hidden
pages conceal data and skip idle polling. Visible idle checks run at most every 15 seconds
without overlapping polls. Explicit authentication/logout stays concealed while unresolved.

Header inspection, body consumption, JSON decoding, current-session verification, context
adoption and cleanup share one policy pipeline. Broken headers/streams/parsers, uncertain
authentication transitions, authentication failures and timeouts retire the local context.
Safe read cancellation discards the result without changing identity. Non-idempotent operations
are never automatically replayed. Checks queued in the same completion batch can coalesce;
later bodies cannot reuse an older in-flight check. Tabs verify independently.

An ordinary read uses one protected request plus one completion check, zero `/api/auth/me`
preflights. Measured: two tab reads/two checks; three tabs/thirty reads/thirty checks. This is
bounded local regression evidence, not a production capacity benchmark. Context/public-bootstrap
headers and body reads have five-second deadlines. Native auth/account headers, idle response
consumption and body reads each have 30-second limits; tracker equivalents have ten-minute
limits. XHR uploads have a ten-minute total timeout. Polling/broadcasts cannot unfreeze an
unresolved logout. Without a browser signal, a cookie change is detected by the next protected
request/check or visible idle poll, not instantly.

Authenticated documents use header-validated fetches and revocable blobs, with no context in
navigation URLs. Document 401s invalidate even before body consumption. Buffered files consume
browser memory; existing delivered downloads cannot be revoked. Drawer-close download
cancellation remains part of the separate DOCX/document-preview increment.

### Disposable verification

All commands below run from `backend/` and explicitly select disposable SQLite settings.
They never select the developer application database or media directory.

Ordinary Django plus the full labelled suite: default gateway mode **off**. Gateway test
classes opt in with their own settings/URLconf overrides.

```sh
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 \
  DJANGO_SETTINGS_MODULE=config.settings.test_sqlite JTH_GATEWAY=false \
  venv/bin/python -B manage.py test \
  accounts applications documents email_sync postings core web gateway --noinput
```

Focused ordinary MFA/passkey tests together with opt-in gateway tests use the same default:

```sh
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 \
  DJANGO_SETTINGS_MODULE=config.settings.test_sqlite JTH_GATEWAY=false \
  venv/bin/python -B manage.py test \
  accounts.tests_mfa_login accounts.tests_passkeys gateway --noinput
```

Gateway-only suite: deliberately enable the gateway deployment contract globally.

```sh
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 \
  DJANGO_SETTINGS_MODULE=config.settings.test_sqlite JTH_GATEWAY=true \
  venv/bin/python -B manage.py test gateway --noinput
```

Do not use `JTH_GATEWAY=true` for the ordinary accounts suites or full combined invocation.
That was the initial 41-failure/one-error configuration mistake: ordinary Django fixtures do
not bootstrap a gateway lineage/context, so gateway enforcement correctly rejects them.
The correction is selecting the intended deployment setting, not bypassing authentication or
weakening the tests. PostgreSQL tests require a separately provisioned disposable database;
never point these checks at an existing application database.

Node: `node --test tests/frontend/*.test.cjs`. On macOS with Chrome and the existing backend
virtual environment: `backend/venv/bin/python -B tests/frontend/run_gateway_security.py`.
The runner owns a synthetic loopback server, two temporary Chrome profiles, real top-level
tabs, temporary downloads and a disposable DB/media directory, cleaning up after completion.
It never starts a real tracker backend. The fixture deliberately exposes controls; it is not
a hosting configuration. The runner currently assumes the default loopback port 18765 is free.

Current local evidence:

- Full labelled Django, Python 3.14.7/SQLite: **1,638 run, 1,623 passed, 15 skipped, zero failures**.
- Gateway, Python 3.14.7/SQLite: **105 run, 103 passed, two PostgreSQL-only skips**.
- Gateway, Python 3.12.16/PostgreSQL 17: **105 passed, zero skips/failures**, using the already
  installed project image and an isolated container with temporary PostgreSQL storage. Both
  containers were removed. No dependency specification or installation changed.
- Focused ordinary MFA/passkeys plus gateway: **147 run, 145 passed, two PostgreSQL-only skips**.
- Frontend: **103 passed** (47 gateway, 54 API client, two workspace context).
- Chrome: **68 passed** across held Set-Cookie headers, actual server identity/rejection reasons,
  explicit recovery, same-account/A→B→A, concurrent anonymous login, broken auth bodies,
  delayed native/tracker replies, document 401/cancellation, cache, portals, uploads, Kanban,
  real MFA enrollment/recovery, PDF drawer/download and multi-tab request counts. Native Pipeline/
  Kanban, CSRF rejection, stale forms, browser multipart integrity, admin errors/changes, password
  rotation and logout also passed. The additional browser checks complete optional verified-user
  enrollment and simulated authorized-reset re-enrollment through the real Security UI, assert
  enrolled/verified state, actual principal and stable context, then use a new recovery code
  for pending sign-in. The reset fixture is restricted to a synthetic user and operator.
  Explicit read-count measurements pause unrelated lifecycle
  events/polling in test windows; normal lifecycle handling is tested separately.

Two new enrollment regressions failed with 409 before the correction and now pass. Seven new
server tests cover these successes, actual-principal/phase changes at the completion boundary,
stale generations, cross-account actions, CSRF, pending sign-in refusal and ordinary Django.
One initial mixed-suite invocation incorrectly set gateway mode globally for ordinary-Django
fixtures (41 failures/one error); rerunning with the normal default and gateway opt-in passed.
No enforcement was relaxed to accommodate that invocation.

The prior four defect regressions and this slice's initial three failing form/entry tests are
retained. Transaction tests
use `TransactionTestCase`, actual response processing and connection instrumentation, rather
than assuming TestCase's wrapper proves atomicity. Faults at either session save or authority
save roll back both records and authentication-side changes. The PostgreSQL race holds the
winning view under its lock and observes the competitor trying to lock before release; it
asserts the persisted winning user, generation and losing rejection reason. A second PostgreSQL
race exercises actual native admin form sign-ins. Upload tests change identity during parsing,
verify parsing outside the transaction, check disk-file cleanup and native-write rollback.

Safari, packaged desktop and physical passkey interaction remain unverified. Python 3.12 was
verified for the gateway suite, not the entire product. The full SQLite suite's thirteen non-gateway
PostgreSQL-only tests were not rerun here; general production/storage/OAuth/capacity validation
remains separate. Gateway passkey tests retain native cryptographic verification interfaces but
mock the authenticator result. DOCX containment remains unresolved. No real database migration,
deployment or hosting-readiness claim is made; the authorized local Git checkpoint is separate.

### Verified-session MFA correction — 2026-11-13

Narrow correction only; v2 payload, phase policy, lineage schema and transaction contract are
unchanged. Existing enrollment confirmation had incorrectly used the pending-sign-in resolver
for verified sessions. These seven existing files changed; no files/dependencies/migrations
were added:

- `backend/gateway/session_lineage.py`
- `backend/gateway/middleware.py`
- `backend/gateway/tests_session_context.py`
- `tests/frontend/gateway-security-browser.html`
- `tests/frontend/serve_gateway_security.py`
- `docs/GATEWAY.md`
- `docs/DJANGO_MIGRATION_STATUS.md`

### Form compatibility increment scope

Exactly these 25 files changed in this increment; earlier security changes are preserved:

- `backend/config/settings/base.py`
- `backend/gateway/middleware.py`
- `backend/gateway/session_context.py`
- `backend/gateway/templates/admin/auth/user/add_form.html`
- `backend/gateway/templates/admin/auth/user/change_password.html`
- `backend/gateway/templates/admin/base.html`
- `backend/gateway/templates/admin/change_form.html`
- `backend/gateway/templates/admin/change_list.html`
- `backend/gateway/templates/admin/delete_confirmation.html`
- `backend/gateway/templates/admin/delete_selected_confirmation.html`
- `backend/gateway/templates/admin/login.html`
- `backend/gateway/templates/registration/password_change_done.html`
- `backend/gateway/templates/registration/password_change_form.html`
- `backend/gateway/templatetags/__init__.py`
- `backend/gateway/templatetags/gateway_forms.py`
- `backend/gateway/tests_forms.py`
- `backend/gateway/tests_session_context.py`
- `backend/gateway/tests_session_lineage.py`
- `backend/gateway/views.py`
- `backend/web/templates/web/base.html`
- `backend/web/templates/web/pipeline.html`
- `docs/DJANGO_MIGRATION_STATUS.md`
- `docs/GATEWAY.md`
- `tests/frontend/gateway-security-browser.html`
- `tests/frontend/serve_gateway_security.py`

### Complete checkpoint file scope

Includes the reviewed cache/session-lineage, form-compatibility and MFA correction files:

- `_app/frontend/api-client.js`
- `_app/frontend/gateway-session.js`
- `_app/frontend/index.html`
- `backend/accounts/email_code_views.py`
- `backend/accounts/email_signin_views.py`
- `backend/accounts/mfa_session.py`
- `backend/accounts/passkey_views.py`
- `backend/accounts/views.py`
- `backend/config/settings/base.py`
- `backend/core/frontend.py`
- `backend/gateway/apps.py`
- `backend/gateway/middleware.py`
- `backend/gateway/migrations/0001_initial.py`
- `backend/gateway/migrations/__init__.py`
- `backend/gateway/models.py`
- `backend/gateway/session_context.py`
- `backend/gateway/session_lineage.py`
- `backend/gateway/templates/admin/auth/user/add_form.html`
- `backend/gateway/templates/admin/auth/user/change_password.html`
- `backend/gateway/templates/admin/base.html`
- `backend/gateway/templates/admin/change_form.html`
- `backend/gateway/templates/admin/change_list.html`
- `backend/gateway/templates/admin/delete_confirmation.html`
- `backend/gateway/templates/admin/delete_selected_confirmation.html`
- `backend/gateway/templates/admin/login.html`
- `backend/gateway/templates/registration/password_change_done.html`
- `backend/gateway/templates/registration/password_change_form.html`
- `backend/gateway/templatetags/__init__.py`
- `backend/gateway/templatetags/gateway_forms.py`
- `backend/gateway/tests.py`
- `backend/gateway/tests_forms.py`
- `backend/gateway/tests_session_context.py`
- `backend/gateway/tests_session_lineage.py`
- `backend/gateway/urls.py`
- `backend/gateway/views.py`
- `backend/web/templates/web/base.html`
- `backend/web/templates/web/pipeline.html`
- `docs/DJANGO_MIGRATION_STATUS.md`
- `docs/GATEWAY.md`
- `tests/frontend/api-client.test.cjs`
- `tests/frontend/gateway-security-browser.html`
- `tests/frontend/gateway-session.test.cjs`
- `tests/frontend/run_gateway_security.py`
- `tests/frontend/serve_gateway_security.py`
