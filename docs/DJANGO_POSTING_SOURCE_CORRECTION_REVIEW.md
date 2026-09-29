# PostingSource Correction / Effective-Mapping Authority

Historical implementation/pre-commit evidence follows. This slice was subsequently
reviewed, committed and pushed at `ac6d13db7f52889bff12b128a153e397769fee67`
(`Implement PostingSource correction authority`), parent
`482bcc5f9528fb9a6e9b3e7dce1c43a7443c40b3`. The original test evidence below is
preserved; it is not fresh validation of later slices.

## Verified base

Repository `/Users/dev/Documents/GitHub/jobtracker-hub`, branch `django-migration`.
Before editing, HEAD, origin/django-migration and live remote all matched
`482bcc5f9528fb9a6e9b3e7dce1c43a7443c40b3`, subject
`Implement initial PostingSource mapping`, parent
`8812bf8f61de1db5b622af6f61b71a5a1b68fdb3`. Ahead/behind 0/0; clean tree/index;
backend/db.sqlite3 absent/untracked and unrelated provider migration absent.
The existing external `/tmp/review_disposition_settings.py` was inspected and
confirmed to override DATABASES with in-memory SQLite before application commands.

## Bounded implementation

Modified models.py and admin.py, plus the separately authorized single read-only
allowlist entry in backend/core/tests.py; added posting_source_corrections.py, postings
0008_posting_source_corrections, and two focused correction/migration test modules.
Approved documentation: Foundations, Status, historical PostingSource review and
this review. Initial mapping/item/correction/extraction services, prior migrations,
parser/ingestion, API/frontend, provider, lifecycle and dependency/settings surfaces
remain unchanged.

PostingSourceCorrection inherits ordinary insert-only provenance guards. It anchors
one initial PostingSource with PROTECT, has caller UUIDv4 operation identity,
contiguous positive revision, associate/withdraw, nullable protected existing posting,
protected actor, fixed explicit_owner/version 1, and creation time. Generated 0008
contains one CreateModel with six approved constraints in its options; dependencies
are postings 0007 and swappable user. No data operation, backfill or prior schema change.

The initial assertion is revision 0. The new sole internal command serializes
Workspace -> retained source, validates source and persisted initial/target scope,
checks operation payload collision, validates the chain, then handles exact replay.
New work checks expected revision, eligibility, no-op and capacity before one append.
Replay returns the original event plus current state; actor/time are unchanged and
old events never reapply. No hidden retries or endpoint locks.

The alias-aware resolver captures a revision prefix and validates contiguity,
policy/shape and all historical posting/account scopes. Model insertion uses its
supplied write alias, tested against a real disposable non-default connection while
default cursor access is forbidden. Ordinary model guards are not raw/bulk/QuerySet
tamper resistance.

Effective reader distinguishes unresolved, initial-only, associated and withdrawn
states, and returns decision reference, revision, eligibility and advisory append
availability. History uses default 100/max 200 and cursor (item, initial source,
through revision, last revision). Later appends do not enter the captured prefix;
eligibility is current. Initial readers retain their historical meanings.

Sticky conflict permits reads/replay but blocks new withdrawal/remap. Source content
corruption and invalid chains fail closed. Existing posting lifecycle flags and
conversion do not block mapping. Zero-output items remain mapped and membership
corrections do not create mapping events. No descriptors, postings or conversions are
mutated/allocated. Historical PROTECT remains after withdrawal/remap.

## Final verification

All application commands used `-B` and the inspected external in-memory settings.
Migration fixtures use disposable SQLite files/aliases; no real tracker database was
opened or migrated. Run from backend (the focused/postings runs earlier in this same
implementation used equivalent repository-root paths where applicable):

