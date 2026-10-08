# Django migration: current status

Maintained checkpoint: 2026-10-07. Authoritative branch: `django-migration`;
current implementation checkpoint `dbaa85926e35466dd6be7b8e02ff625828bc73f0`
(`Implement retained review source text inspection browser workflow`). Its parent documentation
checkpoint is `58f3d7ee51f0781f4f27b55de6445934cb29c8b8`
(`Reconcile retained review disposition browser status`). The implementation is committed/pushed.
This Status-only reconciliation adds no application execution or operational validation;
no future documentation commit SHA is asserted. Before this edit, local HEAD, tracking ref
and live remote matched the implementation checkpoint, ahead/behind 0/0, with a clean
working tree and empty index.

Retained Email Source Identity and Content
Foundation is committed at `2f0cd1f`; Gmail Mailbox Identity and Durable Lineage
Foundation is committed at `9f6627770c43fd3b3af492d2201e647af77cc53f` on
`django-migration`. Gmail Provider Adoption into Retained-Source Authority is committed
at `fcbfcf353201552d4a579408299323e0bf731b21`. **Backend ApplicationMessage Relationship
Foundation** is committed at `b5c1faf1ad100acfd3d24aead679c3a1831f3a48`.
**Retained Application Review Identity & Candidate Snapshot Foundation** is committed
at `eedf57abbdf98f05d430ac116941fc447336f87b`. **Retained Review Attach to Existing
Application** is committed at `4d545820f62d92c76cf4da189706f17b3832949f`.
**Retained Review Disposition — Dismiss / Restore Foundation** is committed at
`5e25093a62a6c908d2da8123d1d6a7323eca2cd5`. **Retained Review Create Application
Orchestration** is committed at `ab1cb0e5e37faff606b1be7c84cf83fb99f77e30`
(`Implement retained review create application orchestration`).
**JobPosting Portable Identity Foundation** is committed at
`6863f277b04e1f084d6f7b2169c4a8209c65592c` (`Implement JobPosting portable identity`).
**Retained Posting Extraction Provenance Foundation** is committed at
`c5f8e20f9db15e2cf4dc9f0e80a0929bd222fff6` (`Implement retained posting extraction provenance`).
**Durable Posting Source-Item Identity + Immutable Initial Output Association** is
committed at `2090a61b1a43252a8eb93d82c87c7d90e4c40074`
(`Implement retained posting item identity`). **Append-Only Posting-Item Association
Corrections + Revision-Based Effective State** is committed at
`8812bf8f61de1db5b622af6f61b71a5a1b68fdb3` (`Implement retained posting item corrections`).
**Attach Existing JobPosting Only + Immutable Initial PostingSource Mapping** is
committed at `482bcc5f9528fb9a6e9b3e7dce1c43a7443c40b3`
(`Implement initial PostingSource mapping`). **PostingSource Correction / Effective-Mapping
Authority** is committed at `ac6d13db7f52889bff12b128a153e397769fee67`
(`Implement PostingSource correction authority`). **Retained Posting Interpretation
Selection Authority** is committed/pushed at `d46ef1508259f0418d1d0c842678456c883f5732`
(`Implement retained posting interpretation authority`). **Posting-Level Interpretation
Arbitration Authority** is committed/pushed at
`5f832dcc261d13365d851806623fca1a373e1644`
(`Implement posting-level interpretation arbitration authority`). Descriptor Projection
Authority is committed/pushed at `8ba7bc869787f80b217c0c066f9c713a337a5669`
(`Implement descriptor projection authority`). Canonical JobPosting Allocation is
committed/pushed at `cce6cf08717d6dca18fd1ce8945f68df9589f39e`
(`Implement canonical JobPosting allocation authority`). Retained Posting Review
Orchestration was reviewed and committed/pushed at
`ecb2ecf98c7d12552b5b0b9327f1f74fd28388ff`
(`Implement retained posting review orchestration`). Retained Posting Candidate
Discovery was reviewed and committed/pushed at
`3aab4762224efbf1d8e5b11f57040b88eb9a4094`
(`Implement retained posting candidate discovery`). Retained-Text Job-Alert
Extraction Producer was reviewed and committed/pushed at
`56c45dcb6768e6af9ab73f7c739ee27c665020f1`
(`Implement retained text extraction producer`). It provides explicit retained-message
extraction production from retained-selector-derived arguments using the existing
`job_alert_rules` / `"1"` parser, immutable ordered extraction evidence, historical
replay before parsing and shared persisted-batch validation; it is not canonical ingestion.
Explicit Retained Extraction Request Batch Command was reviewed and committed/pushed
at `97751b857ba0ce784cd7b80d7c9fa42930204285`
(`Add retained extraction batch command`). It is an operator-controlled execution adapter
around that producer: explicit retained-message IDs, caller-owned UUIDv4 operations and
exact input specifications undergo complete bounded preflight before sequential producer
invocation. Independent per-entry transactions preserve earlier successes on first failure;
unchanged retry uses producer idempotency. Content-free reporting ends at immutable
extraction evidence, without provider automation or downstream orchestration.
Source-Scoped Retained Extraction Evidence Inspection was reviewed and committed/pushed
at `b3a8d451272bd1ee5e4626e4b30ebd5f5f6cbc63`
(`Implement source-scoped retained extraction inspection`). The owner-authorized,
read-only domain contract exposes bounded source history before item association,
including no recorded history, completed zero-output operations and unassociated outputs.
It reuses complete extraction-batch validation and returns detached immutable evidence
with advisory current source eligibility; it adds no execution or downstream authority.
Workspace-Scoped Read-Only Retained Extraction Evidence HTTP API was reviewed and
committed/pushed at `56214508cd646650863b23628e58c10b80fea010`
(`Implement retained extraction evidence API`). This authenticated, owner-scoped,
bounded endpoint consumes the existing source-scoped evidence reader and adds HTTP
transport/navigation only, without extraction execution or downstream mutation authority.
Retained Extraction Evidence Read-Only Workspace UI was reviewed and committed/pushed
at `8a4af32e4fb9949430487449e5cbaaea5ab93a3c`
(`Implement retained extraction evidence workspace UI`). It adds authenticated,
Workspace-scoped browser presentation/navigation over existing summary/evidence GETs.
The completed sequence is recorder → producer → explicit batch execution → source-scoped
domain inspection → read-only HTTP evidence API → read-only Workspace browser evidence UI.
Isolated PostgreSQL validation at `c71f6cdcf183a4e76333b2c62582b8ecfdb1fc68` adds bounded
extraction/retention concurrency evidence for existing production services, without
changing production transaction semantics or adding mutation authority.
Workspace-Scoped Read-Only Application List and Core Detail Browser Workflow is
committed/pushed at `845ad1f57addaf350b974aeaecc5aba5a750d2fa`, consuming existing
Application GET authority without changing backend semantics. Workspace-Scoped Read-Only
Retained Application Review Inspection and Application Core Navigation is committed/pushed
at `bcad64038e6fbb4c224dc5a7ddfe075d4b3f22f7`. Workspace-Scoped Read-Only Category
Navigation and Application Core Inspection is committed/pushed at
`17ec29a476503d0e91ce7b6f123604386e04dad3`, adding read-only presentation/navigation.
Workspace-Scoped Application Category Assignment Browser Workflow is committed/pushed at
`6d2c736cb9a5a2bb68850019e74a77546c819f25`: explicit browser invocation of existing Application
Category assignment authority, exposed only from standalone Applications. This is the first
completed bounded domain browser mutation workflow, not general mutation infrastructure.
Accumulated browser capability is Workspace/session shell → extraction-evidence inspection
→ Application list/core-detail browsing → retained-review inspection with Application navigation
→ named Category inspection with Application navigation → standalone Application Category-assignment
mutation → retained Application review dismiss/restore in the existing review detail panel
→ explicit read-only retained-review source-text inspection.
The disposition browser workflow is committed/pushed at
`3b9a56f593dc3eed1238a8cc890420e67d010c89`, consuming existing backend authority.
Read-only retained-review source-text inspection is committed/pushed at
`dbaa85926e35466dd6be7b8e02ff625828bc73f0`, consuming existing retained-message detail GET
from the review panel without extending backend authority.
These are accumulated UI capabilities, not one domain authority chain. Category mutations,
remaining Application/review mutations (including review attach/create), broader evidence workflows,
frontend migration, historical reconciliation, email derivation and operational cutover remain pending.
**Production fail-closed configuration admission** remains
implemented at `160c8a4007f262bab1361485b959accce145a628` as an architecture-hardening
checkpoint, not a browser capability or extension of domain authority. This validates
configuration admission and profile selection; operational production gates remain open.

## 1. Scope and source of truth

- Code and migrations establish implementation. [Decisions](DJANGO_MIGRATION_DECISIONS.md)
  owns accepted product/architecture boundaries; [Foundations](DJANGO_MIGRATION_FOUNDATIONS.md)
  owns accepted detailed contracts; this document owns current implementation,
  verification, and readiness. Apparent conflicts must be surfaced for review,
  never silently resolved by rewriting an authoritative document.
- The [plan](DJANGO_MIGRATION_PLAN.md) supplies broader context. Handoffs/specs
  are supporting historical/behavioral evidence, subordinate where stale or conflicting.
- Keep four states separate: **accepted/designed**, **implemented**,
  **automated-test verified**, and **operationally/end-to-end validated**.
  Acceptance is not implementation; passing component tests is not cutover proof.
- Correct this checkpoint when code/evidence materially changes. Do not change
  accepted decisions implicitly or append a chronological session transcript.

## 2. Current verification evidence

### Workspace-Scoped Read-Only Retained Review Source Text Inspection — committed checkpoint, 2026-10-07

Reviewed, committed and pushed at `dbaa85926e35466dd6be7b8e02ff625828bc73f0`
(`Implement retained review source text inspection browser workflow`), parent documentation checkpoint
`58f3d7ee51f0781f4f27b55de6445934cb29c8b8`
(`Reconcile retained review disposition browser status`). Exactly five implementation paths changed,
with **436 insertions and 10 deletions**:

- `_app/frontend/api-client.js`
- `_app/frontend/index.html`
- `tests/frontend/api-client.test.cjs`
- `tests/frontend/foundation-browser.html`
- `tests/frontend/serve_foundation.py`

The existing retained-review detail panel now offers explicit **Inspect retained text**.
Review selection does not eagerly fetch source content. The client consumes the existing
`GET /api/workspaces/{workspace}/retained-messages/{source}/` using authenticated sessions,
explicit captured Workspace context and the existing owner/Workspace/mailbox authorization.
No production backend route, model, migration, dependency or domain authority changed.

The browser validates positive safe-integer source/mailbox runtime IDs, selected source portable
UUID, supported root representation/content version 1, state/eligibility consistency and required
bounded metadata. Workspace/review identity and mailbox portable identity are not invented as
response fields; authorization comes from the scoped endpoint and captured context. Plain text
supports the configured ceiling of **262,144 UTF-8 bytes**. NUL, unpaired surrogates, malformed
fields and unsupported representations fail closed; the browser does not silently truncate,
normalize or reconstruct retained text.

Complete, partial, explicitly empty and unavailable plain text remain distinct. HTML-only content
is disclosed as unavailable plain text with retained HTML availability, without conversion or
original HTML exposure. Generated truncation validates UTF-8 prefix location, retained/original
byte counts, digest shape and source completeness/reason; a zero-byte retained prefix stays partial.
Partial content without truncation metadata does not acquire an inferred truncation claim.
Source conflict is disclosed independently of review disposition and completeness: preserved
canonical content remains inspectable, without conflict resolution or current provider-truth claims.
Retention time, header-sent time and provider-received time remain separate, with recorded
instant/date/uncertain/unknown precision, provenance and source offset where present.

Source content renders literally through React text nodes, without active HTML, Markdown,
automatic links or remote resources. Only the selected validated projection is retained transiently;
raw provider locators, headers, conversation IDs and truncation digests are not retained in that
projection. No sensitive-content persistence, logging or analytics is added. Refresh clears content
before a new GET; Back, Close, selection, panel/Workspace navigation, actor/session changes and
disposal clear or discard the source view and invalidate reads. Captured review/source/Workspace/
actor identities, aborts and request generations prevent obsolete success/error/finally updates,
including obsolete 401 handling. A current authentication failure clears the sensitive view.

Loading, safe errors and explicit **GET retry**, Refresh, Back and Close are supported.
Back performs a fresh review-detail GET. Opening inspection cancels prepared disposition
confirmation; returning does not resurrect it. Inspection is withheld during disposition submission
and reconciliation, including stale source controls. Existing one-POST confirmation protection,
uncertain-outcome GET-only recovery, parent-list invalidation/page-one reload and inclusive
dismissed-review discovery remain intact. Source, relationship, attachment, lifecycle, evidence,
creation and disposition authority are unchanged.

This read-only consumer adds no writes, provider calls, file operations, evidence generation,
attachment/create workflow, Application/Category mutation or general HTML viewer. It adds no
backend routes/models/migrations/dependencies, historical reconciliation or provider expansion.
**Inherited response-memory limitation:** the browser parses the full JSON response before
validating the retained projection; field and text limits do not establish an aggregate
response-memory bound. Selection is transient; production scale/performance remains unvalidated.

Retained **Stage 3 application-test execution evidence**, not post-commit execution:

| Verification | Retained result |
|---|---|
| Node/client | **45 passed**, zero failures/skips |
| Combined source/disposition/assignment/Category/review/Application/evidence/shell/session browser harness | **112 passed**, zero failures; HeadlessChrome **153** on macOS |
| Focused Django | **79 passed**, zero failures/errors/skips |
| Full labelled Django (`accounts applications documents email_sync postings core`, isolated SQLite) | **1,362 passed, 13 PostgreSQL-only skipped**, 1,375 total; zero failures/errors |
| Full legacy regression | **378 passed, 6 failed, 2 warnings** |
| Targeted unchanged-HEAD reproduction of affected legacy modules | **26 passed, the same 6 failed, 2 warnings**; not a full baseline rerun |

Stage 3 exercised actual production client/projection helpers and the product UI against disposable
Django endpoints. Coverage includes literal malicious-looking text, Unicode and size boundaries,
content/completeness/conflict cases, malformed identities/payloads, read retry, delayed success/error/
401, navigation/Workspace/actor/session isolation, confirmation cancellation and pending-disposition
exclusion. Source-specific traffic assertions bind reads to selected fixture review/source/Workspace
intent across the source interval. Domain snapshots and disposition comparison, SELECT-only endpoint
auditing and provider/attachment/storage guards support read-only preservation. Existing workflows
remain in the combined harness. These assertions do not resolve historical traffic limitations.

The six legacy failures comprise three missing-Django failures in the legacy interpreter's database
harness, two sandbox filesystem restrictions in export/import tests and one baseline deletion/history
HTTP 500 instead of 200. All six reproduce against unchanged parent HEAD; the HTTP 500's root cause
remains unresolved. They were not repaired; the legacy suite remains not green. Generic discovery
remains **PRE-EXISTING NON-BLOCKER**, unresolved and not green; no new generic-discovery validation
is claimed.

Stage 5 was **read-only pre-commit review**, not another application test run: complete diff/log
inspection, unchanged-HEAD source comparison, syntax/AST/Git and artifact checks.
Verdict: **READY FOR COMMIT**, zero blockers and zero new findings. Stage 6 verified reviewed/staged/
committed content, committed and pushed normally, then verified synchronized local/tracking/live
remote SHA, parent, clean tree, empty index and absent prohibited artifacts. Stage 9 is this bounded
**documentation-only edit**. No post-commit application tests or new operational validation ran.

All five historical MINORs remain unchanged, nonblocking and unremediated:

- **MINOR — workflow-specific traffic assertion coverage**
- **MINOR — Category traffic assertion excludes later coexistence intervals**
- **MINOR — Assignment GET traffic policy is not bound to workflow scope**
- **MINOR — invalid-command tests do not directly assert dispatcher non-entry**
- **MINOR — disposition GET traffic assertion not bound to the selected review**

No fresh Safari validation is claimed; Chromium's Safari user-agent token is not Safari evidence.
PostgreSQL-only skips do not establish operational or broader concurrency validation; existing
bounded PostgreSQL retention/extraction evidence remains separate. Production-browser acceptance,
providers/OAuth, private storage, Redis/Celery/Beat, deployment, scale/load, coordinated backup/restore,
historical reconciliation, cutover and rollback gates remain open. This completes one bounded
read-only browser workflow, without establishing general frontend or operational readiness.

### Workspace-Scoped Retained Application Review Dismiss/Restore Browser Workflow — committed checkpoint, 2026-10-07

Reviewed, committed and pushed at `3b9a56f593dc3eed1238a8cc890420e67d010c89`
(`Implement retained review dismiss restore browser workflow`), parent documentation checkpoint
`7bc6cb11935088b3b5dc93e224217b0552aebcaf`
(`Reconcile production settings hardening status`). Exactly five implementation paths changed,
with **301 insertions and 17 deletions**:

- `_app/frontend/api-client.js`
- `_app/frontend/index.html`
- `tests/frontend/api-client.test.cjs`
- `tests/frontend/foundation-browser.html`
- `tests/frontend/serve_foundation.py`

The existing authenticated, Workspace-scoped retained-review detail panel now offers explicit
whole-review Dismiss and Restore. Preparation fetches fresh scoped detail before confirmation;
review ID, Workspace, portable identity, disposition state/timestamp and JavaScript-safe integer
revision are validated. The desired state follows that fresh observation. Unsafe identifiers,
revisions or revision-increment arithmetic withhold mutation. A synchronous submission lock and
confirmation generation consume each intent before asynchronous work; repeated/rapid clicks and
cancelled or consumed confirmations cannot send another POST. The existing session/CSRF transport
sends only `expected_revision` to the existing dismiss/restore endpoint, without an Idempotency-Key,
automatic POST retry or FastAPI fallback write.

Receipts validate review identity, Workspace, desired disposition, timestamp consistency and exact
revision increment. Existing backend authority still checks revision before no-op detection:
`409 stale_revision` invalidates the old confirmation even if another writer reached the desired
state. No optimistic disposition update occurs. Lost-after-commit, empty, malformed and ambiguous
responses preserve uncertainty. Fresh GET-only reconciliation shows current state, not proof that
this request caused it; an acknowledged transition can be followed by another writer's change.
Failed reconciliation clears actionable detail and withholds further changes. Explicit recovery
retries only the GET and preserves the uncertain-outcome note; another mutation needs a fresh
observation and new confirmation. Current authentication expiry uses the existing session UI.

Every submission attempt invalidates accumulated parent rows, cursor and list requests. Returning
to reviews reloads page one before reuse; old pages cannot repopulate the list. Discovery remains
inclusive, so dismissed reviews stay visible and restorable. Back, Close, selection/reload,
referenced-Application navigation, panel changes and disposal cancel action lifetime and reads.
Captured actor/Workspace/session context, attempt generations and selected-review checks reject
obsolete success, error, finalization and 401 responses. Aborting a POST does not prove server
rollback; reopening obtains fresh observations. Selection remains transient, without new deep links
or persistent action state. Existing accumulated-page memory, unpaginated detail arrays, inherited
creation-result payload cost, safe-ID requirements and unvalidated large-Workspace performance remain.

The unchanged backend disposition service remains the sole writer. Source conflict permits both
transitions; dismissal is independent from attachment, Application Trash, business status and source
eligibility. Candidates, canonical relationships, retained sources/observations, creation provenance,
Documents/evidence and prior Application lifecycle state are preserved. No backend production route,
model, migration, serializer, service, settings, dependency or provider authority changed. Added
fixture-controller routes exist only in the disposable test server. Review attachment/create/accept,
candidate rejection, filtering/queue redesign, bulk actions, Application/Category/Document mutation,
message-body/file/dossier or creation-result browsing, extraction/evidence generation, provider
execution, historical reconciliation and generalized mutation infrastructure remain excluded.

**Retained Stage 3 pre-commit execution evidence**, not tests run during this documentation edit:

| Validation | Result |
|---|---|
| Node/client | **38 passed**, zero failures/skips |
| Combined disposition/assignment/Category/review/Application/evidence/shell/session browser harness | **99 passed**, zero failures; HeadlessChrome **153** |
| Focused Django | **104 passed**, zero failures/errors/skips; final run 3.697s |
| Full labelled Django (`accounts applications documents email_sync postings core`, isolated SQLite) | **1,362 passed, 13 PostgreSQL-only skipped**, 1,375 total; zero failures/errors; final run 197.352s |
| Full legacy regression | **378 passed, 6 failed, 2 warnings** |
| Targeted unchanged-HEAD reproduction of affected legacy modules | **26 passed, the same 6 failed, 2 warnings**; not a full baseline rerun |

