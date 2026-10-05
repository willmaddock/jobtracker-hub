# Retained Posting Review Orchestration

Implementation-stage evidence, 2026-10-04. This six-file slice remains unstaged,
uncommitted and unpushed; separate read-only pre-commit review and explicit commit/
push authorization remain required. Prior authoritative checkpoint:
`cce6cf08717d6dca18fd1ce8945f68df9589f39e`, subject
`Implement canonical JobPosting allocation authority`, parent
`8ba7bc869787f80b217c0c066f9c713a337a5669`, branch `django-migration`.

## Scope and authority

Added: backend/postings/retained_posting_reviews.py,
backend/postings/tests/test_retained_posting_reviews.py and this document.
Modified: DJANGO_MIGRATION_FOUNDATIONS.md, DJANGO_MIGRATION_STATUS.md and
DJANGO_JOB_POSTING_ALLOCATION_REVIEW.md. No model, migration, admin, existing
canonical primitive, Application production, API or frontend change.

`review_retained_posting(actor, workspace, item_id, command)` coordinates explicit
owner intent at RetainedPostingItem identity. It delegates initial attach or canonical
allocation, then optional explicit posting selection, then optional descriptor projection.
Mapping does not imply selection; selection does not imply projection. There is no
Application creation, evidence attachment, apply or review-disposition side effect.
No candidate discovery, automatic remap, semantic dedupe, ingestion/provider fetching,
cleanup or high-level review identity is introduced.

## Request and validation

Frozen slotted DTOs:

- MappingRequest: action, target_posting_id=None, operation_id=None,
  expected_interpretation_revision=None.
- SelectionRequest: operation_id, expected_arbitration_revision,
  expected_interpretation_revision, expected_mapping_revision.
- ProjectionRequest: operation_id, expected_projection_revision,
  expected_descriptor_digest.
- RetainedPostingReviewCommand: mapping, selection=None, projection=None.

MappingAction is attach_existing or allocate_new. Strict parse_review_command accepts
mapping-shaped input, rejects unknown top-level/nested keys, constructs DTOs and
normalizes UUID inputs through the existing canonical UUIDv4 helper. The coordinator
requires exact DTO types and revalidates them; arbitrary command objects/dicts are not
accepted directly. Shape failures use 400 invalid_retained_posting_review.

Attach supplies only a positive bounded target posting ID, no UUID or interpretation
revision. Allocation supplies a UUID and interpretation revision, no target ID. Optional
phases require their explicit DTOs; projection requires same-bundle selection. All
requested phase UUIDs must be distinct after normalization. No high-level operation ID,
generated phase UUID or derived UUID exists. Underlying commands used independently
retain their own ID scopes.

Integers must be exact ints, never bool. Maximum is 9223372036854775807. Allocation and
selection interpretation revisions are positive; selection arbitration/mapping and
projection revisions permit zero. Allocation plus selection must name the same item
interpretation revision. Digest is exactly 64 lowercase hexadecimal characters. No
caller precondition is refreshed or replaced by a hidden read.

## Independent commits and context guard

Review orchestration is replay-safe and resumable, not globally atomic. Each public
canonical command commits before the next phase begins. The coordinator holds no locks,
opens no transaction and has no retries or compensation. Earlier valid authority
operations remain committed after a later failure.

Before database-backed authorization, both coordinator and composed reader inspect the
default connection: in_atomic_block OR not get_autocommit() rejects with APIException
400 retained_posting_review_transaction_context_invalid. There is no TestCase bypass.
Successful orchestration tests use TransactionTestCase; ordinary TestCase is tested as
a rejected context. This service is intentionally default-database-only.

Attach/allocation, selection and projection retain their canonical lock orders. In
particular, source locks from earlier phases are released before projection's posting
lock. Each public command reauthorizes, including its Workspace gate; initial owner
validation is never cached as authority for later phases.

## Phase contracts and continuation

Attach delegates only actor/workspace/item/posting to attach_posting_source. Same
initial target replays, different initial target conflicts. Corrected/withdrawn initial
mapping is not restored. Another item can attach to an allocated posting.

Allocation delegates unchanged to allocate_job_posting and consumes its frozen result.
No locator, binding, namespace, insertion or historical validation is duplicated.
Allocation preserves its item-scoped UUID and original interpretation witness.

Selection delegates mode=select, reviewed item, resulting posting and the caller's
operation/revision inputs. Canonical unchanged/conflict behavior propagates. Projection
binds the exact returned or replayed selection decision revision, never a newer current
revision. Caller projection revision/digest remain unchanged. Capacity, no-op, drift,
source eligibility and history rules remain owned by the projection authority.

Retry the original bundle from mapping. Completed phases replay without duplicate
provenance; selection can replay before retrying a failed projection. For a known
uncommitted phase, changed intent can use a new operation ID and revised preconditions.
For an ambiguous result, retry the exact original IDs and CAS inputs first.

An allocation originally creating P still replays P after a correction to Q. The
coordinator does not redirect later phases to Q; current mapping witnesses may reject
those phases. Work on Q and selection-only/projection-only continuation remain explicit
calls to existing canonical commands. Ownership transfer preserves original actor/time
on replay; the new owner may execute later operations while the old owner is denied.

## Results, receipts and failure classification

