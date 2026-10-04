# Posting-Level Interpretation Arbitration Authority

Historical implementation-stage evidence for the explicitly authorized eleven-file slice.
The slice subsequently completed read-only review and was committed/pushed at
`5f832dcc261d13365d851806623fca1a373e1644`
(`Implement posting-level interpretation arbitration authority`). Original test evidence
and implementation-stage Git statements below describe that earlier stage; they do not
describe the current Descriptor Projection work or grant it commit/push authorization.

## Checkpoint and scope

Repository `/Users/dev/Documents/GitHub/jobtracker-hub`, branch `django-migration`.
Verified pre-edit local HEAD, origin/django-migration and live remote:
`d46ef1508259f0418d1d0c842678456c883f5732`, subject
`Implement retained posting interpretation authority`, parent
`ac6d13db7f52889bff12b128a153e397769fee67`. Clean pre-edit tree/index, ahead/behind
0/0; backend/db.sqlite3 absent/untracked and provider migration absent. On continuation,
partial implementation was preserved and all changes remained inside the authorized scope.
The missing external settings guard caused a stop; the user separately authorized its
exact recreation. Its content was read back and verified before resuming Django commands.

Modified files:

- backend/postings/models.py
- backend/postings/admin.py
- backend/core/tests.py (only the established read-only admin allowlist entry)
- docs/DJANGO_MIGRATION_FOUNDATIONS.md
- docs/DJANGO_MIGRATION_STATUS.md
- docs/DJANGO_RETAINED_POSTING_INTERPRETATION_REVIEW.md

Added files:

- backend/postings/job_posting_interpretations.py
- backend/postings/migrations/0010_job_posting_interpretation_decisions.py
- backend/postings/tests/test_job_posting_interpretations.py
- backend/postings/tests/test_job_posting_interpretation_migrations.py
- docs/DJANGO_JOB_POSTING_INTERPRETATION_REVIEW.md

No existing mapping, item-interpretation, membership, extraction, ingestion, application,
API/frontend, legacy, settings/dependency or prior migration production file changed.

## Authority and witnesses

The append-only posting chain explicitly selects one exact retained item interpretation
and its immutable initial PostingSource plus mapping revision. Revision 0 is unresolved
regardless of candidate count. No mutable current pointer, timestamp-based authority,
ranking, automatic fallback/transfer/reactivation or descriptor projection.

Every historical selection validates its mapping prefix targeting the posting and exact
item-interpretation prefix selecting the same item. Existing interpretation validation
checks historical membership and complete extraction evidence, including sibling outputs,
without duplicating digest code or invoking a parser. Full captured posting history is
validated even after withdrawal or replacement. Per-call caches include identity and prefix.

New selections check current mapping revision before target, then exact current item
interpretation and current output membership. Stale membership requires item-level
reaffirmation, then explicit posting reselection. New mapping witnesses and newer item
interpretations are meaningful decisions. Identical witnesses and unresolved/repeated
withdrawal reject as no-ops and reserve no UUID or revision.

Effective readers preserve the historically selected evidence and separately return
applicable_output. Four states: unresolved, withdrawn, selected and stale. Stale reasons
accumulate in fixed order: mapping_revision_changed, interpretation_revision_changed,
membership_revision_changed. The historically selected output's current membership is
always checked, including after a different output or withdrawal becomes the current item
interpretation. Away-and-back changes do not reactivate authority.

Eligibility is separate from staleness. A selected conflicted source returns selected,
source_eligible=False and no applicable output. No selected source means eligibility None.
Append advisory reflects capacity only; withdrawal advisory requires latest select, eligible
source and capacity. Staleness does not itself block withdrawal. Corruption is an exception.

## Serialization, conflict and replay

Commands and both readers use one transaction: Workspace gate/owner recheck, scoped posting,
captured posting-history boundary, source discovery, ascending retained-source locks,
validation and result. Discovery includes sources through both historical interpretation
items and historical initial mapping items, plus the requested item. IDs are deduplicated
and sorted; no uncollected source locks, item/mapping/descriptor locks or hidden retries.
Discovery is not validation. SQLite's gate performs a no-op Workspace update, so readers
preserve domain state but are not SQL-SELECT-only.

Replacement checks the new candidate source's eligibility; older valid sticky-conflicted
sources do not block selecting a different eligible source. Withdrawal checks the latest
selected source and rejects sticky conflict. Validated reads and exact replay are allowed
during conflict. Corruption in required historical dependencies blocks replacement too.

Operation scope is (posting, UUID). Semantic payload includes mode, item, exact interpretation
revision, mapping revision, expected posting revision, method and version; actor is attribution.
Changed valid payload conflicts before stale checks. Source integrity and requested endpoint
resolution precede operation lookup. Missing exact endpoints return not_found; existing older
interpretations yield stale_interpretation_revision in new-work validation. Exact replay
preserves original event/actor/time and returns fresh current state without reapplying it.
Current owners may replay an earlier owner's command; former owners are denied.

History returns a frozen decisions tuple, captured through_revision and next_cursor, without
aggregate source eligibility. Cursor (posting, through, last), bounded actual integers,
default 100/max 200, ascending revision, limit+1 and entire-prefix validation exclude later
posting appends. History rows carry no live lower-layer applicability annotation.

## Schema, insertion guards and admin

