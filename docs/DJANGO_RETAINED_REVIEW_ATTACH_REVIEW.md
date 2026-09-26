# Retained Review Attach to Existing Application

Bounded implementation for review, 2026-09-26; uncommitted, no push.

## Checkpoint and scope

Repository `/Users/dev/Documents/GitHub/jobtracker-hub`, branch `django-migration`.
HEAD, local `origin/django-migration` and live `refs/heads/django-migration` matched
`eedf57abbdf98f05d430ac116941fc447336f87b`, parent
`b5c1faf1ad100acfd3d24aead679c3a1831f3a48`, subject
`Implement retained application review foundation`. The working tree was clean.
Initial DNS failure stopped work; the user-authorized exact `git ls-remote origin
refs/heads/django-migration` command succeeded with network escalation, then local
conditions were rechecked before edits. No fetch, reference repair or branch operation.

Inspected repository instructions, Decisions, Foundations, Status, migration plan,
retained review and ApplicationMessage reports, models/migrations, lifecycle, scope,
relationship/snapshot writers, inspection APIs, Gmail integration and existing tests.
Accepted architecture documents are unchanged. Broad historical references to review
dismissal do not establish semantics for this new review identity: dismiss/restore
semantics remain unapproved and deferred under the explicit bounded request.

## Behavior and authorities

`POST /api/workspaces/{workspace_id}/application-reviews/{id}/attach/` accepts exactly
`{"application_id": positive canonical integer}` (maximum signed 64-bit integer).
Malformed JSON, extra fields, bool/string/float/null IDs and alternate source/scope
fields reject. JSON suffix, authentication, CSRF and scoped error handling are retained.
Foreign/inaccessible references return 404; malformed payload returns 400; Trash returns
409 `resource_trashed`; source conflict returns 409 `retained_source_ineligible`;
SQLite lock refusal returns 503 `lifecycle_busy`. Eligible creation returns 201 and
existing-pair replay 200, with canonical relationship representation plus
`attachment_status` and `relationship_count`.

Zero, one or many candidates never select a target automatically. Each request names
one existing Application, including eligible outside-snapshot targets, archived targets,
non-pipeline targets and targets in archived/trashed categories. Repeated same-label
attempts remain distinct. Different requests may create different Application/source
pairs; the candidate snapshot remains historical provenance.

Review list/detail derive attachment status from valid same-Workspace canonical links:
zero is `unattached`, one or more is `attached`. Both counts use distinct identities to
avoid join multiplication. Attached reviews remain listed. Links to trashed Applications
and links whose source later conflicts remain counted and visible. Relationship detail
adds current target `availability` (`live` or `trashed`). Direct ApplicationMessage
API writes immediately appear without review writes or historical backfill.

## Transaction and response boundary

`attach_review()` validates authenticated ownership and scoped review/source/originating
observation references, obtaining the source ID solely from the immutable review.
It does not acquire locks or open a transaction. Supported writers cannot reparent or
delete this provenance; raw SQL/QuerySet maintenance remains privileged, as before.
Pre-existing corrupt references are rejected. Concurrent arbitrary maintenance rewriting
immutable references is not a supported product writer contract.

Unchanged `attach_message()` alone opens the creation transaction, reauthorizes current
Workspace ownership, and serializes Workspace → Application → RetainedMessage → pair.
It checks mutable Trash/source conflict before pair resolution, including replay.
Lifecycle and retention use the same Workspace gate. No source/review lock precedes
Application locks; no duplicate writer, new request-intent storage or retry loop exists.
Insert failure rolls back the canonical relationship. The endpoint performs a fresh
scoped count after writer completion, then serializes the canonical result. A concurrent
attachment may already be included in that count; the response is not a frozen inventory
snapshot. Response failure does not undo a committed pair: deliberate replay resolves
its original ID, origin and timestamp while rechecking current eligibility.

## Files changed