The six legacy failures comprise three missing-Django errors in the legacy interpreter's database-
harness tests, two sandbox filesystem restrictions in export/import tests, and one deletion/history
HTTP 500 instead of 200. All six reproduce against unchanged parent HEAD; the HTTP 500's underlying
cause remains unresolved. They were not repaired and do not establish a newly introduced browser
regression. The legacy suite is not green. Generic no-label Django discovery remains the separate
**PRE-EXISTING NON-BLOCKER**, unresolved and not green; no new generic-discovery validation is claimed.

Stage 3 exercised production client/helpers and the actual Django product panel with disposable
SQLite/media. Real disposition endpoints covered transitions, stale-before-no-op, concurrent state
changes and a committed-but-response-lost case followed by rendered GET reconciliation. The harness
covered failed recovery, malformed responses, rapid clicks, page invalidation and obsolete navigation/
actor/auth responses. A domain-table digest excluding the disposition sidecar was compared after
primary dismissal; restoration/conflict browser assertions are narrower, supplemented by existing
backend preservation tests. Syntax/AST/whitespace and isolated Django system checks passed.

Stage 5 was **read-only review**, not another application test run: full diff and retained logs,
checkpoint/inventory, baseline archive/source comparisons, syntax/static/Git and artifact checks.
Verdict: **READY FOR COMMIT**, zero blockers, one new nonblocking test-coverage MINOR. Stage 6 staged
content matched the reviewed diff and five blob identities exactly, then committed/pushed normally;
HEAD, tracking ref and live remote synchronized with a clean tree and empty index. Application tests
were not rerun after commit/push or in this documentation reconciliation.

**MINOR — disposition GET traffic assertion not bound to the selected review** remains nonblocking
and unremediated. Its GET policy admits unrelated numeric review-detail reads in the same Workspace,
with Application reads also admitted by the interval assertion. POST identity/transition/body/revision
and unique confirmation checks are tighter. No unauthorized extra production read was identified;
the assertion alone does not prove all reads belong to the selected review. This does not remediate
or replace the four retained historical MINORs:

- **MINOR — workflow-specific traffic assertion coverage**
- **MINOR — Category traffic assertion excludes later coexistence intervals**
- **MINOR — Assignment GET traffic policy is not bound to workflow scope**
- **MINOR — invalid-command tests do not directly assert dispatcher non-entry**

No fresh Safari validation is claimed; a Safari token in Chromium's user-agent is not Safari evidence.
SQLite skips do not establish PostgreSQL operational or broader concurrency validation. Existing
bounded PostgreSQL retention/extraction evidence remains separate. Production-browser acceptance,
provider/OAuth operation, private storage, Redis/Celery/Beat, deployment, scale/load, coordinated
backup/restore, historical reconciliation, cutover and rollback gates remain open. This completes one
bounded browser workflow, not general mutation support or operational readiness.

### Production Settings Fail-Closed Configuration Prerequisite — committed checkpoint, 2026-10-07

**Fail-closed production configuration admission is implemented** at
`160c8a4007f262bab1361485b959accce145a628` (`Harden production settings admission`),
parent documentation checkpoint `c96be928f065b82f114aa0ecc3b845b0c6e92334`
(`Reconcile Application Category assignment status`). This validates configuration admission
and profile selection; operational production gates remain open.

The reviewed implementation contains exactly seven paths, one added file, **559 insertions
and 33 deletions**: `backend/config/settings/base.py`, `backend/config/settings/dev.py`,
`backend/config/settings/prod.py`, `backend/config/celery.py`, `backend/manage.py`,
`backend/requirements.txt`, and the added `backend/core/tests_production_settings.py`.
No models, migrations, views, serializers, domain services, frontend, provider behavior,
real data, credentials or documentation changed in that implementation commit.

Configuration/profile boundary:

- Shared base no longer loads dotenv. Development still loads repository-local `backend/.env`
  before base with `override=False`; process environment wins. Production does not
  automatically load development dotenv and expects process/service configuration.
  Admission assumes a fresh process; in-process profile switching is not supported.
- Production fixes the engine to `django.db.backends.postgresql` and requires explicit
  `DJANGO_DB_NAME`, `DJANGO_DB_USER`, `DJANGO_DB_PASSWORD`, `DJANGO_DB_HOST`, and
  `DJANGO_DB_PORT`. Required values reject missing/empty/control-containing input;
  name/user/host/port reject surrounding whitespace, while passwords are preserved exactly.
  Hosts accept validated DNS/IP forms, not URLs, lists, embedded ports or socket paths;
  port is ASCII decimal in `1..65535`. There is no SQLite fallback or alternate engine;
  nonempty `DATABASE_URL` and `DJANGO_DB_ENGINE` are unsupported and rejected.
  This is configuration-shape admission, not live connectivity, TLS/certificate or pooling validation.
- Runtime `backend/requirements.txt` now declares `psycopg==3.3.6`, without a binary extra;
  the PostgreSQL test manifest is unchanged. No dependency installation occurred.
  Native libpq deployment remains unresolved; local driver availability is not deployed-runtime evidence.
- Production requires explicit valid `DJANGO_SECRET_KEY`, rejecting the committed development
  fallback, `django-insecure-` prefix, controls and weak values (fewer than 50 characters or
  five distinct characters). Accepted values are preserved; no fallback is generated and
  `SECRET_KEY_FALLBACKS=[]`.
- `GMAIL_TOKEN_ENCRYPTION_KEY`, `MICROSOFT_TOKEN_ENCRYPTION_KEY`, and
  `IMAP_TOKEN_ENCRYPTION_KEY` are all explicit production requirements. Local validation
  requires canonical URL-safe Base64 encoding of 32 bytes, rejects every committed
  development fallback in any provider position, and requires distinct decoded keys.
  No credentials were inspected, rotated or re-encrypted; no provider was enabled.
- `DJANGO_ALLOWED_HOSTS` is required and validated as comma-separated exact DNS/IPv4/
  bracketed-IPv6 entries, with trim, case normalization and deduplication; empty entries,
  wildcards, schemes, paths, userinfo, ports and controls are rejected. Same-origin CSRF
  uses `CSRF_TRUSTED_ORIGINS=[]`; nonempty `DJANGO_CSRF_TRUSTED_ORIGINS` is rejected.
  Production explicitly sets `DEBUG=False`, secure session/CSRF cookies, session HttpOnly,
  Lax SameSite behavior and HTTPS redirect. Forwarded host/port trust remains disabled and
  `SECURE_PROXY_SSL_HEADER=None`. HSTS remains zero; rollout and proxy topology are separate gates.
- Bare/default Celery selects production; explicit `DJANGO_SETTINGS_MODULE` selectors remain
  respected, including development workers. No task behavior changed or broker connectivity was validated.
- Bare management commands still default to development. Exact production selection by
  environment or either CLI `--settings` form triggers admission before Django command dispatch;
  CLI selection retains Django precedence. `prod.py` owns policy; `manage.py` only enforces
  the pre-dispatch gate. Actual WSGI/ASGI bootstrap paths retain production defaults.
  This does not add special handling for arbitrary Python entrypoints.
- Admission failures use deterministic, fixed, secret-free `ImproperlyConfigured` messages,
  without supplied values, environment dumps or input-bearing parsing exception chains.

Management blocker/correction: initial readiness inspection assumed production settings-import
admission covered commands. Verification demonstrated Django could suppress admission failure
and still execute shell code. Implementation stopped at the authorized file boundary;
a separately authorized one-file expansion added `backend/manage.py`. The pre-dispatch
blocker was corrected and validated before commit, with normal successful dispatch preserved.

Retained **pre-commit final-snapshot evidence**:

| Validation | Result | Time |
|---|---|---|
| Production-settings focused suite | 12 passed; zero skips/failures/errors | 52.357s |
| Existing settings/auth suite | 45 passed; zero skips/failures/errors | 5.618s |
| Full labelled Django (`accounts applications email_sync postings documents core`) | 1,375 discovered/reported run; 1,362 passed; 13 skipped; zero failures/errors | 198.144s |

The 13 skips are PostgreSQL-only concurrency tests under isolated SQLite; these counts
are not PostgreSQL operational validation. Focused fresh-subprocess tests use controlled
synthetic configuration and redirected temporary dotenv fixtures, assert secret-canary
non-leakage, and assert zero guarded database/socket/DNS/HTTP/provider/broker/storage/AWS/
additional-subprocess attempts. Positive/negative admission covers WSGI, ASGI, Celery,
management selection and the shell execution-marker regression; development/test profiles remain preserved.
All six Python paths, including the added test module, passed AST parsing; whitespace and
isolated system checks passed. Installed versions satisfied the runtime manifest. Postings
migration drift was absent; global drift remained only known `EmailAccount.provider`; no
migration was generated. Suites were not rerun after implementation commit/push or during
this documentation reconciliation. No new operational validation is claimed.

**MINOR — invalid-command tests do not directly assert dispatcher non-entry** remains
non-blocking and unremediated. The shell regression directly proves the original bypass
is fixed; representative invalid-command tests assert admission failure and zero external
attempts, but do not independently mock/assert `execute_from_command_line()` non-entry.
The straight-line pre-dispatch gate plus shell regression provides implementation confidence;
this is a test-strength limitation only.

Generic no-label discovery retains **PRE-EXISTING NON-BLOCKER**, unresolved and not green;
no generic-discovery remediation or new validation is claimed. The three historical traffic
MINORs remain unchanged, non-blocking, unremediated and unrelated to this settings slice:
**MINOR — workflow-specific traffic assertion coverage**,
**MINOR — Category traffic assertion excludes later coexistence intervals**, and
**MINOR — Assignment GET traffic policy is not bound to workflow scope**.

This checkpoint does not establish PostgreSQL connectivity/TLS, native libpq deployment,
trusted proxy topology, private storage, Redis/Celery broker operation, OAuth/provider
credentials or execution, production browser acceptance, deployment, coordinated backup/restore,
or cutover/rollback. Manual-status concurrency and provider-automation policy remain unresolved.

### Workspace-Scoped Application Category Assignment Browser Workflow — committed checkpoint, 2026-10-06

Reviewed, committed and pushed at `6d2c736cb9a5a2bb68850019e74a77546c819f25`
(`Implement Application Category assignment browser workflow`), parent documentation checkpoint
`a8b2cbfead42fcf0b0f187ca305ca59e4a604f2f`
(`Reconcile Category workspace browser status`). Six files changed, with 526 insertions and
five deletions: browser/client, disposable fixtures and tests only. Production backend contracts,
models, migrations, settings, dependencies, provider code and documentation were unchanged
in the implementation commit. No accepted contract changed.

Authenticated Django mode now supports the first completed **bounded domain browser mutation
workflow**: **explicit browser invocation of existing Application Category assignment authority**.
Only standalone Applications offers assignment/move/clear after core-detail inspection.
Shared Application inspection remains read-only; standalone action state owns mutation intent
and `category_revision`. Category → Application, retained-review → Application and extraction-evidence
views remain read-only. This does not establish a generic mutation framework or confer the same
recovery behavior or implementation readiness on other writes.

Opening the action obtains a fresh scoped Application observation and fresh server Category
choices, not another panel's cache. Server order, empty Categories and duplicate names are
preserved. Name, numeric ID, organization section and Archive disclosure distinguish destinations;
writes use numeric identity, never names. Archived non-trashed Applications and Category targets
remain eligible. Pipeline/pseudo-Categories are excluded. Trashed Applications cannot be
reassigned and trashed targets cannot be entered; a live Application may leave a trashed source
by moving or clearing. Unavailable source metadata remains an explicit Category reference,
not uncategorized. No reverse Category navigation, restore or unarchive control was added.

Non-null destinations are reread by scoped detail GET before final confirmation, validating
identity and disclosing current lifecycle/Archive/section. This improves disclosure but does
not eliminate races or create a transaction snapshot; backend admission remains final authority.
Explicit confirmation distinguishes the Application, current membership and desired identity
or clear operation, and states classification is unchanged. Same-target assignment and
already-uncategorized clear are suppressed in the UI; valid backend no-op receipts remain supported.
There is no backend confirmation challenge or durable assignment replay protocol.

The existing `category_revision` protects Application Category-membership changes only.
Stale checking precedes no-op handling. Assignment/move/clear increments it only when membership
changes; same-target/current-revision no-op does not increment. It does not version Application
labels or classification, Category metadata or Category lifecycle; it is not a general
Application version and does not solve manual-status concurrency.

Each confirmed intent dispatches at most one assignment PUT with frozen scope, identity,
destination and observed revision. Separate read/mutation generations, aborts and immediate
invalidation guard obsolete callbacks after Back/Close, selection, Workspace, panel or session
changes. Pending writes/reconciliation withhold another assignment; client cancellation does
not prove server rollback. Revisiting requires fresh authoritative reads.

Mutation receipts are transient, not final display authority. After a dispatched attempt,
current Application state is reread and standalone detail refreshed. Stale revision and
Trash/unavailable refusals reconcile without silently substituting a revision or target;
ambiguous unavailable errors do not identify a specific resource without subsequent evidence.
Inherited busy wording is normalized to assignment-specific guidance without request-key language.
Known rejection means the server rejected the requested mutation; unknown outcome means the
browser cannot prove whether a dispatched request committed. Lost responses, malformed success
and uncertain server failures refetch membership while preserving uncertainty about causality.
No automatic write retry occurs, including with a refreshed revision; another mutation requires
fresh action observation and explicit user intent. If post-write reconciliation fails, mutation
authority is discarded and further writes are withheld until GET-only refresh successfully
reestablishes safe current state.

Every assignment attempt invalidates the standalone Application list observation; list reload
precedes Back presenting it again as current. Cached rows are not patched into authority.
Category browsing refetches through existing read authority on reopening; retained-review current
Application observations refetch normally. Hidden panels are not synchronously updated and no
shared mutable membership cache exists. Historical review candidates/classification/relationships
and extraction evidence remain unchanged.

Assignment changes only organizational Category membership and `category_revision`. Clearing
means no Category membership, not movement into a pipeline or pseudo-Category. Neither assignment
nor clear changes Application section/classification, lifecycle, status, overrides, dates,
documents, messages, retained relationships, extraction evidence or canonical posting state.

Retained **pre-commit implementation evidence**: Node **33 passed, zero failures/skips**;
Chromium 154 combined assignment/Application/Category/review/evidence/shell/session browser
**87 passed, zero failures**; focused Django **31 passed in 1.575 seconds**; neighboring Django
**128 passed in 16.800 seconds**. Explicitly labelled `accounts applications documents email_sync postings core` suites **1,363 total: 1,350 passed, 13 PostgreSQL skips**, zero failures/errors,
159.507 seconds. System check, Python AST, JavaScript syntax and whitespace passed. Postings drift:
none; global drift: only known `EmailAccount.provider` alteration, not generated. Tests ran before
implementation commit; the reviewed/staged snapshot matched tested implementation. Tests were
not rerun during implementation commit/push or documentation planning; application tests are not
being rerun during this documentation edit. No fresh PostgreSQL operational, Safari, legacy-suite,
deployment or generic-discovery validation is claimed.

Browser validation included a genuine committed-but-response-lost case: the real assignment PUT
reached the backend and successful completion preceded hiding the caller response. Reconciliation
GET observed changed membership; exactly one PUT occurred and the UI preserved causal uncertainty.
This is validation evidence, not a durable backend replay guarantee.

Generic no-label discovery remains a **PRE-EXISTING NON-BLOCKER**, unresolved, unremediated and
not green; this slice did not alter discovery. Both prior traffic-coverage MINORs remain
non-blocking, unremediated and test-specific; their historical explanations remain below.

**MINOR — Assignment GET traffic policy is not bound to workflow scope** remains a non-blocking,
unremediated test-coverage limitation. Assignment PUT assertions remain exact; production helpers
validate captured scope and safe IDs, and no mis-scoped production GET was observed. The GET test
allowlist accepts matching off-context identities more broadly than ideal; this is not a production
scoping defect, security defect, authority violation or implementation blocker.

Positive JavaScript-safe numeric identities and nonnegative JavaScript-safe revisions remain
required; unsafe values fail visibly. Backend integer representation is unchanged; support for
arbitrarily large numbers remains unresolved. Lists remain unpaginated, navigation/action selection transient,
resource/deep links absent, inherited payload/serializer costs unchanged and scale/performance
unvalidated. Category create/edit/rename/archive/unarchive/Trash/restore, Application Trash/restore,
manual-status override, retained-review actions, document/message/dossier browsing, provider
automation and canonical-posting browser/mutation work remain outside this checkpoint. It adds
no persistent action state, routing redesign, general mutation infrastructure or deployment readiness.
All production browser, storage/jobs, deployment, operations, backup/restore, cutover and retirement
gates remain open. The future documentation commit has not been created; its SHA is unknown.

### Workspace-Scoped Read-Only Category Navigation and Application Core Inspection — committed checkpoint, 2026-10-06

Reviewed, committed and pushed at `17ec29a476503d0e91ce7b6f123604386e04dad3`
(`Implement read-only Category workspace browser`), parent documentation checkpoint
`6b91cd0f8c0b3a58334535db2a42a122a6ce73c0`
(`Reconcile retained Application review browser status`). Six files changed, with
511 insertions and nine deletions: browser/client, disposable fixtures and tests only.
Production Category/Application APIs and business semantics, models, migrations, settings,
dependencies, provider code and documentation were unchanged in the implementation commit.

Authenticated Django mode now offers Workspace-scoped named Category list/detail/member
inspection and direct member Application core-detail navigation. This consumes existing
backend GET authority; new authority is read-only browser presentation and transient
navigation only. Back/Close, explicit refresh, loading/error/retry and unavailable states
are supported. Request generations, aborts and immediate cancellation protect Category
list, sequential detail/member inspection and shared Application detail, including obsolete
success/error/finalization and authentication responses. Workspace/session/selection changes
clear obsolete state; one primary workflow panel is active. Category/member strings render
as plain text without raw HTML presentation or a general security-audit claim.

Archived, non-trashed Categories are intentionally included. Empty Categories remain
inspectable; duplicate/similar names remain distinct by stable numeric and portable identity,
with ID, organization section and Archive disclosure distinguishing records. Server ordering
is preserved. Archived Category detail and archived live member Applications remain visible;
Archive is independent from Trash. Category organization section and Application section may
differ legitimately; neither determines or rewrites the other. The protected `applications`
pipeline classification remains outside named Categories; no pipeline/uncategorized row is
synthesized.

Displayed membership comes only from the Category membership GET, not reconstruction from
the Application list or inference from names/sections. It is a current observation, not
historical provenance or cached frontend authority. Category detail and membership are
sequential advisory reads, not one transaction-wide snapshot. Known trashed detail prevents
a member request. If later membership reports Category Trash or unavailability, previously
validated detail may remain as an earlier observation while members clear. Trash, 404 and
request errors are not empty Categories; empty is shown only after successful empty membership.
Retry Category inspection clears dependent state and repeats detail before eligible membership.

Known member Applications open directly by scoped detail GET without loading the full
Application list, reusing existing core-detail read authority and lifecycle disclosure.
Supplied portable Application identity is verified case-insensitively. Current detail may
show changed Category, Archive, Trash or unavailability; Application identity is distinct
from membership state, and later observations do not erase the earlier Category observation
or prove continued membership. The standalone Application detail Category reference remains
non-navigable: this slice adds Category → Application navigation, not the reverse direction.

Retained pre-commit implementation evidence: Node **28 passed, zero failed/skipped**;
Chromium combined Category/Application/review/extraction-evidence workflow **65 passed,
zero failed**; focused Category/membership Django **23 passed**; neighboring Django
**128 passed**. Explicitly labelled `accounts applications documents email_sync postings core`
suites **1,342 passed, 13 PostgreSQL-only skipped**, zero failures/errors (1,355 total;
final run 144.211 seconds). System, Python AST/static, JavaScript syntax and whitespace
checks passed. Postings drift: none; global drift: only known `EmailAccount.provider`
alteration, not generated. Tests ran before implementation commit; the staged snapshot
matched the reviewed implementation. Tests were not rerun after commit/push or during
documentation reconciliation. No fresh Safari, production-browser, PostgreSQL operational,
legacy-suite or generic-discovery validation is claimed.

