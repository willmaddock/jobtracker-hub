# Backend ApplicationMessage relationship foundation

Bounded implementation for review, 2026-09-20 (America/Denver). Uncommitted;
no commit or push. Repository `/Users/dev/Documents/GitHub/jobtracker-hub`, branch
`django-migration`, starting and current HEAD
`fcbfcf353201552d4a579408299323e0bf731b21` —
`Adopt Gmail messages into retained-source authority`, parent
`9f6627770c43fd3b3af492d2201e647af77cc53f`.

Initial root, branch, clean tree, HEAD, tracking reference and live remote were
verified. Continuation reconfirmed the same HEAD and preserved the intentional
implementation diff. No branch operations, dependency changes or real-data migration
were performed by this implementation run.

## Authority and inspected architecture

The user authorized explicit backend relationships under accepted Decisions and
Foundations Topic 5. Those accepted documents are unchanged. Code/migrations establish
implementation; automated evidence below does not establish operational readiness.

Inspected migration Decisions, Foundations, Status, plan, retained-email, Gmail
identity/adoption, derivation and Trash reviews; retained models/service/inspection;
Gmail producer, retention handoff and sync classification/projection; Application
identity, creation, lifecycle, admin and routes; legacy matching and migration tests.

`RetainedMessage` is the durable workspace-owned canonical source. Its strong
namespace is separate from append-only `RetainedObservation` and retry `RetentionKey`.
Gmail uses durable `MailboxLineage`; `MailboxPrincipal` and `AccountMailboxBinding`
establish prospective verified account lineage. Credential lifecycle is independent
of retained evidence. Attachment consumes this authority without changing it.

The actual Django legacy relationship is `AccountMatch`, not `EmailMatch` or `Match`.
Review uses `Discovery` and its candidate Applications; posting discoveries are
`Discovery(kind="posting")`, not a separate `PostingDiscovery` model. `JobPosting`
is separately persisted. Legacy `_app` stores `account_matches`, `discovered_matches`
and `job_postings`. Existing RFC/thread trust and company/role candidate logic remains
compatibility behavior, never canonical relationship allocation.

## Model and migration

`applications.ApplicationMessage` has a stable BigAutoField runtime ID, immutable
workspace-unique UUID `portable_id`, Workspace, Application, RetainedMessage,
`created_at`, and bounded `origin="manual"` (explicit manual attachment). All three
FKs use PROTECT. The Application owns the link; the source remains Workspace-owned.
No actor/observation identity, purpose variants, review state or future origins are
speculatively added.

Database uniqueness is exactly `(application, retained_message)`, plus
`(workspace, portable_id)`. A database check permits only the implemented manual
origin. Both many messages per Application and many Applications per message are
supported. Repeated attempts retain distinct Application PKs regardless of matching
company/role, RFC Message-ID or provider thread metadata.

The sole schema migration is `applications.0007_application_message`, containing
one CreateModel. Dependencies:

- `applications.0006_deterministic_derivation`
- `accounts.0002_deterministic_derivation`
- `email_sync.0006_retained_email_foundation` (the migration creating RetainedMessage)

The existing `email_sync.0007_gmail_mailbox_identity` remains independently in the
graph. No cycle or duplicate relationship migration exists. The initial generator
also emitted an unwanted provider-choice AlterField; that generated file was removed
without applying it. The final dependency is the minimal retained-schema dependency,
not the temporary generated migration or an unnecessary Gmail-specific dependency.
There is no new email_sync migration, RunPython/backfill, source rewrite or heuristic
promotion. Fresh test databases and populated forward upgrades exercise the graph.

### Historical migration-test targets

`test_retention_migrations` still starts at `email_sync.0005_imapcredential`, before
retention, with `applications.0006_deterministic_derivation`, the Application schema
it used at the committed starting checkpoint. Assertions prove RetainedMessage and
ApplicationMessage tables are absent. Its existing all-column/table preservation
checks and no-email-promotion assertions remain intact.

`test_gmail_identity_migrations` still starts at `email_sync.0006_retained_email_foundation`,
before verified Gmail principal/binding storage, with the same Application `0006`.
Assertions prove retained storage exists while principal, binding and relationship
tables do not. Its unchanged checks still prove additive identity upgrade without
backfill and preservation of every pre-existing table/column.

Both formerly selected the latest Application leaf dynamically. The new cross-app
dependency would pull retained storage into the pre-retention baseline and future
relationship storage into the pre-lineage baseline. Pinning only the Application
target preserves their original historical schemas; it does not advance them to
make tests pass. Narrowing the new dependency to retained `0006` avoids an unnecessary
Gmail `0007` requirement but cannot itself preserve the old Application baseline.
Rewriting committed migrations or reversing retained tables is neither necessary
nor used.

