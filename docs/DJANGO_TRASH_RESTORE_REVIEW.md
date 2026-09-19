# Backend Trash & Restore — implementation review

2026-09-19. **Uncommitted; stop for human review. No commit or push performed.**

## Checkpoint and authorization

Repository: `/Users/dev/Documents/GitHub/jobtracker-hub`.
Branch: `django-migration`.
Starting and final HEAD: `3f564ba3cb3522ff494444635756df2b26f0ec36`
(`Implement named category identity and membership`).

Inspection verified the canonical root, branch, clean starting tree, HEAD, local
`origin/django-migration` and live remote (`git ls-remote`), recent history and
Named Categories implementation. The initial architecture gate paused over
Document evidence/derivation scope. The user's subsequent explicit clarification
resolved it: implement eligibility now and defer recalculation. No accepted
Decisions or Foundations were rewritten. Known status-document staleness was corrected.

Neither documented virtual environment existed. With explicit user approval,
created `backend/venv/` and `.venv/`, installing their declared requirements.
Dependency manifests were not changed. No real tracker database was migrated or
used for tests; populated migration tests use separate temporary SQLite databases.

## Model, migration and service contract

Application, Document and Category inherit `core.lifecycle_models.RetainedLifecycle`:

| Field/property | Meaning |
|---|---|
| `trashed_at` | Nullable, noneditable DateTimeField; NULL is directly live; set on real Trash and cleared on restore |
| `lifecycle_revision` | Noneditable PositiveBigIntegerField, default 0; increments exactly once per real transition |
| `is_trashed` | Read-only direct state derived from `trashed_at` |
| `effective_trashed` | Direct state for Application/Category; direct OR parent state for Document |
| `.objects.live()` | Centralized live/evidence-eligible queryset; Document also excludes trashed parents |

Default managers stay **unfiltered** for retained identity, duplicate detection,
reconciliation and inspection. Category membership does not affect Application
eligibility. Existing category metadata `revision` and Application
`category_revision` remain independent from lifecycle revision.

Migration order:

1. `applications.0005_retained_lifecycle` follows
   `applications.0004_application_category_revision` and `accounts.0001_initial`.
2. `documents.0005_retained_lifecycle` follows the Application migration,
   `documents.0004_backfill_synthetic_categories` and `accounts.0001_initial`.

Both migrations add live/default-zero state without backfilling invented history.
Application.workspace, Category.workspace, Document.workspace and
Document.application change to PROTECT against incidental ancestor deletion.
No identity, archive state, membership, legacy provenance, override, history,
request-intent, extraction metadata or file reference is rewritten. The populated
upgrade test compares every pre-existing column in its representative graph.
The existing Category backfill test now explicitly targets its own committed
checkpoint; the new lifecycle migration has separate preservation coverage.

`core.lifecycle.set_trash` is the canonical transactional desired-state service.
It revalidates ownership through the existing workspace gate, then scopes and locks
the target. Document operations lock the parent Application before the Document.
Category assignment retains Category-before-Application order. All competing
included mutations acquire the workspace gate first. PostgreSQL uses the existing
workspace row lock; SQLite obtains its write lock before transactional reads.

Expected lifecycle revision is checked before no-op handling. Current-revision
no-ops preserve timestamp/revision; stale retries get 409 and must refetch. No new
request-intent architecture, lifecycle history or background task was introduced.
SQLite lock contention returns bounded 503 responses; reconciliation tests permit
both admissions to encounter SQLite locking and verify one valid retained state.
A restore of an initially live resource can no-op before a concurrent Trash;
it consumes no revision and cannot undo the later committed transition.

## Retention, visibility and identity behavior

- Application Trash preserves the same row, stable identities, Category link,
  Archive, business fields, overrides, history and all Documents/files. Children
  become effectively unavailable without changing their direct Trash state.
- Document Trash preserves its row, file bytes/reference, metadata, override and
  extraction/provenance. Restore reuses that row. Restore under a trashed parent
  is blocked, including an otherwise direct-state no-op.
- Application restore makes previously live children eligible again; independently
  trashed children remain excluded until explicitly restored.
- Category Trash hides organizational presentation while retaining Archive and
  memberships. Member Applications retain their own lifecycle/archive/status and
  remain visible in system views. Live Applications can detach or move away;
  assigning into a trashed Category is rejected. Assignment committed before
  Category Trash survives; admission after Trash cannot commit a new membership.
