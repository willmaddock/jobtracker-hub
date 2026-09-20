# Backend Deterministic Application Derivation — review

2026-09-19. Uncommitted continuation of the interrupted implementation. No commit,
push, dependency change, real-data migration, or production configuration performed.

## Repository and review scope

Confirmed root: `/Users/dev/Documents/GitHub/jobtracker-hub`; branch:
`django-migration`; base HEAD: `74f1e916d83a1865a93962e37243f2c1b96694bd`
(`Implement backend trash and restore lifecycle`). Local tracking reference also
points there; this continuation did not query the live remote. `main` remains at
`913effb`. The requested root, branch, HEAD, branch listing, twelve-entry log,
status, diff stat/summary and whitespace checks were inspected before edits.

The initial tree was intentionally dirty: 27 tracked files modified, six untracked
implementation/migration/test files; tracked diff 381 insertions, 266 deletions.
All were retained. Complete tracked changes and all six new files were reviewed
against Decisions, Foundations, Status, the migration plan and the historical
Trash/Restore review. No production-code correction was needed in this continuation;
its edits complete the verification documentation. Earlier counts are historical.

## Architecture and behavior

`applications.derivation` is the explicit per-Application authority. Effective
Document classifications yield `rejected > interviewing > applied > drafted >
unknown`; non-pipeline Applications yield `n/a`. Only live Documents in the same
workspace and Application contribute. Stored manual status wins over automatic
status, including existing manual Ghosted values; Ghosted expansion remains deferred.

Upload, rename/classification correction, direct Document Trash/Restore, relevant
Application/Override admin edits and manual status/date resets invoke derivation.
Creation initializes derived state and preserves request replay and posting
conversion identity. Category membership, Archive and Category lifecycle are
independent. Admin automatic fields and evidence/cache provenance cannot be edited
through ordinary admin forms; extraction-cache admin is read-only.

Parent Trash retains its business snapshot and child direct states. Deriving a
trashed parent does nothing. A direct child lifecycle change while its parent is
trashed marks the parent for reconciliation on restore; an unchanged parent-only
Trash/Restore cycle does not manufacture business transitions. Retained files and
source evidence survive, and independently trashed children remain excluded.

Source selection distinguishes identified event instants/dates, conservative
event-document extraction, verified legacy mtime, genuinely new user-upload time,
and unknown. Conflicted extracted event dates do not fall through to upload time.
Historical `uploaded_at`, extraction, import, restore and metadata-edit times are
not fallback evidence. Shared extraction caches contain byte-derived claims;
arrival times and source facts remain Document-owned. Extraction version 4/date
extraction version 2 preserve agreeing/conflicting date claims.

Date-only evidence stays date-only. Mixed-precision bounds use workspace calendar
days without inventing within-day order. Workspace timezone defaults to explicit
UTC; configuration UI is deferred. Attention uses reset → effective application
date → last evidence, with workspace-calendar due/snooze/day calculations.

Automatic confirmation dates are separate from stored overrides. Manual and
legacy-preserved dates survive evidence changes; clearing suppresses automatic
dates until `reset_date_applied` explicitly restores automatic mode. Conflicting
strong dates have no winner. Posting dates remain suggestions requiring acceptance.

Fingerprints, version, provenance, completeness and `derived_at` describe the derived
snapshot. Identical recalculation does not rewrite it. History compares effective
status before/after, ignores automatic transitions hidden by a manual override,
and suppresses consecutive duplicate recorded statuses. Existing history is retained;
new transition times are recording times, never invented evidence times.

POST `/api/workspaces/{workspace_id}/applications/{id}/derive/` reconciles one
authorized live Application and suppresses historical transition creation. Dossier
GET reads existing current-version extraction only, reports missing extraction,
and never derives, writes caches or autofills overrides. Serializer additions expose
effective/automatic date, precision, provenance and derivation state. Frontend
integration of these contracts remains a separate slice.

## Transactions and migration preservation

