# Durable Posting Source-Item Identity + Immutable Initial Output Association

Implemented and uncommitted for final read-only review. No staging, commit or push.

## Verified base

Repository `/Users/dev/Documents/GitHub/jobtracker-hub`, branch `django-migration`.
Before edits HEAD, origin/django-migration and live refs/heads/django-migration all
matched `c5f8e20f9db15e2cf4dc9f0e80a0929bd222fff6`, subject
`Implement retained posting extraction provenance`, parent
`6863f277b04e1f084d6f7b2169c4a8209c65592c`. Working tree/index were clean.
`backend/db.sqlite3` was absent/untracked; no unrelated provider migration existed.

## Authority and models

RetainedPostingItem identifies one explicitly established occurrence within one
canonical RetainedMessage. It is not a global vacancy, parser output, JobPosting or
PostingSource. It has BigAutoField PK, source PROTECT FK, immutable callable UUIDv4
and server creation time. `posting_item_portable` is unique on source/UUID, not global
UUID. Portable reference includes Workspace lineage + retained-message portable ID +
item UUID. No descriptive fields or redundant Workspace/account/domain FKs.

RetainedPostingItemAssociation records an immutable initial assertion. Required
item/output/actor references all use PROTECT; output OneToOne is the database authority
for at most one initial assertion. No redundant uniqueness or association UUID. Checks
`posting_item_assoc_mode`, `posting_item_assoc_method`, `posting_item_assoc_version`
restrict allocate_new/attach_existing, explicit_owner and integer version 1.
Creation time is server insertion time, not source activity.

The canonical service and ordinary model save/clean validate same-source equality
using persisted endpoints. Save validation does not depend on full_clean. No FK-spanning
SQL CHECK or redundant ownership columns. Both models reject edits, replacement-instance
saves, reparenting and ordinary deletion, using the routed write DB. Privileged bulk,
QuerySet and raw SQL remain maintenance bypasses. Item insertion precedes association
inside one transaction; the domain does not expose independent orphan allocation.

An item may have many outputs across operations, including several outputs in one
operation. Outputs can remain unassigned indefinitely. Fields/URLs/order/hash similarity
never allocate or attach automatically. Reorder, label changes, disappearance and
reappearance do not change identity or delete history. Interpretation evidence stays
on the immutable extraction output; no duplicated descriptive snapshot or current choice.

## Authorization and attribution

All writers/readers require a persisted authenticated current Workspace owner, using
the existing extraction authorization helper. The Workspace gate revalidates ownership
inside writes. Staff/superuser status does not bypass this. There is no actorless/system
entry point or producer integration. The caller must deliberately assert continuity or
a distinct occurrence; this internal boundary cannot independently prove human review.

A different currently authorized owner can replay an identical decision after a
legitimate ownership change, preserving original actor and timestamps. The fixture
changes ownership solely to test that contract; no transfer workflow is implemented.
Actor PROTECT preserves attribution even after transfer; generalized purge is deferred.

## Canonical writer, replay and errors

`postings.retained_items.associate_posting_output` takes keyword-only actor, Workspace,
output_id, mode and optional item_id. allocate_new forbids a target and creates item +
first association atomically. attach_existing requires a same-source item. Method/version
are internal constants; no arbitrary caller-controlled policy or justification blob.

Output identity is the one-shot decision key, with no RequestIntent or generic request
key. Exact allocation retry returns the originally allocated item. Exact attachment
retry returns the original assertion. Mode, attach target, method and version are compared;
actor is attribution, not replay identity. Even attach-to-the-allocated-item after an
allocate decision conflicts because the mode differs.

| Condition | Outcome |
|---|---|
| Invalid mode/target combination | 400 invalid_posting_item_association |
| Missing/foreign/inconsistent endpoint or malformed ID | Non-leaking 404 |
| Different recorded decision | 409 posting_item_association_conflict |
| Source representation/digest/semantic invalidity | Existing 409 retained_source_invalid |
| New work on sticky-conflicted source | Existing 409 retained_source_ineligible |
| Exact replay after sticky conflict | Original evidence, replay=True, source_eligible=False |
| DB contention | Propagated; explicit caller retry |

Write order: bounded authentication/IDs/shape; atomic Workspace gate and ownership
revalidation; scoped output and derived source; committed scoped_source lock/integrity;
endpoint checks; prior assertion consistency and replay/conflict; new-work eligibility;
item if allocating and association insertion; commit. Integrity failure blocks even
replay. Existing helpers are reused unchanged. No mailbox, item, output, JobPosting or
Application locks, no hidden retries and no downstream effects. OneToOne uniqueness
backs the serialized writer. Failed insertion rolls back the entire allocation.

## Readers and admin

Internal readers return optional initial output association, item and current source
eligibility. Item history orders by (created_at, id), default 100/max 200, with an
item-scoped validated (timestamp string, ID) continuation tuple. Equal timestamps use
ID ordering. There is no snapshot guarantee across pages during concurrent appends.
All reads validate source scope/integrity and allow sticky-conflict history. No parser,
writes, current interpretation selection or synthesized description.