- Ordinary Application lists, Document lists, dossier evidence, search, browse,
  attention, insights, manage and document duplicate counts use live eligibility.
  Archived state remains independent.
- Duplicate warnings retain authorized archived/trashed Application candidates,
  including lifecycle state in challenge fingerprints. Creation replay for manual
  Applications, posting conversions and Categories returns the original current
  identity without cloning/restoring it or recreating cleared membership.
- Product metadata mutations use the workspace gate and reject direct/effective
  Trash. Bulk override validates eligibility for every target before any effect.

**Acknowledged temporary limitation:** this slice does not recalculate stored
Application status/activity when evidence eligibility changes. Existing business
status, manual overrides, activity timestamps and history stay unchanged. Stored
values may still reflect subsequently trashed evidence. No pretend recalculation
or synthetic status history is produced. The later deterministic derivation slice
must use lifecycle eligibility and the retained original evidence, preserving
manual precedence and accepted timestamp rules. The pre-existing live dossier
GET extraction/autofill behavior remains, but is limited to eligible Documents
and blocked for trashed Applications.

## API and admin contract

All new endpoints require authenticated ownership of the explicit route workspace:

| Method and path under `/api/workspaces/{workspace_id}/` | Contract |
|---|---|
| POST `applications/{id}/trash/` or `restore/` | Application transition |
| POST `documents/{id}/trash/` or `restore/` | Document transition |
| POST `categories/{id}/trash/` or `restore/` | Category transition |
| GET `applications/{id}/` | Added retained-state detail inspection |
| GET `documents/{id}/`, `categories/{id}/` | Existing inspection includes retained lifecycle state |
| GET `applications/`, `categories/`, `applications/{id}/documents/` with `show_trashed=true` | Explicit inclusion of retained objects; Category `show_archived` still independently applies |

Transition JSON is exactly `{"expected_revision": 0}` with a nonnegative integer.
Success returns 200 and the normal resource representation plus lifecycle fields.
No-op success is also 200. Malformed/unknown input is 400; unauthorized/mismatched
objects are 404; unauthenticated requests are 401; CSRF failures are 403.

Conflict codes: `stale_revision`, `parent_trashed`, `resource_trashed` (409).
Lifecycle contention uses `lifecycle_busy` (503, refetch before retry). Existing
creation/Category mutation contention retains its prior `creation_busy` handling.
Dossier and Category-context member access are blocked while their target is
trashed; use retained detail/list inspection for recovery.

These authenticated old routes now return **410 `endpoint_retired`**, without
looking up or deleting any target:

- POST `/api/applications/{id}/delete/`
- POST `/api/applications/bulk-delete/`
- POST `/api/documents/{id}/delete/`

Their existing format suffixes are also retired. No DELETE or permanent-purge
endpoint was added. Remove the retirement stubs before legacy retirement.

Application and Document admin retain live metadata edits, but disallow hard
or bulk deletion and changes while effectively trashed. Lifecycle fields are
read-only; Document ownership/file references are read-only. Save-time checks use
the workspace gate and preserve current lifecycle/membership revisions when a
form was loaded before a concurrent transition. Document add and standalone
DocumentOverride writes are disabled; product upload/override APIs provide the
guarded write path. Existing read-only Category/Membership/FolderOverride admin
safeguards remain. PROTECT prevents ancestor admin deletion from cascading into
these retained resources. No purge admin action exists.

## Verification ledger

Commands are shown exactly apart from log redirections. Django commands run from
`backend/`; legacy/frontend commands from the repository root unless indicated.
Final full-suite results supersede intermediate counts. Logs from this session
are available under `/tmp/lifecycle-verification/`.