Migration 0010 has only CreateModel JobPostingInterpretationDecision, depending on postings
0009 and the swappable user model. Six approved constraints enforce posting/UUID and
posting/revision uniqueness, positive revision, select/nonnegative-witness versus withdraw/
null shape, fixed method and fixed version. Normal FK and unique indexes only; no RunPython,
backfill, unrelated operation or alteration of existing tables.

Posting, selected interpretation, initial source and actor use PROTECT; withdrawal preserves
historical protection. Ordinary model insertion reloads persisted dependencies on the
supplied alias and validates contiguous revision, historical/current witnesses, scope and
actual change. Ordinary updates, replacement-PK saves and instance deletion reject. Admin
has no add/change/delete/actions; existing JobPosting descriptor admin behavior is unchanged.

The migration test snapshots every pre-existing table's columns and rows (excluding migration
bookkeeping) at representative populated 0009, applies 0010, proves preservation and an empty
new table, then repeats the target. Current select/withdraw guards run on the disposable
non-default alias while default database cursor access is forbidden. No real tracker database
is used or migrated.

## Fresh validation

Validation completed on 2026-10-03. The first three suites completed earlier in this
implementation pass; their results are preserved without reruns. The affected-app log
contained a completed successful result and was reused. Full Django and remaining checks
ran during this continuation. No production/test edits followed these results. Prior
item-level interpretation counts remain historical and are not arbitration evidence.

| Suite | Passed | Failures | Errors | Skips | Seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Arbitration + migration | 47 | 0 | 0 | 0 | 4.591 |
| Neighboring regressions | 216 | 0 | 0 | 0 | 10.204 |
| Postings | 331 | 0 | 0 | 0 | 24.316 |
| Affected apps | 1030 | 0 | 0 | 0 | 119.098 |
| Full Django | 1048 | 0 | 0 | 0 | 138.057 |

Logs: /tmp/arbitration-focused.log, /tmp/arbitration-neighbors.log,
/tmp/arbitration-postings.log, /tmp/arbitration-affected.log and /tmp/arbitration-full.log.
PDF fixture warnings and expected negative-path provider logs are not test failures.

- Django check: no issues.
- Scoped postings migration drift: no changes detected.
- Global migration dry-run with verbosity 3: exit 1 only for the known
  email_sync.0008_alter_emailaccount_provider choice-label AlterField; no file generated.
- Migration plan reaches postings.0010_job_posting_interpretation_decisions.
- sqlmigrate 0010: one new table, six approved constraints, normal integer type checks
  and four automatic FK indexes. No existing-table alteration, data/backfill or unrelated SQL.
- Python AST/syntax, trailing whitespace, final newline, local Markdown links and
  git diff --check pass across the eleven changed/untracked files.

All Django commands use `PYTHONPATH=/tmp:. venv/bin/python -B manage.py` from backend,
`--settings=review_disposition_settings`, and tests add `--noinput`. The external settings
file imports dev settings and sets default SQLite NAME to `:memory:`. Test databases are
isolated; the migration test uses a temporary disposable alias. No repository database.

Coverage includes explicit candidate authority, all stale-reason combinations, lower-layer
reaffirmation, replay and payload precedence, ownership transfer, cross-source conflict and
corruption, scope/bounded input, no-ops, four-state fields, frozen history pagination,
immutability/PROTECT/constraints, alias validation, same UUID/revision races, changed-payload
races, mapping/interpretation/membership competitors, cross-source replacement races,
sorted locks, coherent readers versus membership writes, rollback, and read-only admin.
All existing tables are snapshotted across arbitration workflows; parser invocation is
forbidden. Long retained strings, null and blank remain unchanged; no URL is synthesized.
Capacity uses a mocked validated prefix at MAX_REVISION rather than billions of fixture rows.
SQLite lock failures are explicitly retried by test callers, never by the service.

Early development runs exposed test-expectation/setup problems: replay payload/endpoint
precedence, provenance instance-delete guards preceding FK collection, and an artificial
capacity ceiling also bounding candidate IDs. The tests were corrected to exercise the
approved contracts. These early failures are not represented as successful validation.

## Documentation and final Git state

Foundations records the approved schema, witness, locking, conflict, replay/error, reader
and projection boundaries. Status records the prior authoritative checkpoint and fresh
arbitration evidence. The retained interpretation review's stage/Git statements are marked
historical and its original results are preserved.

Exactly the six modified and five untracked files listed above; all five untracked files
explicitly inspected. Index empty; no staging, commit or push. Branch remains django-migration;
HEAD, origin/django-migration and live remote remain
`d46ef1508259f0418d1d0c842678456c883f5732`, ahead/behind 0/0. Subject/parent unchanged.
backend/db.sqlite3 is absent/untracked; unrelated provider migration absent. The approved
external settings override remains intact. Implementation is complete and awaits the
separately authorized read-only pre-commit review. No repository scope/architecture deviation.

## Limitations

Full-prefix validation cost grows with history; caches are per-call only. Ordinary model
immutability and digest checks do not make coherent privileged bulk/raw rewrites detectable.
PROTECT can block endpoint/actor cascades even after withdrawal; purge and error translation
remain separate work. Descriptor projection, allocation, candidate enumeration, parser/
ingestion adoption, API/frontend and broader lifecycle changes remain deferred.

SQLite tests establish the exercised serial outcomes and explicit caller retry behavior,
not PostgreSQL locking/deadlock guarantees or production scale. No live providers/OAuth,
storage, workers, export/restore, cutover or fresh legacy validation is claimed.
