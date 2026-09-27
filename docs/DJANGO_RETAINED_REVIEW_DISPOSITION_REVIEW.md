# Retained Review Disposition — Dismiss / Restore Foundation

Bounded implementation reviewed on 2026-09-26; subsequently committed and pushed at
`5e25093a62a6c908d2da8123d1d6a7323eca2cd5` (`Implement retained review disposition`).

## Verified base and recovery

Repository `/Users/dev/Documents/GitHub/jobtracker-hub`, branch `django-migration`.
Committed HEAD, local tracking reference and live remote matched
`4d545820f62d92c76cf4da189706f17b3832949f`, subject
`Implement retained review attachment`, parent
`eedf57abbdf98f05d430ac116941fc447336f87b`. Initial tree was clean. The interrupted
implementation left eight authorized modified Python files; continuation inspected
all files and the full diff before further edits, reverified HEAD/tracking/live remote,
and confirmed no new commit/push or unrelated changes. Read-only AST diagnostics and
Django system checks passed. No reset, checkout, stash, repair or branch operation.

The user's explicit disposition approval supersedes the prior deferral. Foundations
records only that new contract; Decisions and historical reports remain unchanged.
The implementation excludes the disposition filter proposed during inspection.

## Schema and authority

`RetainedApplicationReviewDisposition` is a separate mutable model, not ReviewProvenance
or RetainedLifecycle. Its three fields are:

- `review`: protected one-to-one primary key, reverse name `disposition`.
- `dismissed_at`: nullable, default null, noneditable timestamp; null means active.
- `revision`: noneditable PositiveBigIntegerField, default 0.

No redundant Workspace/portable identity, dismissed boolean, stored attachment state,
handled/accepted state or candidate decisions. The primary key enforces one sidecar per
review. Ordinary instance reparenting and deletion reject; admin can only inspect.
QuerySet/bulk/raw SQL remain privileged maintenance surfaces, not product writers or
a database-trigger guarantee against arbitrary administrative rewrites.

Migration `applications.0009_retained_application_review_disposition` depends solely on
`applications.0008_retained_application_review`, with one CreateModel and no RunPython.
It creates no historical records. No existing migration changes. Historical Discovery
status never supplies canonical disposition; absent sidecars remain active/revision 0.

## Service/API behavior

One `set_review_dismissal(actor, workspace, review_id, dismissed, expected_revision)`
service owns transitions. Within an atomic transaction it acquires the Workspace gate,
resolves scoped immutable review/source/observation provenance, reads disposition,
checks revision before no-op detection, and performs at most one state transition.
Source conflict does not block this operation. No Application/source locks or canonical
relationship writes are needed. No HTTP Idempotency-Key or automatic retry loop.

First dismissal lazily allocates revision 1 with current dismissal time. Restore clears
that timestamp and increments revision, preserving the row. Current-revision no-op
preserves timestamp/revision and performs no sidecar write; restore of absent disposition
creates nothing. Stale requests reject even when the requested state already matches.
The timestamp records current dismissal, not last restoration or full audit history.

Routes support the existing JSON suffix conventions:

- `POST /api/workspaces/{workspace_id}/application-reviews/{id}/dismiss/`
- `POST /api/workspaces/{workspace_id}/application-reviews/{id}/restore/`

Exact body: `{"expected_revision": nonnegative_integer}`. Booleans, strings, floats,
negative/out-of-range integers, missing/extra fields and malformed JSON reject. Success
and current-revision no-op return 200 with `id`, `workspace_id`, and nested `disposition`:
`state` (`active` or `dismissed`), `revision`, `dismissed_at` (timestamp or null).
List/detail add the same nested object, using a one-to-one join without count multiplication.
Listing stays inclusive with its existing ascending-PK pagination. No filtering API added.

Existing error framework provides 401 authentication_required, 403 csrf_failed,
404 not_found for inaccessible/corrupt scope, 400 validation_error, 409 stale_revision,
409 review_dismissed, and 503 lifecycle_busy on SQLite lock refusal. Canonical attachment
still supplies 409 resource_trashed/retained_source_ineligible for delegated requests.