| Command | Result |
|---|---|
| `backend/venv/bin/python backend/manage.py makemigrations applications documents` (root, before environment setup) | Exit 127: executable absent; no migration generated by this command |
| `python3 -m compileall -q backend/core/lifecycle.py backend/core/lifecycle_models.py backend/core/lifecycle_views.py backend/core/tests_lifecycle.py backend/core/tests_lifecycle_migrations.py` | Exit 0, initial syntax verification |
| `venv/bin/python manage.py test core.tests_lifecycle core.tests_lifecycle_migrations` | Initial 12 passed; **final 14 passed** after additional race/admin tests |
| `venv/bin/python manage.py test core.tests_lifecycle core.tests_lifecycle_migrations core.tests` | Intermediate 16 passed, including admin smoke tests |
| `venv/bin/python manage.py test documents.tests.test_categories documents.tests.test_category_membership documents.tests.test_category_migrations` | 20 passed |
| `venv/bin/python manage.py test applications.tests.test_identity applications.tests.test_creation postings.tests.test_views core.tests_workspace_scope core.tests_cross_cutting` | 92 passed |
| `venv/bin/python manage.py test documents.tests.test_views documents.tests.test_services applications.tests.test_documents applications.tests.test_dossier` | 30 passed |
| `venv/bin/python manage.py test applications documents postings core` | Initial 282: one obsolete admin-add expectation failed; updated for intentional safeguard. Intermediate 283 passed; **final 284 passed** |
| `venv/bin/python manage.py test` | Intermediate 543 passed; **final 544 passed**, exit 0 |
| `venv/bin/python manage.py check` | Initial and final: no issues, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run applications documents core postings` | Initial and final: no changes detected, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run` | Initial and final: exit 1, only existing `email_sync` provider-choice drift |
| `venv/bin/python manage.py showmigrations applications documents core postings --plan` | Initial and final: exit 0; dependency plan inspected; migrations unapplied locally |
| `.venv/bin/python -m pytest tests/test_build_index.py tests/test_overrides_store.py tests/test_hub_settings.py tests/test_workspace_inspect.py` | 40 passed, 2 warnings, exit 0 |
| `.venv/bin/python -m pytest tests/test_export.py tests/test_import_local_folder.py tests/test_overrides_portability.py` | 13 passed, 2 baseline failures, 2 warnings, exit 1 |
| `node --test tests/frontend/*.test.cjs` | Exit 127: Node absent on PATH |
| `/Users/dev/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --test tests/frontend/*.test.cjs` | 8 passed, 0 failed, exit 0 |
| `.venv/bin/python -m pytest` | 367 passed, 3 baseline failures, 2 warnings, exit 1 |
| `git diff --check` | Passed throughout and at final review |
| `git status --short`, `git diff --stat`, `git diff --summary` and complete tracked/new-file inspection | Only listed authorized source/tests/docs changes; no executable-mode changes |

No failing legacy test was rerun with permission to write into real tracker storage.
The legacy failures are:

1. `tests/test_overrides_portability.py::test_export_then_import_round_trips_notes_and_status`
2. `tests/test_overrides_portability.py::test_export_then_import_round_trips_hub_settings`
3. `tests/test_status_history.py::test_deleting_an_application_clears_its_status_history`

The first two raise PermissionError at `/Users/dev/Documents/JobTracker Hub`; the
third expects 200 and receives 500. All three reproduced on the unmodified start
commit exported with `git archive` to `/tmp/lifecycle-baseline-3f564ba`, using:

```sh
/Users/dev/Documents/GitHub/jobtracker-hub/.venv/bin/python -m pytest tests/test_overrides_portability.py::test_export_then_import_round_trips_notes_and_status tests/test_overrides_portability.py::test_export_then_import_round_trips_hub_settings tests/test_status_history.py::test_deleting_an_application_clears_its_status_history
```

Result: 3 failed, 2 warnings, exit 1, identical failure signatures. From that
export's `backend/`, this command also reproduced exactly the same provider drift:

```sh
/Users/dev/Documents/GitHub/jobtracker-hub/backend/venv/bin/python manage.py makemigrations --check --dry-run
```

Result: exit 1; proposed `email_sync.0006_alter_emailaccount_provider` only. No
migration was generated. These baseline issues were left unchanged.

Existing tests were changed only for intentionally retired hard deletion,
retained-ownership protection, admin bypass restrictions, and the explicit target
of the historical Category migration test. Frontend and legacy tests are unchanged.

## Limits and human review

PostgreSQL concurrency **was not validated**. SQLite transactional tests establish
retained-state invariants under the tested lock outcomes, not production database
semantics. Production/private storage, browser lifecycle integration, real provider
flows, Redis/Celery, backup/restore and operational cutover were not validated.

Review the transition/revision and inspection API contracts, ancestor PROTECT
boundaries, admin restrictions, and later derivation integration before commit.
No scope expansion beyond mechanical lifecycle guards and the explicitly
clarified evidence-eligibility behavior was made.

Explicit exclusions: **no permanent purge, no physical file deletion, no Workspace
Trash, no frontend Trash UI, no unrelated migration drift fix, no commit, no push**.

## Changed files and final Git state

All changed/added files (including new files not included by plain `git diff --stat`):

