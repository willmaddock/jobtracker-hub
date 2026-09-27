# Retained Review Create Application Orchestration

Bounded implementation for review, 2026-09-26. Uncommitted; no staging, commit or push.

## Checkpoint

Verified repository `/Users/dev/Documents/GitHub/jobtracker-hub`, branch
`django-migration`, clean tree, local HEAD/tracking/live remote
`5e25093a62a6c908d2da8123d1d6a7323eca2cd5`, subject
`Implement retained review disposition`, parent
`4d545820f62d92c76cf4da189706f17b3832949f`. Live remote verification used authorized
network escalation. `backend/db.sqlite3` was absent and untracked before edits.
No checkout, reset, stash, merge, rebase, dependency or real-data changes.

## Authority and atomic composition

`applications.creation.create_attempt()` remains the sole Application allocator and
request-key/digest/challenge/completion authority. Its internal transaction executor
now returns a small immutable outcome; the public wrapper constructs the DRF response
after the executor exits. Existing manual/posting payloads, digests, warning fingerprints,
status codes, replay and Category helper behavior are preserved. A regression test
reconstructs the old digest/challenge formulas and checks confirmation/replay.

The new review source kind is `review_create`. Inside one atomic transaction:

1. Acquire Workspace; reject continuations with no existing actor/Workspace/key intent; get/validate the actor/Workspace/key intent and semantic digest.
2. Validate scoped review/source/observation references. Completed requests resolve the
   durable result immediately, before mutable new-work admission.
3. Admit active review, unconflicted source and optional scoped immutable candidate.
4. Lock optional Category, Applications ordered by PK, and Overrides ordered by Application.
5. Compute existing duplicates plus distinct review-created result/source-link context;
   validate or issue the existing creation challenge.
6. Allocate Application and initial membership/derivation/explicit status records.
7. Delegate to `attach_message()`; insert immutable `RetainedReviewCreationResult`.
8. Complete RequestIntent, clear challenge, construct success data, and commit.

No Review/Candidate/source row lock precedes Applications. Canonical attachment reacquires
the already-held Workspace gate, locks the new Application then RetainedMessage. The
outer gate remains held through final completion. New source admission and final attachment
share `require_eligible_source()`; no competing source policy or additional observation
content requirement was added. There is no second relationship writer, general callback,
public deferred-completion allocator, process mutex or automatic retry loop.

All failures after allocation propagate through the transaction. No ordinary returned
error can commit partial Application/link/result effects. Pending confirmation legitimately
commits only intent/challenge bookkeeping. A fresh key carrying a continuation is
rejected with `invalid_challenge` under the Workspace gate before intent insertion.
Invalid/expired/stale continuations against an existing pending intent preserve its
previously committed challenge state. Issued pending confirmation is the only legitimate
durable incomplete intent state. Existing-key digest mismatch still precedes challenge
evaluation, and completed replay remains unchanged. Arbitrary IntegrityError is not
translated to a duplicate warning. Response loss after commit requires the same key and
returns the original effect, not compensating deletion or reallocation.

## Model and migration

`RetainedReviewCreationResult` inherits insert-only ReviewProvenance, not RetainedLifecycle:

- ordinary BigAutoField ID;
- protected required review FK, reverse `creation_results`;
- protected required RequestIntent OneToOne, reverse `review_creation_result`;
- protected optional candidate FK;
- protected required ApplicationMessage OneToOne, reverse `review_creation_result`;
- `created_at` insertion timestamp, not exact commit time;
- noneditable `snapshot_version=1`, enforced by a database check;
- required noneditable `input_snapshot` JSON.

No redundant Application/source/Workspace FK, portable UUID, disposition, or handled state.
Review may have many results. Unique request intent and relationship prevent duplicate
claims. Model/service guards validate same-Workspace endpoints, candidate membership,
source agreement, intent kind/result identity and semantic snapshot shape. Intent result
identity is populated in memory before result insertion; persisted completion occurs last.
Cross-row completion consistency is transactional, not a database check/trigger.

Ordinary updates/reparenting/deletion reject. Admin is inspection-only with no mutation
or bulk-delete actions. As with existing provenance, privileged bulk/QuerySet/raw SQL is
not protected by model instance guards. Missing/inconsistent completed result returns
500 `creation_result_inconsistent`, never repair/recreation. Cross-scope references reject.

`applications.0010_retained_review_creation_result` depends on
`applications.0009_retained_application_review_disposition` and
`core.0004_applicationrequestintent_category`. One additive CreateModel, no RunPython,
backfill, historical intent relabeling or source/candidate fabrication. RequestIntent schema
is unchanged. Protected references block unsupported deletion; future purge/export must
explicitly compact terminal identities and remove descriptive snapshots, outside this slice.

## API, snapshot and replay

`POST /api/workspaces/{workspace_id}/application-reviews/{pk}/create-application/`
(with existing `.json` suffix support) requires normal authentication/CSRF and the
existing 16–128-character opaque `Idempotency-Key`.

Strict JSON object fields:

- `company`: required trimmed nonblank string, maximum 255;
- `role_label`: optional trimmed string, blank allowed, maximum 255;
- `status`: optional blank or supported Application status;
- `category_id`, `candidate_id`: optional null or genuine positive signed-64-bit integer;
- `challenge`: optional nonempty ASCII string, maximum 64, following existing rules.

Reject unknown fields, bool/float/string IDs, non-string labels, caller section, identities,
Workspace/source IDs, timestamps, disposition revision and derived input. New serializer
strictness does not change manual/posting serializers. Section is always `applications`.
Omitted/null Category creates no membership; scoped archived Category is allowed, trashed
Category rejects. Category section cannot change Application section.

Snapshot version 1 retains exactly the explicitly supplied validated semantic fields:
company, role_label, status, category_id, candidate_id. Omission/blank/null remain distinct.
No challenge, key, headers, credentials, source content, labels copied from candidates,
fixed section or execution defaults are stored. New digest binds version 1, `review_create`,
Workspace, review and these fields; actor is bound by existing intent uniqueness. Mutable
state and challenge tokens are excluded. Existing manual/posting digests remain unchanged.

Success is 201; exact completed replay is 200. Both contain result id, review_id,
workspace_id, candidate_id, stable created_at/snapshot_version/input_snapshot, current
Application representation, canonical ApplicationMessage representation and current
review disposition. No key/digest/challenge secret is exposed in successful results.
Completed replay never allocates, attaches or inserts a result, including after dismissal,
source conflict, Application Trash/Restore or unrelated candidate-label changes.

Review detail adds `creation_results: {results, next_after}` using ascending IDs, 50 rows
and 51-row lookahead. `creation_results_after` uses existing cursor validation semantics.
List remains inclusive/lightweight and has no new filtering. Existing relationship and
candidate representations remain distinct from creation results and disposition.

## Confirmation, state and errors

A fresh key cannot bypass confirmation when ordinary company/role duplicates, prior
review-created results or source ApplicationMessage relationships exist. Response keeps
`candidates` separate from `prior_creation_results` and `source_relationships`, alongside
existing challenge/expiry/code. Successful continuation creates a new Application, never
merges/reuses an attached target. Prior creation results necessarily have their protected
source link; both facts are still represented and fingerprinted independently.

Fingerprint includes existing duplicate/posting/category context plus review identity,
request digest, current disposition revision, sorted result/link identities and all
Application labels/lifecycle data displayed for those signals. Dismiss/restore cycles,
relevant result/link/duplicate/category changes stale old confirmation. Unrelated candidate
labels are not bound or copied. Pending requests renew by resubmitting without challenge.

New work rejects dismissal (409 review_dismissed), conflict (409 retained_source_ineligible),
trashed Category (409 resource_trashed), scoped corruption/inaccessibility (404), invalid
input (400), and key/challenge conflicts using existing creation codes. Authentication and
CSRF retain 401/403. The new APIView explicitly opts into CreationContentionMixin, including
initial Workspace lookup: SQLite lock refusal is 503 creation_busy, not lifecycle_busy.

Creation never changes disposition. Application Trash/Restore and review dismiss/restore
preserve results independently. Without eligible Documents or explicit manual status,
status remains unknown with no manufactured activity/application date. Explicit status
uses existing Override/history/derivation with history source `review_create`.

## Files and bounded adjustment

Modified:

- `backend/applications/creation.py`
- `backend/applications/message_relationships.py`
- `backend/applications/models.py`
- `backend/applications/serializers.py`
- `backend/applications/review_views.py`
- `backend/applications/urls.py`
- `backend/applications/admin.py`
- `backend/applications/tests/test_creation.py`
- `backend/applications/tests/test_review_disposition_migrations.py`
- `backend/core/tests.py`
- `docs/DJANGO_MIGRATION_FOUNDATIONS.md`
- `docs/DJANGO_MIGRATION_STATUS.md`
- `docs/DJANGO_RETAINED_REVIEW_DISPOSITION_REVIEW.md`

Added:

- `backend/applications/review_creation.py`
- `backend/applications/migrations/0010_retained_review_creation_result.py`
- `backend/applications/tests/test_review_create.py`
- `backend/applications/tests/test_review_create_migrations.py`
- `docs/DJANGO_RETAINED_REVIEW_CREATE_REVIEW.md` (this report).

The one additional related file beyond the approximate authorization list is the historical
disposition migration test. Its old target used latest migration leaves but asserted a
one-migration plan containing only 0009. Adding 0010 exposed that stale test target in the
broader focused run. The test is now explicitly pinned to 0009, preserving its exact
migration-plan and all historical preservation assertions. The new migration test is
likewise pinned to 0010. This adjustment was disclosed during implementation; no production
behavior was changed to accommodate it.

Only the disposition report's stale checkpoint wording is corrected; its original
pre-commit/recovery/test evidence remains historical. Status separates prior verification
from the new slice; Foundations contains the approved durable contract.

## Verification

All Django commands run from `backend/`, prefixed `PYTHONPATH=/tmp:.` and using
`--settings=review_disposition_settings`. The existing external settings file imports
`config.settings.dev` and selects SQLite `:memory:`. Migration tests use disposable
SQLite fixture files. No real development database is opened.