Generic no-label discovery remains a **PRE-EXISTING NON-BLOCKER**, unresolved, unremediated
and not green. This Category slice did not change discovery/settings; earlier evidence remains
below. The prior retained-review traffic-coverage caveat remains unchanged in its entry below.

**MINOR — Category traffic assertion excludes later coexistence intervals** remains a
non-blocking testing limitation: the narrow assertion covers the main Category workflow,
while later coexistence-test Category intervals use the broader combined traffic policy.
No unauthorized production Category request was observed. No remediation was performed.

Accepted limitations: Category list and membership arrays are unpaginated; all returned
records render without silent truncation. Full serializer/download cost is inherited;
payloads are not bounded by this slice; large-scale performance remains unvalidated.
JavaScript-safe numeric IDs remain required; unsafe identities fail visibly without changing
backend representation or providing arbitrary-large-ID support. Selection is transient,
Workspace hash routing is unchanged, and panel state is not persisted; browser refresh loses
selection. No pagination API or resource/deep links were added.

No Category create/rename/edit/archive/unarchive/Trash/restore, Application assignment/
Trash/restore/manual override, retained-review mutation, pipeline redesign, document/message/
body/dossier browsing, canonical posting UI, provider automation, generalized routing or
persistence was added. This is frontend/product progress only; production browser support,
scale/performance, deployment, operations, backup/restore and cutover gates remain open.
Documentation reconciliation was subsequently committed at
`a8b2cbfead42fcf0b0f187ca305ca59e4a604f2f`
(`Reconcile Category workspace browser status`), with this implementation checkpoint as parent.

### Workspace-Scoped Read-Only Retained Application Review Inspection and Application Core Navigation — committed checkpoint, 2026-10-06

Reviewed, committed and pushed at `bcad64038e6fbb4c224dc5a7ddfe075d4b3f22f7`
(`Implement retained Application review browser`), parent documentation checkpoint
`4fea42f9de9baa2ce86e4cf26f3c6138fde15d90`
(`Reconcile Application browser migration status`). Six files changed, with
586 insertions and 38 deletions: browser/client, disposable fixtures and tests only.
Production review/Application APIs and business semantics, models, migrations, settings,
dependencies, provider/Category production code and documentation were unchanged.

Authenticated Django mode now offers Workspace-scoped inclusive retained Application
review list/detail inspection, with explicit **Load more reviews**, Back/Close and
loading/empty/unavailable/error/retry states. It consumes existing backend GET authority;
new authority is presentation and transient navigation only. Request generations,
aborts and immediate navigation cancellation protect list/page, review and Application
reads, including obsolete success/error/finalization and authentication responses.
Workspace/session/selection changes clear obsolete state; only one workflow panel is active.
Provider/user strings render as plain text, without a body/HTML viewer or a general
security-audit claim. Existing Application and extraction-evidence workflows passed
combined regression validation; legacy frontend separation is preserved.

**Initial candidate snapshot** membership and initial classification are historical
provenance. **Current Application information** (company/role/section) and **Current
availability** are current observations; original company/role snapshot labels are not
supplied or fabricated. Candidates remain distinct and are not relationships or acceptance;
ordering is not confidence ranking. **Existing source relationships** are separate canonical
retained-source/Application links, not review completion or proof of a browser action.
Current disposition is **Active** or **Dismissed**; restored reviews appear Active.
Current sticky source conflict is independent of disposition and does not mean dismissal,
acceptance or review invalidity. No corrective-action authority was introduced.

Referenced Applications open directly by scoped detail GET without loading the full
Application list, reusing existing core-detail read behavior and lifecycle disclosure.
Candidate destinations additionally verify the known Application portable UUID; relationship
references do not supply that UUID. Live and archived targets are inspectable; Archive is
separate from Trash. Trashed targets have read-only disclosure and no restore control.
Removed candidates retain portable provenance without a destination request; unavailable/
disappearing destinations clear detail without erasing historical review provenance.

Retained pre-commit implementation evidence: Node **23 passed, zero failed/skipped**;
Chromium combined review/Application/extraction-evidence workflow **51 passed, zero failed**;
retained-review Django **27 passed**; neighboring regression **127 passed**; combined
focused/neighboring **154 passed**. Explicitly labelled
`accounts applications documents email_sync postings core` suites **1,338 passed,
13 PostgreSQL-only skipped**, zero failures/errors (1,351 total; final run 159.765 seconds).
System, Python AST/static, JavaScript syntax and whitespace checks passed. Postings drift:
none; global drift: only known `EmailAccount.provider` alteration, not generated.
Tests ran before implementation commit; the staged snapshot matched the reviewed state.
Tests were not rerun after commit/push or during documentation reconciliation. No fresh
Safari, PostgreSQL, legacy-suite or generic-discovery validation is claimed.

Generic no-label discovery remains a **PRE-EXISTING NON-BLOCKER**: harness-gated
`config.settings.test_postgres` requires its PostgreSQL manifest. This slice did not
cause or remediate the limitation; discovery/settings are unchanged and generic discovery
is not green. Earlier observed discovery evidence remains below.

**MINOR — workflow-specific traffic assertion coverage** remains a non-blocking testing
limitation: the combined browser allowlist permits reads used by other panels and is
broader than the review-specific GET boundary. Reviewed production retained-review code
contains no unauthorized extra reads. No remediation was performed in this slice.

Accepted limitations: review-list traversal uses existing deterministic keyset continuation,
not a snapshot; current values may change between reads and accumulated pages consume
browser memory. Complete returned candidate/relationship arrays are unpaginated and not
silently truncated. Reported counts can differ from returned references under filtering/
concurrency; large-detail performance remains unvalidated. Creation-result history is not
retained in browser state, rendered or navigated; inherited backend serialization, payload
and validation work remains. JavaScript-safe numeric IDs remain required; unsafe IDs fail
visibly without changing backend identity representation or adding general large-ID support.
Navigation is transient, Workspace hash routing unchanged, and panel state is not persisted;
refresh loses selection. No resource routes, deep links or generalized pagination were added.

No review create-Application/attach/accept/dismiss/restore or other browser mutation, Category
workflow, document/message/body/dossier/AccountMatch or creation-result-history browsing,
extraction execution, canonical posting navigation, provider automation, candidate/relationship
pagination or generalized routing was added. This is frontend/product progress only;
production browser support, large-scale performance, deployment, operations, backup/restore
and cutover gates remain open.
Its documentation reconciliation was subsequently committed at
`6b91cd0f8c0b3a58334535db2a42a122a6ce73c0`
(`Reconcile retained Application review browser status`), with this retained-review
implementation checkpoint as parent. Later Category browsing above extends the browser
consumers; original scope, counts, exclusions and limitations remain historical.

### Workspace-Scoped Read-Only Application List and Core Detail Browser Workflow — committed checkpoint, 2026-10-06

Reviewed, committed and pushed at `845ad1f57addaf350b974aeaecc5aba5a750d2fa`
(`Implement read-only Application workspace browser`), parent documentation checkpoint
`29142286011a2e4d15ae148f998506ed08bcbaea`
(`Reconcile PostgreSQL validation migration status`). Six files changed, with
353 insertions and seven deletions. Only the Django browser/client and disposable
fixtures/tests changed; production Application APIs, serializers, services, models,
migrations, settings, dependencies, provider/Category production code and documentation
were unchanged in the implementation commit.

Authenticated Django mode can open Applications for the selected Workspace, load the
existing list, select one scoped core detail, return to the retained list and close.
Repeated company/role attempts remain distinct numeric-ID records, with portable UUID
as secondary detail identity. Non-pipeline sections remain visible as classifications.
The browser displays existing server-resolved effective status/applied date, lifecycle,
activity/provenance and derivation state without client business-logic recomputation.
This adds presentation/navigation authority only; backend read authority already existed.
Loading, empty, unavailable, error and explicit retry states are supported. Separate
list/detail request generations and aborts protect Workspace/session/selection changes,
Back, Close and retries; session expiry clears sensitive panel state. The existing
extraction-evidence browser remains separate and passed combined regression validation.

The default list uses existing live-record filtering without requesting Trash. A
subsequently trashed detail remains inspectable with prominent read-only disclosure
and no restore control; Archive is independent. Unavailable detail clears old content.
Core detail preserves activity date/instant precision, descriptive source labels and
calendar timezone where available. Empty historical provenance remains unknown/
unreconciled. Document identities, dossier, documents, messages/email and retained-review
evidence navigation are excluded. Category reference is a reference only: no name fetch,
visibility inference, navigation or mutation; Category never defines identity or status.

Retained implementation evidence: Node **18 passed, zero failed/skipped**; Chromium
combined Application/evidence workflow **34 passed, zero failed**; Application view tests
**23 passed**; surrounding Application/Workspace/authentication/frontend-entry subset
**68 passed**; explicitly selected `accounts applications documents email_sync postings core`
suites **1,335 passed, 13 PostgreSQL-only skipped**, zero failures/errors (1,348 total).
Django system, Python/static and whitespace checks passed. Postings migration drift:
none; global drift: only the known `EmailAccount.provider` alteration, not generated.
Tests ran against the reviewed implementation before commit; staging verified the
matching snapshot. Tests were not rerun after commit/push or during this documentation
reconciliation. No fresh legacy suite or Safari validation is claimed for this slice;
prior evidence remains historical.

Generic no-label discovery: **PRE-EXISTING NON-BLOCKER**. That run was unsuccessful:
1,349 total, one discovery error and 13 skips. It imports the intentionally harness-gated
`config.settings.test_postgres` without its required PostgreSQL manifest. That settings
file was verified byte-identical to the authoritative parent; this Application slice
neither introduced nor worsened the behavior. The successful explicit application-suite
run above is separate evidence; generic discovery is not green. No remediation occurred.

Accepted limitations: Workspace hash routing is unchanged; Application selection is
transient and refresh loses panel/detail selection. No Application resource/deep-link
route exists. Numeric Workspace/Application/Category identities used here must be
JavaScript-safe; unsafe identities fail visibly, without changing backend representation
or providing general large-integer support. The Application list remains unpaginated:
the entire returned current list loads without silent truncation, so server/download work
is not bounded by this slice. Large-Workspace performance remains unvalidated; pagination
requires separate API scope. Reads are advisory observations, not a list/detail snapshot.

No Application create/edit, override/status/date/derivation mutation, Trash/restore,
permanent deletion, Category workflow, document/upload/dossier/message browsing, review
acceptance, canonical posting mutation, provider automation, execution state, pagination,
generalized routing, deep links or framework migration was added. Production browser
acceptance/support, performance, mutation workflows, deployment and cutover remain open.
Its documentation reconciliation was subsequently committed at
`4fea42f9de9baa2ce86e4cf26f3c6138fde15d90`
(`Reconcile Application browser migration status`), with this Application implementation
checkpoint as parent. Later retained-review browsing above extends its consumers; the
original slice scope, exclusions, counts and limitations remain historical.

### Isolated PostgreSQL Validation of Retained Extraction Transactions and Workspace Gating — committed checkpoint, 2026-10-05

Reviewed, committed and pushed at `c71f6cdcf183a4e76333b2c62582b8ecfdb1fc68`
(`Validate retained extraction concurrency on PostgreSQL`), parent documentation checkpoint
`88b3c11f0b98e76b55c0cbd46fc2f4ffabd68696`
(`Reconcile retained extraction evidence workspace UI status`). The implementation commit
contains nine files, 784 insertions and nine deletions: isolated validation infrastructure,
new tests and narrowed test-only SQLite contention handling. Production services,
transaction semantics, models, migrations, default/production settings and
`backend/requirements.txt` are unchanged.

PostgreSQL evidence covers the exercised producer/recorder serialization, Workspace
gating, retained-source row locking, equivalent first-attempt replay and conflicting
valid operation payloads. Real retention/extraction conflict ordering passes in both
directions, alongside same-Workspace serialization, independent-Workspace progress,
caller-owned rollback/uncommitted visibility, atomic rollback after later-output
persistence failure, and authorization/cross-Workspace rejection without parsing or
evidence creation. Observed blocking and outcomes are scenario-specific evidence,
not universal lock-ordering, deadlock, isolation or performance guarantees.

Retained implementation evidence: harness safety **14 passed**; focused PostgreSQL
**13 passed, zero skipped**; six existing PostgreSQL suites **157 passed, zero skipped**;
full isolated SQLite **1,332 passed, 13 PostgreSQL-only skipped**. PostgreSQL and SQLite
system checks passed. Postings migration drift: none; global drift: only the known
`EmailAccount.provider` alteration, not generated. Whitespace checks passed. Tests ran
against the reviewed implementation before commit; the staged snapshot was verified to
match it. Tests were not rerun after commit/push or for this documentation edit.
Populated historical migration-fixture evidence remains SQLite-specific.

Environment: Homebrew PostgreSQL **17.11**, Psycopg **3.3.6**, Apple Silicon/macOS;
a disposable private cluster and Unix socket with TCP disabled. The harness verifies
cluster identity, refuses existing test databases and creation collisions without
clobbering, and verifies owned-cluster shutdown/removal. No `brew services`, forced
global linking or production/default database configuration change was used.

This resolves absence of bounded extraction/retention PostgreSQL evidence only.
Concurrency outside that cooperating boundary, provider automation/integration,
production throughput/load and deployment/database/cutover behavior remain unvalidated.
No provider extraction automation, source-admission or recurring automatic operation
identity policy, selector policy, durable execution intent/state, retry/outbox behavior,
provider cursor integration, automatic retained-to-canonical workflow, Application
mutation/workflow or broader frontend completion is established. Production storage,
Redis/Celery/Beat, static/media delivery, backup/restore, rollback and browser/cutover
acceptance remain open. Its documentation reconciliation was subsequently committed
at `29142286011a2e4d15ae148f998506ed08bcbaea`
(`Reconcile PostgreSQL validation migration status`), with this PostgreSQL implementation
checkpoint as parent.

### Retained Extraction Evidence Read-Only Workspace UI — committed checkpoint, 2026-10-05

Reviewed, committed and pushed at `8a4af32e4fb9949430487449e5cbaaea5ab93a3c`,
parent `4da29a186322aa2eb4aa53d388aec2322785b6d1`. After successful Workspace
connection, DjangoFoundation offers an `Extraction evidence` panel consuming existing
`GET /api/workspaces/{workspace_id}/retained-messages/` summaries and
`GET /api/workspaces/{workspace_id}/retained-messages/{retained_message_id}/posting-extractions/`
history. Source selection is transient; `#/workspaces/{id}` is unchanged, with no source
deep link. Close discards panel state; reopen refetches. No browser persistence, polling
or automatic fetch of all sources/history is added.

Bounded summaries use explicit `Load more sources`; labels show safe numeric source ID,
retained time and Retained/Conflicted state, without subject/body/sender/provider locator.
No raw retained-detail viewer or fetch is added. History uses the server default evidence
limit, explicit `Load more history` and opaque `next_cursor`, without browser decoding,
reconstruction or editing. Server order and advisory/non-snapshot semantics are preserved.
No-source, no-history, completed zero-output and conflicted/ineligible historical states
remain distinct. Outputs start collapsed, with one operation expanded at a time;
already-loaded outputs reveal in batches of 50, with all returned outputs accessible
(including the 1,000-output fixture) and no additional evidence request for disclosure.
React text escaping, duplicate outputs and distinct null/explicit blank values are
preserved; `input_spec_json` and extraction/output database IDs are not displayed.

Browser-routed Workspace/source/continuation numeric IDs must be positive JavaScript-safe
integers; unsafe values fail closed. This is a browser-consumer limitation only, without
narrowing the backend ID contract. Portable UUIDs provide UI/key identities where
appropriate, not replacement numeric API route identity. Captured Workspace context,
source-level request generations and cancellation reject stale success/error/finalization;
Workspace, panel close, account/session and logout changes reset state. Independent tabs
retain separate context; no global active Workspace is introduced.

The existing CDN React/Babel runtime remains: no package.json, npm/Vite/webpack build
pipeline, TypeScript migration or framework rewrite. Legacy `App` behavior is unchanged;
the workflow lives in DjangoFoundation. New authority is browser presentation/navigation
only: no extraction/retry execution, provider/sync automation, source mutation, association,
interpretation, mapping, allocation, arbitration, projection, Application mutation,
queue/scheduling or production/cutover readiness. No backend production, model, migration,
settings, URL, provider, dependency, package or documentation file changed in this
five-file implementation (673 insertions, 5 deletions).

Retained implementation/final-review evidence: Node/client **16 passed**, no failures/skips;
Chromium **28 passed**, no failures; relevant Django **95 passed**, affected apps and full
Django **1,332 passed** each, with no failures/errors/skips. System/static checks passed;
postings migration drift: none; global drift: only the known `EmailAccount.provider`
alteration, not generated. Browser validation rejected forbidden mutation/provider/raw-detail
traffic and confirmed expected read-only evidence workflow requests. Fixture hooks,
interception and framing relaxation remain test-only; production root retained
`X-Frame-Options: DENY`, without fixture hooks/endpoints/credentials. These targeted checks
do not establish production operational readiness. Tests were not rerun during commit/push,
documentation planning or this documentation edit; these are retained results.

Retained legacy pytest: **367 passed, 3 failed, 2 warnings**. The failures
`test_export_then_import_round_trips_notes_and_status`,
`test_export_then_import_round_trips_hub_settings` and
`test_deleting_an_application_clears_its_status_history` independently reproduced on the
untouched authoritative parent; they are pre-existing/environment-dependent, not
regressions introduced by this UI slice. Safari was not freshly validated because native
automation permissions were unavailable; older Safari results below remain historical.
Accepted limitations include browser safe integers, memory consumed by manually accumulated
history and advisory pagination. Broader Application/domain frontend migration, provider
extraction automation and production/cutover validation remain separately scoped. This UI
run did not validate PostgreSQL; the later checkpoint above supplies only bounded
extraction/retention concurrency evidence, leaving broader PostgreSQL operation unverified.

### Workspace-Scoped Read-Only Retained Extraction Evidence HTTP API — committed checkpoint, 2026-10-05

Reviewed, committed and pushed at `56214508cd646650863b23628e58c10b80fea010`,
parent `e96a33c13a3a554a4faa6bdffa6118a30a89316f`. The endpoint
`GET /api/workspaces/{workspace_id}/retained-messages/{retained_message_id}/posting-extractions/`
(route name `retained-posting-extraction-list`) requires authenticated session ownership,
reuses existing Workspace scoping and explicit source routing, and calls the existing
source-scoped evidence reader. Historical operations preserve no-history versus completed
zero-output semantics and valid conflicted-source inspection with `source_eligible=false`.

Strict bounded navigation uses default limit 2 and maximum 5, with a stateless unsigned
canonical base64url cursor. The cursor carries navigation state, not authorization;
Workspace/source context is independently revalidated. Valid numeric `last_extraction_id`
changes intentionally alter navigation. Pagination remains advisory, not a snapshot.
Explicit response-field whitelists exclude raw retained content, provider payload/locator,
credentials and association/canonical identity fields. `input_spec_json` remains a canonical
extraction-metadata string; historical order, nulls, blanks, duplicates and timestamps are
preserved.

JSON-only GET/HEAD/OPTIONS handling has no mutation handlers and sets
`Cache-Control: no-store`. Existing 400/401/404/409 conventions are preserved; DatabaseError
inside APIView dispatch receives a fixed sanitized 500 without raw exception text, SQL or
source content. Earlier middleware failures remain governed by existing infrastructure.
Ordinary endpoint/domain behavior is read-only; exceptional Django session maintenance may
legitimately update/delete session infrastructure without becoming domain mutation.

This adds HTTP transport/navigation authority only: no extraction execution, provider/sync
adoption, automatic source admission, generated operation identity, selector inference,
item association, interpretation, PostingSource mapping, allocation, arbitration,
projection, Application mutation, frontend workflow, PostgreSQL validation or scheduling/
retry state. No model, migration or durable cursor state is added.

