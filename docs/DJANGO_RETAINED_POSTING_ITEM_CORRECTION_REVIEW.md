# Append-Only Posting-Item Association Corrections + Revision-Based Effective State

Implemented and verified, **uncommitted** for final read-only review. Nothing staged;
no commit or push. No next slice started.

## Verified checkpoint

Repository `/Users/dev/Documents/GitHub/jobtracker-hub`, branch `django-migration`.
Fresh pre-edit local HEAD, origin/django-migration and live remote matched
`2090a61b1a43252a8eb93d82c87c7d90e4c40074`, subject
`Implement retained posting item identity`, parent
`c5f8e20f9db15e2cf4dc9f0e80a0929bd222fff6`. Working tree/index were clean;
backend/db.sqlite3 and unrelated provider migration were absent. Live remote was
verified with git ls-remote using authorized network escalation.

## Exact scope

Modified:

- `backend/postings/models.py`
- `backend/postings/admin.py`
- `backend/core/tests.py`
- `docs/DJANGO_MIGRATION_FOUNDATIONS.md`
- `docs/DJANGO_MIGRATION_STATUS.md`
- `docs/DJANGO_RETAINED_POSTING_ITEM_REVIEW.md`

Added:

- `backend/postings/retained_item_corrections.py`
- `backend/postings/migrations/0006_retained_posting_item_corrections.py`
- `backend/postings/tests/test_retained_item_corrections.py`
- `backend/postings/tests/test_retained_item_correction_migrations.py`
- `docs/DJANGO_RETAINED_POSTING_ITEM_CORRECTION_REVIEW.md`

Core tests change only the intentional forbidden-add model list. Existing provenance
admin registers the correction model with no add/change/delete/actions and readonly fields.

## Model and persistence authority

RetainedPostingItemCorrection has integer PK, protected initial association, required
caller-supplied operation UUID, positive BigInteger revision, associate/withdraw mode,
nullable protected target, protected actor, explicit_owner method, decision version 1
and immutable server creation time. No expected-revision column, mutable pointer,
redundant scope FK or descriptive interpretation. Exactly six constraints:

- `posting_corr_operation`: unique initial association/operation UUID.
- `posting_corr_revision`: unique initial association/revision.
- `posting_corr_positive_revision`: revision >= 1.
- `posting_corr_target`: associate/non-null or withdraw/null.
- `posting_corr_method`: explicit_owner.
- `posting_corr_version`: 1.

Ordinary save/clean uses persisted endpoints on the routed write database, validates
UUID/shape/method/version/same-source and the next contiguous revision, and rejects
no-op insertions. Existing-row mutation, replacement-instance save, reparenting and
deletion reject through the established provenance guard. No full_clean prerequisite.
Direct saves have validation and DB uniqueness, not a separate concurrency protocol.
Privileged bulk/QuerySet/raw SQL remain bypasses; this is not tamper-proof auditing.

Migration 0006 depends exactly on postings.0005 and swappable AUTH_USER_MODEL;
one CreateModel and six AddConstraint operations, no data operation/backfill.
Initial-only revision 0 is reader semantics, never a synthetic row. The historical
migration fixture uses historical models at 0005, including source/extraction/output/
item/initial assertion, snapshots all previous tables/columns/rows, migrates to 0006,
asserts only an empty correction table was added, and repeats the target stably.

## Writer, replay and ordering

No initial association returns effective item/revision None and correction fails with
initial_association_required. Initial-only state is its original target at revision 0.
Successful correction appends expected_revision+1: associate selects target, withdraw
selects null. Revision establishes ordering, regardless of timestamps.

The keyword-only correct_posting_item_association service requires a persisted current
Workspace owner; staff status confers no bypass. Validation precedes atomic Workspace
gate/ownership revalidation, scoped output lookup, derived source lock/integrity,
initial source validation and same-source target lookup. No mailbox, Application,
JobPosting or extra item/output locks. No hidden retries.

Operation UUID must be caller-supplied RFC-variant UUIDv4, UUID instance or exact
canonical string. No generated default; namespace is initial association, so another
output can independently use the same UUID. Successful UUIDs do not expire/reuse.
Replay identity binds mode, target/null, expected revision derived from stored revision
minus one, method and version. Actor is original attribution, not replay identity.
A later owner can append or replay; replay preserves original actor and timestamp.

After scoped endpoint validation the exact precedence is operation lookup → changed
valid payload conflict → chain validation → exact replay → new-operation stale check
→ source eligibility → no-op → revision capacity → atomic insert.

- Invalid UUID/revision/mode/shape: 400 invalid_posting_item_correction.
- Missing/unauthorized/foreign endpoint: non-leaking 404.
- Missing initial assertion: 409 initial_association_required.
- Changed used-UUID payload: 409 idempotency_key_reused before stale checking.
- Invalid captured chain: 409 posting_association_history_invalid.
- New operation with obsolete expected revision: 409 stale_revision.
- Invalid source/ineligible new work: existing retained_source_invalid/ineligible.
- New operation already at target/null: 409 posting_association_unchanged.
- Increment past 9223372036854775807: 409 posting_correction_revision_exhausted.