The new populated migration test starts from the full fcbfcf3 schema on a disposable
SQLite file. It compares every column of every pre-existing table, including repeated
attempts, lifecycle/derivation values, retained content/observations/keys, mailbox
lineage/principal/binding, synthetic credentials, legacy matches, ordinary and
posting-kind Discoveries, candidate M2M rows, posting rows and stored file references.
The relationship table starts empty after upgrade. Reapplying the forward plan is
a no-op, also after a synthetic relationship is inserted. No backwards migration or
real tracker data is used.

## Service, API and locking

`applications.message_relationships.attach_message` is the sole canonical product
writer. One atomic transaction reauthorizes the authenticated owner using the existing
Workspace gate, locks the workspace-scoped Application, rejects direct Trash, locks
the workspace-scoped RetainedMessage and validates its mailbox Workspace, rejects
source conflict, then resolves/creates the pair. Existing redundant relationship
Workspace corruption is rejected rather than returned. No provider or credential
lookup, network operation, derivation or legacy write occurs.

Lock order is Workspace → Application → RetainedMessage → pair resolution. The
retained query uses `select_for_update(of=("self",))` so its scope-validation join
does not add a mailbox lock. Competing lifecycle, retention and Gmail writers share
the Workspace gate first. SQLite uses the existing no-op Workspace write gate;
PostgreSQL uses its row lock. Pair uniqueness is the final database duplicate guard.
No automatic retry or generalized request-intent model is introduced.

Under `/api/workspaces/{workspace_id}/applications/{id}/messages/`:

| Method | Behavior |
|---|---|
| POST | Exact JSON `{"retained_message_id": positive_integer}`; 201 on first creation, 200 on eligible same-pair replay |
| GET/HEAD | Live Application relationship inspection; ascending PK cursor `after`, 50 results and `next_after` |
| PUT/PATCH/DELETE | 405; no edit, detach, dismiss or deletion workflow |

JSON format suffixes use the same writer/read contract. Scope comes only from route
and authenticated ownership. Foreign workspace/Application/source references are 404;
unauthenticated access is 401; session-CSRF failure is 403; unknown/forged scope,
origin, observation identity or malformed IDs are 400. Direct Trash is 409
`resource_trashed`; source conflict is 409 `retained_source_ineligible`; SQLite lock
refusal uses existing 503 `lifecycle_busy` handling and deliberate client replay.

Responses contain relationship IDs, Workspace/Application/source IDs, original origin
and creation time, plus the existing read-only `message_summary`. Retained content
is not duplicated; its existing scoped detail endpoint supplies safe inspection.
No credential or original HTML is added to this representation. Existing links to a
source that later conflicts remain readable with `eligible=false`; new attachments
and POST replay while conflicted reject without altering the link.

Canonical source allocation remains the existing retention writer's responsibility:
unresolved observations have no RetainedMessage and are not promoted. An observation
ID is never looked up as an observation by this API. IDs belong to the named model;
clients must use the canonical retained-message ID. Eligibility means resolved,
unconflicted source identity, not complete content; partial canonical content can be
linked without claiming evidence-generation readiness.

## Lifecycle, integrity and side effects

Application Trash preserves links and retained sources. The Application-side messages
read and all attachment POSTs reject while directly trashed, including a replay.
Restore exposes the original link without recreation, timestamp churn or duplication.
Relationships have no independent Trash or permanent-deletion operation.

Ordinary persisted model saves reject reparenting and all provenance/identity edits,
including attempts to change the PK; model delete rejects. New ordinary saves validate
redundant Workspace endpoints and origin. Admin is inspection-only: every field is
read-only, add/change/delete permissions are false and bulk actions are disabled.
The admin smoke test explicitly expects 403 for the new protected add route.
QuerySet/bulk/raw-SQL operations remain privileged maintenance surfaces, matching the
existing retained-evidence model boundary; this is not a database-trigger guarantee
against arbitrary maintenance writes.

Attachment leaves Application business/derived fields, activity, revisions, histories,
Documents, retained content/source facts, observations, mailbox lineage, AccountMatch,
Discovery (including posting kind), candidate links, ThreadIdentifier and JobPosting
unchanged. Synthetic Gmail projection tests also prove sync does not automatically
allocate links and preserves an explicitly created link on replay. There is no dual
write or historical promotion. Compatibility consumers still require replacement
before legacy retirement; this slice does not retire them.

## Verification ledger

All Django commands below run from `backend/` using the existing `venv/`. Tests use
the Django test database and disposable migration fixture databases. No dependencies
were installed. Final full-suite results apply to the current implementation tree.

