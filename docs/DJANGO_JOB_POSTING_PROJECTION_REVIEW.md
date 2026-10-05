# Descriptor Projection Authority

Historical implementation-stage evidence for the thirteen-file projection slice,
subsequently committed/pushed at `8ba7bc869787f80b217c0c066f9c713a337a5669`
(`Implement descriptor projection authority`). Git-stage statements below describe
the original pre-commit verification, not current repository state. Validation evidence
is preserved unchanged.

## Checkpoint and scope

Repository `/Users/dev/Documents/GitHub/jobtracker-hub`, branch `django-migration`.
Pre-edit HEAD, tracking branch and live remote matched
`5f832dcc261d13365d851806623fca1a373e1644`, subject
`Implement posting-level interpretation arbitration authority`, parent
`d46ef1508259f0418d1d0c842678456c883f5732`. Ahead/behind 0/0; clean working tree/index;
backend/db.sqlite3 absent/untracked; unrelated EmailAccount.provider migration absent.
The external `/tmp/review_disposition_settings.py` matched the approved in-memory
SQLite override exactly before Django commands. No repair/substitution was needed.

Modified:

- backend/postings/models.py
- backend/postings/admin.py
- backend/postings/services.py
- backend/postings/tests/test_services.py
- backend/core/tests.py
- docs/DJANGO_MIGRATION_FOUNDATIONS.md
- docs/DJANGO_MIGRATION_STATUS.md
- docs/DJANGO_JOB_POSTING_INTERPRETATION_REVIEW.md

Added:

- backend/postings/job_posting_projections.py
- backend/postings/migrations/0011_job_posting_descriptor_projections.py
- backend/postings/tests/test_job_posting_projections.py
- backend/postings/tests/test_job_posting_projection_migrations.py
- docs/DJANGO_JOB_POSTING_PROJECTION_REVIEW.md

No arbitration/API/conversion production changes or separate forms module.
The accepted detailed contract is in [Foundations](DJANGO_MIGRATION_FOUNDATIONS.md).

## Schema and canonical insertion

JobPostingDescriptorProjection inherits PostingItemProvenance. Fields are BigAuto
ID, posting, caller UUIDv4 operation_id, contiguous positive revision, exact
arbitration_decision, snapshot, expected_descriptor_digest, actor, fixed method
explicit_owner, fixed projection_version 1 and created_at. Posting, arbitration and
actor are PROTECT. Reverse names are descriptor_projections for posting/arbitration,
and job_posting_descriptor_projections for actor. No mutable pointer, mode, redundant
witness, second digest, custom index or timestamp ordering.

Five constraints: job_post_proj_operation, job_post_proj_revision,
job_post_proj_positive, job_post_proj_method, job_post_proj_version. Digest syntax
and signed-64-bit bounds/contiguity are validated in Python. Ordinary create/save,
replacement save and instance delete reject. Only the private append/materialize
helper deliberately invokes base insertion within the canonical transaction.

Migration 0011 creates one table, depends on postings 0010 and swappable user, and
has no backfill, RunPython, field widening, JobPosting alteration or automatic
projection. Populated 0010 migration tests preserve existing tables and repeat the
migration; alias validation disables default-connection access. Historical-model
fixture insertion is explicitly test-only and paired with descriptor materialization.

## Snapshot, digest and atomicity

Exact six fields: source, title, company, location, salary, employment_type. Reuse
retained validation, then enforce destination character capacities 64,255,255,255,
255,64. Preserve null/blank/Unicode/case/whitespace, without normalization, salary
parsing, truncation or coercion. Capacity failure reports field names/limits in fixed
order without values; no event, descriptor change, UUID or revision reservation.

Digest is lowercase SHA256 of canonical UTF-8 JSON
`{"descriptor_digest_version":1,"fields":{...six current columns...}}`, recursively
sorted keys, compact comma/colon separators, ensure_ascii false, allow_nan false.
Current columns deliberately do not require retained vocabulary/byte limits. The
caller-supplied matched precondition is stored, not a fabricated prior-state snapshot.
No ABA/history guarantee: A→B→A ending with equal values has the same digest.