- `backend/applications/admin.py` — modified
- `backend/applications/creation.py` — modified
- `backend/applications/migrations/0005_retained_lifecycle.py` — added
- `backend/applications/models.py` — modified
- `backend/applications/serializers.py` — modified
- `backend/applications/tests/test_identity.py` — modified
- `backend/applications/tests/test_views.py` — modified
- `backend/applications/urls.py` — modified
- `backend/applications/views.py` — modified
- `backend/core/api_errors.py` — modified
- `backend/core/lifecycle.py` — added
- `backend/core/lifecycle_admin.py` — added
- `backend/core/lifecycle_models.py` — added
- `backend/core/lifecycle_views.py` — added
- `backend/core/tests.py` — modified
- `backend/core/tests_lifecycle.py` — added
- `backend/core/tests_lifecycle_migrations.py` — added
- `backend/core/tests_workspace_scope.py` — modified
- `backend/core/views.py` — modified
- `backend/core/workspace_scope.py` — modified
- `backend/documents/admin.py` — modified
- `backend/documents/category_services.py` — modified
- `backend/documents/category_views.py` — modified
- `backend/documents/migrations/0005_retained_lifecycle.py` — added
- `backend/documents/models.py` — modified
- `backend/documents/serializers.py` — modified
- `backend/documents/services.py` — modified
- `backend/documents/tests/test_category_migrations.py` — modified
- `backend/documents/tests/test_views.py` — modified
- `backend/documents/urls.py` — modified
- `backend/documents/views.py` — modified
- `docs/DJANGO_MIGRATION_STATUS.md` — modified
- `docs/DJANGO_TRASH_RESTORE_REVIEW.md` — added

Final `git status --short`:

```text
 M backend/applications/admin.py
 M backend/applications/creation.py
 M backend/applications/models.py
 M backend/applications/serializers.py
 M backend/applications/tests/test_identity.py
 M backend/applications/tests/test_views.py
 M backend/applications/urls.py
 M backend/applications/views.py
 M backend/core/api_errors.py
 M backend/core/tests.py
 M backend/core/tests_workspace_scope.py
 M backend/core/views.py
 M backend/core/workspace_scope.py
 M backend/documents/admin.py
 M backend/documents/category_services.py
 M backend/documents/category_views.py
 M backend/documents/models.py
 M backend/documents/serializers.py
 M backend/documents/services.py
 M backend/documents/tests/test_category_migrations.py
 M backend/documents/tests/test_views.py
 M backend/documents/urls.py
 M backend/documents/views.py
 M docs/DJANGO_MIGRATION_STATUS.md
?? backend/applications/migrations/0005_retained_lifecycle.py
?? backend/core/lifecycle.py
?? backend/core/lifecycle_admin.py
?? backend/core/lifecycle_models.py
?? backend/core/lifecycle_views.py
?? backend/core/tests_lifecycle.py
?? backend/core/tests_lifecycle_migrations.py
?? backend/documents/migrations/0005_retained_lifecycle.py
?? docs/DJANGO_TRASH_RESTORE_REVIEW.md
```

Final `git diff --stat` (tracked files only; new-file inventory above):

```text
 backend/applications/admin.py                      |   5 +-
 backend/applications/creation.py                   |   9 +-
 backend/applications/models.py                     |   5 +-
 backend/applications/serializers.py                |   1 +
 backend/applications/tests/test_identity.py        |   4 +-
 backend/applications/tests/test_views.py           |  68 +++---------
 backend/applications/urls.py                       |  10 ++
 backend/applications/views.py                      |  80 +++++----------
 backend/core/api_errors.py                         |   2 +
 backend/core/tests.py                              |   2 +-
 backend/core/tests_workspace_scope.py              |  10 +-
 backend/core/views.py                              |  14 +--
 backend/core/workspace_scope.py                    |   2 +-
 backend/documents/admin.py                         |  16 ++-
 backend/documents/category_services.py             |   8 +-
 backend/documents/category_views.py                |   6 +-
 backend/documents/models.py                        |  17 ++-
 backend/documents/serializers.py                   |   1 +
 backend/documents/services.py                      |  12 +--
 .../documents/tests/test_category_migrations.py    |   6 +-
 backend/documents/tests/test_views.py              |   9 +-
 backend/documents/urls.py                          |   9 ++
 backend/documents/views.py                         |  30 ++----
 docs/DJANGO_MIGRATION_STATUS.md                    | 114 ++++++++++++++++++---
 24 files changed, 255 insertions(+), 185 deletions(-)
```
