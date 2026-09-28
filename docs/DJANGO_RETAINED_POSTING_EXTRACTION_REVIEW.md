# Retained Posting Extraction Provenance Foundation

Implemented for final read-only review; uncommitted. No commit/push authorization.
This is completed-extraction recording, not parser execution, source-item identity,
interpretation selection, PostingSource or JobPosting ingestion.

## Verified base and scope

Before edits, repository `/Users/dev/Documents/GitHub/jobtracker-hub`, branch
`django-migration`, HEAD/tracking/live remote all matched
`6863f277b04e1f084d6f7b2169c4a8209c65592c`, subject
`Implement JobPosting portable identity`, parent
`ab1cb0e5e37faff606b1be7c84cf83fb99f77e30`. Tree/index were clean;
`backend/db.sqlite3` was absent/untracked and no provider migration existed.
No real database was opened or migrated.

The approved twelve-file scope gained one explicitly approved test-only change:
`email_sync/tests/test_retention_migrations.py` pins its pre-retention historical
baseline to postings 0003. Selecting the new postings leaf also required retained
0006, contradicting that fixture's email_sync 0005 target and causing an invalid
mixed forward/backward plan. No historical migration or assertion was weakened.

## Models and authority

RetainedPostingExtraction has integer PK, protected retained-message FK, required
caller operation UUIDv4, finite extractor method/version, snapshot version, input
specification, server-computed digest, producer completion time and server recording
time. Unique source/operation UUID is replay identity; it is not globally unique.
Workspace derives through the source; no connection or other domain FK is added.

RetainedPostingExtractionOutput has integer PK, protected extraction FK, callable
UUIDv4 portable identity, diagnostic position and the six-field JSON observation.
Extraction/UUID and extraction/position are unique. Recorder assigns 0..n-1.
Duplicate-looking outputs remain separate; output UUIDs never establish cross-run
item continuity. Portable reference is Workspace lineage + source portable UUID +
operation UUID + output UUID, not source/output UUID alone.

Posting-local ordinary-save guards reject edits and replacement instances using
existing PKs, with existence checks routed to the write database. Instance deletion
is forbidden, including zero-output extractions. QuerySet/bulk/raw SQL remain
privileged maintenance surfaces. Source/output-parent protection blocks incidental
deletion; future approved purge must explicitly address provenance and replay state.

`retained_extractions.record_posting_extraction` is the sole atomic writer. A scoped
internal reader and privileged read-only admin inspect records; no HTTP API exists.
Admin prohibits add/change/delete, has no actions or editable inlines, and uses
escaped default JSON rendering. Existing JobPosting admin behavior is preserved.

## Finite validation and declared inputs

Pure `extraction_contract` owns constants, strict validation, canonicalization and
digest primitives. Initial extractor is `job_alert_rules` / `1`, identifying current
rules at the base commit, not a Python import path. Parser semantics change its
version; refactors do not. Transform/schema versions evolve separately and historical
contracts must remain recognizable. No parser file or production caller is changed.

Exact input specification:

```json
{
  "version": 1,
  "representation_version": 1,
  "selectors": {
    "sender": {"role": "from", "index": 0},
    "subject": "content.subject",
    "body": "content.text.value"
  },
  "transform": {"method": "retained_text_arguments", "version": "1"}
}
```

Sender role is from/sender, index is a real integer 0..99 selecting an existing entry.
Null is allowed only when neither role has entries. Declared arguments are the
selected address without display name, unchanged subject and unchanged text value,
including nulls. No implicit choice, HTML, entity decoding, concatenation, whitespace
preparation or URL extraction. The recorder resolves the declaration but never calls
the parser. Address-only preparation is this approved future producer contract;
existing sync's raw sender behavior is not silently adopted or changed.

Source representation/content versions must match at 1, the normalized retained
content shape is validated without rewriting it, and its canonical SHA-256 must
match. Workspace/mailbox/provider scope is checked. Source content/completeness is
referenced rather than copied. Partial, unavailable and truncated content remain
honest; zero results do not prove absence of job listings.

Outputs require exactly source/title/company/location/salary/employment_type.
Source is one of linkedin, handshake, lensa, indeed, honeywell, jobs2web, awseducate,
builtin, symplicity, at most 64 UTF-8 bytes. Other fields allow null or unchanged
strings including blanks, at most 4096 UTF-8 bytes each. Limits are 1000 outputs,
2048 canonical input-spec bytes and 2 MiB complete canonical replay payload. These
are defensive recording bounds, not claimed parser-output guarantees. Unknown or
missing keys, wrong types, boolean integers, NUL, invalid Unicode and non-finite
values reject without partial recording. Nothing is truncated or label-normalized.

Completion time is producer-declared RFC3339: explicit Z/±HH:MM, valid date with
seconds and at most six fractional digits, representable UTC instant. Naive values,
leap seconds, excess precision and offset overflow reject. Canonical UTC includes
six fractional digits. No relation to retention/server time is asserted.

## Replay, conflicts and transactions

