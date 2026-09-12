# Django migration: accepted architectural decisions

Status: approved architectural baseline, 2026-09-11.

These are accepted **target decisions**, not claims that implementation is
complete. Accepted Topics 1–9 detailed contracts are recorded in
[Foundations](DJANGO_MIGRATION_FOUNDATIONS.md). Code and migrations establish what
is implemented; this Decision Record owns product/architecture boundaries,
Foundations owns their detailed contracts, and Status owns implementation/readiness.
The plan and historical handoffs/troubleshooting are supporting context, subordinate
where stale or conflicting. Surface apparent contradictions for review rather than
silently rewriting either authoritative document.

See [current migration status](DJANGO_MIGRATION_STATUS.md) for the
implementation checkpoint and [migration plan](DJANGO_MIGRATION_PLAN.md) for
broader historical context. The approval baseline is `django-migration` at
`ecd1727`, before implementation of the newly accepted decisions.

Change an accepted decision only when the user explicitly changes it. Do not
silently reinterpret it through implementation, cleanup, or status-document
edits. Detailed implementation designs must stay within these boundaries.

## 1. Workspace UX

**Chosen option: A — One selected workspace at a time.**

Accepted boundaries:
- Normal application, posting, document, settings, search, and dashboard views
  are scoped to one selected workspace.
- Workspace context is explicit in requests and UI state, never a single
  global server-side active-workspace pointer.
- Different browser tabs can operate on different workspaces safely.

Implementation consequences:
- API queries and object references must validate both workspace membership
  and authenticated-user ownership.
- Frontend navigation, requests, and asynchronous results must retain the
  correct workspace context; test isolation and independent tabs.

Deferred: all-workspaces overview until after the initial migration.

## 2. Frontend migration strategy

**Chosen option: A — Adapt the existing frontend in place.**

Accepted boundaries:
- Preserve existing UI, screens, styling, and interactions; no visual redesign.
- Change only what Django authentication, explicit workspace context, API
  contracts, uploads, file access, email workflows, and other migration
  requirements need.
- No new frontend build system or broad component refactor. Small, narrowly
  scoped refactors are acceptable when needed for safe integration.

Implementation consequences:
- Adapt the current frontend rather than replacing it.
- Introduce the small centralized API client from Decision 8 and validate
  end-to-end behavior, not merely rendering.

Deferred: structured React modernization after Django replaces the legacy
backend and end-to-end workflows are validated.

## 3. Application status/activity derivation

**Chosen option: A — Preserve automatic derivation from stored documents.**

Accepted boundaries:
- Recalculate automatic application status from stored documents and their
  classifications. Manual status always takes precedence.
- Needs Attention precedence remains: explicit activity reset, application
  date, then document-derived last activity.
- Strong confirmation evidence may populate an otherwise empty application
  date. Weaker posting evidence remains a suggestion.
- Never treat migration/import time as activity. Preserve known legacy
  document/activity timestamps.
- Keep storage/upload time distinct from evidence/activity time. For new
  uploads, upload time is only a fallback when no better timestamp exists.
- Renaming, classification correction, or metadata edits do not themselves
  create activity. Classification may change inferred status without changing
  the activity date.

Implementation consequences:
- Schema must distinguish relevant timestamps and their provenance.
- Replace whole-filesystem rebuilding with a reusable, deterministic,
  explicitly callable per-application derivation service.
- Run derivation after relevant document create/delete/type-correction
  operations and during import/reconciliation; repair jobs and tests can call
  it explicitly.
- Update only derived/automatic fields, never overwrite manual overrides.
- Test precedence, evidence tiers, repeatability, and metadata-only changes.

Deferred: broader event-based lifecycle redesign.

## 4. Application identity and repeated applications

**Chosen option: B — Separate records for separate application attempts.**

Accepted boundaries:
- Each Application row represents a distinct tracked attempt. Stable Django
  ID/foreign-key identity is authoritative.
- Company, role, section, dates, and source paths describe records but do not
  uniquely identify them. Matching company/role attempts are allowed.
- Preserve distinct legacy applications; never silently merge based only on
  company/role similarity.
- Suspected duplicates produce a warning, allowing the user to open an
  existing application or explicitly create another attempt.
- Prevent duplicate request/import effects through idempotency/reconciliation,
  not company/role uniqueness.