Mutations acquire the authenticated workspace gate before Application and Document
locks; Category locks precede Application where applicable. Evidence mutation,
cache work and derived database state share the transaction. SQLite contention may
reject either or both competing admissions; tests assert committed consistency and
no partial changes, not that one competitor must win. PostgreSQL row-lock,
deadlock and concurrency behavior has **not** been validated.

Three additive migrations:

- `accounts.0002_deterministic_derivation`: workspace calendar timezone.
- `applications.0006_deterministic_derivation`: derived date/precision/provenance,
  fingerprint/version/state, override date mode and precision constraints.
- `documents.0006_deterministic_derivation`: event precision/provenance, verified
  legacy mtime, original upload fallback and precision constraint; depends on both
  preceding migrations and `documents.0005_retained_lifecycle`.

Applications depend on their lifecycle migration. The only data classification is
non-null existing Override dates → `legacy_preserved`; original values and labels
remain unchanged. Historical Applications stay pending until individual explicit
reconciliation or a relevant future mutation. No bulk business derivation, source
timestamp invention, file mutation or synthetic history occurs in migration.
The populated forward test compares every existing column across representative
workspaces, Applications, overrides, duplicate history, Documents, extraction,
Categories/membership, request intents and posting conversions using disposable SQLite.
The inspected local migration plan leaves migrations unapplied; no real database
upgrade or operational rollback was performed.

## Final verification

Django commands run from `backend/`; frontend and legacy from the root. Logs use
`/tmp/jobtracker-derivation-resumed-*.log`.

| Command | Fresh result |
|---|---|
| `venv/bin/python manage.py test applications.tests.test_derivation applications.tests.test_derivation_migrations core.tests_lifecycle core.tests_lifecycle_migrations --noinput` | 43 passed, exit 0 |
| `venv/bin/python manage.py test applications documents core postings accounts --noinput` | 331 passed, exit 0; includes identity/repeated attempts, creation/replay, dossier, categories, Trash/Restore, workspace/cross-cutting coverage |
| `venv/bin/python manage.py test --noinput` | 573 passed in 95.972 seconds, exit 0 |
| `venv/bin/python manage.py check` | No issues |
| `venv/bin/python manage.py makemigrations --check --dry-run accounts applications documents` | No changes detected |
| `venv/bin/python manage.py makemigrations --check --dry-run` | Exit 1; only known `email_sync.0006_alter_emailaccount_provider` proposal; no file generated |
| `venv/bin/python manage.py showmigrations accounts applications documents --plan` | Exit 0; dependency order inspected, migrations unapplied locally |
| `/Users/dev/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --test tests/frontend/*.test.cjs` | 8 passed, exit 0 |
| `.venv/bin/python -m pytest` | 367 passed, exactly 3 known failures, 2 warnings, exit 1 |

Legacy failure names and signatures match the supplied baseline:

1. `tests/test_overrides_portability.py::test_export_then_import_round_trips_notes_and_status`
2. `tests/test_overrides_portability.py::test_export_then_import_round_trips_hub_settings`
3. `tests/test_status_history.py::test_deleting_an_application_clears_its_status_history`

The first two encounter PermissionError at `/Users/dev/Documents/JobTracker Hub`;
the third receives 500 instead of 200. No permission escalation to write real
tracker storage or baseline-failure fix was attempted. Prior baseline reproduction
is documented in the Trash/Restore review; it was not repeated in this continuation.

The earlier `/tmp/jobtracker-derivation-full.log` did finish with 573 passing tests;
it is prior evidence and does not substitute for the fresh run.

## Limitations

No frontend lifecycle/category integration, Ghosted expansion, bulk reconciliation,
purge, Workspace lifecycle, retained-email architecture, importer/exporter or
production infrastructure was added. Browser end-to-end flows, private storage,
PostgreSQL, Redis/Celery, real provider flows, backup/restore and cutover remain
unvalidated. Accepted Decisions and Foundations were not rewritten. Existing legacy
baseline failures and unrelated email provider migration drift remain outside scope.