RetainedPostingReviewResult contains item_id, requested_mapping_action, posting_id,
posting_portable_id and a tuple of PhaseProgress. Each phase is mapping, selection or
projection; status is completed, replayed, failed_known, failed_outcome_unknown,
unattempted or unrequested. Success includes no current-state refresh.

Receipts are frozen slotted scalar data:

- MappingReceipt: action, item/posting/portable IDs, initial_source_id, original
  actor_id/created_at, replay, optional frozen allocation record.
- SelectionReceipt: decision_id/revision, posting_id, item_id,
  selected_interpretation_id, initial_source_id, mapping_revision, operation_id,
  actor_id/created_at and replay.
- ProjectionReceipt: event_id/revision, posting_id, arbitration_decision_id,
  exact arbitration_revision, operation_id, expected_descriptor_digest,
  actor_id/created_at and replay.

Detachment uses already-loaded scalar fields, never lazy relation traversal or a new
query. Allocation records are reused directly. Tests prohibit queries in all receipt
helpers on creation/replay and during later result access.

RetainedPostingReviewPhaseError is an ordinary Exception, not APIException or a frozen
exception. Its ReviewFailure context is frozen and contains item_id,
requested_mapping_action, failed_phase, failure_stage (command or receipt), immutable
phase_progress, outcome_may_be_unknown and optional DomainErrorSnapshot. Exception
chaining preserves the original exception and traceback.

DomainErrorSnapshot preserves status_code, recursive codes and structured detail.
Mappings are read-only copies, sequences become tuples and string subclasses become
plain immutable strings. No generic review_failed code replaces the original domain
error. A future API adapter must translate this internal wrapper explicitly.

A canonical APIException before successful return is failed_known. Unexpected command
exceptions are conservatively failed_outcome_unknown, including IntegrityError where
the coordinator cannot establish the rollback outcome. Never claim rollback merely
from an exception type. Successful canonical return records completed/replayed before
receipt assembly: a receipt exception retains that status, uses failure_stage=receipt,
sets outcome_may_be_unknown=False and stops later phases. The exceptional receipt may
be absent; the known completion marker remains. Requested later phases stay unattempted;
absent phases stay unrequested.

## Advisory composed reader

read_retained_posting_review_state composes item interpretation, effective mapping,
allocation provenance, observed target arbitration, the same target's projection, then
a final effective mapping read. It calls canonical readers and propagates authorization/
history failures. It persists nothing and adds no lock or outer transaction.

Frozen observations include item interpretation revision/state and membership witnesses,
initial source/target, effective mapping revision/target, original allocation, target
posting IDs, mapping-revision anchors, arbitration selection/state, projection state,
current descriptor snapshot/digest/drift and stale reasons. Nested descriptor mappings
are immutable copies. No broad can_attach/can_allocate/can_select/can_project is exposed.

consistency is always advisory. changes_detected flags initial/final mapping identity,
revision or target differences, or differing arbitration revisions in the separate
arbitration/projection observations. A false flag does not prove global consistency.
P's observations remain labeled P even when final mapping is Q. Original allocation
and current effective mapping remain separate facts. No admission promise is inferred.

## Validation

| Fresh suite | Passed |
|---|---:|
| Retained posting review orchestration | 53 |
| PostingSource regressions | 70 |
| Allocation regressions | 40 |
| Interpretation/arbitration/projection regressions | 151 |
| Application review regressions | 83 |
| Postings | 488 |
| Affected apps | 1,187 |
| Full Django | 1,205 |

All final runs: zero failures/errors/skips. Focused tests took 2.937s, postings 39.142s,
affected apps 136.534s and full Django 143.027s. Logs are external temporary artifacts
at /tmp/orchestration-{focused,mapping,allocation,authority,application,postings,affected,full}.log.
These are actual fresh orchestration-pass results, not prior allocation counts reused
as current validation.

Django check passed. Postings migration dry-run reports no changes. Global migration
dry-run exits 1 only for the known EmailAccount.provider AlterField; nothing generated.
Both new Python files pass ast.parse. Final newlines, trailing whitespace, local
Markdown links/anchors and git diff --check pass. All three untracked files were
explicitly inspected. Final scope is three modified docs and three untracked files,
empty index, unchanged HEAD/origin/live remote at the prior checkpoint, ahead/behind
0/0. No staging, commit or push. backend/db.sqlite3 and both prohibited provider
migration paths remain absent; the database is not tracked.

The exact /tmp/review_disposition_settings.py in-memory SQLite override was verified.
No real tracker database is used. The initial focused run identified two test expectation
errors (frozen sequence comparison and mapping-phase error wrapping); these were corrected
within the authorized test file. Error snapshots additionally copy DRF string subclasses
to plain strings to keep recursive snapshots immutable. No primitive or scope change.

## Limitations

Separate phase commits intentionally permit partial completion. A lost response may
require exact replay to resolve an unknown outcome. Underlying provenance records
completed decisions, not a durable grouping of phases into one UI interaction or
unattempted intent. The caller must retain its original bundle; server-side workflow
resume is deferred. Readers are advisory, not globally atomic. SQLite concurrency tests
use explicit caller retries for busy errors and do not establish PostgreSQL operational
behavior. Future transaction wrappers, routers or commit callbacks require reassessment.
Public API/frontend, correction orchestration, candidate search, semantic dedupe,
disposition, Application actions, provider cutover and cleanup remain excluded.