- Protect repeated posting conversion unless the user explicitly requests
  another attempt.
- Preserve legacy keys/paths as useful provenance, not permanent identity;
  provenance must not block legitimate reapplications.
- Distinguish attempts with available dates or lightweight context. Do not
  require dates, requisition IDs, or artificial attempt numbers.

Implementation consequences:
- Remove source_relpath from permanent application uniqueness.
- Define provenance mappings, idempotent creation/conversion/import, explicit
  duplicate-warning contracts, and frontend continuation choices.
- Import preserves separate source records even when their labels match.

Deferred: richer attempt grouping or lifecycle features beyond lightweight
presentation; no mandatory business-key system is part of this migration.

## 5. Category behavior

**Chosen option: B — Named categories as workspace-owned records.**

Accepted boundaries:
- Section is system-level classification/navigation; category is a named
  workspace-owned container with a stable ID independent of its name.
- Multiple categories may share a section. Empty categories are allowed.
- No nested categories or multi-category membership.
- Import preserves names where possible, distinct categories, membership,
  and archive state; never collapse categories merely because sections match.
- Retain folder/path provenance where useful without making it identity.
- Category archive hides the category and its contents from normal category
  views without rewriting member archive/status state.
- Applications retains special pipeline semantics. It is not an ordinary
  category that can be archived/deleted wholesale. Category membership must
  not redefine application status or pipeline behavior.

Implementation consequences:
- Add category identity, workspace ownership, section association, membership,
  and lifecycle state to schema/API/frontend.
- Import maps legacy containers separately; queries respect category and item
  visibility independently. Deletion follows Decision 6.

Deferred: nested categories and multiple-category membership.

## 6. File lifecycle, deletion, recovery, previews, and export

**Chosen option: B — Application-managed Trash.**

Accepted boundaries:
- Archive controls visibility/organization; Trash means deletion pending
  restoration or permanent removal. Both remain separate from business status.
- Trash is soft deletion: preserve database records, relationships, and files.
  Physically delete stored files only during explicit permanent deletion.
  Orphaned storage is not a recovery mechanism.
- Trashing a parent preserves children/relationships. Restore respects prior
  child state: independently trashed children are not silently restored.
- Permanent deletion is a separate confirmed action and consistently removes
  records/files according to explicit ownership/lifecycle rules. Workspace
  permanent deletion requires stronger confirmation. No automatic expiration.
- Rename changes visible filename/metadata; storage keys need not change.
  Downloads, previews, and exports present the current visible filename.
- Preserve inline PDF, text, and web-appropriate rendered DOCX previews.
  Use browser download/open behavior, not server-side desktop launching.
- Preserve workspace export with documents and structured restoration data:
  identities/reconciliation metadata, applications, categories, memberships,
  overrides, status/history, settings, and relevant provenance.
- Never export credentials, tokens, encryption secrets, or other authentication
  secrets. Reconnect email accounts after restore/import. Paths stay provenance.

Implementation consequences:
- Add soft-delete state, deterministic parent/child restoration, and explicit
  permanent-cleanup services with tests.
- Build Trash/restore/confirmation APIs and UI, previews, downloads, and
  portable export/import. Database and storage lifecycle must agree.

Deferred: automatic Trash expiration and later retention-policy expansion.

## 7. Email evidence persistence and review

**Chosen option: B — Persist relevant messages and readable evidence.**

Accepted boundaries:
- Persist messages retained as application evidence, discoveries under review,
  or posting sources, not the entire mailbox or every examined message.
- Retain sufficient content, headers, provider/source IDs, timestamps,
  sender/recipient metadata, subject, and provenance for preview, extraction,
  matching, and evidence generation.
- One stable retained source can support multiple relationships/postings
  without duplicating the underlying message unnecessarily.
- Do not automatically import attachments unless an existing workflow
  explicitly requires them during the initial migration.
- Application matching/review and job-alert posting extraction stay distinct.
- Support preview, attach, accept/create, dismiss, restore, and sender
  classification. Ambiguous matches require explicit review.
- Accept/attach may generate readable evidence but must not silently overwrite
  manual application values. Evidence generation is deterministic/idempotent.
- Repeated sync, review, posting extraction, and evidence/backfill operations
  must not duplicate messages, relationships, postings, or documents.
