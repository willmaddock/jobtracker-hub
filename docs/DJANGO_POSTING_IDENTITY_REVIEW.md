# JobPosting Portable Identity Foundation

Implemented and uncommitted for final read-only review, 2026-09-27. No staging,
commit or push is authorized by this implementation checkpoint.

## Verified base

Repository `/Users/dev/Documents/GitHub/jobtracker-hub`, branch `django-migration`.
Before edits, HEAD, tracking and live remote matched
`ab1cb0e5e37faff606b1be7c84cf83fb99f77e30`, subject
`Implement retained review create application orchestration`, parent
`5e25093a62a6c908d2da8123d1d6a7323eca2cd5`. Tree/index were clean;
`backend/db.sqlite3` was absent/untracked and no provider migration existed.
No real database was inspected or migrated.

## Identity and compatibility

JobPosting keeps its ordinary integer PK and gains a non-null UUIDField with callable
`uuid.uuid4`, `editable=False`, and `unique_posting_portable_per_ws` over Workspace and
portable_id. No global UUID uniqueness contract. The existing routed ordinary-save
Workspace/account immutability guard now also rejects portable-ID changes, including
replacement instances using an existing PK. Metadata, status and saved changes remain
permitted. QuerySet/bulk/raw SQL remain privileged bypasses, as elsewhere in the project.

Workspace is the intended long-term owner. Existing Workspace/EmailAccount CASCADE
behavior is unchanged; account cascade is transitional. UUIDs do not solve account-deletion
ownership. Decoupling that ownership requires a separate approved slice.

The posting serializer adds read-only top-level portable_id immediately after integer id.
Integer routes/actions and conversion representation remain unchanged. Nested conversion
portable_id still means Application UUID. Admin displays posting UUID and excludes it
from editable add/change forms; a forged submission cannot change it.

Production ingestion, extraction, Application allocation and PostingApplicationConversion
are unchanged. The existing account-bound dedupe namespace, normalized URL equivalence,
account/message/company/title fallback, positional URL association and descriptor-overwriting
update_or_create remain transitional compatibility behavior. Dedupe keys and descriptors
are not canonical business identity. UUID survives updates to the same existing row;
adding UUIDs does not make this ingestion path canonical.

## Migration and preservation

`postings.0003_jobposting_portable_identity` depends only on
`postings.0002_posting_application_conversions`. It follows Application identity's pattern:
nullable UUID without populated default; historical-model RunPython using the schema
editor's database alias; non-null callable UUID default; Workspace/UUID unique constraint.
The helper iterates null rows and updates only portable_id with an independent UUID,
retaining the null predicate. Existing populated IDs are untouched on helper replay.

This is identity allocation only. No merge, deduplication, business-equivalence inference,
retained-source lineage or conversion backfill. Old PKs, every old posting column and all
relationships remain unchanged. Duplicate-looking historical rows remain distinct.

Reverse data uses RunPython.noop, but reversing schema removes the UUID column. This is
not identity-preserving rollback after UUIDs have been externally consumed. No production
scale is inferred; row-wise iteration follows the established migration style. Deployment
must plan/quiesce posting writes during migration; concurrent migration writes are not
validated by these tests.

## Test design

New identity tests cover default UUID/integer PK, independent allocation, mutable metadata,
status/saved preservation, UUID/ownership mutation rejection, Workspace uniqueness and
read-only serializer exposure. Posting API tests cover integer actions and distinct meanings
of top-level posting UUID versus nested Application UUID. Existing admin ownership coverage
now also checks visible/read-only identity and forged UUID submission.

Ingestion regressions exercise real update_or_create for both linkless and URL paths,
asserting PK/UUID/dedupe stability and descriptor updates. The URL test supplies controlled
parser dictionaries to prove the existing positional association remains unchanged.

The disposable populated migration fixture pins postings 0002 → 0003 with multiple
Workspaces/accounts, duplicate-looking rows, URLs/linkless rows, saved/dismissed variants,
and surviving/null conversion endpoints and request intents. It compares every old posting
column and every pre-existing table/relationship, asserts no tables/models for source
items or PostingSource appeared, tests uniqueness scope, explicitly reruns the helper,
and replays the migration target. A first test run exposed the executor's cached applied
migration state after constructing the baseline; refreshing MigrationExecutor corrected
the test harness. No production migration change was needed.

## Exact file inventory

Modified:
- `backend/postings/models.py`
- `backend/postings/serializers.py`
- `backend/postings/admin.py`
- `backend/postings/tests/test_services.py`
- `backend/postings/tests/test_views.py`
- `docs/DJANGO_MIGRATION_STATUS.md`
- `docs/DJANGO_RETAINED_REVIEW_CREATE_REVIEW.md`

Added:
- `backend/postings/migrations/0003_jobposting_portable_identity.py`
- `backend/postings/tests/test_identity.py`
- `backend/postings/tests/test_identity_migrations.py`
- `docs/DJANGO_POSTING_IDENTITY_REVIEW.md`

Status and the creation review correct only stale current checkpoint wording for ab1cb0e;
the retained-review 2/193/758/776 ledger remains historical. Foundations is unchanged.

## Verification

Commands use `PYTHONPATH=/tmp:. venv/bin/python -B manage.py` from `backend/` with
`--settings=review_disposition_settings`. The existing external settings import dev
settings and replace the database with SQLite `:memory:`; migration fixtures use disposable
temporary SQLite databases. No real tracker database is opened.

| Command suffix (same settings above) | Result |
|---|---|
| `test postings.tests.test_identity` | 5 passed, exit 0, 0.010s |
| `test postings.tests.test_identity_migrations` | 1 passed, exit 0, 0.878s |
| `test postings.tests.test_services postings.tests.test_views` | 31 passed, exit 0, 6.048s |
| `test applications.tests.test_creation applications.tests.test_identity applications.tests.test_identity_migrations` | 25 passed, exit 0, 1.235s |
| `test postings` | 68 passed, exit 0, 7.384s |
| `test applications documents email_sync core postings` | 767 passed, exit 0, 105.766s |
| `test` | 785 passed, exit 0, 108.560s |
| `check` | No issues, exit 0 |
| `makemigrations postings --check --dry-run` | No changes, exit 0 |
| `makemigrations --check --dry-run --verbosity 3` | Exit 1: only known EmailAccount.provider choices; no file generated |
| Python AST, whitespace, local Markdown references, `git diff --check` | Passed |

Nine new tests bring the previous full count of 776 to 785. Existing admin coverage
was strengthened without removing prior assertions. All final suite results above ran
against the final code/test state. The first new identity-only command ran from repository
root with equivalent `PYTHONPATH=/tmp:backend backend/venv/bin/python -B backend/manage.py`.
`backend/db.sqlite3` remains absent/untracked; no provider migration exists. Exactly the
11 listed files are changed, nothing is staged, and no commit or push occurred.

## Exclusions and operational limitations

No source-item identity, interpretation models, PostingSource, retained-source mappings,
historical inference, canonical Gmail posting ingestion, parser/URL/dedupe redesign,
split/merge/remapping, reconciliation, ownership decoupling, evidence/PDF/Documents,
frontend, provider changes, lifecycle redesign or import/export workflow.

SQLite verification does not establish PostgreSQL migration locking/concurrent writes,
deployed table size/performance, live provider behavior or cutover readiness. No fresh
legacy suite or operational validation is claimed. The next dependency is an approved
source-item/interpretation contract, then durable items, PostingSource assertions,
correction/remapping reconciliation and canonical ingestion. None is implemented here.
