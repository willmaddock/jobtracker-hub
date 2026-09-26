# Retained Application Review Identity & Candidate Snapshot Foundation

Bounded implementation for human review, 2026-09-26. Uncommitted; no push.

## Repository checkpoint before work

Canonical root `/Users/dev/Documents/GitHub/jobtracker-hub`; branch `django-migration`.
Starting HEAD, tracking reference and live remote all matched
`b5c1faf1ad100acfd3d24aead679c3a1831f3a48`, subject
`Implement application message relationship foundation`, parent
`fcbfcf353201552d4a579408299323e0bf731b21`. Working tree was clean.
Inspected pwd/root, branches, twelve-commit history, remotes, parent and diff.
Live remote verification required an approved network escalation; no Git state changed.

## Baseline reconstruction and authority

Decisions and Foundations describe accepted architecture, not completed operational
work. Inspected their retained-source, identity, lifecycle, scoping and idempotency
contracts, Status and the migration plan, prior retained/Gmail/relationship/derivation/
Trash reviews, models, services, routes, migrations, tests, admin and legacy consumers.
No accepted decision was changed. The historical plan and review documents contain
superseded implementation descriptions; current code and Status take precedence.

- `RetainedMessage` remains canonical workspace-owned source identity/content, with
  runtime PK, portable UUID and strong namespace. Gmail identity is Workspace +
  durable verified mailbox lineage + provider/native locator (not RFC ID/thread/hash).
- `RetainedObservation` records immutable observation/reconciliation variants; its
  retry key and optional source result are not review identity. Unresolved observations
  remain under existing inspection and cannot create a canonical review.
- Gmail principal/account binding establishes prospective durable lineage independently
  of credentials. Retention precedes legacy projection, within a per-message transaction;
  provider fetching is outside that transaction. Source conflicts pause new effects.
- Applications have distinct runtime/portable IDs, including repeated same-company/role
  attempts. `ApplicationMessage` remains unique per Application/source and manual-only.
  Its sole attachment service rejects direct Trash and conflicted sources. Links survive
  Trash/Restore; review creation never calls or duplicates that writer.
- Actual Django compatibility models are `AccountMatch` and `Discovery`, including
  `Discovery(kind="posting")`; there is no separate `Match` or `PostingDiscovery` model.
  Matching uses RFC thread trust, posting rules, company/role terms and general
  application phrases. Ambiguous term matches retain all specific attempts.
- Legacy `_app` acceptance/attachment writes matches/thread hints and may generate
  evidence; dismiss/restore updates discovery status. Existing frontend code still calls
  those legacy discovery routes. None of these consumers/actions were changed.
- Retained content inspection is workspace-scoped JSON and omits original HTML value.
  Workspace is the shared first write gate. ApplicationMessage then locks Application
  and source; retention locks lineage. This slice introduces no inverse Application lock.

Prior suite counts in Status are historical evidence. Fresh verification is recorded
below. Neither establishes live Gmail, PostgreSQL, browser or production readiness.

## Models and additive migration

The models live in `applications` because the review domain is Application association;
the provider supplies classifications but does not own relationship/review authority.

`applications.RetainedApplicationReview` has a protected Workspace, one-to-one protected
RetainedMessage, workspace-unique portable UUID, protected originating observation,
initial classification, snapshot schema version 1 and creation timestamp. Observation
is provenance only; it does not define review cardinality. No decision/status/Trash
field, evidence body or duplicate relationship state is added.

`RetainedApplicationReviewCandidate` has a protected review reference, nullable
Application FK (`SET_NULL`), immutable Application portable UUID and creation time.
Uniqueness is `(review, application_portable_id)`, independent of nullable FK. This
preserves suggestion identity if a future authorized target removal nulls the FK;
there is no purge workflow here. No descriptive Application snapshot is retained:
current labels are explicitly presented as current, while portable identity and
initial set/classification are historical provenance. Candidates do not own targets.

Ordinary saves/deletes of persisted provenance are blocked. New ordinary saves check
scope/reference consistency. Admin has no add/change/delete permission or bulk actions.
QuerySet/bulk/raw SQL remain privileged maintenance surfaces, not supported product
writers or a database-trigger immutability guarantee.

Sole new migration: `applications/migrations/0008_retained_application_review.py`.
Dependencies:

- `applications.0007_application_message`
- `accounts.0002_deterministic_derivation`
- `email_sync.0006_retained_email_foundation`

Two CreateModel and three AddConstraint operations; no RunPython/data migration.
The one-to-one field enforces source uniqueness. Existing migrations are unchanged.
The generator emitted an unrelated email provider-choice AlterField as well; that
unapplied generated file was removed and the dependency narrowed to the actual retained
schema. No provider migration remains. The graph is acyclic.