## Attachment and serialization

`ApplicationMessage` remains the sole Application/source relationship authority;
unchanged `attach_message()` is the sole writer. `attach_review()` now opens an outer
atomic transaction and acquires Workspace before reading disposition. It validates
review scope, reads disposition, resolves the same-Workspace target and checks for the
canonical pair. A corrupt pair Workspace returns 404. Dismissed + no pair returns
409 review_dismissed before delegation; active or valid existing pair delegates normally.
For a dismissed new pair, dismissal admission is checked before canonical target/source
eligibility; existing-pair replay always reaches the canonical eligibility checks.

No review/source row lock precedes Application locks. The nested canonical service
reacquires the already-held Workspace gate, then locks Application → RetainedMessage,
validates Trash/conflict and resolves/creates the pair. The outer transaction retains
the gate through commit. PostgreSQL uses the existing Workspace row lock; SQLite uses
its existing no-op Workspace write. No process-only mutex or stale pre-gate decision.

If attachment wins, its pair commits and survives later dismissal. If dismissal wins,
a subsequent new review-mediated pair rejects. Eligible existing-pair replay remains
200 with unchanged identity/origin/timestamp. The direct ApplicationMessage endpoint
is independent of disposition; attachment through either path never changes disposition.
Response counts remain derived after the writer transaction, not frozen inventory.
Candidate attachability reflects current disposition and valid existing-pair replay,
source eligibility and target availability; candidate rows themselves never change.

## Preservation and boundaries

Active/dismissed each supports zero, one and many canonical relationships. Dismiss and
restore never create/delete/mutate relationships, Applications, immutable provenance,
source content/observations, legacy Discovery/M2M, Documents, manual/derived activity,
posting or provider state. Source conflict permits disposition transitions while
remaining independently authoritative for attachment. Application Trash preserves links;
Application restoration does not restore review disposition, and review restoration
does not restore Applications. Existing relationships stay visible/countable.

No candidate rejection, generic handled state, source-global irrelevance, detach,
Application accept/create, PostingSource, posting identity/mapping/ingestion/extraction,
evidence generation, historical reconciliation/conversion, provider/Gmail/sender-rule,
frontend, dependency, retained-source deletion, generalized review Trash or disposition
list-filter work. No new dependency on the separately deferred posting branch.

## Files

Modified:

- `backend/applications/models.py`: disposition model and instance identity/deletion guards.
- `backend/applications/admin.py`: inspection-only disposition registration.
- `backend/applications/retained_reviews.py`: disposition setter/representation, gated attach admission.
- `backend/applications/review_views.py`: disposition responses, actions, candidate attachability.
- `backend/applications/urls.py`: scoped dismiss/restore actions before suffix expansion.
- `backend/applications/tests/test_retained_reviews.py`: formerly absent action expectations.
- `backend/applications/tests/test_review_attach.py`: require outer admission transaction.
- `backend/core/tests.py`: protected admin-add expectation.
- `docs/DJANGO_MIGRATION_FOUNDATIONS.md`: newly approved bounded contract only.
- `docs/DJANGO_MIGRATION_STATUS.md`: current behavior, verification and checkpoint wording.

Added:

- `backend/applications/migrations/0009_retained_application_review_disposition.py`.
- `backend/applications/tests/test_review_disposition.py`.
- `backend/applications/tests/test_review_disposition_migrations.py`.
- `docs/DJANGO_RETAINED_REVIEW_DISPOSITION_REVIEW.md` (this report).

## Verification environment and coverage

All Django commands run from `backend/` in the existing `venv`, prefixed
`PYTHONPATH=/tmp:.` and suffixed `--settings=review_disposition_settings`.
External `/tmp/review_disposition_settings.py` contains only:

```python
from config.settings.dev import *
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
```

No real development database is opened. Historical migration tests create disposable
SQLite files under temporary directories. `backend/db.sqlite3` remains absent.