Materialization is exactly one six-column QuerySet.update followed by a fresh reread
and exact comparison. Mismatch or later transaction failure rolls back event and
columns. URL, dedupe, identity, account, metadata, status/saved, relationships and
timestamps remain unchanged. No parser or allocation occurs.

## Witnesses, states, replay and precedence

New projection requires the exact current arbitration selection, applicable current
mapping/item interpretation/historical output membership, eligible source and valid
complete evidence. Historical events validate their recorded arbitration prefix and
exact retained snapshot without pretending that later applicability stayed unchanged.

States: unprojected/projected/stale. Ordered reasons: arbitration_revision_changed,
arbitration_not_applicable, descriptor_drift. Valid replacement alone adds the first;
recorded lower-layer staleness or current unresolved/withdrawn/stale arbitration adds
the second. Recorded and current arbitration reasons are separate. Drift is current
six-column mismatch, not evidence corruption and not attribution of a writer.

Sticky conflict alone leaves otherwise-current state projected, source_eligible false
and applicable_snapshot unavailable. Old valid conflicted evidence does not block an
eligible replacement; corrupt required history does fail closed. No automatic clear,
fallback, transfer, repair or release of writer ownership.

Replay identity binds posting/UUID, exact arbitration, predecessor projection revision,
expected descriptor digest and fixed policy. Actor is attribution only. Exact replay
returns the original event with fresh state and never writes descriptors, including
after drift, later projection/arbitration or conflict. First equal-value projection
establishes provenance; identical later authority/snapshot/current values is unchanged.
New authority with equal values and explicit drift repair are meaningful.

Precedence: authorize/input → transaction/gate/posting → capture/discover/lock sources
→ requested endpoint → operation/payload collision → history/dependencies → replay
→ projection revision → arbitration revision/applicability → source eligibility
→ retained snapshot/capacity → current digest comparison → no-op → revision exhaustion
→ append/materialize/reread/result. Capacity precedes stale_descriptor_digest.
New errors and existing lower-layer error reuse match Foundations.

## Competing writer changes

Ownership is existence of any projection event, including when history is corrupted.
Ingestion now serializes each output Workspace-before-posting, rechecks persisted
account scope and explicitly creates/updates instead of row-first update_or_create.
Unprojected descriptor behavior is preserved. Projected descriptors remain unchanged;
existing separate URL/email metadata updates continue. Incoming dedupe calculation
and global uniqueness remain unchanged. No message-wide transaction or hidden retry;
noncooperating creation races may surface IntegrityError.

Ordinary JobPosting saves are alias-aware, preserve identity guards and freeze actual
write fields before deferred loading. Descriptor writes hold Workspace/posting locks
through ownership comparison and save; protected changes raise
ValidationError(descriptor_projection_owned). Status/saved-only and appropriate
deferred saves remain allowed. Stale full saves cannot overwrite projection.

Admin dynamic readonly fields preserve URL editing. POST serialization covers form
construction/validation/save. Inline form validation rejects submitted protected keys,
including keys excluded from generated readonly forms; privileged admin is not required
to own the Workspace. Model protection remains final enforcement. Projection events
use existing read-only provenance admin and the core allowlist is extended.

## Locks and readers

Atomic Workspace gate/owner recheck → scoped posting row → captured boundaries →
complete deduplicated sorted source set → validation → writes → verification. Discovery
covers every referenced arbitration prefix and both selected/initial-anchor sources;
reference discovery is not authorization. No late source lock. Reuse arbitration
Dependencies, _source_ids, resolve_chain, _state without production changes or nested
public readers. Existing arbitration/conversion ordering is compatible; descriptor
writers were brought under Workspace-first ordering.

Effective results are frozen with detached immutable snapshot mappings and separate
recorded/current authority reasons. can_project is advisory, not a promise that later
caller preconditions match. History uses captured (posting,through,last) pagination,
ascending revisions, default100/max200, strict integer validation, limit+1 and whole
prefix validation. Later events/dependencies are excluded from historical pages; no
live per-event annotations or aggregate source eligibility.