Retained implementation/final-review evidence: API **18 passed**, source inspection
**22 passed**, recorder **34 passed**, producer **22 passed**, batch command **29 passed**,
retained interpretation **58 passed**, retained posting review **53 passed**, Candidate
Discovery **26 passed**, combined focused **262 passed**, postings **615 passed**, affected
apps **1,332 passed** and full Django **1,332 passed**, with no failures/errors/skips.
Django system check passed; postings migration drift: none. Global dry run reported only
the known `EmailAccount.provider` alteration, not generated. Static/scope checks passed.
Application tests were not rerun during commit/push and are not being rerun merely for
this documentation maintenance; these are retained results, not fresh documentation-stage
application tests.

Accepted limitations: advisory pagination, unsigned valid boundary edits, APIView-local
DatabaseError sanitization and exceptional session maintenance remain as described above.
This HTTP run did not validate PostgreSQL; the later checkpoint above supplies bounded
extraction/retention evidence. Broader PostgreSQL operation and production deployment
remain unverified; provider extraction automation remains unresolved/unvalidated. At this HTTP checkpoint, the
browser/frontend workflow was unimplemented; the later UI checkpoint above now supplies
retained extraction evidence inspection. Broader Application/domain frontend work remains
separately scoped.
Provider/storage/jobs/backup-restore/cutover gates remain open.

### Source-Scoped Retained Extraction Evidence Inspection — committed checkpoint, 2026-10-05

Reviewed, committed and pushed at `b3a8d451272bd1ee5e4626e4b30ebd5f5f6cbc63`,
parent `09e07d821615b1571668dcc7c3e5734bafeed906`. Explicit actor/Workspace/source
context reuses existing owner authorization and retained-source integrity validation.
The domain reader exposes historical operations before item association, distinguishing
no recorded extraction history from a completed zero-output operation without drawing
job/relevance conclusions. Unassociated outputs remain inspectable.

Bounded ascending-PK keyset navigation returns detached immutable source/operation/output
DTOs and canonical immutable input-specification JSON. Every returned operation uses the
existing extraction-owned complete batch validator; corrupt returned evidence fails the
whole call rather than returning a partially validated page. SELECT-only reads acquire
no write locks. Source eligibility is advisory current state; pages are not snapshots,
and later higher-PK operations may appear on subsequent reads.

This adds read/navigation authority only: no extraction or replay execution, provider/sync
adoption, automatic admission, generated operation identity, inferred selectors, item
association, interpretation/mapping/allocation/arbitration/projection or Application writes.
No HTTP routes, serializers, frontend consumer, cursor transport encoding, durable work
state or scheduling were introduced by that slice. At that checkpoint, a later read-only
HTTP API remained separately scoped and unselected; the completed adapter is recorded above.

Retained implementation/final-review evidence: targeted correction **2 passed**, source
inspection **22 passed**, combined focused **244 passed**, postings **597 passed**,
affected apps **1,314 passed** and full Django **1,314 passed**, with no failures/errors/
skips. Django system check passed; postings migration drift: none. Global dry run reported
only the known `EmailAccount.provider` alteration, not generated. Static/scope checks passed.
Application tests were not rerun during commit/push and are not being rerun for this
documentation maintenance; these are retained results, not fresh application tests.

Accepted limitations: reads are advisory, not snapshots. This inspection run did not
validate PostgreSQL; later bounded extraction/retention evidence is recorded above,
without establishing broader operational behavior. Reusing the complete validator costs queries per returned operation
and transient memory. Privileged evidence rewrites remain unsupported; arbitrarily
oversized corrupt database JSON may allocate before validation rejects it. Cursor transport
serialization was future API work at that checkpoint and is now supplied by the adapter
above. Provider/storage/jobs/backup-restore/cutover gates
remain open.

### Explicit Retained Extraction Request Batch Command — committed checkpoint, 2026-10-05

Reviewed, committed and pushed at `97751b857ba0ce784cd7b80d7c9fa42930204285`,
parent `1f79d0050b154112d7cd033fbf35376559b052ea`. The management command accepts
one bounded strict JSON request file, validates the entire structure and authorizes an
explicit persisted actor/Workspace before any execution. Caller-owned operation UUIDv4s
and exact retained input specifications define requests; specifications are detached before
execution, with regression coverage proving nested mutation independence.

Requests run sequentially in supplied order through the existing producer as the sole
extraction execution authority. No command-wide transaction encloses the independent
producer transactions. First failure stops execution while preserving earlier committed
entries; unchanged retry replays completed operations. Transaction-context rejection
before invocation leaves the current request unattempted; once invocation begins, that
request counts as attempted even if it fails. Execution terminates at immutable extraction
evidence with deterministic content-free JSON reporting.

This is an operator execution boundary only. It does not complete provider/sync adoption
or decide provider operation-ID, admission/classification or failure/retry policies.
Automatic retained-item association, interpretation/PostingSource/allocation automation,
arbitration/projection automation, retained-to-canonical JobPosting ingestion and
retained-workflow API/frontend integration remained incomplete at that checkpoint; later
checkpoints above supply the extraction evidence HTTP API and browser consumer only.
No model, migration or downstream authority change is included in the batch slice.

Retained implementation/final-review evidence: command **29 passed**, combined focused
**174 passed**, postings **575 passed**, affected apps **1,292 passed** and full Django
**1,292 passed**, with no failures/errors/skips. Django system check passed; postings
migration drift: none. Global dry run reported only the known `EmailAccount.provider`
alteration, not generated. Diff, AST, final-newline, whitespace and empty-initializer
checks passed. Application tests were not rerun during commit/push and are not being
rerun for this documentation maintenance; these are retained results, not fresh tests.

Accepted limitations: this batch-command validation used isolated SQLite databases.
Later bounded extraction/retention PostgreSQL evidence is recorded above; broader
operational behavior remains unverified. Invocation is operator-controlled, with no durable batch
lifecycle; retry requires preserved operation UUIDs/specifications. Stdout delivery can
fail after successful persistence, and unexpected connection/commit failures can leave
the failing request's state uncertain. Standard operator debugging such as `--traceback`
may expose stack details outside the normal sanitized output contract. Broader
provider/storage/jobs/backup-restore/cutover gates remain open.

### Retained-Text Job-Alert Extraction Producer — committed checkpoint, 2026-10-05

Reviewed, committed and pushed at `56c45dcb6768e6af9ab73f7c739ee27c665020f1`,
parent `a9e2be91dd4a6bac0a67e8d21788066e8fcebd3c`. The explicit synchronous producer
resolves declared retained selectors and executes the existing `job_alert_rules` / `"1"`
parser only for new operations. It records through the existing extraction recorder,
using shared extraction-owned persisted-batch validation. Historical replay occurs
before parsing and preserves ordered outputs, IDs and timestamps; changed operation
intent is rejected. Zero-output completion is valid, parser failure records no completed
evidence, and valid historical replay remains available after sticky source conflict
with `source_eligible=False`. Workspace/source locks cover parsing, nested recording
and detached frozen receipt construction; recording and receipt failure roll back new evidence.

This completes extraction production only. Existing explicit downstream authorities
remain implemented separately; automatic retained-item association, interpretation,
PostingSource mapping, canonical allocation and arbitration/projection adoption remain
incomplete. Provider/sync adoption remains unresolved; retained-workflow API/frontend
integration was incomplete at that checkpoint, before the later evidence HTTP/UI adapters
above. No model, migration, parser-semantic, provider, API or frontend change is included
in the producer slice.
The earlier recorder-only provenance scope and exclusions remain historical evidence.

Retained implementation/final-review evidence: focused producer/recorder/interpretation/
parser suites **145 passed**; full Django **1,263 passed**, with no failures/errors/skips.
Django system check passed; postings migration drift: none. Global dry run reported only
the known `EmailAccount.provider` alteration, not generated. Diff, AST, final-newline
and whitespace checks passed. Application tests were not rerun during commit/push
or this documentation maintenance; these retained results are not fresh documentation-stage tests.

Accepted limitations: parsing holds Workspace/source locks; historical replay performs
repeated bounded validation. This producer run used SQLite; later PostgreSQL evidence
above covers exercised contention scenarios only, not broader operational behavior.
Privileged bulk/raw maintenance can bypass cooperative protections, rolled-back parsing
may execute again on explicit retry, and caller-owned outer transactions determine
eventual commit. Provider/storage/jobs/backup-restore/cutover gates remain open.

### Retained Posting Candidate Discovery — committed checkpoint, 2026-10-05

Reviewed, committed and pushed at `3aab4762224efbf1d8e5b11f57040b88eb9a4094`.
The four-file backend slice adds advisory SQL-read-only interpretation observation,
exact company/title candidate discovery, location as factual evidence only, Workspace
and posting-account Workspace safety, ascending-PK keyset pagination and detached
advisory results. It confers no identity or mapping authority and performs no allocation,
interpretation selection, arbitration, projection or Application/disposition writes.
No model, migration, API or frontend change is included.

Retained final-review evidence: focused interpretation/candidate tests **83 passed**;
full Django **1,239 passed**, with no failures/errors/skips. Django system check,
SQL-read-only, detachment and diff checks passed. Postings migration drift: none;
global dry run reported only the known EmailAccount.provider alteration, not generated.
This documentation-only update adds no new application-test or operational evidence;
application tests were not rerun during documentation maintenance.

Accepted limitations: advisory observations are non-serialized; interpretation validation
cost grows with history; candidate pagination bounds canonical rows materialized, not
total database scan cost. PostgreSQL operational behavior remains unvalidated.
Browser/provider/storage/jobs/backup/restore/cutover gates remain open.

### Retained Posting Review Orchestration — historical implementation-stage evidence, 2026-10-04

Subsequently reviewed, committed and pushed at
`ecb2ecf98c7d12552b5b0b9327f1f74fd28388ff`. Counts and Git-stage statements
below describe the original implementation-stage verification, not current repository state.

Prior authoritative checkpoint: `cce6cf08717d6dca18fd1ce8945f68df9589f39e`.
Stateless coordinator and advisory reader implemented within six authorized files;
no model/migration or canonical primitive changes. Independent phase commits preserve
explicit mapping/allocation, selection and projection authority. Strict transaction
context guard, immutable DTOs, detached receipts and structured partial failures are
implemented. Application/disposition/API/frontend behavior remains outside scope.

Fresh tests: orchestration 53; PostingSource 70; allocation 40; combined retained
interpretation/arbitration/projection 151; Application review 83; postings 488;
affected apps 1,187; full Django 1,205. All final runs passed without failures/errors/
skips. Django check passed; postings drift none; global dry-run only the known
EmailAccount.provider alteration, not generated. Python AST, final newlines,
whitespace, Markdown links/anchors and diff checks passed. All three added files
inspected; exact three modified/three untracked scope, empty index, checkpoint and
remote synchronized 0/0, database/provider migration paths absent.

At that implementation stage, the slice was complete and ready for separate read-only
pre-commit review, not yet committed or operationally validated. Independent commits can leave partial
success, ambiguous outcomes require replay, and composed reads remain advisory.
SQLite concurrency is not PostgreSQL operational validation. See
[orchestration review](DJANGO_RETAINED_POSTING_REVIEW_ORCHESTRATION.md).



### Canonical JobPosting Allocation — historical implementation verification, 2026-10-04

Subsequently committed/pushed at `cce6cf08717d6dca18fd1ce8945f68df9589f39e`.
The counts and Git-stage statements below describe the original allocation verification.

Implemented and automated-test verified; sixteen files remain unstaged, uncommitted
and unpushed on django-migration. Prior authoritative checkpoint:
`8ba7bc869787f80b217c0c066f9c713a337a5669`. Separate read-only pre-commit review is next.

- Explicit owner allocation atomically creates a default-only JobPosting, initial
  PostingSource and immutable JobPostingAllocation. Selected interpretation/evidence,
  locator and mailbox binding are validated; reserved identity and ingestion guards,
  historical replay/readers and read-only admin are implemented.
- Fresh implementation-pass results: allocation + migration 40; Gmail migration 1;
  PostingSource 70; retained interpretation 49; arbitration 46; projection 57;
  services/ingestion 19; postings 435; affected apps 1,134; full Django 1,152.
  All final runs: zero failures/errors/skips. Existing passing suites were retained;
  Gmail migration, affected apps and full Django ran after the test-only correction.
- Django check passed; postings drift none; global drift only the known provider
  AlterField (dry-run only). Graph through 0012; inspected SQL creates only the new
  allocation table and constraints/indexes. Populated migration fixture preserves
  existing tables without backfill and checks alias-aware validation.
- Two bounded interruptions required explicit authorization: accidental provider
  migration generation was stopped and repaired only by deleting that file and
  correcting 0012 to email_sync 0007; the Gmail historical fixture's impossible
  email_sync 0006/latest-postings combination was corrected in the authorized
  sixteenth file by pinning postings 0011, preserving current forward leaves and
  all assertions. The latter changes no production behavior.
- Scope: eleven modified, five untracked, nothing staged. Local/origin/live remote
  remain synchronized at the checkpoint (0/0); real DB and both provider migration
  paths absent. Python parsing, newlines, whitespace, Markdown links/anchors and
  diff checks passed; all five added files inspected.
- SQLite concurrency tests use caller retries for contention, not production retries
  or PostgreSQL verification. PROTECT can block account deletion; disconnect remains
  allowed. Raw maintenance bypass, semantic duplicates, orphan lifecycle, unbound
  allocation, API/frontend, historical reconciliation and operational cutover remain
  outside this implementation evidence.

See [allocation review](DJANGO_JOB_POSTING_ALLOCATION_REVIEW.md) for the full contract,
scope, validation and limitations.


### Descriptor projection authority — historical pre-commit verification, 2026-10-03

Subsequently committed/pushed at `8ba7bc869787f80b217c0c066f9c713a337a5669`.
The Git-stage statements and counts below are historical projection evidence.

Prior authoritative checkpoint: `5f832dcc261d13365d851806623fca1a373e1644`.
The current thirteen-file slice is implemented and validated, unstaged/uncommitted/
unpushed, awaiting separately authorized read-only pre-commit review.

- Immutable JobPostingDescriptorProjection records an exact arbitration FK, six-field
  snapshot and matched descriptor-digest precondition. One transaction appends and
  materializes exactly source/title/company/location/salary/employment_type, then
  rereads/verifies. URL, dedupe, identity, metadata and lifecycle remain outside it.
- Destination capacities reject atomically; no widening or normalization. Ownership
  persists after first projection. Ingestion preserves owned descriptors, ordinary
  saves enforce alias-aware guards, and admin rejects stale protected submissions.
- Replay never rematerializes. Explicit drift repair is supported; arbitration/lower
  staleness, descriptor drift and sticky-conflict eligibility remain distinct. Frozen
  coherent readers and captured-prefix history reuse existing arbitration validation.
- Additive migration 0011 creates one table with five named constraints and three
  protected FKs. Populated 0010 and non-default-alias tests pass; no backfill/allocation.
- Fresh corrective-pass suites, 2026-10-04: focused **57 passed** (8.024s),
  postings **393 passed** (32.790s), affected apps **1092 passed** (130.831s),
  full Django **1110 passed** (136.678s), with zero failures/errors/skips.
  Three added regressions cover primary-key-only deferred saves (including forced
  saves), explicit empty saves, and continued projection ownership. Automatic empty
  inference now leaves update_fields unset. Earlier services **17 passed** and
  neighboring authority **256 passed** are prior implementation evidence, not reruns.
- Fresh Django check passed. Prior schema validation: postings drift none; global dry
  run only the known provider
  choice-label alteration, deliberately ungenerated. Graph through 0011; SQL inspected.
  AST/newline/whitespace/local Markdown links and git diff --check passed.
- Exactly eight modified/five untracked authorized files, nothing staged. Checkpoint
  remains unchanged and synchronized. Real DB/provider migration absent. SQLite test
  contention uses explicit caller retry, not production retries or PostgreSQL proof.
- Digest detects current equality, not ABA history. Bulk/raw bypasses, growing history
  cost, PROTECT/purge handling and stale values in existing consumers remain limitations.
  No API/frontend, field widening, allocation, provider or cutover expansion.

See [projection review](DJANGO_JOB_POSTING_PROJECTION_REVIEW.md) for implementation,
commands/log locations, validation details, scope and limitations.

### Posting-level interpretation arbitration — historical pre-commit verification, 2026-10-03

Subsequently committed/pushed at `5f832dcc261d13365d851806623fca1a373e1644`.
The Git-stage statements and counts below are historical arbitration evidence.

Prior authoritative checkpoint `d46ef1508259f0418d1d0c842678456c883f5732`,
subject `Implement retained posting interpretation authority`, parent
`ac6d13db7f52889bff12b128a153e397769fee67`. Branch/local/tracking/live remote,
0/0 ahead/behind, clean pre-edit tree/index, and DB/provider migration absence verified.
See [arbitration review](DJANGO_JOB_POSTING_INTERPRETATION_REVIEW.md).

- Explicit append-only posting selection binds an exact item interpretation and initial
  mapping/revision. No implied winner, fallback, transfer, reactivation or projection.
- Historical mapping/interpretation/membership and extraction witnesses validate;
  independent current witness changes yield all applicable ordered stale reasons.
- Atomic Workspace gate then all relevant sources in ascending order. Replacement checks
  new-source eligibility; conflicted old valid sources allow replacement but current-source
  conflict blocks withdrawal. Validated replay/reads remain allowed; corruption fails closed.
- Additive 0010: one empty table, six constraints, protected references, alias-aware
  insertion guard and read-only admin. Populated-0009 preservation and repeat target tested.
- Focused **47 passed** (4.591s), neighboring **216 passed** (10.204s), postings
  **331 passed** (24.316s), affected apps **1030 passed** (119.098s), full Django
  **1048 passed** (138.057s); all zero failures/errors/skips. Completed affected log
  reused on continuation; full suite ran on 2026-10-03. No production/test edits followed.
- Django check and scoped postings drift pass. Global dry run reports only the known
  EmailAccount.provider choice-label alteration; no file generated. Graph reaches 0010;
  SQL confirms one additive table, six constraints and four automatic FK indexes.
- Exactly eleven authorized files, six modified/five untracked, unstaged/uncommitted/unpushed.
  All added files inspected; syntax, whitespace, local Markdown links and diff checks pass.
  HEAD/local/tracking/live remote remain the prior checkpoint, ahead/behind 0/0;
  DB/provider migration absent. Separate read-only pre-commit review is next.
  PostgreSQL, production scale, providers and cutover remain unvalidated.

### Retained posting interpretation selection — historical pre-commit verification, 2026-09-29

Base `ac6d13db7f52889bff12b128a153e397769fee67` on `django-migration`; branch,
local/tracking/live remote, subject/parent, clean pre-edit tree/index, and DB/provider
migration absence verified. See [interpretation review](DJANGO_RETAINED_POSTING_INTERPRETATION_REVIEW.md).

- Item-level append-only select/withdraw decisions; revision 0 unresolved. Whole-output
  selection records a validated logical membership witness. Later membership revisions
  make selection stale, including away-and-back; explicit reaffirmation appends.
- UUID replay returns original immutable event plus current state; historical membership
  prefixes and complete persisted extraction envelopes/digests validate without parsing.
  Coherent readers share Workspace/source serialization; captured-prefix history pagination.
- Additive 0009 creates one empty table with six constraints and protected references.
  Read-only admin and alias-aware ordinary insertion guards. No mapping, descriptor,
  allocation, ingestion, API/frontend or lifecycle side effects.
- Historical final suites from that implementation pass: interpretation/migration **50 passed** (3.265s), neighboring
  retained-posting **166 passed** (8.586s), postings **284 passed** (18.516s), affected
  apps **983 passed** (118.894s), full Django **1001 passed** (124.966s); zero
  failures/errors/skips. Affected/full completion logs were reused on continuation;
  no implementation/test edits followed these results. Isolated SQLite only.
- Django check and scoped postings drift pass. Global drift is only the known provider
  choice-label alteration; no provider migration generated. Graph/SQL confirm additive
  0009; populated-0008 preservation, repeated target and non-default alias validation pass.
- At that implementation checkpoint: eleven files, six modified/five added,
  unstaged/uncommitted/unpushed; HEAD was the base. DB/provider migration absent;
  added-file inspection, syntax, whitespace, local Markdown links and diff checks passed.
  Separate review and commit/push subsequently completed at
  `d46ef1508259f0418d1d0c842678456c883f5732`. PostgreSQL, production scale,
  providers and cutover remained unvalidated.

### PostingSource correction/effective mapping — historical pre-commit verification, 2026-09-28

