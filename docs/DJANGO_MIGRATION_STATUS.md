# Django migration: current status

Maintained checkpoint: 2026-09-12, Workspace Scoping Core — Backend Only implemented and automated-test verified.

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

## 2. Current verified baseline

| Item | Baseline |
|---|---|
| Branch | `django-migration` |
| Base commit for this implementation | `8108a9f` — Consolidate Django migration foundations |
| Legacy suite | 370 passed |
| Django full suite | 491 passed |
| Workspace scope and cross-cutting tests | 52 passed (subset) |
| Application views, documents, dossier tests | 44 passed (subset) |
| Document views, categories, posting views tests | 31 passed (subset) |
| Django system check | No issues |

These results were freshly obtained for the Workspace Scoping Core implementation,
including format-suffix compatibility. The legacy suite reported two deprecation
warnings. The standalone workspace-scope module passed 25 tests; targeted counts
are subsets of the full Django suite. `git diff --check` passed.

No schema migration was created. `makemigrations --check --dry-run` remains blocked
by pre-existing `email_sync` provider-choice drift (proposed
`0006_alter_emailaccount_provider.py`), independently reproduced at clean `8108a9f`.
That check was not rerun for the format-suffix correction; the drift was not changed.
Browser, OAuth, Celery, storage-security, and production validation remain outstanding.
Commit/push state is separate from implementation/readiness.

Historical user-confirmed results at `ecd1727` were 370 legacy, 466 full Django,
and 59 core tests. They describe the earlier audit baseline, not this checkpoint.

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
| Auth/workspaces | Login/logout/me, owned workspace CRUD; included core APIs use explicit URL workspace and ownership checks; auth infrastructure unchanged | Same-user/cross-user backend isolation covered; browser/tab flows pending | Product onboarding/cutover pending |
| Frontend/desktop | Legacy UI/runtime only; no Django product integration/client | Legacy baseline; Django UI acceptance pending | Browser replacement pending |
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
email/account/auth infrastructure, frontend, or task changes are part of this slice.
This is not completion of the broader workspace contract or historical phases.
Evidence regeneration replacement versus supersession still requires an explicit
decision before that behavior is implemented; other remaining implementation and
operational details are listed in Foundations.

## 8. Next recommended implementation actions

1. Record the verified Workspace Scoping Core checkpoint.
2. Separately authorize and plan the next slice under Decisions and Foundations.
3. Complete remaining workspace/auth integration and the small frontend client.
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