New coverage includes strict API/service admission, input snapshots, model/admin integrity,
immutable and removed/trashed candidate provenance, repeated attempts, challenge invalidation,
current-state replay, bounded detail history, and all-other-table negative-scope snapshots.
Seven injected failure seams call real writes before raising where applicable, covering
allocation through intent completion and pre-commit outcome construction, both fresh and
pending intents. A separate TransactionTestCase fails response construction after commit
and replays the completed result.

Separate-connection tests exercise same/different-key races, both dismiss/create winners,
both attach/create winners, competing same/different-intent confirmations and renewal versus
old token. Ordered service calls instrument but execute the real gate; API admission busy
mapping is separately tested. SQLite can refuse a contender; deliberate retry verifies the
post-winner state. No PostgreSQL waiting/deadlock/isolation claim follows from these tests.

The new populated migration fixture preserves all pre-existing tables/columns, including
reviews/candidates/dispositions/relationships/Applications and old request intents. It
fabricates zero results; explicit post-upgrade test inserts verify separate intent/link
uniqueness and snapshot-version constraints. Forward replay preserves fixture state.

The first broader focused run exposed only the historical disposition test's moving
latest-leaf target; pinning its intended target fixed that test without weakening its
assertions. A repeated run started before the correction was loaded reported the same
failure. Final focused, affected and full Django runs below completed successfully.

Focused command (with the prefix/settings above):

```text
venv/bin/python manage.py test applications.tests.test_review_create applications.tests.test_review_create_migrations applications.tests.test_creation applications.tests.test_identity applications.tests.test_identity_migrations applications.tests.test_derivation applications.tests.test_derivation_migrations applications.tests.test_messages applications.tests.test_message_migrations applications.tests.test_retained_reviews applications.tests.test_review_migrations applications.tests.test_review_attach applications.tests.test_review_disposition applications.tests.test_review_disposition_migrations documents.tests.test_categories documents.tests.test_category_membership documents.tests.test_category_migrations core.tests_lifecycle core.tests
```

| Verification | Result |
|---|---|
| Focused command above | 193 passed, exit 0, 11.751s |
| `venv/bin/python manage.py test applications documents email_sync core postings` | 758 passed, exit 0, 102.083s |
| `venv/bin/python manage.py test` | 776 passed, exit 0, 107.240s |
| `venv/bin/python manage.py check` | No issues, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run applications` | No changes, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run --verbosity 3` | Exit 1, only known EmailAccount.provider choice drift; no migration generated |
| `git diff --check`, new-file whitespace, Python AST and local Markdown references | Passed |

## Exclusions and operational limitations

No frontend, queue/filter, candidate rejection, generic accepted/handled state, automatic
dismissal, detach, PDF/evidence generation, email-derived activity, PostingSource, posting
identity/source-item mapping/ingestion/reconciliation, historical retained-review reconciliation,
legacy Discovery conversion, provider/Gmail/sender-rule or generalized purge/export work.
Legacy FastAPI/frontend behavior remains unchanged; no dual writes or legacy-ID translation.

SQLite automated verification does not validate PostgreSQL locking/deadlocks/isolation,
live Gmail, browser workflow, Redis/Celery, storage, deployment, backup/restore or cutover.
No fresh legacy suite or operational validation is claimed. No dependency updates or real
tracker data changes. Leave the slice uncommitted for separate diff review and explicit
commit/push authorization.

## Bounded pre-commit correction, 2026-09-27

Final read-only review found that a fresh-key continuation could commit an incomplete
intent without ever issuing a challenge. The shared allocator now checks intent existence
inside the Workspace gate before get_or_create when a challenge is supplied. This applies
to manual, posting and review creation; no compensation delete, new authority, schema,
digest/fingerprint, Category helper or successful response change was introduced.

Two regression tests snapshot every model table to prove rejected continuations create
no intent or domain records, while real issued pending challenges remain intact. They
cover all three routes, cross-key tokens, normal issuance, successful confirmation,
completed replay and material key mismatch precedence. Existing rollback/concurrency,
lost-response, digest and migration coverage remains intact.

The first correction-focused run exposed one expected error-precedence change: a token
sent to another owned Workspace with no matching intent now returns 409 invalid_challenge
before review lookup. That test now checks zero persisted changes and separately retains
the no-challenge 404 scope assertion. The affected run started before this correction was
stopped after 160 tests and is not counted as successful verification.

Final correction verification (same isolated settings and commands above): targeted
`ReviewCreateTests.test_continuation_intent_persistence` and
`CreationTests.test_continuation_intent_persistence_manual_and_posting`: **2 passed**,
0.249s. Focused **193 passed**, affected **758 passed**, full Django **776 passed**.
All exited 0. These supersede the pre-correction counts of 191/756/774. System checks
pass; Application drift is absent; global dry-run drift remains only EmailAccount.provider
(exit 1, no generated file). Python AST, whitespace, local Markdown references and
`git diff --check` pass. Migration 0010 is byte-for-byte unchanged. Foundations already
expresses the durable contract and was not changed by this correction. No staging,
commit or push; the same 18-file slice remains for final read-only review.
