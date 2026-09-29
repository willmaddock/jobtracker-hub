# Attach Existing JobPosting Only + Immutable Initial PostingSource Mapping

Implemented, unstaged and uncommitted for final read-only pre-commit review.
No commit, push or next slice. Fresh verification is recorded below.

## Verified base and exact scope

Repository `/Users/dev/Documents/GitHub/jobtracker-hub`, branch `django-migration`.
Before editing, local HEAD, origin/django-migration and live remote all matched
`8812bf8f61de1db5b622af6f61b71a5a1b68fdb3`, subject
`Implement retained posting item corrections`, parent
`2090a61b1a43252a8eb93d82c87c7d90e4c40074`. Tree/index were clean. Local DB absent/
untracked; only existing email_sync migrations 0001–0007, no unrelated provider 0008.

Modified:

- `backend/postings/models.py`
- `backend/postings/admin.py`
- `backend/core/tests.py`
- `docs/DJANGO_MIGRATION_FOUNDATIONS.md`
- `docs/DJANGO_MIGRATION_STATUS.md`
- `docs/DJANGO_RETAINED_POSTING_ITEM_CORRECTION_REVIEW.md`

Added:

- `backend/postings/posting_sources.py`
- `backend/postings/migrations/0007_posting_source_initial_mapping.py`
- `backend/postings/tests/test_posting_sources.py`
- `backend/postings/tests/test_posting_source_migrations.py`
- `docs/DJANGO_POSTING_SOURCE_REVIEW.md`

## Model, cardinality and identity

PostingSource asserts that a durable retained posting occurrence corresponds to and
supplies provenance for an existing JobPosting. It is scoped identity-mapping evidence,
not global vacancy equivalence, interpretation/descriptor authority, automatic dedupe,
allocation or canonical ingestion. An assertion is accountable, not proof of truth.

Integer PK; item OneToOne PROTECT (initial_posting_source); posting PROTECT FK
(initial_posting_sources); actor PROTECT FK (posting_source_assertions); non-editable
explicit_owner method and version 1; auto_now_add server timestamp. OneToOne item
uniqueness plus posting_source_method and posting_source_version checks enforce the
approved cardinality/policy. No redundant uniqueness, UUID, operation identity,
revision, mode, mutable state, Workspace/source/output FK or descriptive snapshot.

One item has zero/one initial mapping; one posting may have many items. No row means
unresolved. Internal future corrections can reference this immutable PK; portable
exchange must translate item lineage/portable identity and posting portable UUID,
not copy database PKs. Initial assertion never claims permanent effective authority.

Ordinary save/clean validates persisted routed-write endpoints: source/mailbox scope
and provider, posting/account scope, common Workspace, persisted actor and exact
policy (version actual int, not bool). Cached objects cannot bypass validation.
Existing provenance guard rejects edits, replacement saves, reparenting and deletion.
Current owner and source-content admission are service responsibilities, not a parallel
model-write authorization protocol. Bulk/QuerySet/raw SQL remain maintenance bypasses.

## Writer and replay

Keyword-only attach_posting_source takes actor, workspace, item_id, posting_id.
It cannot allocate a JobPosting or choose an output. Item identity is the one-shot
key: same target/policy replays; changed target/policy conflicts. Mapping ID, actor
and timestamp are preserved on replay, including by a later currently authorized
owner. Result has item, initial_source, posting, replay and source_eligible.

Order: persisted authenticated current owner → bounded IDs → atomic Workspace gate/
owner revalidation → scoped item → derived source lock/integrity → posting/account
scope → initial mapping lookup and persisted target validation → replay/conflict →
new-work source eligibility → insert. Workspace gate is canonical serialization;
there are no extra mailbox/output/Application/descriptor locks or hidden retries.
FK integrity handles endpoint deletion races; database errors are never success.

The common Workspace is item.retained_message.workspace = posting.workspace =
posting.account.workspace = authorized Workspace. Source mailbox must be consistent.
Source account need not equal posting account; no account/message heuristic maps items.
Staff/superuser alone, anonymous, unsaved actors and non-owners have no authority.

Malformed IDs (including bool/out-of-range), absent/foreign endpoints and inconsistent
stored scope yield non-leaking 404 not_found. Changed target/policy yields 409
posting_source_conflict. Existing retained_source_invalid blocks every source read,
replay and write for invalid representation/digest/semantic receipt provenance.
Sticky conflict permits reads/exact replay with source_eligible=False but rejects new
mapping with retained_source_ineligible. Changed-target conflict and replay precede
new-work eligibility; source integrity precedes both. No new HTTP endpoint/serializer.

## Membership, lifecycle and consumers

Zero effective outputs neither erase item identity nor prevent attachment. Multiple
outputs are equally compatible: no interpretation is chosen. Output remap/withdrawal
leaves the original mapping unchanged and never creates a mapping for the new item.
No stale/current/supported flag, item membership revision or evidence-set snapshot.

Normal/dismissed/saved/converted postings can be mapped. Existing restore/save/dismiss
and real Application conversion preserve the mapping. No posting Trash/archive policy
is introduced. No parser, ingestion, allocation, descriptor or Application/Document
write is caused by mapping. Tests snapshot all non-mapping tables across attach/replay/
read and prohibit parser/ingestion calls.