Both new models reuse privileged read-only admin: fields read-only; add/change/delete
and actions disabled; no editable inlines. Core smoke tests add exactly these two
intentionally forbidden add forms. No public API or frontend changes.

## Migration and preservation

Additive postings 0005 depends exactly on postings 0004 and the swappable user model.
The actor dependency is explicit even though accounts already exists transitively.
Two empty new tables, protected FKs, OneToOne uniqueness, item UUID uniqueness and
three finite checks; no existing-table alteration or RunPython. Migration was authored
within scope and validated by posting model-drift dry run; no provider migration was
generated. No historical items are inferred, even from existing extraction outputs.

The disposable pre-0005 fixture includes existing retained sources/reviews, legacy
projections, applications/documents/categories, postings/conversions, account fixture
credentials, and zero/one/many extraction outputs. It compares all columns/rows of
all pre-existing tables, asserts the new tables empty, and repeats the target stably.
No real tracker database is opened or migrated.

## Verification

All tests used external `review_disposition_settings` with SQLite `:memory:` and
migration fixtures used disposable temporary databases. Explicit-label runs used
`PYTHONPATH=/tmp:backend backend/venv/bin/python -B backend/manage.py test ...
--settings=review_disposition_settings --noinput` from repository root. Full discovery
used `PYTHONPATH=/tmp:. venv/bin/python -B manage.py test
--settings=review_disposition_settings --noinput` from backend. An initial root-level
full-discovery invocation discovered zero tests; it is not verification and was rerun
correctly from backend. Logs are outside the checkout at `/tmp/posting-items-*.log`.

| Verification | Result |
|---|---|
| New retained-item service tests | 26 passed, 0.399s |
| New populated migration test | 1 passed, 0.870s |
| Postings suite | 129 passed, 10.312s |
| Affected applications/documents/email_sync/core/postings | 828 passed, 106.954s |
| Full Django | 846 passed, 112.804s |
| System checks | No issues |
| Posting migration/model dry-run drift | No changes |
| Global migration dry-run drift | Only known EmailAccount.provider, exit 1; no file generated |
| AST / whitespace / Markdown local references / git diff --check | Passed |

All actual suite runs exited 0 against the final implementation/test state; only
review documentation was completed afterward. The 27 new tests increase the full
count from 819 to 846. Expected PDF fixture warnings are not test failures. No existing
tests or historical migration assertions were changed except the two approved admin
add-denial entries in core tests.

Coverage includes all replay mode/target combinations, different-owner replay retaining
original attribution, Workspace revalidation, same-source checks, malformed inputs,
finite DB checks, OneToOne/UUID namespaces, ordinary immutability, protected references,
sticky conflict, semantic receipt corruption with a recomputed matching digest,
rollback before/after association insertion, four contention cases with explicit retry,
reorder/disappearance/unresolved observations, bounded history, admin and unchanged
non-item tables. Migration coverage preserves all old tables and asserts no backfill.

Final scope is exactly eleven authorized files, with empty index and unchanged HEAD.
No backend/db.sqlite3 or provider migration exists. No commit or push occurred.

## Scope

Modified:
- `backend/postings/models.py`
- `backend/postings/admin.py`
- `backend/core/tests.py`
- `docs/DJANGO_MIGRATION_FOUNDATIONS.md`
- `docs/DJANGO_MIGRATION_STATUS.md`
- `docs/DJANGO_RETAINED_POSTING_EXTRACTION_REVIEW.md`

Added:
- `backend/postings/retained_items.py`
- `backend/postings/migrations/0005_retained_posting_items.py`
- `backend/postings/tests/test_retained_items.py`
- `backend/postings/tests/test_retained_item_migrations.py`
- `docs/DJANGO_RETAINED_POSTING_ITEM_REVIEW.md`

Documentation records extraction provenance committed at c5f8e20, preserving its
initial 815-test ledger, integrity finding, corrected 819-test ledger and review history.
Foundations records only the approved item/initial-association contract.

## Limits and deferred authority

Wrong assertions cannot be reassigned here. Preserve the initial row until explicit
correction/supersession authority exists. No active/withdrawn/current/revision flags.
No interpretation selection, split/merge, PostingSource, JobPosting mapping, parser
changes/execution, automatic continuity, ingestion, provider work, frontend/API,
Application allocation/evidence, scheduling/outbox, historical reconciliation, ownership
decoupling or generalized purge. Extraction 0004/contract/replay semantics are unchanged.

SQLite tests do not establish PostgreSQL locking/deadlock behavior, production-scale
performance, live-provider completeness, durable scheduling/retries, export/restore or
cutover readiness. No fresh legacy-suite or live operational verification is claimed.
No dependencies or real data changed. Leave unstaged/uncommitted for final review.
