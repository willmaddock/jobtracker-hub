# Django migration: current status

Maintained checkpoint: 2026-09-12, Frontend API Foundation — Auth + Explicit Workspace Context implemented in the uncommitted tree based on `e1785f9`; bounded browser checks passed; all three legacy-suite failures also reproduce on clean `e1785f9` in the same environment.

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

Base: `django-migration` at `e1785f9` — Implement workspace-scoped Django API.
Frontend foundation changes remain uncommitted; no migrations were created.

| Command | Actual current-tree result |
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
  URL. Email APIs and legacy deletion paths remain outside this slice.
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
| Applications/overrides | Create/list/overrides/history; path uniqueness still restricts repeats | Baseline coverage; repeats/warnings/history parity pending | Integrated workflow pending |
| Derivation/dossier | PDF/TXT extraction, dossier/date evidence; no document-to-application status/activity recalculation | Existing extraction/dossier coverage; derivation pending | Target timestamp/import behavior pending |
| Categories | Section-derived groups and archive/delete, no named category model | Existing section-category coverage only | Target category workflow pending |
| Documents/files | Upload/list/type correction/metadata rename; storage URL; permanent individual delete | Existing API/extraction coverage | Production storage/previews pending |
| Trash/recovery | No application-managed Trash; parent deletion lacks object cleanup | Target lifecycle unimplemented/unverified | Restore/permanent cleanup pending |
| Search/dashboards/settings | Included reads, counts, search, section adapters, merges, and settings scoped to URL workspace; search parity and Ghosted still pending | Scoped isolation coverage; broader target parity pending | Frontend integration pending |
| Provider connections | Gmail/Outlook/IMAP connect/sync/disconnect; encrypted credentials | Baseline provider/view coverage, mocked external seams | Historical Gmail OAuth/live-sync checkpoint; complete target flows unvalidated; Outlook/IMAP live validation unestablished |
| Sync/jobs | Match/discovery/thread writes; inline single sync, queued bulk/Beat | Existing sync/task coverage; not real-broker proof | Real Redis/worker/Beat operation unestablished |
| Retained messages/review | Metadata records only; no durable source model or discovery review API/account-list API | Target retention/review unimplemented/unverified | Pending |
| Postings | Fixture-tested extractor, ingestion helper, list/save/dismiss/restore/apply APIs | Baseline component/fixture coverage | Sync does not call ingestion; apply lacks evidence; full workflow pending |
| Import/export | No Django legacy importer or portable export/restore | Unimplemented/unverified | Reconciliation/cutover pending |
| Production | Partial settings/storage/task scaffolding; SQLite inherited, development fallbacks remain | Suite success is not deployment verification | PostgreSQL/storage/jobs/backup/restore/rollback pending |

## 6. Known parity gaps and blockers

- Connect `email_sync/sync_service.py` to `postings/services.py` ingestion;
  currently sync writes discoveries/matches, not JobPosting rows. Carry over
  safe job/URL association and evidence behavior.
- Implement retained sources, account listing, discovery preview/attach/accept/
  dismiss/restore/sender classification, and evidence/backfill.
- Add per-application derivation and timestamp provenance without modifying
  manual overrides. Django history currently logs repeated identical statuses;
  legacy suppresses consecutive duplicates.
- Add Ghosted choices/metrics/UI parity. This main-branch change exists only
  in the legacy implementation.
- Replace path uniqueness, section-only categories, and immediate deletion
  with accepted identities, named categories, and Trash/lifecycle rules.
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

Deletion remains legacy behavior awaiting lifecycle work. No Trash, schema,
email/account/auth infrastructure, frontend, or task changes were part of that backend-only slice.
This is not completion of the broader workspace contract or historical phases.
Evidence regeneration replacement versus supersession still requires an explicit
decision before that behavior is implemented; other remaining implementation and
operational details are listed in Foundations.

### Frontend API Foundation — current uncommitted slice

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
No commit or push has been performed.

## 8. Next recommended implementation actions

1. Review the uncommitted frontend foundation and the verification limitations above.
2. Resolve the legacy verification blockers under separately approved scope before declaring a fully green checkpoint.
3. Separately authorize the next slice; remaining email/job workspace integration and broader frontend workflows are still pending.
4. Implement schema/lifecycle foundations, derivation, and parity corrections.
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