```sh
PYTHONPATH=/tmp:. venv/bin/python -B manage.py test postings.tests.test_posting_source_corrections postings.tests.test_posting_source_correction_migrations postings.tests.test_posting_sources postings.tests.test_posting_source_migrations postings.tests.test_retained_item_corrections postings.tests.test_retained_item_correction_migrations --settings=review_disposition_settings --noinput
PYTHONPATH=/tmp:. venv/bin/python -B manage.py test postings --settings=review_disposition_settings --noinput
PYTHONPATH=/tmp:. venv/bin/python -B manage.py test applications documents email_sync core postings --settings=review_disposition_settings --noinput
PYTHONPATH=/tmp:. venv/bin/python -B manage.py test --settings=review_disposition_settings --noinput
PYTHONPATH=/tmp:. venv/bin/python -B manage.py check --settings=review_disposition_settings
PYTHONPATH=/tmp:. venv/bin/python -B manage.py makemigrations postings --check --dry-run --settings=review_disposition_settings
PYTHONPATH=/tmp:. venv/bin/python -B manage.py makemigrations --check --dry-run --verbosity 3 --settings=review_disposition_settings
PYTHONPATH=/tmp:. venv/bin/python -B manage.py showmigrations postings --plan --settings=review_disposition_settings
PYTHONPATH=/tmp:. venv/bin/python -B manage.py sqlmigrate postings 0008 --settings=review_disposition_settings
```

| Final run | Passed | Failures | Errors | Skips | Seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Six focused modules | 105 | 0 | 0 | 0 | 5.338 |
| Postings | 234 | 0 | 0 | 0 | 15.194 |
| Affected apps | 933 | 0 | 0 | 0 | 111.575 |
| Full Django | 951 | 0 | 0 | 0 | 120.240 |

These are fresh results from this implementation, not historical checkpoint counts.
Focused/postings preceded the sole subsequent code edit: adding
postings.PostingSourceCorrection to the existing core admin smoke-test read-only
allowlist. The prior affected run had 933 tests with one expectation failure (114.307s),
because that allowlist expected 200 instead of the intentional 403. User explicitly
authorized the one-line test-only extension; affected/full then passed. No production
admin behavior changed. Initial focused run passed 104 before final coverage additions.

Logs: /tmp/posting-source-correction-focused.log,
/tmp/posting-source-correction-postings.log,
/tmp/posting-source-correction-affected-final.log and
/tmp/posting-source-correction-full.log. The earlier failing affected run remains at
/tmp/posting-source-correction-affected.log.

SQLite concurrency tests explicitly retry from callers after threaded attempts;
no service retry loop. PDF fixture parser warnings are not test failures.
Django system check passes; postings dry run has no changes. Global dry run exits 1
only for the known proposed email_sync.0008_alter_emailaccount_provider choice-label
AlterField. No provider migration was generated or fixed. Graph ends at postings 0008;
SQL contains only the correction table, approved constraints, normal type checks and
three automatic FK indexes. No application of migrations to real data occurred.

## Historical pre-commit scope and Git state

Modified:
- backend/postings/models.py
- backend/postings/admin.py
- backend/core/tests.py (one explicitly authorized allowlist entry)
- docs/DJANGO_MIGRATION_FOUNDATIONS.md
- docs/DJANGO_MIGRATION_STATUS.md
- docs/DJANGO_POSTING_SOURCE_REVIEW.md

Added, untracked:
- backend/postings/posting_source_corrections.py
- backend/postings/migrations/0008_posting_source_corrections.py
- backend/postings/tests/test_posting_source_corrections.py
- backend/postings/tests/test_posting_source_correction_migrations.py
- docs/DJANGO_POSTING_SOURCE_CORRECTION_REVIEW.md

At that implementation checkpoint: exactly eleven authorized files; index empty,
HEAD unchanged at `482bcc5f`.
All added files were explicitly inspected; Python syntax, whitespace, local Markdown
references and git diff --check pass. backend/db.sqlite3 remains absent/untracked;
unrelated provider migration absent. No staging, commit or push had occurred at
that point; the implementation then awaited separate read-only review. Those historical stages subsequently completed
at the authoritative commit recorded above.

## Limitations

No PostgreSQL contention/deadlock, production scale, provider/OAuth, worker, cutover,
portable export/import, reconciliation or fresh legacy verification is claimed.
Workspace/account deletion may be blocked by protected historical references; error
translation/purge redesign remains separate. No interpretation selection, allocation,
downstream API/frontend consumer or ownership-transfer workflow is added.