**Zero historical backfill:** no scan of retained/legacy rows, historical matching or
fabricated source/review identity. The initial queue is incomplete relative to legacy
history. Newly fetched, relevance-qualified Gmail messages enter the new path, including
normal incremental overlap; this is not a historical reconciliation job.

## Service, sync and API

`applications.retained_reviews.ensure_application_review` is the sole canonical internal
snapshot writer. It validates authenticated ownership, positive typed IDs, observation/
source agreement, candidate Workspace and classification cardinality. Duplicate candidate
IDs collapse only when they name the exact same Application; repeated attempts stay
separate. Zero/one/many map to `application`/`match`/`ambiguous`.

An atomic transaction acquires Workspace → RetainedMessage → review. No Application
row locks are acquired. Workspace serialization and database uniqueness prevent duplicate
sets; candidates publish atomically with their review. A valid replay returns the
existing review without changing candidates, classification, timestamps or portable IDs.
Changed matching facts cannot reevaluate that first set. Existing conflicted reviews
remain inspectable/replayable; initial conflict cannot create new automatic review state.
SQLite contention is exposed for caller replay, without automatic retry loops.

Gmail order is classification → retention → review snapshot → legacy projection.
Integration is inside the existing per-message transaction, before RFC-ID suppression.
No RFC ID is needed for a canonical review; two native sources sharing an RFC ID have
separate reviews. Posting classification never enters this domain. Unresolved observations
produce no review. Existing legacy projection, thread matching and classification rules
are unchanged. Projection failure rolls back review/retention; snapshot failure rolls
back retention before projection. Other providers retain their existing behavior.

Read-only routes:

- `GET /api/workspaces/{workspace_id}/application-reviews/`
- `GET /api/workspaces/{workspace_id}/application-reviews/{id}/`

HEAD/OPTIONS and existing JSON suffix conventions are supported. List uses ascending
PK cursor `after`, 50 results and `next_after`. It shows identity, canonical source
summary, source subject, initial classification/count, timestamps and observation ID.
Detail adds candidate UUIDs, current target labels and `live`/`trashed`/`removed`
availability, current attachability, and existing ApplicationMessage identities/origin/
time. Attachability is informational; no review attachment action exists. Conflict
makes source eligibility and candidate attachability false; direct Application Trash
makes that target unavailable. Restore exposes the same candidate again.

Every read authorizes the route Workspace and validates redundant source/provenance
scope. Candidate/relationship references are scoped too. No original HTML or body is
returned; existing retained-message inspection supplies content. Unauthenticated reads
are 401, foreign references 404, malformed cursor/redundant scope 400. POST/PUT/PATCH/
DELETE are 405, and review-action routes are absent. No read changes legacy or canonical
state. This queue is an inspection inventory, not a pending/handled decision queue.

## Verification

Commands run from `backend/` using the approved `venv`. Every management command
uses `PYTHONPATH=/tmp:.` and `--settings=retained_review_settings`. The external
`/tmp/retained_review_settings.py` contains only:

```python
from config.settings.dev import *
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
```

No repository settings change is needed and no default local database is opened.

| Command (with the prefix/settings above) | Result |
|---|---|
| `venv/bin/python manage.py test applications.tests.test_retained_reviews applications.tests.test_review_migrations applications.tests.test_messages applications.tests.test_message_migrations email_sync.tests.test_retention_migrations email_sync.tests.test_gmail_identity_migrations core.tests` | 47 passed, exit 0 |
| `venv/bin/python manage.py test applications email_sync core postings` | 638 passed, exit 0; before two additional tests, subsequently covered by focused/full runs |
| `venv/bin/python manage.py test applications.tests.test_retained_reviews.ReviewSyncTests.test_ambiguous_sync_snapshot_survives_new_single_match` | 1 passed, exit 0, after strengthening it to use a fresh observation and assert no source conflict |
| `venv/bin/python manage.py test` | 713 passed, exit 0 (final tree, 101.463s) |
| `venv/bin/python manage.py check` | No issues, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run applications` | No changes, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run --verbosity 3` | Exit 1: only known `email_sync.0008_alter_emailaccount_provider` choice drift; no new drift |
| `venv/bin/python manage.py showmigrations applications email_sync --plan` | Exit 0; disposable empty DB, acyclic graph |
| `venv/bin/python manage.py migrate --plan` | Exit 0; plan only, disposable empty DB |

