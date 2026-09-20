# Django migration: current status

Maintained checkpoint: 2026-09-20. Backend Deterministic Application Derivation is
committed at `120d49397297c2ba1337c88503769aec6ae87c41` on `django-migration`,
following Trash & Restore, Named Categories and Application Identity. Backend
Retained Email Source Identity and Content Foundation is the current **uncommitted**
review slice. No provider adoption, frontend integration, historical bulk
reconciliation, email derivation integration, or operational cutover is claimed.

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

### Retained-email foundation — fresh final verification, 2026-09-20

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
  Production settings still inherit SQLite.
- Environments: `.venv/` for legacy tests; `backend/venv/` for Django. Manifests:
  `_app/requirements.txt`, `requirements-dev.txt`, `desktop/requirements.txt`,
  and `backend/requirements.txt`.

## 5. Functional migration matrix

All target behavior below is **accepted**. Implementation is assessed against
the audit at `ecd1727`, updated below for Workspace Scoping Core. “Baseline coverage”
means existing component tests, not complete target parity; current counts are in §2.
No newly accepted capability is marked verified merely because it is designed.

| Area | Implemented now | Automated verification | Operational/end-to-end evidence |
|---|---|---|---|
| Auth/workspaces | Session-only product auth, anonymous-login CSRF bootstrap/protection, structured DRF exception codes; owned workspace list/create and explicit route selection in Django entry | 104 accounts/core subset; bounded browser session/tab checks described in §2 | Local foundation validated; broader onboarding/production/cutover pending |
| Frontend/desktop | Existing HTML has explicit Django entry with separate minimal root/client/context; legacy App never mounts in Django mode; desktop remains FastAPI | 8 Node tests; browser harness 7/7 in Safari and Chromium; three legacy suite failures recorded in §2 | Only login → explicit workspace select/create → insights read → logout validated; domain UI pending |
| Applications/overrides | Stable numeric PKs plus workspace portable UUID; shared protected creation, explicit repeat challenges and durable replay | Identity/ownership and duplicate-safe future transition coverage in §2 | Backend-only; duplicate-warning/domain UI pending |
| Derivation/dossier | Canonical per-Application status/activity, manual precedence, source precision, confirmation candidate/modes, duplicate-safe transitions; read-only dossier GET | Current derivation/forward-migration/SQLite coverage in §2 | Historical reconciliation, import provenance, frontend and operations pending |
| Categories | Native stable identity, single revision-protected membership, independent Archive; committed at `3f564ba`; reversible Trash committed at `74f1e91` | Current Category and lifecycle coverage in §2 | Frontend category workflow pending |
| Documents/files | Upload/list/type correction/metadata rename; storage URL; retained Trash and effective parent eligibility | Current Document/lifecycle coverage in §2 | Production storage/previews and frontend integration pending |
| Trash/recovery | Application/Document/Category Trash and Restore, revisions, mutation/admin guards; old deletes retired | Current lifecycle/migration/SQLite race coverage in §2 | Workspace lifecycle, purge, frontend and operational validation deferred |
| Search/dashboards/settings | Included reads, counts, search, section adapters, merges, and settings scoped to URL workspace; search parity and Ghosted still pending | Scoped isolation coverage; broader target parity pending | Frontend integration pending |
| Provider connections | Gmail/Outlook/IMAP connect/sync/disconnect; encrypted credentials | Baseline provider/view coverage, mocked external seams | Historical Gmail OAuth/live-sync checkpoint; complete target flows unvalidated; Outlook/IMAP live validation unestablished |
| Sync/jobs | Match/discovery/thread writes; inline single sync, queued bulk/Beat | Existing sync/task coverage; not real-broker proof | Real Redis/worker/Beat operation unestablished |
| Retained messages/review | Four protected source/observation models, explicit retention service and workspace-scoped read-only inspection; provider sync remains unadopted | Retention, API, migration and SQLite race coverage in §2 | Provider adoption, review actions, frontend and operational validation pending |
| Postings | Fixture-tested extractor, ingestion helper, list/save/dismiss/restore/apply APIs | Baseline component/fixture coverage | Sync does not call ingestion; apply lacks evidence; full workflow pending |
| Import/export | No Django legacy importer or portable export/restore | Unimplemented/unverified | Reconciliation/cutover pending |
| Production | Partial settings/storage/task scaffolding; SQLite inherited, development fallbacks remain | Suite success is not deployment verification | PostgreSQL/storage/jobs/backup/restore/rollback pending |

## 6. Known parity gaps and blockers

- Connect `email_sync/sync_service.py` to `postings/services.py` ingestion;
  currently sync writes discoveries/matches, not JobPosting rows. Carry over
  safe job/URL association and evidence behavior.
- Review the retained-source foundation; separately authorize provider adoption,
  account listing, discovery preview/attach/accept/dismiss/restore/sender
  classification, and evidence/backfill.
- Per-Application derivation is committed at `120d493`. Historical rows are
  intentionally not bulk-reconciled; missing source facts remain unknown. Future
  importer/cutover work must supply verified provenance and preserve history.
- Add Ghosted choices/metrics/UI parity. This main-branch change exists only
  in the legacy implementation.
- Named Categories and Application/Document/Category Trash are now implemented
  in the backend. Their frontend integration, Workspace lifecycle and confirmed
  permanent cleanup remain pending.
- Complete remaining workspace integration for email/jobs and the frontend;
  included synchronous core APIs are scoped. Adapt remaining payloads/errors and
  search semantics deliberately. Preserve PDF/text/DOCX browser previews.
- Build importer/exporter and validate restoration. Existing documents migration
  `0002` deletes/recreates DocumentOverride assuming no real data; fresh-database
  tests do not establish safe upgrades of populated intermediate databases.
- Legacy Finding 9 lock mitigations are present, but its field root cause is
  unresolved; do not turn that unrelated investigation into migration scope.

## 7. Current implementation phase

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
This frontend checkpoint was committed and pushed as `188351c`.

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
the fresh regression verification in §2.

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

### Backend Retained Email Source Identity and Content Foundation — uncommitted

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

Current sync remains transitional and unadopted. No review actions, posting ingestion,
generated Documents, derivation hooks, frontend integration, purge, import/export,
workers or historical reconstruction are included. PostgreSQL and operational
validation remain open; SQLite race tests are not production concurrency proof.

## 8. Next recommended implementation actions

1. Review the uncommitted retained-email foundation and verification limitations above.
2. Resolve the legacy verification blockers under separately approved scope before declaring a fully green checkpoint.
3. Separately authorize the next slice; retained email/job integration and broader frontend workflows remain pending.
4. Plan provenance-aware historical reconciliation with importer/cutover work; do not silently backfill current records.
5. Connect core browser workflows, then retained email/review/postings/evidence.
6. Develop import/export alongside models; rehearse representative workspaces.
7. Validate production operations and cutover gates before retiring legacy.

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

All remain open unless supported by new, recorded evidence:
- Same-origin product sessions/CSRF, administrative onboarding/recovery, isolation.
- PostgreSQL, private storage, Redis, separate web/worker/Beat, safe required secrets.
- Full enabled-provider flows, including retained evidence, retries, and disconnect.
- Browser acceptance for core workflows, imports/exports, previews, and Trash.
- Coordinated database/content backup and tested restoration.
- Documented/logged deployment, migrations, jobs, storage, and rollback operations.
- Successful reconciliation, end-to-end acceptance, and rollback readiness before
  desktop retirement; no deletion/alteration of local source data without approval.

## 11. Recent checkpoint

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