Base `482bcc5f9528fb9a6e9b3e7dce1c43a7443c40b3` on `django-migration`; local,
tracking/live remote, parent/subject, clean tree/index and DB/provider-migration absence
verified before edits. See [correction review](DJANGO_POSTING_SOURCE_CORRECTION_REVIEW.md).

- Append-only associate/withdraw events anchored to the initial assertion; revision 0
  initial, contiguous later revisions, UUID replay returning original event plus current
  state, no-op rejection, scoped historical-target validation and captured-prefix readers.
- Additive 0008 creates one empty table with six constraints. PROTECT/read-only admin;
  no allocation, descriptors, interpretation, membership coupling, ingestion or API changes.
- Focused **105 passed** (5.338s); postings **234 passed** (15.194s); affected
  **933 passed** (111.575s); full Django **951 passed** (120.240s). All final runs have
  zero failures/errors/skips, isolated SQLite only. Focused/postings ran before the
  separately authorized one-line core admin read-only allowlist update; affected/full
  ran afterward. The prior affected run's single allowlist expectation failure is resolved.
- Django check and postings drift check pass. Global dry run reports only known
  EmailAccount.provider drift; no file generated. Migration graph/SQL confirm additive
  0008; disposable populated-0007 preservation and non-default alias validation pass.
- At that implementation checkpoint: eleven authorized files, unstaged/uncommitted;
  HEAD was `482bcc5f`. Separate review and commit/push subsequently completed at
  `ac6d13db7f52889bff12b128a153e397769fee67`. The counts above are historical
  implementation evidence. Real DB/provider migration were absent; added-file inspection,
  syntax/whitespace/local Markdown links and diff checks passed. PostgreSQL, production
  scale, providers, cutover and purge remained unvalidated/deferred.

### Initial PostingSource mapping — historical pre-commit verification, 2026-09-28

Base `8812bf8f61de1db5b622af6f61b71a5a1b68fdb3` on `django-migration`; repo/branch,
local/tracking/live remote, subject/parent, clean tree/index and DB/provider-migration
absence verified before edits. See [PostingSource review](DJANGO_POSTING_SOURCE_REVIEW.md).

- Immutable explicit-owner item→existing JobPosting assertion; item-keyed replay,
  many items per posting, no allocation/descriptive interpretation or downstream writes.
  Zero-output items are allowed; later membership correction leaves mapping unchanged.
- Current-owner Workspace gate, persisted endpoint/account scope, source integrity,
  sticky-conflict read/replay semantics, bounded initial-only readers and read-only admin.
  PROTECT intentionally blocks mapped endpoint/account cascades; deletion API handling
  and account decoupling remain deferred. Disconnect retains mapping and account.
- Focused **30 passed** (29 service/model/reader/concurrency/admin + 1 migration; 1.551s),
  postings **192 passed** (13.949s), affected **891 passed** (112.008s), full Django
  **909 passed** (117.394s). External in-memory SQLite/disposable fixtures only.
- System checks, posting migration drift, AST/whitespace/local references/diff checks
  pass. Global dry-run drift is only known EmailAccount.provider; no migration generated.
- Additive 0007 creates one empty table with item OneToOne and two policy checks.
  Historical 0006 fixture preserves all prior rows/columns, including correction history,
  and repeated migration target is stable. No historical mapping inference/backfill.
- At that review: exactly eleven approved files, unstaged/uncommitted; subsequently
  committed at `482bcc5f`. backend/db.sqlite3 absent/untracked;
  provider migration absent. Initial/correction/extraction services, ingestion, parser,
  provider, API/frontend and deletion surfaces unchanged.
- Initial mappings are historical assertions for inspection only. Mapping corrections/
  effective authority must precede canonical consumers. SQLite explicit-retry tests do
  not validate PostgreSQL contention, production scale, live providers or cutover.

### Append-only posting-item corrections — historical pre-commit verification, 2026-09-28

Base `2090a61b1a43252a8eb93d82c87c7d90e4c40074` on `django-migration`; repository,
local/tracking/live remote, subject/parent, clean tree/index and DB/provider-migration
absence verified before edits. See [correction review](DJANGO_RETAINED_POSTING_ITEM_CORRECTION_REVIEW.md).

- Immutable owner-attributed associate/withdraw revisions, operation UUID replay and
  expected-revision concurrency; historical operation and current state are separate.
  No-op rejection does not reserve UUIDs. Initial assertions and old items remain intact.
- Shared chain validation checks all captured revisions; owner-scoped effective reads,
  captured-bound history and read-only admin. Source integrity precedes replay; sticky
  conflict blocks new work including withdrawal, while permitting read/exact replay.
- Focused **33 passed** (32 service/model/reader/concurrency/admin + 1 migration; 1.678s),
  postings **162 passed** (12.477s), affected **861 passed** (110.282s), full Django
  **879 passed** (115.308s). External in-memory SQLite settings/disposable fixtures only.
- System checks, postings drift, AST, whitespace, documentation references and diff
  checks pass. Global dry-run drift remains only known EmailAccount.provider; no file generated.
- Additive 0006 creates one empty table and six constraints; populated historical
  migration test preserves all old tables/rows/columns and repeats the target stably.
- At that review: exactly eleven authorized files, unstaged/uncommitted; subsequently
  committed at `8812bf8f`. Initial service, migration 0005,
  extraction contracts, provider/frontend/API and unrelated production code unchanged.
  backend/db.sqlite3 and unrelated provider migration remain absent.
- SQLite contention tests use explicit retry; PostgreSQL locks/deadlocks, production
  scale, live providers, export/restore and cutover remain unvalidated. No interpretation
  selection, split/merge, PostingSource, ingestion or historical backfill is implemented.

### Durable posting items + immutable initial associations — historical pre-commit verification, 2026-09-28

Base `c5f8e20f9db15e2cf4dc9f0e80a0929bd222fff6` on `django-migration`; local/tracking/live
remote, subject/parent, clean tree/index and DB/provider-migration absence were verified
before edits. See the [item foundation review](DJANGO_RETAINED_POSTING_ITEM_REVIEW.md).

- Source-scoped immutable item identity and initial output associations; explicit-owner
  allocation/attachment only. Output-keyed replay preserves original actor even for a
  different current owner. Same-source validation, atomic allocation, bounded readers
  and read-only admin; no automatic continuity, correction, current selection or mapping.
- Retained-item tests **26 passed** (0.399s), populated migration **1 passed** (0.870s),
  postings **129 passed** (10.312s), affected apps **828 passed** (106.954s), full Django
  **846 passed** (112.804s). Isolated SQLite only; no real database opened or migrated.
- System checks, posting drift, AST, whitespace, local references and diff checks pass.
  Global dry-run drift remains only known EmailAccount.provider; no migration generated.
- Additive 0005 creates two empty tables with protected references and finite constraints;
  existing extraction provenance and all other populated fixture tables are preserved.
- At that review: exactly eleven authorized files; unstaged/uncommitted; backend/db.sqlite3
  and provider migration absent. Subsequently committed at `2090a61b`. Committed extraction 0004/contracts/helpers remain unchanged.
- PostgreSQL locking/deadlocks, production scale, live providers, scheduling, export/restore
  and cutover remain unvalidated. Actor assertion is accountable, not proof of human review.
  At that checkpoint correction/effective decisions were deferred. Interpretation
  selection, split/merge, PostingSource, historical reconciliation and ingestion remain deferred.

### Retained Posting Extraction Provenance — historical pre-commit verification, 2026-09-28

Base `6863f277b04e1f084d6f7b2169c4a8209c65592c` on `django-migration`; repository,
HEAD/tracking/live remote, subject/parent, clean tree/index and absent local DB/provider
migration were verified before edits. See the [extraction provenance review](DJANGO_RETAINED_POSTING_EXTRACTION_REVIEW.md).

- Immutable completed operations and ordered output observations, strict versioned
  input/output contracts, source integrity/scope validation, atomic replay/conflict
  recording, scoped reader and read-only admin. No parser execution or JobPosting writes.
- Initial implementation verification (before correction): provenance **29**, migration
  **1**, combined **30**, postings **98**, retained-source/review **69**, affected **797**,
  full Django **815** passed. The review then found receipt-provenance semantic validation
  missing despite matching digests. This history is preserved in the slice review.
- The bounded correction enforces canonical provider/receipt-source compatibility and
  adjacent receipt precision/value rules, without retention or digest-schema changes.
  New receipt regressions **4 passed**; all provenance **33 passed**, migration **1 passed**
  (combined **34**, 1.440s), retained-source/review **69 passed**, postings **102 passed**,
  affected apps **801 passed** (103.609s), full Django **819 passed** (108.779s).
- System check, posting drift, AST, whitespace, local Markdown references and diff
  checks pass. Global dry-run drift remains only known `EmailAccount.provider`.
- Additive postings 0004 creates two empty tables and three unique constraints; no
  historical backfill. Disposable migration fixture preserves every pre-existing row.
  The separately approved thirteenth-file correction pins the old retained-email
  migration test's pre-retention postings baseline to 0003; assertions remain intact.
- Isolated in-memory/disposable SQLite only; no real database opened or migrated.
  At verification, `backend/db.sqlite3` and provider migration were absent and nothing
  was staged/committed. The slice subsequently committed at `c5f8e20`.
- PostgreSQL concurrency, production payload performance, providers, task/retry
  orchestration, export/restore and cutover remain unvalidated. Recorder trusts the
  producer envelope. At that checkpoint, source items, PostingSource, evidence and
  ingestion remained deferred.

### JobPosting portable identity — historical verification, 2026-09-27

Base `ab1cb0e5e37faff606b1be7c84cf83fb99f77e30` on `django-migration`; local HEAD,
tracking and live remote matched with a clean tree before edits. The approved 11-file
slice was uncommitted during verification and subsequently committed at `6863f277`.
See the [posting identity review](DJANGO_POSTING_IDENTITY_REVIEW.md).

- Identity **5 passed**, populated migration **1 passed**, posting service/view **31 passed**,
  Application identity/creation regressions **25 passed**. Posting-focused **68 passed**
  (7.384s); affected **767 passed** (105.766s); full Django **785 passed** (108.560s).
  All final runs exited 0 against the final code/test state.
- System checks, Python AST, whitespace, Markdown references and diff checks pass.
  Posting model/migration drift is absent. Global dry-run drift is only known
  `EmailAccount.provider`; no unrelated migration file was generated.
- `postings.0003_jobposting_portable_identity` allocates UUIDs without merging rows,
  changing old columns/relationships or inferring source lineage. Direct helper replay
  and migration-target replay preserve assigned identities. A migration test executor-cache
  issue was corrected in the new test harness; production migration was unchanged.
- Verification used isolated SQLite and disposable migration fixtures; no real database
  was migrated. `backend/db.sqlite3` remains absent/untracked; nothing is staged.
- PostgreSQL migration locking/concurrent writes, deployed table size/performance,
  live providers and cutover remain unvalidated. Reverse schema removes UUID identity
  and is not identity-preserving rollback after external consumption.

### Retained review Create Application — historical verification at `ab1cb0e`, 2026-09-27

Base `5e25093a62a6c908d2da8123d1d6a7323eca2cd5` on `django-migration`; HEAD,
tracking and live remote matched before editing, with a clean tree and absent
`backend/db.sqlite3`. Implementation was left uncommitted for review, then committed
and pushed at `ab1cb0e`. See the
[creation review report](DJANGO_RETAINED_REVIEW_CREATE_REVIEW.md) for exact scope,
transaction boundaries, commands and limitations.

- Focused creation/review/identity/Category/derivation/lifecycle/migration/admin:
  **193 passed**, exit 0, 11.751s.
- Affected `applications documents email_sync core postings`: **758 passed**, exit 0,
  102.083s. Full Django: **776 passed**, exit 0, 107.240s, final code/test state.
- Bounded pre-commit correction rejects fresh-key continuations before intent insertion
  under the shared Workspace gate; existing pending state, digest mismatch precedence and
  completed replay are preserved across manual/posting/review creation. Two new persistence
  regression tests pass (0.249s); final suite counts above supersede 191/756/774.
- Django system checks, Python AST, whitespace and local documentation references pass.
  Application model/migration drift is absent; global drift remains only the known
  `EmailAccount.provider` choice change. No unrelated migration file was generated.
- Additive `applications.0010_retained_review_creation_result` is schema-only, with
  no historical backfill. Populated migration preservation and forward replay pass.
  The historical disposition test is pinned to its intended `0009` target without
  weakening preservation assertions; the new creation test is pinned to `0010`.
- Verification uses isolated SQLite settings/fixtures; `backend/db.sqlite3` remains
  absent. The slice was uncommitted during verification and subsequently committed at
  `ab1cb0e` after final review.
- PostgreSQL locking/deadlocks/isolation, live Gmail, browser/frontend, Redis/Celery,
  storage, deployment, backup/restore and cutover remain operationally unvalidated.

### Retained review disposition — historical verification at `5e25093`, 2026-09-26

Base `4d545820f62d92c76cf4da189706f17b3832949f` on `django-migration`; local HEAD,
tracking and live remote verified before edits and again when recovering the eight-file
interrupted implementation. No commit/push occurred during that implementation stage;
the slice was subsequently committed/pushed at `5e25093`. No unrelated changes. See the
[disposition review report](DJANGO_RETAINED_REVIEW_DISPOSITION_REVIEW.md) for exact
commands, file inventory, transaction reasoning and test-harness correction.

- Focused review/disposition/attachment/relationship/historical migration/lifecycle/admin:
  **93 passed**, exit 0, 6.000s.
- Affected `applications documents email_sync core postings`: **726 passed**, exit 0,
  96.230s. Full Django: **744 passed**, exit 0, 102.982s, final code/test state.
  **19 new tests** cover disposition, serialization, preservation and migration.
- System checks, whitespace and local documentation links pass. Application model drift
  check has no changes; new `0009` fully represents the sidecar. Global dry run reports
  only known `email_sync.0008_alter_emailaccount_provider` drift; no file generated.
- Populated forward upgrade from Application `0008` preserves every old table/column,
  fabricates zero dispositions, enforces one-to-one identity and supports forward replay.
  Existing historical migration tests pass unchanged. No data migration/backfill.
- Tests and management checks use external in-memory SQLite settings; historical
  migration fixtures use disposable files. `backend/db.sqlite3` remains absent.
  No real data or dependency changes. PostgreSQL locking/deadlocks, live Gmail, browser,
  Redis/Celery, storage, deployment, backup/restore and cutover remain unvalidated.
  No fresh legacy FastAPI/frontend suite is claimed.

### Retained review attachment — historical verification at `4d54582`, 2026-09-26

Verified clean checkpoint `eedf57a`, including exact live remote SHA after authorized
network escalation. The [attachment review report](DJANGO_RETAINED_REVIEW_ATTACH_REVIEW.md)
records exact commands, API and transaction boundaries, files and limitations.

- Focused attachment/review/relationship/historical migration/admin run: **59 passed**.
- Affected `applications email_sync core postings`: **652 passed**.
- Full Django suite: **725 passed**, exit 0, 98.664s, final code/test state; 12 new tests.
- System check, local documentation links and whitespace checks pass. Application model
  drift check reports no changes; global dry run reports only the known
  `email_sync.0008_alter_emailaccount_provider` choice drift, left unchanged.
- No schema/data migration. Existing historical migration preservation passes unchanged.
  Every database command uses external in-memory SQLite settings; migration fixtures
  use disposable databases. `backend/db.sqlite3` remains absent; no real data changed.
- No dependency, frontend, provider or legacy implementation changes. No PostgreSQL,
  live Gmail, browser, Redis/Celery, storage, backup/restore or cutover validation.
  Dismiss/restore was deferred at this checkpoint; the approved disposition slice is
  recorded separately below. These results predate that implementation.

### Retained Application review foundation — historical verification at `eedf57a`, 2026-09-26

Started from clean `b5c1faf`; root, branch, HEAD, tracking reference and live remote
matched. See the [review record](DJANGO_RETAINED_APPLICATION_REVIEW.md) for exact
commands, schema/API contracts, file inventory and limitations.

- Final focused review/relationship/historical migration/admin run: **47 passed**.
  Affected `applications email_sync core postings`: **638 passed** before two further
  tests. Final full Django, including those tests and a strengthened fresh-observation
  replay assertion: **713 passed**, exit 0. **25 new tests** including migration safety.
- System check, documentation links and whitespace checks pass. Scoped Application
  migration check has no changes; global dry run reports only known
  `email_sync.0008_alter_emailaccount_provider` choice drift. No new unexpected drift.
- Sole new migration: `applications.0008_retained_application_review`, additive schema
  only. Populated pre-review tables/rows remain unchanged and zero historical reviews/
  candidates are created. Plans were inspected using disposable settings.
- Missing `backend/venv` was created and declared requirements installed with explicit
  user approval; dependency declarations are unchanged. `backend/db.sqlite3` was absent
  at inspection and remains absent. All database verification used in-memory/disposable
  SQLite; the previous run's unresolved local provenance is not resolved by this run.
- No PostgreSQL, live Gmail, browser, worker/storage or cutover validation. No fresh
  legacy/frontend suite is claimed. Review actions, historical reconciliation, evidence
  generation and frontend integration remain separately scoped.

### ApplicationMessage relationship foundation — historical verification at `b5c1faf`, 2026-09-20

Started from clean `fcbfcf3`; root, branch, HEAD, tracking and live remote matched.
Continuation preserved the intentional diff at the same HEAD. See the
[ApplicationMessage review](DJANGO_APPLICATION_MESSAGE_REVIEW.md) for exact contracts,
changed files, historical migration-test rationale, verification and limitations.

- Final focused relationships, populated/historical migrations and admin: **22 passed**,
  exit 0. Affected `applications email_sync core postings`: **615 passed**, exit 0.
  Full Django: **688 passed**, exit 0. System, whitespace and local documentation-link
  checks pass.
- System check passes. Scoped Application migration check reports no changes;
  global dry run reports only the pre-existing EmailAccount.provider choice drift.
  Sole new migration: `applications.0007_application_message`; additive CreateModel,
  no historical backfill. Fresh and populated disposable database upgrades pass.
- Two historical migration tests pin their original Application `0006` schema while
  retaining the original email `0005`/`0006` baselines; explicit absence assertions
  prevent later schema from silently entering those baselines.
- Unexpected local `backend/db.sqlite3` already records `0007` as applied at
  `2026-09-20 20:12:32 UTC`; the user did not apply it. Read-only investigation found
  the table and record but cannot attribute the writer. This run did not migrate or
  alter that database; subsequent verification checks its hash/size/mtime unchanged.
  This is unresolved local provenance, not operational migration validation.
- No fresh legacy or frontend suite is claimed. SQLite logical concurrency, synthetic
  Gmail and API checks do not validate PostgreSQL, live Gmail or browser workflows.
  Review mutations, generated evidence, historical reconciliation and cutover remain
  separately scoped; replacement versus supersession remains unresolved.

### Gmail provider adoption — historical verification at `fcbfcf3`, 2026-09-20

Started from the exact clean `9f66277` checkpoint; local/tracking/live remote matched.
The implementation was subsequently committed at `fcbfcf3`. See the
[Gmail adoption review](DJANGO_GMAIL_ADOPTION_REVIEW.md) for inspection, contracts,
changed files, exact commands and limitations.

- Final focused `email_sync core.tests_workspace_scope core.tests
  applications.tests.test_derivation`: **394 passed**, exit 0, including 30 new
  producer/adoption tests. Full Django: **671 passed**, exit 0.
- Django system check, whitespace and local documentation links pass.
- Migration dry run exits 1 only for the pre-existing EmailAccount.provider choice
  drift (`0008_alter_emailaccount_provider`), independently reproduced before edits;
  no schema migration or new drift. No real tracker database was migrated.
- No fresh legacy `_app` or frontend run is claimed; those trees are unchanged.
  Historical legacy failures below remain separately scoped. Django compatibility
  matching/discovery/posting, identity/lifecycle and retained inspection tests pass.
- SQLite verifies logical convergence/rollback/replay, not PostgreSQL operations.
  Synthetic Gmail fixtures are not live-provider certification. Review relationships,
  frontend, historical reconciliation and production cutover remain pending.

### Gmail mailbox identity — historical verification at `9f66277`, 2026-09-20