Initial focused tests exposed test-fixture errors (multiple observations, exception
class expectations and a nonmatching posting phrase); these were corrected without
changing product behavior. Final focused coverage includes service replay, zero/one/
multiple suggestions, exact-attempt deduplication, cross-Workspace/auth isolation,
readonly methods, safe content, portable identity, current Trash/Restore/conflict,
nullable target provenance, admin/model protections, database uniqueness, concurrency
and complete transaction rollback. Synthetic Gmail tests preserve legacy behavior,
exclude postings/unresolved/other providers, and do not auto-create relationships.

The populated pre-review migration test starts at Application `0007` with repeated
attempts, links, retained evidence/observations, unresolved cases, lineage/bindings,
synthetic credentials, legacy matches/discoveries/posting discoveries, candidate M2M,
posting and document references. It compares all columns/rows of every pre-existing
table after forward migration and no-op replay, and asserts zero new reviews/candidates.
Existing historical migration tests pass unchanged. No fresh legacy/frontend suite
is claimed; their code is unchanged and historical limitations remain in Status.

Final source/import/route/admin/schema/test inspection found no excluded-domain
changes. All new files are mode `0644`, with no existing file-mode changes.

## Exclusions and limitations

No accept/attach/resolve/dismiss/restore/reject/reevaluate review action, detach/removal,
automatic relationship, Application allocation/derivation change, Document/evidence
generation, PostingSource/JobPosting ingestion change, historical backfill, provider
expansion, frontend change, permanent purge, import/export or production cutover.
Evidence replacement versus supersession remains unresolved. Legacy compatibility
must be replaced by approved consumers before retirement; no permanent dual authority.

PostgreSQL compatibility was inspected for uniqueness, nullable references, atomicity
and lock order. Automated SQLite concurrency exercises convergence or exposed lock
refusal, not PostgreSQL isolation/deadlocks. No PostgreSQL environment was run.
Gmail tests use deterministic producer/provider fixtures; no live credentials or real
mailbox operations. Browser/frontend review integration is outside this slice and
unvalidated. Redis/Celery, storage, backup/restore and operational cutover remain open.

`backend/db.sqlite3` was absent at inspection and remains absent. The previous review's
unresolved local database provenance remains historical and unattributed; this run did
not recreate, migrate or repair that database. With explicit user approval, the missing
`backend/venv` was created and `backend/requirements.txt` installed unchanged. Verification
uses an external temporary settings module selecting in-memory SQLite; migration
preservation tests create disposable SQLite files. No real tracker data is used.

## Final changed files

- `backend/applications/models.py`: review and candidate schema, provenance protections.
- `backend/applications/retained_reviews.py`: internal idempotent snapshot writer (new).
- `backend/applications/review_views.py`: scoped read-only inspection (new).
- `backend/applications/urls.py`: list/detail routes.
- `backend/applications/admin.py`: inspection-only registrations.
- `backend/applications/migrations/0008_retained_application_review.py`: additive schema (new).
- `backend/email_sync/sync_service.py`: bounded Gmail integration.
- `backend/applications/tests/test_retained_reviews.py`: service/API/sync/concurrency tests (new).
- `backend/applications/tests/test_review_migrations.py`: populated preservation/no-backfill test (new).
- `backend/core/tests.py`: expected protected admin add routes.
- `docs/DJANGO_MIGRATION_STATUS.md`: current checkpoint and historical commitment correction.
- `docs/DJANGO_RETAINED_APPLICATION_REVIEW.md`: this review/verification record (new).

## Final repository state

HEAD remains `b5c1faf1ad100acfd3d24aead679c3a1831f3a48` on `django-migration`.
No commit, push, staging or branch operation. Six modified tracked files and six new
untracked files comprise this slice. `git diff --check` exits 0. Documentation local
links pass. `backend/db.sqlite3` remains absent.

`git status --short`:

```text
 M backend/applications/admin.py
 M backend/applications/models.py
 M backend/applications/urls.py
 M backend/core/tests.py
 M backend/email_sync/sync_service.py
 M docs/DJANGO_MIGRATION_STATUS.md
?? backend/applications/migrations/0008_retained_application_review.py
?? backend/applications/retained_reviews.py
?? backend/applications/review_views.py
?? backend/applications/tests/test_retained_reviews.py
?? backend/applications/tests/test_review_migrations.py
?? docs/DJANGO_RETAINED_APPLICATION_REVIEW.md
```

`git diff --stat` (tracked files only; new files are listed above):

```text
 backend/applications/admin.py      | 13 ++++++-
 backend/applications/models.py     | 71 ++++++++++++++++++++++++++++++++++++++
 backend/applications/urls.py       |  3 ++
 backend/core/tests.py              |  2 +-
 backend/email_sync/sync_service.py |  5 +++
 docs/DJANGO_MIGRATION_STATUS.md    | 66 ++++++++++++++++++++++++++++++-----
 6 files changed, 150 insertions(+), 10 deletions(-)
```