- `backend/applications/retained_reviews.py`: shared scoped provenance query and minimal attachment orchestration; snapshot writer unchanged.
- `backend/applications/review_views.py`: derived counts/status, target availability and attachment endpoint.
- `backend/applications/urls.py`: explicit attachment route, including existing suffix conventions.
- `backend/applications/tests/test_review_attach.py`: bounded API, preservation, rollback, response failure, concurrency and Gmail tests.
- `backend/applications/tests/test_retained_reviews.py`: remove attachment from the absent-route expectation; other deferred routes remain absent.
- `docs/DJANGO_MIGRATION_STATUS.md`: current behavior/evidence and corrected foundation commit status.
- `docs/DJANGO_RETAINED_APPLICATION_REVIEW.md`: narrow historical checkpoint clarification.
- `docs/DJANGO_RETAINED_REVIEW_ATTACH_REVIEW.md`: this report.

No model/migration changes. RetainedMessage remains source authority, ApplicationMessage
relationship authority, review/candidates immutable initial provenance. No stored status,
accepted target, selected/rejected flag or alternate review-to-Application relationship.

## Verification

All Django commands run from `backend/` with the existing `venv`, prefixed
`PYTHONPATH=/tmp:.` and suffixed `--settings=review_attach_settings`. The temporary
external settings module contains only:

```python
from config.settings.dev import *
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
```

No real tracker database is opened. Existing historical migration tests use disposable
fixture files; no schema/data migration or historical scan is performed on user data.

| Command (prefix/settings above) | Actual result |
|---|---|
| `venv/bin/python manage.py test applications.tests.test_review_attach applications.tests.test_retained_reviews applications.tests.test_messages applications.tests.test_review_migrations applications.tests.test_message_migrations email_sync.tests.test_retention_migrations email_sync.tests.test_gmail_identity_migrations core.tests` | 59 passed, exit 0, 4.103s |
| `venv/bin/python manage.py test applications email_sync core postings` | 652 passed, exit 0, 85.525s |
| `venv/bin/python manage.py test` | 725 passed, exit 0, 98.664s; final code/test state |
| `venv/bin/python manage.py check` | No issues, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run applications` | No changes, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run` | Exit 1: only known `email_sync.0008_alter_emailaccount_provider` choice drift; no file generated |
| Local Markdown-link existence check; `git diff --check` | Passed |

An initial focused invocation ran before the new test file existed due to a shell
working-directory mistake (one import error); corrected invocation passed 51 tests.
A later command used the repository root instead of `backend/` and did not launch
Python. Final focused/regression results above include the completed new fixtures.
No dependency changes or application fixes were needed for those invocation errors.

Coverage includes zero/one/many and outside-snapshot selection, repeated attempts,
pre-existing links, inclusive lists and count multiplication, API-to-API replay, strict
payloads, scoped corruption, session CSRF, Trash/Restore and conflict/replay, partial
content, archive/category independence, actual post-insert rollback, lost-response
recovery and no outer transaction. Populated source/provenance, legacy matching and
posting-kind Discovery/candidate rows, Documents and manual values remain unchanged.
Synthetic Gmail replay with changed matching facts preserves attached review snapshots.
Concurrent same/different-pair, lifecycle and source-conflict tests exercise logical
serialization or exposed SQLite refusal, followed by deliberate caller replay.

## Deferred and operational limitations

No Application creation, acceptance, dismissal/restore semantics, rejection, detach,
batch attachment, purge, evidence generation, derivation/activity changes, matching,
provider fetch/expansion, posting ingestion, historical reconciliation, frontend or
dependency changes. Legacy consumers/projections remain unchanged and are not retired.

SQLite tests do not establish PostgreSQL row locking, deadlocks, production isolation
or worker concurrency. No live Gmail, browser, Redis/Celery, storage, backup/restore or
cutover validation. Full retained-review workflow completion is not claimed.
`backend/db.sqlite3` remains absent; no real data was modified. No commit or push.

## Final repository inspection

HEAD remains `eedf57abbdf98f05d430ac116941fc447336f87b` on `django-migration`.
Six tracked files modified and two new files (listed above); no staging, commit or push.
Full tracked diff and new-file contents reviewed. Whitespace and documentation-link
checks pass. `backend/db.sqlite3` remains absent after all verification. The 12 new
tests bring the full Django suite from the historical 713 to 725 passing tests; historical
migration-preservation tests remain unchanged and pass in focused and full runs.