Expected revision must be an actual integer, not bool, in 0..9223372036854775807.
No-op rejection persists nothing, advances no revision and reserves no UUID. A future
intentional request should use a new UUID. Exact successful replay precedes stale,
eligibility, no-op and capacity checks. Result contains historical correction/replay
plus separately resolved current state: replaying revision 1 after revision 3 returns
the original operation and reports revision 3 without reapplying revision 1.

## Integrity, readers and compatibility

One resolver revalidates persisted initial endpoints and uses count/min/max with
positive unique revisions to establish contiguous 1..N. It validates every correction
in the captured prefix for mode/target/method/version/source consistency, then resolves
its highest revision. Gaps or old malformed targets fail closed, without repair.
Queries after aggregation stay bounded to its captured revision, even if an append
occurs between queries. Coherent privileged rewrites cannot be detected as tampering.

Owner-scoped effective reads return output, optional initial assertion, effective item,
revision None/0/N, effective decision type/reference and current source eligibility.
History is numeric, default 100/max 200, with cursor (output ID, initial association ID,
through revision, last revision). Continuations satisfy last < revision <= through;
new appends cannot enter the existing page sequence. Malformed/foreign cursors reject.
Readers do not write or invoke parsers and do not select descriptive interpretation.

Representation/digest/semantic receipt corruption blocks reads, replay and new writes.
Sticky source conflict allows reads/exact replay with source_eligible=False but blocks
all new corrections including withdrawal. Eligibility does not authorize downstream work.

The unchanged initial service still returns its historical initial target: after A→B,
initial AssociationResult.item remains A; effective reader returns B. Old A and its
UUID/initial assertion survive even with no effective outputs. No automatic deletion,
archive, merge or supersession. Membership is not lifecycle state.

## Fresh verification

All commands use isolated external review_disposition_settings (SQLite :memory:) and
disposable migration fixtures. No real database was opened or migrated. Commands:

```sh
# From repository root:
PYTHONPATH=/tmp:backend backend/venv/bin/python -B backend/manage.py test postings.tests.test_retained_item_corrections postings.tests.test_retained_item_correction_migrations --settings=review_disposition_settings --noinput
# From backend (three separate runs):
PYTHONPATH=/tmp:. venv/bin/python -B manage.py test postings --settings=review_disposition_settings --noinput
PYTHONPATH=/tmp:. venv/bin/python -B manage.py test applications documents email_sync core postings --settings=review_disposition_settings --noinput
PYTHONPATH=/tmp:. venv/bin/python -B manage.py test --settings=review_disposition_settings --noinput
```

| Run | Passed | Time |
| --- | ---: | ---: |
| Focused correction and historical migration | 33 (32 + 1) | 1.678s |
| Postings | 162 | 12.477s |
| Affected applications/documents/email_sync/core/postings | 861 | 110.282s |
| Full Django | 879 | 115.308s |

All exited 0. Logs: /tmp/posting-corrections-focused.log, -postings.log, -affected.log,
-full.log (same prefix). Documentation was completed after these application runs.
System checks pass; postings makemigrations --check --dry-run reports no changes.
Global dry-run drift exits 1 only for known EmailAccount.provider; no file generated.
Python AST, trailing whitespace, local Markdown references and git diff --check pass.

Coverage includes unresolved/initial/withdraw/restore/remap sequences; lost-response
and old-operation replay; changed mode/target/revision/method/version; UUID namespaces
and invalid values; no-op nonreservation; scoped ownership and ownership revalidation;
source corruption/sticky conflict; model immutability/persisted target validation;
FK and six DB constraints; gaps and old-target corruption; timestamp independence;
captured pagination and append between resolver queries; admin; rollback after insert;
initial replay compatibility; old-item survival; parser prohibition and unchanged
non-correction tables. Revision exhaustion uses a controlled resolver boundary seam,
not a physically materialized maximum-length chain.

Four SQLite contention cases cover same UUID/same payload, same UUID/changed payload,
different UUID/same expected revision and associate/withdraw. Explicit caller retry
converges to one revision or deterministic conflict. This does not verify PostgreSQL
locking/deadlocks or production contention.

## Documentation and exclusions

The prior item slice is now recorded as committed at 2090a61b, preserving historical
26 item/1 migration/129 postings/828 affected/846 full results, its zero-test root
invocation correction and final pre-commit review history. Foundations records the
approved correction/no-op contract; Status distinguishes this uncommitted checkpoint.

Exactly the eleven approved files; no staging, commit or push. No backend/db.sqlite3
or unrelated provider migration. Migration 0005, retained_items.py, extraction services/
contracts, parser, providers/Gmail, public APIs/serializers/frontend remain unchanged.
No PostingSource, descriptive selection, JobPosting/evidence ingestion, split/merge,
historical reconciliation, lifecycle redesign, dependencies or real-data changes.
Production-scale performance, PostgreSQL, providers, scheduling, export/restore and
operational cutover remain unvalidated. No fresh legacy-suite claim.