- Deduplication uses provider message IDs plus account/provider provenance,
  with reconciliation when identifiers are unavailable or unstable.
- Disconnect removes/invalidates credentials and stops access, not saved
  evidence. Retained content/evidence follows Trash and explicit permanent
  cleanup under defined ownership rules.
- Treat retained content as sensitive workspace data. Scope sources and
  relationships to owner/workspace; no cross-workspace content exposure.
- Export may include retained content/provenance, never authentication secrets.
  Reconnection creates a new provider connection reconciled where possible.
- Preserve legacy evidence PDFs/references. Never fabricate unavailable source
  content; mark it unavailable while retaining evidence that exists.

Implementation consequences:
- Add a provider-independent retained/source-message model referenced by
  matches, discoveries, posting sources, and evidence documents rather than
  copying bodies into each record.
- Connect persistence, review, extraction, evidence, lifecycle, and import/export
  services with explicit ownership and idempotency.

Deferred: whole-mailbox archiving and broad automatic attachment ingestion.

## 8. API compatibility strategy

**Chosen option: B — Adapt the frontend to explicit Django contracts.**

Accepted boundaries:
- Django contracts are authoritative for migrated workflows; preserve useful
  visible behavior, not necessarily legacy URLs/payloads/shapes.
- One authoritative API and write path per migrated workflow. No silent
  FastAPI write fallback or competing long-lived write implementations.
- Use stable Django IDs. Legacy keys/paths are import/provenance data only.
- Explicit workspace context and object ownership validation are mandatory;
  separate tabs remain safe.
- Preserve familiar fields where useful without distorting the model.
- Introduce a small centralized API client within the existing frontend for
  base API handling, workspace context, sessions/auth, CSRF, error normalization,
  retries, idempotency keys/headers, and asynchronous task/status handling.
- Make expired sessions/auth failures, duplicate warnings, validation/ownership
  errors, and task state explicit and machine-readable as appropriate.
- Define deliberate contracts for categories, Trash, retained email, uploads,
  exports, and other accepted behavior.
- Protect retryable creation/conversion/import operations, including application
  creation, posting conversion, retained-message ingestion, and evidence.
- Temporary read adapters are acceptable only with a defined removal point
  before legacy retirement.

Implementation consequences:
- Adapt frontend calls and backend contracts together through the small client.
- Add workflow/contract tests for isolation, errors, warnings, and idempotency;
  isolated serializer/view tests alone are insufficient.

Deferred: permanent legacy API compatibility and broad frontend modernization.

## 9. Onboarding and production deployment

**Chosen option: A — Private hosted deployment, administrator-created accounts.**

Accepted boundaries:
- Administrative provisioning and assisted recovery initially; no signup or
  invitations. Small user populations do not relax ownership/isolation.
- Allow later onboarding expansion without redesigning ownership.
- Same-origin frontend/API, Django sessions and CSRF. Normal production use
  must not depend on Basic authentication or development shortcuts.
- PostgreSQL is production's database; SQLite may serve local development/tests.
- Private S3-compatible storage, Redis for Celery, and distinct web, worker,
  and scheduler/Beat processes.
- Separate development/production configuration. Deployment supplies secrets;
  do not commit them. Fail safely when required production secrets are missing.
- After login, create a workspace or import/restore one. Email connection is
  optional and follows workspace setup.
- Enable a provider only after its authentication, sync, retained-message,
  review, posting, evidence, retry, and disconnection workflows are validated.
  All three implemented providers need not launch simultaneously.
- Establish database backups and storage backup/versioning/recovery; test
  database and content restoration together.
- Document deployment, migrations, worker/scheduler operations, backup, restore,
  and rollback. Provide failure visibility for requests, jobs, sync, imports,
  and storage.
- Passing automated tests does not prove infrastructure/OAuth operational
  validation. Private hosting does not lower data-integrity/cutover gates.
- No hosting vendor is chosen or encoded by this decision.

Implementation consequences:
- Complete onboarding/session flows, production service configuration,
  fail-safe secrets, operational procedures, logging, and real-service validation.
- Release providers according to validation evidence, not code presence.

Deferred: invitations, public registration, expanded self-service recovery,
and hosting-vendor selection (to be decided during deployment planning).

## 10. Desktop role after migration