## Verification

Fresh corrective-pass validation, 2026-10-04, with the approved in-memory settings
and `python -B manage.py`. The three added regressions cover primary-key-only deferred
ordinary/forced saves, explicit empty saves, and projection ownership. Automatic empty
deferred inference leaves update_fields unset; explicit empty behavior is preserved.
All four fresh suites exited 0 with zero failures, errors and skips; Django check passed.

| Suite | Passed | Seconds |
|---|---:|---:|
| Focused projection + migration | 57 | 8.024 |
| Postings | 393 | 32.790 |
| Affected apps | 1092 | 130.831 |
| Full Django | 1110 | 136.678 |

Fresh logs: `/tmp/projection-correction-focused.log`,
`/tmp/projection-correction-postings.log`, `/tmp/projection-correction-affected.log`,
`/tmp/projection-correction-full.log`.

Earlier implementation validation (2026-10-03): services/ingestion **17 passed**
(1.369s) and neighboring authority **256 passed** (9.297s), not separately rerun in
this corrective pass. Earlier focused/postings/affected/full results were 54/390/1089/1107;
the fresh counts above supersede them. Earlier logs remain `/tmp/projection-focused.log`,
`/tmp/projection-services.log`, `/tmp/projection-neighbors.log`,
`/tmp/projection-postings.log`, `/tmp/projection-affected.log`, `/tmp/projection-full.log`.
The neighboring suite includes arbitration, initial/corrected mapping, item
interpretation, initial/corrected membership and retained extraction.

An initial focused invocation encountered test-module collection failure because the
migration-test file creation command used an incorrect working-directory-relative
path. No unauthorized file was created; the path was corrected and the complete
focused suite passed. Subsequent inspection strengthened the populated-0010 fixture
and retained admin lookup validation; focused and postings were rerun afterward.
No unresolved test failures remain. PDF fixture diagnostics and expected sync-task
messages in broader logs are not test failures.

Django check passed. Scoped postings dry-run drift: none. Global dry-run exited 1
only for the already-known EmailAccount.provider choice-label AlterField; no provider
migration was generated. Graph reaches postings 0011. SQL inspection confirms one
CREATE TABLE, five named constraints, three FK indexes and no existing-table writes.
No migrations were applied to a real database; migration tests use isolated fixtures.

AST parsing, final newlines, trailing-whitespace checks, local Markdown targets/anchors
and git diff --check passed. All five untracked files were explicitly inspected.
Final Git scope is eight authorized modified files and five authorized untracked files,
nothing staged. HEAD remains the checkpoint above; no commit/push occurred. The real
SQLite database and unrelated provider migration remain absent.

Coverage includes values/capacity/atomic rollback, all stale-reason combinations,
conflict versus corruption, non-writing replay, explicit repair/ABA limitation,
protected ordinary/deferred/admin/ingestion writes, owner transfer, captured history,
sorted source locks, SQLite competing writers, read serialization, database constraints,
API lifecycle/conversion consumption, and non-default-alias validation.

Implementation is complete and ready for separately authorized read-only pre-commit
review; this report does not establish a new authoritative commit checkpoint.

## Limitations

- PostgreSQL, provider operations and end-to-end cutover were not exercised.
- SQLite concurrency tests explicitly retry busy outcomes at the test caller; the
  production service has no retry. They do not prove PostgreSQL lock behavior.
- Privileged raw/bulk writers can bypass ordinary protections; detected column drift
  has no inferred actor or cause. Coherent forged provenance is outside these guards.
- Digest protects current equality, not descriptor-history/ABA transitions.
- Full-prefix validation cost grows with history; no candidate enumeration was added.
- PROTECT can block posting/account/workspace/user deletion; purge is separate.
- Existing consumers show stored materialized values even after authority becomes stale.
- Allocation, field widening, projection withdrawal, manual overrides, frontend/API,
  historical reconciliation, provider changes and legacy cutover remain excluded.