## Documentation and final Git review

Status now records the completed fresh verification, distinguishes the committed
Trash/Restore checkpoint from the uncommitted derivation slice, and retains the
historical and operational limits. This report supplies the previously missing
review link. The Trash/Restore review is labeled historical. Local Markdown links
in all three documents resolve. No accepted architecture documents changed.

All required verification is complete, with the known legacy/drift exceptions
above. `git diff --check` passes. `git diff --summary` is empty: no tracked
mode changes, renames or deletions. New files are ordinary non-executable source,
migrations, tests and this report. No unrelated modifications, generated junk,
dependency/environment changes or temporary files appear in the final inventory.

The exact status below is also the complete changed/added file inventory (`M` is
modified, `??` is added/untracked). The tracked diff stat excludes these seven new
files, which were separately inspected. HEAD and branch remain unchanged.

Final `git status --short`:

```text
 M backend/accounts/models.py
 M backend/accounts/serializers.py
 M backend/applications/admin.py
 M backend/applications/creation.py
 M backend/applications/dossier.py
 M backend/applications/models.py
 M backend/applications/serializers.py
 M backend/applications/services.py
 M backend/applications/tests/test_dossier.py
 M backend/applications/tests/test_views.py
 M backend/applications/urls.py
 M backend/applications/views.py
 M backend/core/lifecycle.py
 M backend/core/lifecycle_admin.py
 M backend/core/serializers.py
 M backend/core/services.py
 M backend/core/tests.py
 M backend/core/tests_lifecycle.py
 M backend/core/tests_lifecycle_migrations.py
 M backend/documents/admin.py
 M backend/documents/date_extract.py
 M backend/documents/extraction.py
 M backend/documents/models.py
 M backend/documents/serializers.py
 M backend/documents/views.py
 M docs/DJANGO_MIGRATION_STATUS.md
 M docs/DJANGO_TRASH_RESTORE_REVIEW.md
?? backend/accounts/migrations/0002_deterministic_derivation.py
?? backend/applications/derivation.py
?? backend/applications/migrations/0006_deterministic_derivation.py
?? backend/applications/tests/test_derivation.py
?? backend/applications/tests/test_derivation_migrations.py
?? backend/documents/migrations/0006_deterministic_derivation.py
?? docs/DJANGO_DERIVATION_REVIEW.md
```

Final tracked `git diff --stat`:

```text
 backend/accounts/models.py                 |   1 +
 backend/accounts/serializers.py            |   2 +-
 backend/applications/admin.py              |  36 ++++++++-
 backend/applications/creation.py           |   8 +-
 backend/applications/dossier.py            |  91 +++++-----------------
 backend/applications/models.py             |  28 +++++--
 backend/applications/serializers.py        |  11 ++-
 backend/applications/services.py           |   4 +
 backend/applications/tests/test_dossier.py |  14 ++--
 backend/applications/tests/test_views.py   |   3 +-
 backend/applications/urls.py               |   1 +
 backend/applications/views.py              | 121 ++++++-----------------------
 backend/core/lifecycle.py                  |  14 +++-
 backend/core/lifecycle_admin.py            |   4 +-
 backend/core/serializers.py                |   5 ++
 backend/core/services.py                   |  59 ++++++--------
 backend/core/tests.py                      |   2 +-
 backend/core/tests_lifecycle.py            |  44 ++++++++++-
 backend/core/tests_lifecycle_migrations.py |   5 +-
 backend/documents/admin.py                 |  20 ++++-
 backend/documents/date_extract.py          |  23 +++++-
 backend/documents/extraction.py            |  19 +++--
 backend/documents/models.py                |   9 +++
 backend/documents/serializers.py           |   3 +-
 backend/documents/views.py                 |  13 +++-
 docs/DJANGO_MIGRATION_STATUS.md            | 100 ++++++++++++++++++------
 docs/DJANGO_TRASH_RESTORE_REVIEW.md        |  10 ++-
 27 files changed, 384 insertions(+), 266 deletions(-)
```