**Chosen option: A — Browser-first; retire legacy runtime after successful cutover.**

Accepted boundaries:
- Hosted Django is the primary product after cutover; no parallel production
  local FastAPI mode for migrated workspaces.
- Keep legacy desktop during migration for comparison, validation, and rollback.
  Preserve local source data/agreed rollback artifacts until acceptance.
- Do not silently repoint installations or alter/delete local data without
  explicit approval.
- After workspace cutover Django is its authoritative writer; the legacy copy
  must not be a second writer. Do not imply synchronization.
- Validate browser authentication/onboarding, workspace create/import, uploads,
  PDF/text/DOCX previews, downloads, export, email connection/sync/review/evidence,
  postings, applications, Trash/recovery, and other critical native/file actions.
- Replace folder picking/linking with web import/upload, local opening with
  browser behavior, and Mail.app with provider-based email.
- Retirement requires validated import/reconciliation, end-to-end acceptance,
  backup/restore, and rollback procedures.

Implementation consequences:
- Complete browser replacements and explicit workspace authority transitions;
  retain rollback artifacts. Hosted Django is the production runtime.

Deferred: a thin desktop wrapper until browser stability and cutover. Any later
wrapper uses the same hosted backend, not a separate datastore. Offline/local
synchronization is out of scope for initial migration.

## Cross-decision architectural implications

- Workspace is the operational boundary for APIs, UI, tasks, sources, and data
  movement; ownership filtering alone is insufficient.
- Stable IDs replace filesystem identity; legacy IDs support reconciliation.
- Automatic state, manual overrides, Archive, and Trash remain distinct.
- Database relationships and storage must share explicit lifecycle/ownership
  rules, including retained sources referenced by multiple records.
- Named categories, Trash, retained messages, and repeated attempts are accepted
  migration scope, not optional cleanup.
- Idempotency spans browser retries, jobs, imports, conversion, and evidence.
- Preserve visible behavior without freezing legacy transport contracts.
- Cutover changes write authority; rollback copies do not imply synchronization.
- Automated verification and operational/end-to-end evidence are separate gates.
- Lifecycle ownership, reconciliation keys, export representation, task contracts,
  and timestamp selection have accepted detailed contracts in
  [Foundations](DJANGO_MIGRATION_FOUNDATIONS.md); implementation remains pending.

## Migration blockers created or clarified

| Blocker | Required result |
|---|---|
| Workspace scoping | Explicit context, object validation, safe independent tabs |
| Model foundations | Repeated attempts, categories, timestamp provenance, Trash, retained messages |
| Lifecycle | Deterministic restoration and ownership-aware permanent cleanup |
| Derivation | Recalculation preserving manual values and historical activity |
| Email integration | Source persistence connected to review, postings, evidence, and task state |
| API/frontend | One write path, centralized client, explicit errors and retries |
| Browser files | Previews, downloads, Trash/recovery, portable export |
| Import | Repeatable reconciliation without collapsing attempts/categories or fabricating evidence |
| Production | Real-service validation, safe secrets, logging, coordinated backups/restoration |
| Retirement | End-to-end acceptance and validated rollback with preserved source data |

Public onboarding, frontend restructuring, all-workspace dashboards, offline
sync, and a desktop wrapper are not migration blockers.

## Recommended implementation sequence

1. Publish decisions and a concise current status, separating evidence from intent.
2. Foundational contracts are accepted in [Foundations](DJANGO_MIGRATION_FOUNDATIONS.md).
   Review the documentation checkpoint before separately authorizing implementation.
3. Establish explicit workspace/authentication foundations and frontend API client.
4. Implement identity, categories, timestamps, Trash/restore/cleanup, and retained
   source relationships.
5. Implement deterministic derivation and parity corrections, including Ghosted
   and status-history behavior.
6. Complete core browser workflows incrementally: applications, categories,
   documents, previews, dashboards, search, and Trash.
7. Complete email/posting ingestion, review, evidence, task state, retries, and
   disconnection.
8. Build import/export alongside relevant models and rehearse full representative
   workspaces once connected workflows are available.
9. Validate production database/storage/jobs, enabled providers, configuration,
   logging, coordinated backup/restore, and rollback.
10. Cut over under acceptance gates; remove temporary compatibility and retire
    desktop only after all gates pass.
