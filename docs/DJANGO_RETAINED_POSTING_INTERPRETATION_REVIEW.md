# Retained Posting Interpretation Selection Authority

Historical implementation-stage evidence. The slice subsequently completed read-only
review and was committed/pushed at `d46ef1508259f0418d1d0c842678456c883f5732`
(`Implement retained posting interpretation authority`). The original validation evidence
and implementation-stage Git state below are preserved; they are not current arbitration results.

## Verified base and scope

Repository `/Users/dev/Documents/GitHub/jobtracker-hub`, branch `django-migration`.
Before editing, local HEAD, origin/django-migration and live remote matched
`ac6d13db7f52889bff12b128a153e397769fee67`, subject
`Implement PostingSource correction authority`, parent
`482bcc5f9528fb9a6e9b3e7dce1c43a7443c40b3`. Ahead/behind 0/0; clean tree/index;
backend/db.sqlite3 absent/untracked and unrelated provider migration absent.
The external `/tmp/review_disposition_settings.py` was inspected before Django work:
it imports development settings and overrides the default database with in-memory SQLite.

Authorized modified files:

- backend/postings/models.py
- backend/postings/admin.py
- backend/core/tests.py (only the read-only admin allowlist entry)
- docs/DJANGO_MIGRATION_FOUNDATIONS.md
- docs/DJANGO_MIGRATION_STATUS.md
- docs/DJANGO_POSTING_SOURCE_CORRECTION_REVIEW.md

Authorized added files:

- backend/postings/retained_interpretations.py
- backend/postings/migrations/0009_retained_posting_interpretation_decisions.py
- backend/postings/tests/test_retained_interpretations.py
- backend/postings/tests/test_retained_interpretation_migrations.py
- docs/DJANGO_RETAINED_POSTING_INTERPRETATION_REVIEW.md

Existing extraction, membership, mapping, ingestion, API/frontend, legacy, settings,
dependencies and prior migrations remain unchanged. No scope expansion is required.

## Implemented authority

RetainedPostingInterpretationDecision is an append-only item-level chain. Revision 0
is unresolved/no event; select and withdraw append contiguous positive revisions.
Selection identifies one whole retained output through its initial association and
records its membership revision. No mutable current row, timestamp ordering, descriptor
composition, posting-level winner or redundant selected-output FK is introduced.

The sole command authorizes current ownership, serializes Workspace then retained
source in an atomic transaction, validates scoped endpoints, checks item-scoped UUID
payload collision, validates history/evidence, then handles exact replay. New work checks
interpretation revision, source eligibility, membership revision/target, no-op and capacity
before appending. Actor is attribution, not replay identity; old replay preserves the
original event/actor/time and returns current interpretation state without reapplying it.

Historical witnesses reuse the existing membership resolver's through revision and
validate initial policy/mode. A valid recorded prefix must resolve to the decision's
item. Current revision changes produce stale, including away-and-back changes. Explicit
reaffirmation with the newer witness appends a new decision. Invalid history fails closed.

Extraction validation reconstructs the existing complete persisted envelope and digest
source identity, checks bounded contiguous output positions, UUIDs, snapshot, metadata,
timestamp, fields and selectors, and compares payload_digest. Unselected sibling corruption
invalidates the batch. All selected references in the captured interpretation prefix are
validated, including before withdrawal. No reparsing, evidence repair or mutation occurs.

Effective states are unresolved, withdrawn, selected and stale. Frozen result objects
separate historical selected_output from applicable_output and expose both membership
revisions, eligibility and advisory append availability. Sticky conflict permits reads and
exact replay while blocking new select/withdraw. Corruption raises existing source or
membership errors, or the narrow interpretation history/evidence errors.

Both readers acquire the short Workspace/source boundary. SQLite uses the existing
no-op Workspace update, so these are domain-state-preserving reads, not SQL-select-only.
History cursor (item, through revision, last revision), default 100/max 200 and limit+1
preserve a captured interpretation prefix. History rows expose recorded witnesses;
effective reads provide live applicability.

Mapping is independent, before and after mapping creation/remap/withdrawal/restoration.
Multiple items mapped to one posting retain separate interpretation authority. Retained
source/title/company/location/salary/employment_type values preserve null/blank and
length semantics; no URL is invented and no descriptor is projected or truncated.
All unrelated table values are checked for preservation during interpretation workflows.