| Command | Result |
|---|---|
| `venv/bin/python manage.py test applications.tests.test_messages` | Initial 13 passed |
| `venv/bin/python manage.py test applications.tests.test_messages applications.tests.test_message_migrations email_sync.tests.test_retention_migrations email_sync.tests.test_gmail_identity_migrations` | Initial populated fixture failed on its duplicate JobPosting key; corrected to distinct synthetic keys. Subsequent 17 passed |
| `venv/bin/python manage.py test applications.tests.test_messages applications.tests.test_message_migrations email_sync.tests.test_retention_migrations email_sync.tests.test_gmail_identity_migrations core.tests` | Final focused: 22 passed, exit 0 |
| `venv/bin/python manage.py test applications email_sync core postings` | Initial 613: 612 passed, one obsolete admin-add expectation failed; expected 403 added for the protected model. Final: 615 passed, exit 0 |
| `venv/bin/python manage.py test` | 688 passed, exit 0 |
| `venv/bin/python manage.py check` | No issues, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run applications` | No changes, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run --verbosity 3` | Exit 1: only pre-existing `email_sync.0008_alter_emailaccount_provider` proposed; no file generated |
| `venv/bin/python manage.py showmigrations applications email_sync --plan` | Exit 0; acyclic dependency plan inspected; unexpected local applied state described below |
| `git diff --check` | Passed during implementation and final review, exit 0 |
| `git status --short`, `git diff --stat`, `git diff`, full new-file reads | Final inventory below; 7 modified and 6 new files, no commit/push |
| Python local Markdown-link existence check for Status and this review | Passed; no missing local link targets |

Global drift was reproduced before edits and remains solely the provider-choice
AlterField. The intentional ApplicationMessage migration is present in the working
tree and has no remaining model drift. No legacy `_app`/frontend suite was freshly
run; historical failures in Status are not claimed resolved.

### Unexpected local database state — read-only investigation

Continuation's `showmigrations` reported ApplicationMessage `0007` already applied
in `backend/db.sqlite3`. The user confirmed they did not apply it. No command in this
implementation run migrated that database. Direct SQLite `mode=ro` inspection found
the actual relationship table/constraints and migration record dated
`2026-09-20 20:12:32.367040` UTC, alongside other migrations applied within that second.
File mtime was `2026-09-20 20:29:11.859612` UTC; timestamps do not identify a writer or
distinguish original migration from a copied/restored database.

The available saved pre-interruption tool-call record ends about 20:06 UTC and contains
no standalone `manage.py migrate` invocation. Shell history has an undated migration
command, insufficient for attribution. No app terminal is attached. The migration
tests explicitly use isolated aliases/temporary files. Inspected Django SQLite test
creation uses an in-memory database, and normal runs report creating/destroying that
test database. Local read-only counts show no Applications, relationships, retained
messages or observations, and none of the known synthetic fixture usernames; this
does not identify the writer. The origin of this local state remains
**unresolved**; no claim of local migration validation is made. The database was not
modified, migrated, rolled back, deleted or recreated during this investigation.
A SHA-256/size/mtime baseline is retained in `/tmp/application-message-local-db-audit.json`.
Comparison after affected/full verification confirms all three unchanged; the file
hash is `f7fedc005cfffb33662bd9450c8e66178e22e75f6c4cb69414651599063f804b`.
Any database alteration requires separate user approval.

## Changed files

- `backend/applications/models.py`
- `backend/applications/admin.py`
- `backend/applications/urls.py`
- `backend/applications/message_relationships.py` (new)
- `backend/applications/message_views.py` (new)
- `backend/applications/migrations/0007_application_message.py` (new)
- `backend/applications/tests/test_messages.py` (new)
- `backend/applications/tests/test_message_migrations.py` (new)
- `backend/email_sync/tests/test_retention_migrations.py`
- `backend/email_sync/tests/test_gmail_identity_migrations.py`
- `backend/core/tests.py`
- `docs/DJANGO_MIGRATION_STATUS.md`
- `docs/DJANGO_APPLICATION_MESSAGE_REVIEW.md` (new)

## Remaining boundaries and readiness

This implements the accepted relationship foundation only. Retained review queues,
candidate resolution, dismiss/restore decisions, detach, inferred links, historical
reconciliation, generated evidence, PostingSource and JobPosting ingestion are not
implemented. Evidence replacement versus supersession remains unresolved. No provider,
frontend, authentication, storage or workspace-lifecycle architecture was changed.

SQLite tests establish logical convergence and rollback under tested lock outcomes,
not PostgreSQL row locking, isolation, deadlocks, pooling or production workers.
No live Gmail operation was required or performed; synthetic component tests are not
live-provider validation. Browser/frontend integration, production storage, Redis/
Celery, backup/restore and cutover are not operationally validated. Outlook/IMAP
retained adoption and all broader workflows remain separately scoped work.
