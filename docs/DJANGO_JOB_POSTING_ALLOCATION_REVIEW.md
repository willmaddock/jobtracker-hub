# Canonical JobPosting Allocation / Creation Provenance

Implementation-stage evidence, 2026-10-04. This sixteen-file slice remains unstaged,
uncommitted and unpushed. Separate read-only review and commit/push authorization
are required. Preceding authoritative checkpoint is
`8ba7bc869787f80b217c0c066f9c713a337a5669`, subject
`Implement descriptor projection authority`, parent
`5f832dcc261d13365d851806623fca1a373e1644`, branch `django-migration`.

## Contract and implementation

`allocate_job_posting(actor, workspace, item_id, operation_id,
expected_interpretation_revision)` is an explicit owner-only, item-local one-shot
creation command. It atomically inserts a new JobPosting, its initial PostingSource,
and JobPostingAllocation. It never parses, fetches providers, creates Applications,
automatically arbitrates/projects, discovers semantic duplicates or attaches existing.

JobPostingAllocation has BigAuto PK; protected OneToOne posting (`allocation`), item
and initial_source (`job_posting_allocation`); protected interpretation_decision,
account_binding and actor FKs (`job_posting_allocations`); caller UUIDv4 operation_id
without default; fixed Char32 explicit_owner method; fixed positive small version 1;
auto created_at. OneToOne uniqueness is sufficient; UUID is nonunique and item-scoped.
Checks are job_post_alloc_method and job_post_alloc_version. No revision, snapshot,
withdrawal, duplicate portable identity or mutable pointer. Runtime ordinary saves,
replacement inserts and instance deletion reject. Private validated base insertion
is confined to the canonical atomic operation; bulk/raw maintenance remains a bypass.

New work requires current selected/applicable item interpretation, current membership
witness, complete valid extraction evidence, eligible source, no earlier allocation,
and no initial PostingSource ever (including withdrawn/remapped history). It derives
account from the source mailbox's current AccountMailboxBinding; workspace/provider
must agree throughout. Missing binding fails; disconnected/blocked status is allowed.
No credentials are inspected. Binding PROTECT preserves allocation-time routing only,
not historical fetch identity. Account deletion can consequently be blocked; credential
disconnect remains allowed. Purge and unbound-source allocation remain separate.

The posting receives a generated portable UUID and reserved key
`retained-allocation:v1:<item database PK>` (maximum 42 characters). Six descriptors,
URL and optional email metadata start null; status/new and saved/False use defaults.
message_id is the exact retained locator_value. Persisted locator tuple is revalidated:
gmail_message_id / graph_immutable_id / imap_uid, valid nonempty Unicode without NUL,
512 UTF-8 bytes, provider folder/stability and IMAP UID/UIDVALIDITY bounds. Every valid
locator fits the destination's 512-character capacity; never truncate/hash/coerce.
The value is convenience metadata, not a complete provider-fetch/thread identity.

Ordinary creation/mutation into the reserved prefix raises
job_posting_allocation_namespace_reserved, except an allocated row retaining its key.
Existence of any allocation protects dedupe changes with
job_posting_allocation_identity_owned, even if history is malformed. Preserve effective
update_fields/deferred/explicit-empty semantics, identity checks and projection guards.
Key-writing existing saves serialize Workspace then posting. Descriptor ownership
still begins only at first projection; manual/admin edits before then remain allowed.
Ingestion preserves six descriptors if either allocation or projection exists, using
existence only; URL/email metadata behavior is unchanged. Its SHA keys remain separate:
similar real-world jobs may become distinct postings. No cross-pipeline semantic merge.

Order: authorization/bounded input -> atomic Workspace gate -> scoped item -> optional
existing posting lock -> source lock -> allocation lookup/history validation/replay ->
reject initial mapping -> interpretation revision/applicability -> source eligibility
-> locator -> account binding -> global reserved-key collision -> posting insert ->
shared private initial mapping insert -> allocation insert -> persisted verification.
Never lock an existing posting after source. No item locks or hidden retries. Unique
constraints backstop the workspace/source serialization. Unsupported bypass-writer
IntegrityError rolls back the entire transaction; no querying a broken transaction.

Replay validates historical integrity first, then different UUID is already-allocated;
same UUID/different valid interpretation revision is idempotency_key_reused; exact
match returns identical immutable facts without writes. Same UUID on different items
is permitted. Current owner may replay while original actor/time remain. Later source
conflict, interpretation change, mapping correction or disconnect do not invalidate
historical admission. Historical validation resolves exact interpretation prefix,
membership/extraction evidence, locator, initial mapping and binding/account scope;
checks policy/UUID/actor/key; it does not require current descriptors or applicability.
Coherent privileged history rewrites are not cryptographically detectable.

Readers by posting and item return frozen detached scalar records, allocation=None
for existing authorized endpoints without provenance, NotFound for foreign/missing
endpoints. No pagination or current mapping state. Remap leaves original posting and
allocation intact, can leave an orphan and never allows reallocation for that item.
Arbitration starts unresolved at revision 0 and projection history remains empty;
existing explicit arbitration then projection works unchanged.