New coverage exercises absent sidecars, allocation/no-ops, stale revisions before no-op,
timestamps, strict input, ownership/CSRF, corrupt scope, model/admin protection,
post-insert/update rollback, zero/one/many link preservation and populated all-other-table
snapshots. Attach tests cover dismissed admission, canonical replay, independent direct
writes, conflict, Trash/Restore, inclusive list/counts and candidate attachability.
Gate-before-read assertions and ordered concurrent service calls test both race winners;
competing same/opposite revision requests test no-op/stale behavior. Synthetic Gmail
replay with changed matching preserves the dismissed review snapshot.

The populated migration test starts at Application 0008 with reviews/candidates,
zero/one/two links, conflicts, live/trashed Applications, retained/unresolved observations,
lineage/bindings, synthetic credentials, legacy matches/discoveries/posting-kind rows,
M2M, posting rows and document references. Every pre-existing table/column is compared
after migration and forward replay. Zero disposition rows are fabricated; explicit
post-upgrade test allocation verifies one-to-one uniqueness and subsequent replay.
Existing historical migration-preservation tests pass without modification.

The initial focused run had 73 tests with two ordered-race harness failures: SQLite
could refuse the contender's API Workspace read before reaching the patched gate.
The corrected harness invokes services directly to reach that gate; API busy mapping
is covered separately. No production behavior was changed to accommodate those tests.

## Verification ledger

Commands use the prefix/settings described above.

| Command | Result |
|---|---|
| `venv/bin/python manage.py test applications.tests.test_review_disposition applications.tests.test_review_disposition_migrations applications.tests.test_retained_reviews applications.tests.test_review_attach applications.tests.test_messages applications.tests.test_review_migrations applications.tests.test_message_migrations email_sync.tests.test_retention_migrations email_sync.tests.test_gmail_identity_migrations core.tests_lifecycle core.tests` | 93 passed, exit 0, 6.000s |
| `venv/bin/python manage.py test applications documents email_sync core postings` | 726 passed, exit 0, 96.230s |
| `venv/bin/python manage.py test` | 744 passed, exit 0, 102.982s; final code/test state |
| `venv/bin/python manage.py check` | No issues, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run applications` | No changes, exit 0; Application 0009 fully represents the model |
| `venv/bin/python manage.py makemigrations --check --dry-run --verbosity 3` | Exit 1: only known `email_sync.0008_alter_emailaccount_provider` choice drift; no migration generated |
| `git diff --check`; new-file whitespace and local Markdown-link checks | Passed |

## Operational limitations

SQLite logical/concurrent tests do not establish PostgreSQL row locking, deadlocks,
production isolation or worker concurrency. No live Gmail/provider, browser/frontend,
Redis/Celery, storage, deployment, backup/restore or cutover validation. No fresh legacy
FastAPI/frontend suite is claimed. This slice is not full retained-review workflow
completion. No real tracker data or local database was modified. No commit or push
occurred during implementation; the later authorized checkpoint is recorded below.

## Historical pre-commit working tree

At pre-commit review, HEAD remained `4d545820f62d92c76cf4da189706f17b3832949f` on `django-migration`.
Exactly the ten modified and four added files listed above comprise the slice.
Full tracked diff and new files inspected; whitespace/local-link checks pass.
No staging, commit or push occurred during that review. `backend/db.sqlite3` and the proposed unrelated provider
migration file remain absent. Nineteen new tests bring the historical full count of
725 to the freshly verified 744; these are automated SQLite results only.


## Subsequently verified committed checkpoint

The authorized 14-file slice was committed and pushed as
`5e25093a62a6c908d2da8123d1d6a7323eca2cd5`, subject
`Implement retained review disposition`, parent
`4d545820f62d92c76cf4da189706f17b3832949f`. Local HEAD, tracking and live remote
matched; post-push status was clean and `backend/db.sqlite3` remained absent.
The original verification/recovery ledger above is historical evidence, unchanged.