## Schema and migration

Generated only postings 0009_retained_posting_interpretation_decisions. Dependencies
are postings 0008_posting_source_corrections and the swappable user model. One CreateModel
contains exactly six constraints: item/operation uniqueness, item/revision uniqueness,
positive revision, select/nonnegative-witness versus withdraw/null shape, fixed method
and fixed version. Only normal FK/unique indexes; no data operation, backfill or existing
table change. Item, association and actor are PROTECT. Ordinary insertion validates on
the supplied alias; ordinary edits/replacement saves/instance deletion reject. Admin
is read-only with no add/change/delete/actions.

The migration test snapshots every existing table's columns and rows except migration
bookkeeping at a populated 0008 checkpoint, migrates to 0009 and confirms preservation
and an empty new table; repeating the target is stable. Separate fixture preparation then
exercises current model select/withdraw insertion on the disposable non-default alias
while default cursor access is forbidden. No real tracker database is opened or migrated.

## Fresh validation

All five suites completed successfully in this implementation pass. The affected/full
runs completed before continuation; their existing final logs were inspected and reused,
not rerun. No production or test code changed during continuation.

| Suite | Passed | Failures | Errors | Skips | Seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Interpretation + migration | 50 | 0 | 0 | 0 | 3.265 |
| Neighboring retained-posting regression | 166 | 0 | 0 | 0 | 8.586 |
| Postings | 284 | 0 | 0 | 0 | 18.516 |
| Affected apps | 983 | 0 | 0 | 0 | 118.894 |
| Full Django | 1001 | 0 | 0 | 0 | 124.966 |

The first focused development run exposed a cross-workspace test fixture setup error;
that fixture was corrected before the successful runs above. PDF fixture warnings and
expected negative-path provider logs are not failures. Prior PostingSource correction
counts are historical and are not used here.

Logs: /tmp/interpretation-focused.log, /tmp/interpretation-neighbors.log,
/tmp/interpretation-postings.log, /tmp/interpretation-affected.log and
/tmp/interpretation-full.log.

All Django commands used `PYTHONPATH=/tmp:. venv/bin/python -B manage.py` from backend
with `--settings=review_disposition_settings`; tests also used `--noinput`.
Test labels were the two new interpretation modules; the ten neighboring retained
extraction/item/correction/mapping service and migration modules; postings;
applications documents email_sync core postings; then the full suite with no labels.

Continuation checks completed:

- `check`: no issues.
- `makemigrations postings --check --dry-run`: no changes.
- `makemigrations --check --dry-run --verbosity 3`: exit 1 only for the known
  email_sync.0008_alter_emailaccount_provider choice-label AlterField. No file generated.
- `showmigrations postings --plan`: graph through 0009, dependent on 0008 and user.
- `sqlmigrate postings 0009`: one new table, six approved constraints, normal integer
  type checks and three automatic FK indexes; no existing-table change.

## Historical final implementation Git state

Exactly the eleven authorized files above: six modified, five added/untracked.
All added files were explicitly inspected. Python syntax, whitespace, local Markdown
references and git diff --check pass. Index empty; no staging, commit or push.
HEAD remains `ac6d13db7f52889bff12b128a153e397769fee67` on django-migration,
matching origin/django-migration and live remote; ahead/behind 0/0.
backend/db.sqlite3 remains absent/untracked; unrelated provider migration absent.
At that point implementation awaited separately authorized read-only pre-commit review.
Review and commit/push subsequently completed at `d46ef1508259f0418d1d0c842678456c883f5732`.

## Limitations

Full-prefix validation costs grow with history; extraction validation is deduplicated
within each resolver call. Ordinary immutability and digests do not establish tamper-proof
auditing against privileged coherent rewrites. PROTECT may block endpoint/actor cascades;
purge/error translation remains separate. No descriptor projection, JobPosting allocation,
posting-level winner, parser/ingestion, membership/mapping writes, conversion/lifecycle
changes, public API, frontend or historical reconciliation are implemented.

SQLite threaded tests exercise serial outcomes and explicit caller retries after lock
refusal, including a coherent reader competing with a membership writer. They do not
establish PostgreSQL contention/deadlock behavior, production scale, storage, workers,
provider/OAuth, cutover, export/restore or fresh legacy verification.