Digest v1 binds resolved Workspace/source PKs, source portable UUID, representation
version/content digest, operation UUID, extractor method/version, snapshot version,
input spec, completion instant and ordered {position, fields} outputs. Sorted compact
JSON, UTF-8, ensure_ascii=False and allow_nan=False feed SHA-256. Generated output
UUIDs/new PKs and recorded_at are excluded. Object key order and equivalent timezone
representations replay; changed unequal output order, values, selector or instant
conflict. This is local replay identity, not portable business identity.

Writer authenticates/bounds input, then takes Workspace gate → scoped source lock
(`select_for_update(of=("self",))`) → integrity/selectors/digest → operation lookup.
Exact replay returns original IDs/UUIDs/timestamps before new-work conflict admission.
New work reuses canonical `require_eligible_source`, then inserts operation and all
outputs in one transaction. No later mailbox/Application/JobPosting locks or hidden
retry loop. Results contain operation, ordered outputs, replay and source_eligible.

| Condition | Result |
|---|---|
| Invalid/unsupported envelope | 400 invalid_posting_extraction |
| Unauthorized, foreign or inconsistent scope | 404 |
| Malformed/inconsistent retained representation | 409 retained_source_invalid |
| Changed valid payload under existing key | 409 idempotency_key_reused |
| New operation on conflicted source | 409 retained_source_ineligible |
| Exact replay/inspection after conflict | Original evidence; source_eligible=False |
| DB contention | Propagated; caller explicitly retries original envelope |

Errors never echo payload/content. Invalid input is validated before replay comparison,
so unsupported versions are validation errors, not valid changed-payload conflicts.
Source integrity failures do not mutate retained state. Replay is not downstream
authorization. Same source/key/payload converges after retry; competing valid payloads
have one winner and deterministic conflict. Different keys are different observations.

Producer orchestration is deferred. Future producers must select a canonical source
and exact selectors, use registered versions, generate/preserve one operation UUID,
completion instant and full ordered output envelope across response loss. Fresh UUIDs
or timestamps per retry defeat replay. This recorder cannot prove which code ran.

## Migration and historical preservation

`postings.0004_retained_posting_extraction_provenance` depends exactly on
postings 0003 and email_sync 0006. It creates two models and three unique constraints,
with ordinary FK/constraint indexes. No RunPython, backfill or existing-table change.
New tables start empty. Existing posting/account/message/dedupe/URL/discovery metadata
and retention reasons never fabricate extraction operations.

Django's initial generator also emitted known EmailAccount.provider drift. That
unrelated generated file was removed immediately, and the posting dependency was
set to the approved email_sync 0006 rather than the generated provider alteration.
No provider migration remains. All subsequent generation checks use dry-run mode.

The disposable populated migration fixture preserves every column/row of every
existing table, including accounts/credential fixtures, applications, documents/file
references, categories, legacy projections, postings/conversions, retained provenance
and reviews. Only the two empty tables appear. Repeating the target is stable.
Schema reversal after recording would discard provenance; it is not an approved
operational rollback plan.

## Initial implementation verification (before receipt-provenance correction)

All Django commands run from backend with `PYTHONPATH=/tmp:. venv/bin/python -B
manage.py ... --settings=review_disposition_settings --noinput` (omit --noinput where
unsupported). External settings import dev and replace the default DB with SQLite
`:memory:`; migration fixtures use disposable temporary databases. Logs are outside
the checkout at `/tmp/posting-provenance-*.log`.

| Verification | Result |
|---|---|
| New provenance tests | 29 passed |
| New populated migration test | 1 passed (0.912s standalone) |
| Final combined focused/migration run | 30 passed, 1.338s |
| Postings app | 98 passed, 8.720s |
| Retention/migration/review/attach regressions | 69 passed, 1.798s |
| Affected applications/documents/email_sync/core/postings | 797 passed, 104.757s |
| Full Django | 815 passed, 113.619s |
| System check | No issues |
| Posting migration/model dry-run check | No changes |
| Global migration dry-run check | Exit 1: only known EmailAccount.provider choices |
| Python AST, whitespace, Markdown local file references, git diff --check | Passed |

All suite commands exited 0 at the initial implementation checkpoint. Those combined
focused and affected/full runs included the initial production changes; the earlier standalone postings/regression runs preceded
a final retained timestamp-shape validation tightening, which the final runs cover.
No existing tests were removed. The full count increases from 785 to 815. Expected
PDF-fixture parser warnings do not indicate test failures. Global drift was only a
dry-run; no generated provider migration remains. No model drift in postings.

Initial verified inventory was exactly the thirteen authorized files above/below, with empty
index, unchanged branch/HEAD, no backend/db.sqlite3 and no provider migration.
No commit or push occurred. Static/reference checks include all new untracked files.

Tests cover bounded validation, exact and conflicting replay, loss-of-response retry,
scope/integrity/conflict admission, timestamps, byte/count/aggregate boundaries,
immutability/protection, injected rollback, SQLite concurrency with explicit retry,
escaped read-only admin, no parser execution and unchanged non-provenance tables.
Initial focused tests exposed Http404 versus internal NotFound inconsistency; the
service now returns uniform non-leaking internal 404 exceptions. The historical
retention fixture dependency issue and separately approved correction are above.