PROTECT blocks mapped item/posting/actor deletion, including account cascades reaching
mapped postings and potentially Workspace graph deletion. Provider disconnect retains
accounts/mappings. Current Workspace DELETE can surface unhandled ProtectedError;
error translation, account decoupling, deletion redesign and generalized purge remain
explicitly deferred. Protection was approved; references are not weakened to CASCADE.

Only internal historical inspection, tests and read-only admin consume this authority.
PostingSource correction/effective mapping must precede canonical ingestion, dedupe,
descriptor projection, allocation or automated evidence consumers. Interpretation
selection and canonical retained-source JobPosting allocation remain separate slices.

## Readers and admin

read_initial_posting_source returns item, optional initial_source/posting, eligibility
and replay=False for inspection. Attribution/time are on the mapping. No current/effective
mapping claim. list_initial_posting_sources returns entries with the same historical
meaning and current source eligibility; default 100/max 200; internal navigation errors
are 400 invalid_posting_source. List validates returned item/source/posting scope and
integrity, failing closed rather than skipping corrupt entries.

Order is mapping PK. Cursor is (posting ID, last mapping ID), both actual positive
bounded integers; the mapping must belong to the posting. Query id > last, limit+1.
This is ordinary keyset navigation, not a captured snapshot: new mappings may appear
on later pages. No aggregate effective-output/evidence-set reader is introduced.

Existing provenance admin registers PostingSource read-only: all fields readonly,
no add/change/delete/actions or inline. Core smoke test changes only its one add-denial
entry. JobPosting admin and all existing routes are unchanged.

## Migration and historical policy

postings.0007_posting_source_initial_mapping depends exactly on
postings.0006_retained_posting_item_corrections and swappable AUTH_USER_MODEL.
One CreateModel, two AddConstraint operations. No existing-table alteration, RunPython,
provider dependency or backfill. Prior migrations remain unchanged.

Historical migration test populates the explicit 0006 state using historical models,
including retained sources/extractions/outputs/items/initial associations/corrections
and existing JobPostings, along with other populated application/document/provider
fixtures. It snapshots old tables/columns/rows, verifies preservation and an empty new
table after 0007, then repeats the target. No current-model historical assertions.
No mapping is inferred from URL/dedupe/account/message/descriptor/extraction/Application
or legacy data; future explicit owner mapping can address existing rows.

## Verification

External /tmp/review_disposition_settings.py configures in-memory SQLite. Historical
migration uses a disposable temporary SQLite database. No real tracker DB was opened
or migrated. All Python application commands use -B. Commands:

```sh
# Repository root, focused:
PYTHONPATH=/tmp:backend backend/venv/bin/python -B backend/manage.py test postings.tests.test_posting_sources postings.tests.test_posting_source_migrations --settings=review_disposition_settings --noinput
# Backend directory, separate broader runs:
PYTHONPATH=/tmp:. venv/bin/python -B manage.py test postings --settings=review_disposition_settings --noinput
PYTHONPATH=/tmp:. venv/bin/python -B manage.py test applications documents email_sync core postings --settings=review_disposition_settings --noinput
PYTHONPATH=/tmp:. venv/bin/python -B manage.py test --settings=review_disposition_settings --noinput
```

Final verification against the final implementation/test state:

| Run | Passed | Time |
| --- | ---: | ---: |
| Focused (29 service/model/reader/admin/concurrency + 1 migration) | 30 | 1.551s |
| Postings | 192 | 13.949s |
| Affected applications/documents/email_sync/core/postings | 891 | 112.008s |
| Full Django | 909 | 117.394s |

All four exited 0. Logs: /tmp/posting-source-focused.log, /tmp/posting-source-postings.log,
/tmp/posting-source-affected.log and /tmp/posting-source-full.log. Documentation was
completed after application runs. System check passes; postings dry-run migration drift
is absent. Global makemigrations --check --dry-run exits 1 only for known
EmailAccount.provider (proposed 0008); no provider migration was generated. AST,
whitespace, local Markdown references and git diff --check pass. Final scope is eleven
approved files, empty index, unchanged HEAD, absent/untracked backend/db.sqlite3 and
absent provider migration. No staging/commit/push.

The initial focused run passed 29 tests; added policy-replay coverage and stronger
persisted-endpoint/actor assertions were then verified by the final focused/broader runs.

Coverage exercises persisted assertions/replay/conflict, ownership transfer/revalidation,
foreign or inconsistent/cached endpoints, no unrelated writes, membership independence,
actual API posting state transitions and Application conversion, source corruption/sticky
conflict, model/DB guards, protected endpoint/cascade deletion, all three credentialless
provider disconnect paths with Gmail network mocked, readers/keysets/admin, rollback
and historical migration preservation. Three threaded SQLite cases exercise explicit
retry convergence for same/same, same/different and different-items/same-posting.
No PostgreSQL locking/deadlock or live provider verification is claimed.

## Documentation and limitations

Status and prior correction review record committed 8812bf8 while preserving 33 focused,
162 postings, 861 affected and 879 full historical results and final review evidence.
Foundations records only the approved initial mapping contract. This slice is uncommitted.

No item/correction/extraction service, parser, ingestion, provider, API/serializer/frontend,
account-view or deletion-API change. No dependencies or real data changed. Production
scale, PostgreSQL, live providers, portable export/import and operational cutover remain
unvalidated. No fresh legacy-suite claim. Account decoupling, mapping corrections,
interpretation, allocation, evidence aggregation and generalized purge remain deferred.