The clean committed baseline and later intentional partial tree were inspected on
`django-migration` at `2f0cd1f`; all changes are confined to this bounded slice.
See [Gmail identity review](DJANGO_GMAIL_IDENTITY_REVIEW.md) for the Google sources,
assertion/binding contracts, migration details, resume inventory and exact commands.

- Final focused identity/OAuth/provider/retention/core and populated/historical
  migration checks: **125 passed**, exit 0.
- Affected `email_sync accounts core applications documents postings`: **641 passed**,
  exit 0. Separate full Django run: **641 passed**, exit 0.
- System check and `git diff --check`: clean. Global migration dry run exits 1 solely for the known
  EmailAccount.provider choice AlterField; no unrelated migration was generated.
- Frontend Node: **8 passed**. Legacy: **367 passed, 3 known failures**, 2 warnings;
  unchanged real-path import PermissionErrors and deletion 500-versus-200 failure.
- Populated forward migration preserves every old column/row, including retained
  evidence; principal/binding tables remain empty with no guessed identity backfill.
- SQLite tests cover logical convergence and stale refresh interleavings, not
  PostgreSQL race behavior. Google consent/reconnect/Workspace-domain behavior,
  production storage/workers and cutover are not operationally validated.

### Retained-email foundation — historical verification at `2f0cd1f`, 2026-09-20

Continuation verified the canonical root, `django-migration`, HEAD/local tracking
and live remote at `120d493`, preserving the intentional four-modified/seven-new-file
implementation tree. Review required no code/test correction; this continuation
completed documentation and verification only. See the
[retained-email review](DJANGO_RETAINED_EMAIL_REVIEW.md) for exact commands,
contracts, complete inventory and limitations.

- Focused retention/service/API/concurrency, populated migration and core tests:
  **36 passed**, exit 0. Affected `email_sync accounts core applications documents
  postings`: **606 passed**, exit 0. Full Django: **606 passed**, exit 0.
- System check: no issues, exit 0. Scoped/global migration checks: exit 1 solely
  for the pre-existing EmailAccount.provider choice AlterField; verbose dry run
  confirms no retained-model or unrelated drift. Proposed filename is now
  `0007_alter_emailaccount_provider`; no file was generated.
- Migration plan: exit 0; additive `email_sync.0006_retained_email_foundation`
  follows `email_sync.0005_imapcredential` and `accounts.0001_initial`, and is
  unapplied locally. Populated disposable SQLite preservation passed; no real
  tracker database was migrated.
- Frontend Node: **8 passed**, exit 0. Full legacy: **367 passed, exactly the same
  3 known failures**, 2 warnings, exit 1: two portability real-path PermissionErrors
  and deletion 500-versus-200. Names/signatures match the supplied baseline below.
- Final whitespace check passes. Six modified tracked files and seven new files
  remain uncommitted for review; no dependency/environment changes. Every required
  final run completed; the known exceptions prevent a fully green repository claim.
- Provider adoption, live-provider behavior, PostgreSQL concurrency, frontend/domain
  integration, retained-email derivation, storage/Redis/Celery, backup/restore and
  operational cutover remain unvalidated or unimplemented as specified in §7.

### Historical derivation verification (`120d493`)

The interrupted implementation started from `74f1e91`. This continuation verified
the canonical root, branch and local/tracking HEAD and preserved the intentional
dirty tree; no fresh live-remote check was performed. See [derivation review](DJANGO_DERIVATION_REVIEW.md)
for contracts, exact commands, changed files, results and limitations.

- Focused derivation, populated forward migration, and lifecycle/race tests:
  **43 passed**. Affected `applications documents core postings accounts` regression:
  **331 passed** on the final implementation tree.
- Full Django verification: **573 passed**, exit 0, on the final implementation
  tree. All required continuation runs completed; known exceptions remain below.
- Frontend Node regression: **8 passed**. Full legacy: **367 passed, 3 known
  baseline failures**, with the same two real-path PermissionErrors and deletion
  500-versus-200 signature recorded below. Legacy code and frontend are unchanged.
- System check and scoped drift checks pass. Global drift still reports only
  `email_sync.0006_alter_emailaccount_provider`; no such migration was generated.
- Three additive migrations preserve existing data and mark unreconciled rows
  pending; existing non-null stored dates become `legacy_preserved`. No historical
  status/activity backfill, source timestamp invention, or synthetic history.
- Existing environments reused without dependency changes. Tests use isolated
  SQLite/storage fixtures; no real tracker migration or production validation.

### Historical Trash/Restore verification (`74f1e91`)

Trash/Restore started from clean `3f564ba`; branch, local tracking reference, and
live remote were verified. See [review and verification report](DJANGO_TRASH_RESTORE_REVIEW.md)
for exact commands, API contracts, changed-file inventory and limitations.

- New lifecycle/migration tests: **14 passed** on isolated SQLite fixtures.
- Named Categories regression suites: **20 passed**; identity/creation/posting/
  workspace/cross-cutting suites: **92 passed**; affected Document/dossier suites:
  **30 passed**.
- Final combined Django suites: **284 passed**; full Django suite: **544 passed**.
  System check and scoped migration drift check are clean.
- Frontend: **8 passed**, using the bundled Node executable (no `node` on PATH).
- Legacy preservation suites: **40 passed**; portability suites: **13 passed,
  2 failed**; full legacy suite: **367 passed, 3 failed**, 2 warnings.
  The same two import PermissionErrors and deletion 500-versus-200 failure were
  reproduced from an untouched `git archive 3f564ba` with the same Python environment.
- Scoped migration drift check: clean; global check reports only the existing
  `email_sync` provider-choice drift, reproduced on that untouched baseline.
  No unrelated migration generated or fixed.
- Both missing virtual environments were created and declared dependencies
  installed with explicit user approval. No real tracker database was migrated.
  SQLite tests do **not** validate PostgreSQL concurrency, production storage,
  browser lifecycle workflows, backup/restore, or operational readiness.

### Historical Application Identity verification

The following results describe the earlier identity slice, not fresh lifecycle verification.

Base: `django-migration` at `188351c` — Implement frontend auth and workspace foundation.
At that historical verification point, identity changes and four new migrations
were uncommitted; they subsequently landed at `3a62b58`. No real tracker database
was migrated. The legacy implementation and frontend were unchanged.