## Pre-commit receipt-provenance correction, 2026-09-28

The read-only review found that generic timestamp shape validation and a matching
content digest accepted unknown provider_received.source values and provenance for
a different provider. Digest equality establishes consistency with stored bytes,
not canonical semantic validity. The review changed no files; hashes of all thirteen
files matched when the separately authorized correction resumed. Repository, branch,
HEAD/tracking/live remote, subject/parent, empty index and DB/provider-migration absence
were reverified before correction.

Canonical policy is split between retention.source_time(received=True) and
retain_observation's mailbox check; no combined reusable pure helper exists. The
extraction validator now receives the retained provider and faithfully enforces:
Gmail → gmail_internal_date, Outlook → graph_received_datetime, IMAP → imap_internaldate,
with unknown permitted for each. Unknown source requires unknown precision and null
value; provider-specific source with unknown precision/null remains valid, as do the
canonical instant/date/uncertain cases. Empty receipt provenance rejects through the
finite vocabulary; uncertain receipt text must be nonempty, matching retention.
Existing structure/offset/version/digest/scope/conflict checks remain intact.

Correction touches extraction_contract.py, retained_extractions.py (pass actual source
provider), test_retained_extractions.py and these review/Status records only. No retention
production code, parser, schema, migration or replay-digest version/structure changes.
Invalid source semantics return 409 retained_source_invalid with no source mutation
or provenance persistence. Header timestamp rules are not broadened by this correction.

Four new database-backed tests cover unknown/empty labels with recomputed digest,
all cross-provider receipt-label mismatches (instant and unknown precision), canonical
valid receipt combinations created by the actual retention writer, and adjacent invalid
precision/value combinations. Valid cases preserve exact replay IDs/UUIDs/timestamps;
subsequent sticky conflict still allows replay/inspection and rejects new operations.
Existing malformed-digest, canonicalization and rollback tests remain in the suite.

| Correction verification | Result |
|---|---|
| Four new receipt-provenance regression tests | 4 passed, 0.170s |
| All provenance tests | 33 passed |
| Provenance migration test | 1 passed |
| Combined provenance/migration | 34 passed, 1.440s |
| Retained-source/review regressions | 69 passed, 2.203s |
| Postings suite | 102 passed, 8.159s |
| Affected apps | 801 passed, 103.609s |
| Full Django | 819 passed, 108.779s |
| System check / posting migration drift | No issues / no changes |
| Global dry-run migration drift | Only known EmailAccount.provider, exit 1; no file generated |
| AST / whitespace / local Markdown references / git diff --check | Passed |

All test runs exited 0 using the same isolated settings as above. Correction logs use
`/tmp/posting-receipt-*.log`; the four-test run and system/drift checks were also
captured in task output. Earlier 29/1/30/98/69/797/815 counts remain historical and do
not erase the finding. Final scope is the same thirteen files, with only the five
files listed in this correction changed since review. Nothing staged/committed/pushed;
HEAD remains 6863f277, local tracker DB and provider migration remain absent.

## Exact file inventory

Modified:
- `backend/postings/models.py`
- `backend/postings/admin.py`
- `backend/core/tests.py` (admin add-denial allowlist only)
- `backend/email_sync/tests/test_retention_migrations.py` (separately approved baseline pin)
- `docs/DJANGO_MIGRATION_FOUNDATIONS.md`
- `docs/DJANGO_MIGRATION_STATUS.md`
- `docs/DJANGO_POSTING_IDENTITY_REVIEW.md`

Added:
- `backend/postings/extraction_contract.py`
- `backend/postings/retained_extractions.py`
- `backend/postings/migrations/0004_retained_posting_extraction_provenance.py`
- `backend/postings/tests/test_retained_extractions.py`
- `backend/postings/tests/test_retained_extraction_migrations.py`
- `docs/DJANGO_RETAINED_POSTING_EXTRACTION_REVIEW.md`

Status/identity review now identify committed `6863f277` while preserving pre-commit
verification as historical. Foundations adds only this approved bounded contract.

## Exclusions and operational limitations

No source-item identity/allocation, cross-run continuity, selected interpretation,
PostingSource, split/merge/remapping, JobPosting writes/dedupe changes, parser execution
or changes, provider/Gmail sync, tasks/outbox/dispatch/retry envelope, frontend/API,
evidence/PDF, historical reconciliation, account decoupling or generalized purge.

SQLite/unit tests do not establish PostgreSQL locking/contention/deadlocks, production
payload performance, live provider completeness, durable scheduling, export/restore,
deployment/cutover or backup recovery. No fresh legacy-suite or operational validation
is claimed. The recorder trusts the declared execution envelope. Real tracker data,
dependencies and environments are unchanged. Leave uncommitted for read-only review
and separate commit/push approval; do not begin the next dependency.