Errors: 400 invalid_job_posting_allocation; scoped 404; 409
job_posting_allocation_history_invalid, job_posting_already_allocated,
retained_item_initial_mapping_exists, stale_interpretation_revision,
posting_interpretation_not_applicable, job_posting_allocation_account_unavailable,
job_posting_allocation_key_conflict; reuse idempotency_key_reused and retained evidence/
eligibility errors. Key collision reveals no conflicting posting/workspace identity.
Migration 0012 creates only the empty allocation table; depends on postings 0011,
email_sync 0007 and swappable user. No backfill or existing schema alteration.
Commands use default-DB authority helpers; historical validators honor explicit alias.
Public API/frontend, cutover, URL enrichment, widening, cleanup/purge and PostgreSQL
operational validation are excluded.

## Scope

Modified: backend/postings/models.py, admin.py, posting_sources.py, services.py,
tests/test_services.py; backend/core/tests.py;
backend/email_sync/tests/test_gmail_identity_migrations.py; docs/DJANGO_MIGRATION_FOUNDATIONS.md,
DJANGO_MIGRATION_STATUS.md, DJANGO_JOB_POSTING_PROJECTION_REVIEW.md and
DJANGO_GMAIL_IDENTITY_REVIEW.md.

Added: backend/postings/job_posting_allocations.py,
migrations/0012_job_posting_allocations.py, tests/test_job_posting_allocations.py,
tests/test_job_posting_allocation_migrations.py and this review.

## Validation

| Suite | Passed |
|---|---:|
| Allocation + migration | 40 |
| Gmail identity migration | 1 |
| PostingSource regressions | 70 |
| Retained interpretation | 49 |
| Posting arbitration | 46 |
| Descriptor projection | 57 |
| Services / ingestion | 19 |
| Postings | 435 |
| Affected apps | 1,134 |
| Full Django | 1,152 |

All final runs had zero failures, errors or skips. The seven previously passing
allocation/regression suites were retained from this implementation pass; only the
focused Gmail migration test, affected apps and full Django ran after the test-only
baseline correction. Affected apps completed in 138.147s; full Django in 147.837s.
The earlier interrupted affected-app result (1,133 tests, one graph error) is
superseded by the successful 1,134-test result, which also includes the additional
malformed unprojected allocation ingestion regression.

Django check passed. Postings migration dry-run reports no changes. Global dry-run
exits 1 only for the known EmailAccount.provider AlterField; nothing was generated.
Migration graph reaches postings 0012 through email_sync 0007 and postings 0011.
SQL inspection confirms one new table, three OneToOne UNIQUE references, protected
relationships at the ORM layer, two named policy checks, the positive-small-integer
check and three FK indexes; no existing-table alteration or data backfill.

All changed Python files parse with ast.parse. Final-newline, trailing-whitespace,
local Markdown link/anchor and git diff --check validations passed. All five
untracked files were explicitly inspected. Git scope is exactly eleven modified
and five untracked files, nothing staged; no commit or push. HEAD/origin/live remote
remain at the preceding checkpoint, ahead/behind 0/0. backend/db.sqlite3 is absent
and untracked; both accidental and unrelated provider migration paths are absent.

Tests use the exactly verified `/tmp/review_disposition_settings.py` in-memory SQLite
settings and `python -B manage.py`; no real tracker database is used.

## Deviation and authorized repair

An unintended email_sync provider migration was generated during migration creation.
Implementation stopped immediately; explicit repair authorization was obtained. Only
that accidental `0008_job_posting_allocations.py` was deleted, and postings 0012 was
corrected to depend on email_sync 0007. No provider migration is retained. No database
migration was applied to real data. A service write initially failed from an incorrect
relative path; it created no file and was subsequently performed at the authorized path.
An initial test invocation used the wrong directory and did not run; later commands use
backend as their working directory.

The first affected-app validation stopped with one InvalidMigrationPlan in the existing
Gmail identity historical fixture. Postings 0012 validly depends on email_sync 0007,
but that fixture paired email_sync 0006 with automatically selected latest postings.
Implementation stopped at the scope boundary. Explicit authorization added the
sixteenth file, test_gmail_identity_migrations.py: the historical baseline now pairs
email_sync 0006 with postings 0011, while the forward target remains current leaves.
All existing assertions are preserved. This was a historical test-graph incompatibility,
not a production defect; the correction changes no production or migration behavior.

## Limitations

SQLite concurrency tests use explicit caller retries after busy errors; these are not
production retries or PostgreSQL operational validation. Historical validation cannot
detect coherent privileged raw rewrites. One-shot PROTECT relationships can block
account/posting/workspace/user deletion. Separate ingestion keys permit semantic
duplicates. Orphan lifecycle, unbound allocation, provider cutover, metadata/URL
enrichment, public endpoints, frontend and historical reconciliation remain excluded.