| Command (Django from `backend/`, others from root) | Current identity-slice result |
|---|---|
| `venv/bin/python manage.py test applications.tests.test_identity applications.tests.test_creation applications.tests.test_identity_migrations postings.tests.test_views postings.tests.test_services core.tests_workspace_scope` | 76 passed |
| `venv/bin/python manage.py test applications postings core` | 221 passed |
| `venv/bin/python manage.py test` | 523 passed; system check clean |
| `venv/bin/python manage.py check` | No issues |
| `venv/bin/python manage.py makemigrations --check --dry-run applications core postings` | No changes detected, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run` | Exit 1: only known `email_sync` provider-choice drift; no migration generated |
| `venv/bin/python manage.py showmigrations applications core postings --plan` | Exit 0; four new migrations pending on the local database, as intended |
| `node --test tests/frontend/*.test.cjs` | 8 passed |
| `.venv/bin/python -m pytest tests/test_build_index.py tests/test_overrides_store.py tests/test_status_history.py tests/test_job_postings_store.py tests/test_dossier.py` | 56 passed, one known deletion/status-history failure, 2 warnings |
| `.venv/bin/python -m pytest tests/test_export.py tests/test_import_local_folder.py tests/test_overrides_portability.py` | 13 passed, two known import PermissionError failures, 2 warnings |
| `.venv/bin/python -m pytest` | 367 passed, the same 3 baseline failures, 2 warnings |
| `git diff --check` | Passed |

Identity tests exercise both HTTP creation paths, changed-intent rejection, explicit
repeat/replay, challenge expiry/renewal and stale candidates, account/workspace
reauthorization, terminal removal, rollback of initial writes, independent child
rows/document lists, dossier input scoping, and ambiguous email attribution for
identical attempts. Dossier assembly is mocked in the identity isolation test;
the existing dossier/extraction suites remain separate coverage.

Two threaded tests exercise simultaneous same-key requests and competing manual/
posting requests on SQLite. At most one initial effect is permitted. SQLite may
reject one **or both** requests with `503 creation_busy`; explicit reconciliation
using the original keys must yield one effect and (for a competing intent) a
409 review challenge. The first full run exposed an overstrict test assumption
that one concurrent SQLite request must succeed; the test was corrected without
adding automatic retries. These tests do not prove PostgreSQL row-lock, deadlock,
or production concurrency behavior. That validation remains a production/cutover
gate; neither `psycopg` nor `psycopg2` is installed in `backend/venv` (verified
with `importlib.util.find_spec`). No PostgreSQL infrastructure or dependencies were added.

The populated migration test uses a separate temporary SQLite database. It builds
the old checkpoint schema before adding fixture data, then upgrades only forward:
Application PKs, Override/StatusHistory/Document FKs, non-pipeline rows and source
paths survive; UUIDs are distinct and unchanged on repeated backfill; one known
posting link becomes one conversion, while a null link invents none. Historical
conversion timestamp/request identity remain null. It never replays the destructive
historical Document migration over populated data. No real-data upgrade or rollback
has been validated. The conversion migration is deliberately irreversible because
one old pointer cannot represent repeated conversions; operational rollback requires
a separately rehearsed backup/restore plan.

### Historical frontend checkpoint verification (`188351c`)

Base: `django-migration` at `e1785f9` — Implement workspace-scoped Django API.
Frontend foundation was committed and pushed as `188351c`; it created no migrations.

| Command | Historical frontend-checkpoint result |
|---|---|
| `node --test tests/frontend/*.test.cjs` (root) | 8 passed, 0 failed |
| `venv/bin/python manage.py test accounts core` (`backend/`) | 104 passed |
| `venv/bin/python manage.py test` (`backend/`) | 501 passed; system check clean |
| `.venv/bin/python -m pytest` (root) | 367 passed, 3 failed, 2 deprecation warnings |
| `venv/bin/python manage.py check` (`backend/`) | No issues |
| `venv/bin/python manage.py makemigrations --check --dry-run` (`backend/`) | Exit 1: known `email_sync` provider-choice drift, proposes `0006_alter_emailaccount_provider.py`; not generated or fixed |
| `git diff --check` | Passed |

Legacy failures (all reproduced on clean `e1785f9` under the same sandbox):
- `tests/test_overrides_portability.py::test_export_then_import_round_trips_notes_and_status`
- `tests/test_overrides_portability.py::test_export_then_import_round_trips_hub_settings`
- `tests/test_status_history.py::test_deleting_an_application_clears_its_status_history`

The two import tests attempted folder creation under the real
`~/Documents/JobTracker Hub/` location and raised sandbox `PermissionError`.
The deletion test returned HTTP 500 where 200 was expected on both trees; its
underlying cause was not investigated. No broadened access or unrelated fix was
attempted. The full legacy suite is **not green** in this environment, but none of
these three failures is a regression introduced by this slice.

Clean-baseline comparison used `git archive e1785f9` exported into a new temporary
directory (equivalent isolated committed-source checkout), with `.venv` pointing
to the current repository's same Python environment. Original checkout/branch/index
were untouched. The exact three node IDs listed above were passed together to
`.venv/bin/python -m pytest` from the exported root: **3 failed, 2 warnings**, exit 1.
Both import failures reproduced the same real-Documents-path `PermissionError`;
the deletion failure reproduced the same 500-versus-200 assertion. Each is
classified **reproduced on clean e1785f9 / pre-existing or environment-dependent**,
not a slice regression. Temporary paths differed; interpreter, dependencies, user,
fixture behavior and sandbox permissions were shared. No test was rerun with
broadened filesystem permissions.

Isolated browser validation used
`backend/venv/bin/python tests/frontend/serve_foundation.py` (root): a new
TemporaryDirectory for SQLite and media, fixture users Alice/Bob, dedicated cookie
names, and test-only multipart/slow-response endpoints absent from product URLs.
Binding localhost required sandbox escalation; no real tracker database was used.

- `tests/frontend/foundation-browser.html`: 7 passed / 0 failed in actual Safari
  26.6.2, and 7 passed / 0 failed in the in-app Chromium browser (UA Chrome 152).
  Covers anonymous-login CSRF rejection, session login and rotated token, real XHR
  File/text/session/CSRF multipart, XHR CSRF errors, scoped ownership, delayed-read
  invalidation, logout 204, and expired-session 401.
- Product UI: explicit A/B selection in two shared-session tabs; reload and back
  navigation preserve independent selection; create explicitly selects the new
  workspace; logout clears the other tab; Alice→Bob account change clears prior
  context and does not select Bob's sole workspace automatically.
- Separate Safari/Alice and Chromium/Bob sessions concurrently read A and C;
  logging out Safari leaves Bob authenticated after reload.
- Isolated server request-log inspection found zero unexpected/legacy API requests.
  Product traffic was limited to auth, workspace list/create, and scoped insights.
- After final cleanup, a fresh anonymous browser visit shows ordinary login with
  no session-ended alert. Deliberate logout also shows normal login; a previously
  authenticated tab reports session ended after another shared-session tab logs out.
- Node tests cover immutable request snapshots/body serialization, stale success
  and stale authentication errors, read cancellation, XHR error parity, invalid
  routes, empty responses, and no automatic transport retry. Browser race checks
  exercise the transport/context harness, not exhaustive React timing interleavings.

Historical `e1785f9` workspace checkpoint evidence: 370 legacy, 491 full Django,
52 scope/cross-cutting subset, 44 application/documents/dossier subset, and 31
other document/category/posting subset tests passed. Those are historical results,
not substitutes for the current failures. The provider-choice drift was previously
reproduced at clean `8108a9f` and remains unchanged.

Browser checks establish only the bounded foundation on local SQLite. Production
sessions/CSRF, PostgreSQL, storage security, OAuth, workers, import/export, full
product workflows and cutover remain unvalidated.

## 3. Accepted target summary

All ten decisions are approved; full boundaries and consequences live in the
[Decision Record](DJANGO_MIGRATION_DECISIONS.md).

1. One explicitly selected workspace; safe independent tabs.
2. Adapt existing frontend in place; no redesign/build-system replacement.
3. Deterministic document-derived automatic state; manual precedence and real timestamps.
4. Stable application-attempt IDs; repeats allowed, duplicate warnings/idempotency.
5. Named workspace categories separate from sections.
6. Soft-delete Trash, explicit permanent cleanup, previews, portable export.
7. Relevant retained messages, durable evidence, review, provider-independent identity.
8. Authoritative Django contracts and centralized frontend client; one write path.
9. Private administrative onboarding; production PostgreSQL/S3/Redis/Celery.
10. Browser-first cutover; legacy desktop retained only for transition/rollback.

## 4. Current architecture/runtime boundaries

- `_app/`: live legacy FastAPI/Uvicorn, React HTML frontend, filesystem indexing,
  disposable `jobtracker.db`, durable `overrides.db`, and Mail.app integration.
- `_app/domain/` and `_app/infrastructure/`: extracted legacy helpers, not
  repository-root shared layers. Django does not import them.
- `backend/`: independent Django/DRF apps (`accounts`, `core`, `applications`,
  `documents`, `postings`, `email_sync`). Ported helpers are duplicated/adapted;
  fixes do not propagate between architectures automatically.
- `desktop/`: pywebview launcher still starts legacy FastAPI.
- Django has owned workspaces, stable IDs/FKs, admin, file storage abstraction,
  provider integrations, Celery tasks, and Redis configuration. Included synchronous
  core/application/document/posting APIs now require a selected workspace in the
  URL. New retained-email inspection is also workspace-scoped; transitional
  provider APIs remain separate, and old destructive deletion routes are retired.
  Production now admits explicit PostgreSQL configuration without SQLite/development-secret
  fallbacks; admission/profile enforcement is implemented, with operational gates still open (§2).
- Environments: `.venv/` for legacy tests; `backend/venv/` for Django. Manifests:
  `_app/requirements.txt`, `requirements-dev.txt`, `desktop/requirements.txt`,
  and `backend/requirements.txt`. Isolated validation additionally uses
  `backend/requirements-postgres-test.txt` and harness-only test settings. Production runtime
  ownership of `psycopg==3.3.6` is now declared in `backend/requirements.txt`; native libpq
  deployment and live production connectivity remain unvalidated.

## 5. Functional migration matrix

All target behavior below is **accepted**. Implementation is assessed against
the audit at `ecd1727`, updated below for Workspace Scoping Core. “Baseline coverage”
means existing component tests, not complete target parity; current counts are in §2.
No newly accepted capability is marked verified merely because it is designed.

| Area | Implemented now | Automated verification | Operational/end-to-end evidence |
|---|---|---|---|
| Auth/workspaces | Session-only product auth, anonymous-login CSRF bootstrap/protection, structured DRF exception codes; owned workspace list/create and explicit route selection in Django entry | 104 accounts/core subset; bounded browser session/tab checks described in §2 | Local foundation validated; broader onboarding/production/cutover pending |
| Frontend/desktop | Existing HTML has explicit DjangoFoundation root/client/context with authenticated read-only retained extraction evidence, Application list/core-detail browsing, retained Application review inspection/navigation and named Category list/detail/member inspection with Application navigation, plus standalone Application Category assignment/move/clear using existing PUT authority and retained-review detail Dismiss/Restore using existing revision authority, plus explicit read-only source-text inspection using existing scoped GET; legacy App never mounts in Django mode and remains unchanged; desktop remains FastAPI | Retained source-inspection Stage 3 Node 45, combined HeadlessChrome 153 browser 112, focused Django 79 and full labelled Django 1,362 passed/13 PostgreSQL-only skipped in §2; prior retained UI counts remain historical; historical foundation Safari/Chromium 7/7 retained in §2; current Safari unvalidated; legacy 378 passed/6 failed/2 warnings; targeted parent reproduction 26 passed/same 6 failed/2 warnings | Local foundation, evidence, core Application, retained-review and named Category inspection/navigation and bounded assignment and review-disposition/recovery plus literal source-text inspection validated in disposable fixtures; broader Application/domain frontend migration and production/cutover remain incomplete |
| Applications/overrides | Stable numeric PKs plus workspace portable UUID; shared protected creation, explicit repeat challenges and durable replay; existing scoped list/detail reads consumed by read-only Workspace browser, referenced review destinations and Category member navigation; standalone assignment uses fresh membership revision and explicit confirmation, with reconciliation rather than write replay | Identity/ownership and duplicate-safe future transition coverage plus current assignment/browser/read-contract evidence in §2 | Local core browsing and standalone Category move/clear, stale/unknown-outcome reconciliation validated; creation/edit/override and duplicate-warning UI, dossier/documents/messages and broader workflows pending |
| Derivation/dossier | Canonical per-Application status/activity, manual precedence, source precision, confirmation candidate/modes, duplicate-safe transitions; read-only dossier GET | Current derivation/forward-migration/SQLite coverage in §2 | Historical reconciliation, import provenance, dossier/evidence frontend and operations pending; core server-resolved fields are displayed read-only |
| Categories | Native stable identity, single revision-protected membership, independent Archive; committed at `3f564ba`; reversible Trash committed at `74f1e91`; DjangoFoundation now consumes existing list/detail/membership GETs for read-only named Category inspection, archived visibility and Application navigation; standalone Applications invokes existing assignment authority, including archived/empty destinations | Current Category/assignment contract and combined browser evidence and historical lifecycle coverage in §2 | Local read-only named Category inspection/navigation validated in disposable fixtures; Category create/edit/archive/Trash/restore browser mutations, performance and operations pending; standalone assignment is locally validated |
| Documents/files | Upload/list/type correction/metadata rename; storage URL; retained Trash and effective parent eligibility | Current Document/lifecycle coverage in §2 | Production storage/previews and frontend integration pending |
| Trash/recovery | Application/Document/Category Trash and Restore, revisions, mutation/admin guards; old deletes retired | Current lifecycle/migration/SQLite race coverage in §2 | Workspace lifecycle, purge, frontend and operational validation deferred |
| Search/dashboards/settings | Included reads, counts, search, section adapters, merges, and settings scoped to URL workspace; search parity and Ghosted still pending | Scoped isolation coverage; broader target parity pending | Frontend integration pending |
| Provider connections | Gmail/Outlook/IMAP connect/sync/disconnect; encrypted credentials | Baseline provider/view coverage, mocked external seams | Historical Gmail OAuth/live-sync checkpoint; complete target flows unvalidated; Outlook/IMAP live validation unestablished |
| Sync/jobs | Gmail per-message retention plus transitional match/discovery/thread projection; inline single sync, queued bulk/Beat | Gmail adoption/replay and existing sync/task coverage; not real-broker proof | Real Redis/worker/Beat operation unestablished |
| Retained messages/review | Protected source/observation models, verified Gmail lineage and native-ID producer adoption; scoped review inspection, explicit attachment, independent disposition and atomic create-Application orchestration with durable results; retained-source summary browsing supports extraction evidence selection; DjangoFoundation provides retained Application review inspection/navigation, detail-only explicit Dismiss/Restore using existing disposition authority and explicit source-text inspection through existing retained-message GET | Retention, Gmail adoption, attachment/disposition/creation APIs, migration preservation and SQLite logical concurrency coverage in §2; retained Stage 3 source-inspection/combined browser/read-contract evidence, historical disposition evidence and bounded PostgreSQL retention/extraction conflict evidence above | Local browser review Dismiss/Restore, bounded uncertainty/recovery and read-only source-text inspection validated; browser review create/attach, broader evidence/creation-result workflows, other-provider adoption and operational validation pending |
| Postings | Integer PK plus immutable Workspace-scoped portable UUID; existing extractor/ingestion and list/save/dismiss/restore/apply APIs; explicit retained-text extraction production with validated historical replay, operator batch extraction execution and source-scoped read-only extraction evidence inspection, plus a workspace-scoped read-only retained extraction evidence HTTP API and read-only Workspace browser evidence UI; retained extraction/items and corrections, PostingSource mapping/corrections, item interpretation, posting-level arbitration, descriptor projection, canonical allocation, stateless review orchestration and bounded advisory candidate discovery | Identity/migration/replay and authority-boundary coverage in §2; HTTP checkpoint API 18, retained inspection 22, combined focused 262 and postings 615 passed; UI checkpoint Node 16, Chromium 28, relevant Django 95 and full Django 1,332 passed; bounded PostgreSQL extraction/retention evidence above | Sync does not produce canonical postings; automatic retained-to-canonical workflows, broader canonical consumers, provider/sync adoption, canonical-posting/review frontend and remaining Application/review action/evidence UI, broader retained-workflow APIs, concurrency outside the exercised extraction/retention boundary, production load and deployment/cutover validation remain pending |
| Import/export | No Django legacy importer or portable export/restore | Unimplemented/unverified | Reconciliation/cutover pending |
| Production | Fail-closed configuration admission: explicit PostgreSQL shape, required secrets/provider keys, validated hosts/security and profile/pre-dispatch enforcement at `160c8a4`; existing storage/task scaffolding remains | Focused admission and full labelled isolated SQLite regression evidence in §2; suite success is not deployment verification | Bounded extraction/retention PostgreSQL evidence remains separate; production connectivity/TLS/libpq/proxy/storage/broker/providers/browser/deployment/backup/restore/cutover gates open |

## 6. Known parity gaps and blockers

- Production fail-closed configuration admission is complete (§2). Actual PostgreSQL
  connectivity/TLS, deployed libpq, proxy topology, storage, broker, provider operations,
  production browser acceptance, deployment, backup/restore and cutover remain open (§10).
  Provider-key admission does not resolve source-admission/recurring-operation identity,
  selector/retry authority or extraction/cursor coupling; manual-status concurrency is unchanged.
- Retained-text extraction production, explicit operator batch execution, source-level
  evidence inspection, its workspace-scoped read-only HTTP adapter and authenticated
  DjangoFoundation browser evidence UI are complete. Broader retained-review/Application
  frontend work and retained-workflow APIs remain separately scoped gaps; core read-only
  Application list/detail browsing and retained-review inspection with Application navigation
  are complete. Standalone Application Category assignment/move/clear is also complete;
  other Application mutations remain separately scoped. Retained-review Dismiss/Restore is complete
  in the existing review detail panel, using unchanged backend authority. Explicit read-only source-text
  inspection from review detail is complete; it does not complete broader evidence workflows. Browser review attach/create,
  other separately scoped review actions, broader evidence browsing and creation-result history remain incomplete. The batch command,
  reader, HTTP adapter and browser consumer are not
  the provider/sync adoption mechanism. That adoption requires
  separate decisions on recurring extraction-operation identity, source admission,
  deterministic selector/input ownership, durable retry/failure semantics, cursor coupling,
  execution intent/state, provider transaction placement and scheduling/worker ownership.
  Bounded extraction/retention PostgreSQL validation is now recorded above, removing that
  absent-evidence prerequisite only; provider automation concurrency/integration and broader
  production/operational/cutover validation remain future. The reader, HTTP API and browser
  consumer do not resolve provider policy.
  Provider/sync adoption and automatic retained-to-canonical workflows remain unimplemented
  and require separate
  planning and authorization. Sync does not currently produce canonical JobPosting rows;
  explicit retained extraction is distinct from legacy direct canonical ingestion, and
  `ingest_extracted_postings` is not designated as the adoption path.
- Review Gmail producer adoption; separately authorize other-provider adoption,
  account listing, discovery preview/attach/accept/dismiss/restore/sender
  classification, and evidence/backfill.
- Per-Application derivation is committed at `120d493`. Historical rows are
  intentionally not bulk-reconciled; missing source facts remain unknown. Future
  importer/cutover work must supply verified provenance and preserve history.
- Add Ghosted choices/metrics/UI parity. This main-branch change exists only
  in the legacy implementation.
- Named Categories and Application/Document/Category Trash are implemented in the
  backend. Read-only named Category list/detail/member inspection and Category →
  Application navigation and standalone Application Category assignment/move/clear are
  implemented in the browser. Category create/edit/archive/Trash/restore and
  Application/Document Trash/restore browser
  mutations, Workspace lifecycle and confirmed permanent cleanup remain pending.
- Manual override API lacks expected-version rejection semantics; safe manual-status browser mutation
  remains unresolved until an expected-version/stale-observation contract exists. Category
  assignment's membership revision does not change this concurrency limitation.
- Complete remaining workspace integration for email/jobs and the frontend;
  included synchronous core APIs are scoped. Adapt remaining payloads/errors and
  search semantics deliberately. Preserve PDF/text/DOCX browser previews.
- Build importer/exporter and validate restoration. Existing documents migration
  `0002` deletes/recreates DocumentOverride assuming no real data; fresh-database
  tests do not establish safe upgrades of populated intermediate databases.
- Legacy Finding 9 lock mitigations are present, but its field root cause is
  unresolved; do not turn that unrelated investigation into migration scope.

Standalone Application list/core-detail panel limitations are recorded in §2:
JavaScript-safe IDs, unpaginated full-list loading, transient selection/no deep links,
shared core-detail Category reference without reverse navigation, no evidence controls and
unvalidated large-Workspace performance. Standalone assignment separately displays Category
metadata and owns mutation intent/revision; Category/review destinations retain read-only core
inspection. Separate Category → Application navigation does not make the reference navigable.
Retained-review inspection/navigation is complete, with accumulated-page memory, unpaginated
detail arrays, inherited creation-result payload cost and transient selection limitations
recorded in §2. Detail-only review Dismiss/Restore and explicit read-only source-text inspection are
complete. Source inspection retains full-response JSON parsing before projection validation, without
an aggregate response-memory bound. Browser attach/create and other
separately scoped review actions, broader evidence/creation-result browsing and canonical-posting
frontend workflows remain incomplete. Named Category inspection/navigation retains
unpaginated Category/member arrays, inherited serializer/download costs, advisory observations,
safe-ID and transient-navigation limits; scale/performance remains unvalidated.

## 7. Current implementation phase

Workspace-Scoped Read-Only Retained Review Source Text Inspection is committed/pushed at
`dbaa85926e35466dd6be7b8e02ff625828bc73f0`; scope, retained Stage 3 execution evidence,
Stage 5 read-only review and Stage 6 commit verification are in §2. This browser consumer uses
existing scoped retained-message GET without adding backend authority or closing operational gates.

Workspace-Scoped Retained Application Review Dismiss/Restore Browser Workflow is committed/pushed
at `3b9a56f593dc3eed1238a8cc890420e67d010c89`; scope, retained Stage 3 execution evidence,
Stage 5 read-only review and limitations are in §2. It consumes existing backend disposition
authority without adding domain authority or closing operational gates.

Production configuration admission/profile hardening is committed at
`160c8a4007f262bab1361485b959accce145a628`; scope, retained validation and limitations
are in §2. It adds no domain authority and closes no operational production gate.

Decisions 1–10 and foundational Topics 1–9, including final refinements, are
accepted. **Workspace Scoping Core — Backend Only is implemented.** A reusable
request mixin resolves authenticated workspace ownership, rejects conflicting
workspace/owner input, and scopes included object lookups and nested references.
Included application/document/posting APIs and core reads/settings use URL context;
bulk overrides validate all targets before writing. Converted owner-wide routes
are removed, with no redirects or fallback writes. DRF format-suffix variants are
preserved for converted router routes and the existing deletion-only routes;
explicit category/core adapters gain no new suffix behavior.

At the Workspace Scoping checkpoint, deletion remained legacy behavior (superseded
by the current Trash slice below). No Trash, schema,
email/account/auth infrastructure, frontend, or task changes were part of that backend-only slice.
This is not completion of the broader workspace contract or historical phases.
Evidence regeneration replacement versus supersession still requires an explicit
decision before that behavior is implemented; other remaining implementation and
operational details are listed in Foundations.

### Frontend API Foundation — committed and pushed at `188351c`

The explicit Django same-origin entry serves the existing HTML and allowlisted
public assets. Its minimal root provides login, workspace list/create, hash-route
selection, one scoped insights read, and logout. It never mounts the legacy App,
loads its sensitive localStorage cache, or invokes legacy/domain screens. Existing
FastAPI entry behavior and Safari upload helper remain in place.

The client uses session cookies and CSRF, handles empty 204 and structured errors,
captures actor/workspace/navigation generation, cancels obsolete reads or rejects
late results, and never retries/replays mutations. XHR multipart has equivalent
CSRF/context/error handling without forcing Content-Type. Selection has no shared
persistent storage; focus/session-change messages revalidate identity and clear old
context. No singleton selection, destructive workspace UI, generic legacy URL
adapter, domain/schema migration, upload workflow, jobs, or cutover is included.

Auth changes implement `401 authentication_required`, `403 csrf_failed`, genuine
`403 permission_denied`, scoped `404 not_found`, and `400 validation_error` for
DRF exception paths. Invalid credentials have their own code. Existing successful
representations remain unchanged. This does not normalize every historical explicit
error Response or implement future duplicate/operation contracts.

Plan differences: insights replaced settings GET because settings lazily writes a
row; an additional isolated browser-server helper makes the harness reproducible.
Final cleanup distinguishes a fresh anonymous visit from a lost authenticated
session and removes the stray import from config/urls.py's introductory docstring.
All commands in §2 were rerun after these two changes. Browser evidence and
clean-baseline regression comparison are recorded above. Known environment/baseline
failures prevent a fully green suite claim; they do not indicate a slice regression.
This frontend checkpoint was committed and pushed as `188351c`. Later extraction-evidence
and Application core browsing checkpoints in §2 extend its consumers only; the original
foundation exclusions and test results above remain historical.

### Application Identity & Repeated Attempts — committed at `3a62b58`

`applications.0002_application_portable_identity` adds a nullable UUID, backfills
one UUID per historical row, then enforces a generated, non-null UUID unique within
Workspace. `source_relpath` retains its values as blank-allowed provenance. Numeric
PKs remain normal API lookups. Normal create/override APIs reject identity assignment;
Application admin add is disabled and identity fields are read-only. Model save also
rejects identity/workspace changes; privileged bulk SQL/ORM writes are not a supported
identity-editing workflow.

`core.0003_applicationrequestintent` stores only compact actor/workspace/key,
versioned semantic digest, pending challenge and linked/terminal result identity.
No raw request bodies or candidate descriptions are retained. Completed key mappings
remain until workspace deletion; there is no detailed replay cache or background
retention job in this slice. Both manual create and posting apply call
`applications/creation.py`, under one workspace transaction authority. Initial
Application, Override, StatusHistory, intent completion and conversion commit together.
Arbitrary IntegrityError is not translated into a duplicate-company warning.

Both existing creation URLs now require `Idempotency-Key` (16–128 opaque ASCII
letters/digits/underscore/hyphen; clients must generate a random key). Semantic digest
v1 includes route kind/target and validated supplied fields, preserving omission.
Same key/intent resolves the current effect with 200; changed intent returns
`409 idempotency_key_reused`. First allocation returns 201. Removed results return
only `state: removed` and portable identity; retries never recreate them.

Normalized company/role matches warn across the authorized workspace, including
archived attempts. `409 new_attempt_confirmation_required` supplies scoped numeric
candidate IDs/state, a token and expiry. Explicit continuation resubmits the same
URL/key/fields plus `challenge`; the token binds actor/workspace/intent and the visible
candidate/posting/conversion revision. Expiry defaults to 900 seconds, configurable
with `APPLICATION_CHALLENGE_TTL_SECONDS`. Invalid, expired and stale tokens get distinct
409 codes. Re-submit without a token to renew review; no `force` flag or automatic
mutation retry exists. Consuming the token creates a separate attempt once; replay
then resolves that result.

`postings.0002_posting_application_conversions` creates durable conversion rows,
backfills only non-null known links (cross-workspace links fail migration explicitly),
and removes the old pointer. New conversions link one request intent, record actual
conversion time and retain portable result identity when their Application is deleted.
A new request key alone does not authorize another conversion. The list serializer
adds conversion states and retains `applied_application` only as a read projection
of the latest surviving conversion; remove that projection when the posting UI
adopts conversion representations, before legacy retirement. No pointer dual-write
or ordinary admin allocation bypass remains.

Final review found and closed an admin reparenting bypass: existing postings now
keep both `workspace` and `account` read-only in admin, and model saves reject changes
to either persisted FK (including an existing PK supplied on a fresh instance).
New-posting ownership setup and unrelated metadata edits remain available. No
conversion history or historical workspace IDs are rewritten. Three regression
tests cover terminal conversion followed by attempted model/admin reparenting,
forged admin ownership input with allowed metadata edits, new creation and fixed
account identity. The original workspace still requires a new-attempt challenge;
the destination workspace returns 404. Privileged bulk ORM/SQL writes bypass model
save hooks and are not a supported reparenting workflow; the historical-corruption
scope test uses such a write explicitly. This safeguard adds no migration.
The review's non-ASCII challenge validation fix is retained and tested: malformed
non-ASCII tokens return 400 instead of raising TypeError.

Finally, `applications.0003_allow_repeated_attempts`, dependent on conversion setup,
drops descriptive uniqueness. Deploy the protected code with these migrations;
do not run old allocators after removing the constraint. No Categories, Trash,
timestamp/derivation/history parity, retained-message schema, importer/exporter,
discovery acceptance, frontend CRUD, upload/storage or worker framework was added.
The permanent-deletion routes from that checkpoint are now retired by the Trash slice below.

Plan concretizations: continuation uses the existing creation URLs, not an extra
endpoint; compact synchronous intent state lives in one model; unsafe admin creation
is disabled; SQLite contention has a bounded 503 response. These stay within the
approved backend-only boundary. PostgreSQL and full domain/browser workflows remain
unvalidated.

### Named Categories — committed and pushed at `3f564ba`

Native Category IDs/portable IDs, empty containers, independent archive state,
single revision-protected membership, creation replay and conservative synthetic
backfill are implemented. Sections remain classifications. Category membership
never owns Applications. The supplied historical 245/245 result is distinct from
the fresh regression verification in §2. Later named Category inspection/Application navigation
and standalone browser invocation of existing assignment authority are recorded in §2; this backend
checkpoint's scope and counts remain historical.

### Backend Trash & Restore — committed and pushed at `74f1e91`

Application, Document and Category gain nullable `trashed_at` and nonnegative
`lifecycle_revision`, defaulting to live/revision 0 without invented history.
`applications.0005_retained_lifecycle` precedes `documents.0005_retained_lifecycle`;
the latter also follows the committed Category backfill. Ownership FKs use PROTECT
for these resources, preventing incidental ancestor deletion. Identity, membership,
Archive, overrides/history, extraction provenance and file references survive.

`core.lifecycle.set_trash` owns desired-state transitions, with workspace ownership,
expected revision, current-state no-ops and parent-first Document restoration.
The existing workspace transaction gate serializes transitions, membership and
ordinary included mutations; resource locking follows Category → Application →
Document where applicable. Real transitions increment only lifecycle revision;
stale requests return 409. No-ops do not churn timestamps or revisions.

Ordinary reads use centralized `.live()` eligibility. Application Trash makes its
Documents effectively unavailable without changing their direct state. Restoring
it leaves directly trashed children excluded. Document restore under a trashed
Application returns `409 parent_trashed`. Category Trash preserves memberships and
never trashes, archives or changes member Applications. Live members can leave a
trashed Category; new assignments into one are blocked.

Workspace-scoped POST `applications|documents|categories/{id}/trash|restore/`
accepts `expected_revision`. Detail inspection and explicit `show_trashed=true`
Application/Category/child-Document listing retain authorized recovery access.
Ordinary metadata mutation is blocked while directly/effectively trashed. Old
unscoped Application single/bulk and Document delete routes return 410; remove
these retirement responses before legacy retirement. Admin cannot hard-delete the
three resources, mutate trashed Application/Document records, or overwrite newer
lifecycle/membership revisions from stale forms. Document creation and standalone
DocumentOverride writes use product APIs instead of admin bypasses.

Creation/duplicate/replay identity still includes retained attempts. Completed
Application, posting-conversion and Category creation requests resolve the original
current record without cloning, restoring or recreating cleared membership.

**Historical limitation at `74f1e91`:** the lifecycle slice intentionally deferred
status/activity recalculation and retained the old dossier GET autofill behavior.
The derivation slice below now handles future evidence mutations and makes GETs
read-only. Untouched historical Applications remain unreconciled; this is still
not whole-database or final product parity.

No permanent purge, physical file deletion, Workspace Trash, frontend changes,
automatic expiration, provider/background work or unrelated migration fixes are
implemented. PostgreSQL concurrency and operational recovery remain unvalidated.

### Backend Deterministic Application Derivation — committed at `120d493`

`applications.derivation` applies effective Document type priority
`rejected > interviewing > applied > drafted > unknown`; non-pipeline is `n/a`.
Manual status remains authoritative, including existing Ghosted values. Explicit
upload, type/rename, direct Trash/Restore, and manual reset paths use the same
workspace-gated transaction and Application-before-Document locks. Creation replay
remains identity-preserving. Category operations never trigger derivation.

Parent Trash preserves its business snapshot. A direct child change while the
parent is trashed marks reconciliation needed; Restore reconciles that actual
change once. A parent-only cycle produces no business transition. Same inputs do
not churn derived metadata, history, activity, or lifecycle/membership revisions.

Additive `accounts.0002_deterministic_derivation`,
`applications.0006_deterministic_derivation`, and
`documents.0006_deterministic_derivation` retain source-event/date precision,
verified legacy mtime, genuine new-upload fallback, automatic confirmation candidate,
manual/legacy/suppressed date mode, and fingerprint/completeness metadata.
Calendar timezone defaults explicitly to UTC; configuration UI is deferred.
Dates never become invented midnight instants. Extraction claims are content-only;
Document arrival/source facts are separate. Conflicting confirmation dates have no
arbitrary winner. Attention uses calendar days and the existing reset → effective
application date → last evidence precedence and due-first ordering.

Dossier GET does not extract, write caches, or autofill overrides. POST
`/api/workspaces/{workspace_id}/applications/{id}/derive/` explicitly reconciles one
live Application without fabricating historical transitions. Ordinary evidence
mutations record real effective changes once, using recorded-now history timestamps
rather than source dates. Existing duplicate history is preserved. Missing, failed,
and conflicting evidence is reported; no cross-workspace evidence is admitted.

### Backend Retained Email Source Identity and Content Foundation — committed at `2f0cd1f`

`MailboxLineage`, `RetainedMessage`, `RetentionKey` and `RetainedObservation` separate
established mailbox lineage, strong source identity and exact observation retry.
Workspace-owned portable identities and complete source namespaces are unique;
weak IDs/content hashes cannot merge messages. Changed-key and source-content
conflicts preserve canonical content and candidate observations, with sticky
ineligibility. Incomplete identity remains inspectable and unresolved.

The explicit internal service validates ownership/references and bounded content,
then commits under the existing Workspace gate. It performs no provider/network
work. Default UTF-8 text/HTML limits are 128/256 KiB, with explicit truncation;
observations over 2 MiB are rejected. Source time precision/offset/provenance remains
separate from observation and retention times. JSON-only read APIs omit original
HTML and expose authorized state/content without writes. Admin is read-only.

All new FKs use PROTECT, with no EmailAccount/credential or workflow ownership link;
account disconnect/deletion preserves retained data. Additive
`email_sync.0006_retained_email_foundation` follows `email_sync.0005_imapcredential`
and `accounts.0001_initial`, creates only four tables/five constraints, and performs
no historical backfill or existing-field alteration. See the
[retained-email review](DJANGO_RETAINED_EMAIL_REVIEW.md) for contracts and evidence.

The later review-detail source-text browser consumer is committed at
`dbaa85926e35466dd6be7b8e02ff625828bc73f0` (§2), using these existing JSON reads only;
this foundation's original exclusions and evidence remain unchanged.

Gmail producer adoption is described below; other providers remain unadopted. No
review actions, posting ingestion, generated Documents, derivation hooks, frontend
integration, purge, import/export,
workers or historical reconstruction are included. PostgreSQL and operational
validation remain open; SQLite race tests are not production concurrency proof.

### Gmail Mailbox Identity and Durable Lineage Foundation — committed at `9f66277`

New Gmail authorization requests only the approved `openid email gmail.readonly`
scopes (the last uses its full Google scope URI). The callback verifies the exchange
ID token through the installed Google verifier, checks issuer/audience/signature,
subject/times, optional authorized presenter and access-token hash binding, then
uses Google OIDC `sub` as opaque account identity. Email remains metadata.

Additive `email_sync.0007_gmail_mailbox_identity` creates MailboxPrincipal and
AccountMailboxBinding only. The existing retention authority resolves unique
workspace/provider/namespace/principal identity to MailboxLineage. Same-principal
reconnect or account recreation resolves the same lineage; changed email can update
ordinary account metadata without changing lineage. Conflicting principals, ambiguous
legacy accounts and address collisions return a deterministic conflict without merging
or overwriting credentials/history. New bindings require fresh offline authorization.

Legacy accounts/lineages are preserved unverified until prospective authorization;
no historical identity or message backfill runs. Empty stored refresh scopes retain
the old read-only fallback, and refresh never establishes identity. Stale refresh
results cannot overwrite a replacement grant or recreate disconnected credentials.
Workspace-gated identity/account/credential writes are atomic; lineage/principal and
retained evidence survive disconnect and account deletion. New identity admin is
read-only, and bound account workspace/provider cannot be changed by ordinary saves.

That identity slice left provider adoption for the next bounded slice below. Its
retained read APIs and downstream review/posting/evidence workflows are unchanged;
Outlook/IMAP identity is not adopted. See the
[identity review](DJANGO_GMAIL_IDENTITY_REVIEW.md) for historical limits/evidence.

### Gmail Provider Adoption into Retained-Source Authority — committed at `fcbfcf3`

Newly fetched, relevance-qualified Gmail messages now call `retain_observation`
using native Gmail message ID under verified workspace-owned durable MailboxLineage.
The provider DTO keeps native ID, RFC Message-ID, provider thread metadata and
source/observation timestamps separate. Missing RFC ID no longer discards canonical
evidence. `threadId` is conversation metadata only; equal RFC/thread values never
merge different native sources.

Binding/principal/provider/workspace are checked before fetch and revalidated during
persistence; a changed binding requires another fetch. Missing verified lineage or
native identity produces an unresolved observation, with no email/header identity
guess. Same-principal reconnect and account recreation reuse the durable namespace.

Existing relevance order and search semantics are preserved. Retention happens
before legacy RFC duplicate suppression. Selected repeated headers, structured
addresses and available inline plain/HTML MIME bodies pass through existing limits
and truncation. Raw MIME, file parts and nested attachment bodies are not retained.
InternalDate has explicit Gmail provenance; missing/invalid values remain unknown,
with no RFC Date fallback. Header-sent precision, observation and retention stay
separate; Application activity/derivation is untouched.

Gmail fetch/decode/classification is outside persistence transactions. One relevant
message's retention and compatibility projection commit together under the existing
Workspace gate. Fresh fetches produce new observations against one native source;
reusing an attempt replays the original observation. Conflicts preserve variants and
canonical content and suppress new projections. Unresolved cases preserve existing
legacy compatibility behavior without establishing canonical downstream authority.
Earlier committed units survive a later failure, but the sync cursor does not advance;
retry is safe. Other providers keep their existing transaction behavior.

Matches/discoveries/posting discoveries remain one transitional RFC-based projection
path, preserving dismissed state and replay behavior. Missing RFC ID can have no
legacy projection, and two native sources with one RFC ID can have only one legacy
projection. Replace these consumers with retained-backed relationships before legacy
retirement. That adoption slice included no schema migration, historical backfill/
reconciliation, review mutations, ApplicationMessage/PostingSource, JobPosting ingestion,
generated evidence, Outlook/IMAP adoption or frontend work. Retained inspection/admin
remain read-only. See the
[adoption review](DJANGO_GMAIL_ADOPTION_REVIEW.md).

### Backend ApplicationMessage Relationship Foundation — committed `b5c1faf`

`RetainedMessage → ApplicationMessage → specific Application` is now the canonical
explicit relationship path. Immutable runtime/portable link identities, original
creation time and bounded manual origin preserve provenance. Database uniqueness per
Application/source supports many-to-many links and distinct repeated attempts.

One atomic service uses the Workspace gate, then Application and retained-message
locks, validates same-workspace ownership and source eligibility, rejects direct
Application Trash or source conflict, and resolves/creates the pair. POST
`applications/{id}/messages/` under the explicit workspace route takes only
`retained_message_id`: 201 first creation, 200 eligible replay without provenance or
revision churn. GET provides paginated live-Application inspection with existing
retained summaries. No provider calls, alternate writer or request-intent model.

Trash preserves links/sources and Restore exposes the same relationships. Ordinary
model edits/deletion are blocked, ancestor FKs PROTECT, and admin is read-only.
No independent relationship Trash, detach, review decisions or permanent purge.
Attachment does not modify Application status/activity/history, Documents, retained
source/observation identity, legacy AccountMatch/Discovery (including posting kind),
thread hints or postings. Gmail compatibility projection cannot allocate links.

No inference/backfill, generated evidence, PostingSource, JobPosting ingestion,
provider changes or frontend work is included. Legacy consumers remain temporary
compatibility and must be replaced before retirement. See the
[ApplicationMessage review](DJANGO_APPLICATION_MESSAGE_REVIEW.md).

### Retained Application Review Identity & Candidate Snapshot Foundation — committed at `eedf57a`

`RetainedMessage → RetainedApplicationReview → RetainedApplicationReviewCandidate`
separates review identity from source identity and canonical ApplicationMessage links.
One workspace-owned portable review identity per source retains the first zero/one/many
candidate snapshot and originating observation. Candidates preserve specific attempt
portable IDs, with nullable current Application references; replay never replaces the
set when matching facts change. Trash/Restore preserves provenance and only changes
current target availability. Source conflicts remain inspectable and ineligible.

One internal atomic ensure service validates Workspace/source/observation/candidates,
using Workspace → source → review locks, without Application locks. Gmail invokes it
after retention and before legacy projection/RFC suppression for match, ambiguous and
unmatched Application classifications. Posting and unresolved observations do not enter
this domain. Legacy matching/classification/projections and frontend consumers remain.

The foundation added workspace-scoped `application-reviews/` list/detail JSON inspection;
source content stays in existing retained inspection. Detail shows candidates' current
availability and existing relationships. Admin is read-only. Additive Application
migration `0008_retained_application_review` creates no historical reviews/candidates.
The foundation added no review decisions, attachment, detach, evidence, posting-source
ingestion, provider expansion, permanent purge or frontend integration. Explicit
attachment is now added below. Later read-only review browser inspection/navigation
and later explicit source-text inspection are recorded in §2; the foundation
exclusions and evidence here remain historical. See the
[retained Application review](DJANGO_RETAINED_APPLICATION_REVIEW.md) for full contracts,
verification, changed files and limitations. The queue does not cover all legacy history.

### Retained Review Attach to Existing Application — committed at `4d54582`

`POST /api/workspaces/{workspace_id}/application-reviews/{id}/attach/` accepts only
`{"application_id": positive_integer}`. Scoped immutable review provenance supplies
the canonical source ID; `attach_message()` remains the sole relationship writer and
creation/lock authority. At the attachment checkpoint there was no outer
transaction. Disposition admission now holds the Workspace gate around delegation,
as described below, without extra review/source locks.
Creation returns 201; eligible existing-pair replay returns 200. Trash, source conflict,
ownership, strict payload and contention behavior follow the canonical service.

Zero/one/many suggestions require one explicit target per request; eligible targets
outside the initial snapshot and multiple distinct attempts are supported. Initial
classification, candidate membership/portable identities and timestamps never change.
List/detail remain inclusive and derive `attachment_status` and `relationship_count`
from valid scoped ApplicationMessage links, including trashed targets. Distinct counts
avoid candidate/link join multiplication; detail links expose `live`/`trashed`
availability. Existing direct relationship writes are immediately reflected.

No schema/data migration, historical scan, legacy write, provider change, evidence,
derivation or frontend change. No terminal acceptance or stored attachment state.
Dismiss/restore was outside that attachment slice and is now implemented below. See the
[attachment review report](DJANGO_RETAINED_REVIEW_ATTACH_REVIEW.md) for verification,
transaction reasoning and operational limits.

### Retained Review Disposition — committed at `5e25093`

`RetainedApplicationReviewDisposition` is a mutable one-to-one sidecar using review
identity, nullable `dismissed_at` and a nonnegative revision. No disposition row means
active/revision 0. The first actual dismissal allocates revision 1; restore clears the
timestamp while keeping the row. Current-revision no-ops do not write; stale revision
rejects before no-op detection. Ordinary deletion/reparenting and admin mutation are
blocked. One additive schema-only Application `0009` has no historical backfill.

`POST .../application-reviews/{id}/dismiss/` and `/restore/` accept exactly
`{"expected_revision": nonnegative_integer}` and return identity plus nested disposition.
The scoped desired-state service owns both transitions; conflict does not prevent
review dismissal/restoration. List/detail expose state/revision/timestamp and remain
inclusive. No disposition filter, handled state, candidate decision or generalized Trash.

Review attachment holds the Workspace gate before disposition admission through
unchanged canonical `attach_message()` delegation. Dismissed new pairs return
`409 review_dismissed`; existing pairs still recheck canonical Trash/conflict eligibility.
The direct ApplicationMessage API remains independent. No relationship or provenance
changes occur during disposition transitions, and attachment never changes disposition.
Application Trash/Restore remains independent. Historical Discovery is never inferred
or rewritten. See the [disposition review report](DJANGO_RETAINED_REVIEW_DISPOSITION_REVIEW.md)
for transaction reasoning, actual verification and operational limitations. The later browser
Dismiss/Restore consumer is committed at `3b9a56f593dc3eed1238a8cc890420e67d010c89` (§2);
it leaves this backend authority and historical evidence unchanged. The later source-text consumer
at `dbaa85926e35466dd6be7b8e02ff625828bc73f0` cancels prepared confirmation and withholds
inspection during submission/reconciliation, without changing disposition authority (§2).

### Retained Review Create Application — committed at `ab1cb0e`

`POST .../application-reviews/{id}/create-application/` uses an Idempotency-Key and
explicit company/optional role, status, Category and candidate provenance. It creates
an Application through the existing allocator, attaches via `attach_message()`, inserts
an immutable `RetainedReviewCreationResult`, then completes RequestIntent in one atomic
Workspace-gated transaction. Manual/posting request digests and challenge semantics
remain unchanged. New result schema is additive Application `0010`, without backfill.

New requests require confirmation for prior results, existing source relationships or
ordinary duplicates. A fresh key alone cannot bypass repeat protection; confirmed work
always creates a new Application. Completed replay reads its durable result without
allocation/attachment, including after dismissal, conflict or Application Trash. New
work rejects dismissed reviews and conflicted sources. Missing completed result fails
closed. Review detail adds 50-result cursor pages; list/filter behavior is unchanged.

Versioned snapshots preserve explicit semantic inputs only. No candidate label copying,
automatic disposition, email activity/status/date inference, evidence generation,
PostingSource, provider, frontend or historical reconciliation work. Protected references
leave future purge/terminal compaction to a separately approved lifecycle slice.

### JobPosting Portable Identity — committed at 6863f277

JobPosting retains integer PK/routes and gains immutable Workspace-scoped portable UUID.
Serializer/admin expose it read-only; conversion UUID fields still identify Applications.
The existing ingestion dedupe/URL/positional rules and descriptor updates remain transitional,
not canonical posting identity. Workspace/account FK deletion behavior is unchanged:
account cascade remains transitional and requires separate ownership work. No source-item,
PostingSource, retained-source ingestion, evidence, frontend or reconciliation work is included.
See the [posting identity review](DJANGO_POSTING_IDENTITY_REVIEW.md) for exact migration,
preservation, reverse limitations and verification evidence.

## 8. Completed checkpoint and separately scoped remaining work

- Retained-text extraction production, explicit operator batch execution, source-scoped read-only evidence inspection, its workspace-scoped read-only HTTP API and authenticated Workspace browser evidence UI are complete through `8a4af32e4fb9949430487449e5cbaaea5ab93a3c`; bounded extraction/retention PostgreSQL validation is complete at `c71f6cdcf183a4e76333b2c62582b8ecfdb1fc68`, alongside the existing explicit retained-posting authorities. Read-only Application list/core-detail browsing is complete at `845ad1f57addaf350b974aeaecc5aba5a750d2fa`; retained Application review inspection with core-detail navigation is complete at `bcad64038e6fbb4c224dc5a7ddfe075d4b3f22f7`; read-only named Category inspection with Application navigation is complete at `17ec29a476503d0e91ce7b6f123604386e04dad3`, consuming existing GET authority only. Standalone Application Category assignment/move/clear is complete at `6d2c736cb9a5a2bb68850019e74a77546c819f25`, invoking existing assignment authority as one bounded browser mutation workflow. Production fail-closed configuration admission is complete at `160c8a4007f262bab1361485b959accce145a628` as architecture hardening, without extending browser/domain capability. Retained Application review detail Dismiss/Restore is complete at `3b9a56f593dc3eed1238a8cc890420e67d010c89`, consuming existing disposition authority with fresh confirmation, GET-only recovery and inclusive discovery. Read-only retained-review source-text inspection is complete at `dbaa85926e35466dd6be7b8e02ff625828bc73f0`, consuming existing scoped retained-message GET with literal text, honest completeness and context isolation. The next substantive migration slice remains unselected and unauthorized. Provider/sync adoption, automatic canonical workflows, broader canonical consumers, broader retained-workflow APIs, remaining Application/domain frontend work, concurrency outside the exercised boundary, production load and production/operational/cutover validation require separate planning and authorization. Prior local database provenance remains unresolved.

Remaining areas below are unranked and require separate scope/authorization. No next substantive slice is selected.

- Resolve the legacy verification blockers under separately approved scope before declaring a fully green checkpoint.
- Separately scope remaining browser review attach/create and other review actions, future filtering/queue UX, and broader email/job and frontend work; bounded review Dismiss/Restore and read-only source-text inspection are complete.
- Plan provenance-aware historical reconciliation with importer/cutover work; do not silently backfill current records.
- Separately scope remaining core, retained email/review and posting browser workflows; retained extraction evidence inspection, Application core browsing, read-only retained-review inspection/navigation and named Category inspection/Application navigation and standalone Category assignment and detail-only review Dismiss/Restore and explicit read-only source-text inspection are implemented, without completing other Category/Application/review mutations or broader frontend migration.
- Develop import/export alongside models; rehearse representative workspaces.
- Validate production operations and cutover gates before retiring legacy.

Use the [Decision Record sequence](DJANGO_MIGRATION_DECISIONS.md#recommended-implementation-sequence)
for detail. Future work remains scoped to the user's authorized task.

## 9. Import/export and cutover readiness

**Not ready.** No Django importer/exporter or accepted-model reconciliation
implementation exists. Preserve source data, distinct attempts/categories,
legacy timestamps, manual state, evidence PDFs, and provenance. Missing source
email must remain explicitly unavailable. Exports exclude all credentials.

Before cutover, demonstrate repeatable import/reconciliation and export/restore,
preserve rollback artifacts, and explicitly transition workspace write authority.
No local/hosted synchronization or silent installation repointing is implied.

## 10. Production validation and retirement gates

Fail-closed configuration admission and profile enforcement are implemented (§2).
This does not close the operational gates below, which remain open unless supported
by separate recorded evidence:

- Actual production PostgreSQL connectivity, TLS/certificate and pooling policy, native
  libpq deployment, deployment environment and trusted proxy topology; HSTS rollout is deferred.
- Same-origin product sessions/CSRF, administrative onboarding/recovery, isolation.
- Production PostgreSQL deployment/migration and broader concurrency/load validation
  (isolated extraction/retention evidence above does not close this gate), private storage,
  Redis, separate web/worker/Beat, safe required secrets and static/media delivery.
- Full enabled-provider flows, including retained evidence, retries, and disconnect.
- Production browser acceptance/support and large-scale frontend performance for core
  workflows, imports/exports, previews and Trash; local read-only Application/review/Category browsing
  and the bounded standalone assignment, retained-review Dismiss/Restore and source-text inspection workflows do not
  establish general mutation support or deployment/operational/cutover readiness. Fresh Safari,
  production-browser and large-scale disposition/source-text workflow validation remain absent. The
  source viewer's field/text limits do not bound aggregate JSON response memory.
- Coordinated database/content backup and tested restoration.
- Documented/logged deployment, migrations, jobs, storage, and rollback operations.
- Successful reconciliation, end-to-end acceptance, and rollback readiness before
  desktop retirement; no deletion/alteration of local source data without approval.

## 11. Historical checkpoint context

2026-10-07: read-only retained-review source-text inspection was committed/pushed at
`dbaa85926e35466dd6be7b8e02ff625828bc73f0`, parent documentation checkpoint
`58f3d7ee51f0781f4f27b55de6445934cb29c8b8`. §2 retains Stage 3 execution evidence,
Stage 5 read-only review, Stage 6 verified commit/push and all findings/limitations.
This Stage 9 Status-only reconciliation adds no application test run or operational evidence;
prior checkpoint entries and original exclusions remain historical and unchanged.

2026-10-07: retained-review Dismiss/Restore browser workflow was committed/pushed at
`3b9a56f593dc3eed1238a8cc890420e67d010c89`, parent documentation checkpoint
`7bc6cb11935088b3b5dc93e224217b0552aebcaf`. §2 retains Stage 3 execution evidence,
Stage 5 read-only review and all findings/limitations; this Status-only reconciliation
adds no application test run or operational evidence.

2026-10-07: production settings admission was committed/pushed at
`160c8a4007f262bab1361485b959accce145a628`, parent documentation checkpoint
`c96be928f065b82f114aa0ecc3b845b0c6e92334`. §2 records its retained pre-commit evidence,
corrected management-command bypass and configuration-only boundary. This Status-only
reconciliation adds no application tests or operational evidence; prior checkpoints remain intact.

At `ecd1727`, main is integrated and inspected legacy fixes are preserved. Three
repeated legacy commits are patch-equivalent; no inspected evidence of merge
loss. Ghosted and override-lock mitigations landed in legacy, not Django;
backend files were unchanged by those merges.

2026-09-11: user approved audit and Decisions 1–10; created this maintained
checkpoint, the durable Decision Record, and root AGENTS.md only. Historical
handoffs remain unchanged and may still contain stale counts, ZIP workflows,
commit references, and incorrect completion claims. No application changes or
new operational validation are represented by this checkpoint.

2026-09-12: consolidated accepted Topics 1–9 in Foundations and narrowly updated
Decisions, Status, and AGENTS authority/navigation at `8108a9f`. That consolidation
was documentation only and added no fresh test or operational evidence.

Workspace Scoping Core now implements the backend-only subset described in §7,
with fresh automated verification in §2. All operational cutover/retirement gates
remain open.
