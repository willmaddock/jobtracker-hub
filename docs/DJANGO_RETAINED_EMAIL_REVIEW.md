# Backend Retained Email Source Identity and Content Foundation — review

Implemented 2026-09-19; final continuation verification 2026-09-20.
Implemented for human review; uncommitted. No commit, push,
dependency/environment change, real-data migration, or provider adoption.

## Authoritative starting checkpoint

The prior implementation session recorded an initial gate confirming `/Users/dev/Documents/GitHub/jobtracker-hub`, branch
`django-migration`, clean tracked/untracked state, and HEAD, local tracking reference,
and live `origin/django-migration` all at
`120d49397297c2ba1337c88503769aec6ae87c41`
(`Implement deterministic application derivation`). Inspected branch listing,
twelve-entry history and whitespace check. The sandbox initially could not resolve
GitHub; the authorized `git ls-remote origin refs/heads/django-migration` succeeded.
No Git state was changed to satisfy the gate.

The 2026-09-20 continuation independently confirmed the same root, branch, HEAD,
tracking reference and live remote. Its initial tree intentionally contained four
modified tracked files (core tests, email admin/models/URLs) and all seven new
files listed below; tracked diff was 37 insertions and one deletion. The expected
Status/Derivation review edits had not yet been made. This was documentation still
to finish, not missing implementation. No unrelated files or material continuation
state discrepancy was found. All existing implementation was preserved; review
required no production-code or test correction. This continuation only updates the
three review/status documents and runs final verification.

Workspace Scoping Core, frontend authentication/workspace foundation, Application
Identity and Repeated Attempts, Named Categories, Backend Trash & Restore, and
Backend Deterministic Application Derivation remain implemented checkpoints.
The derivation review's old “uncommitted” wording describes its pre-commit review;
derivation is now committed at `120d493`. Decisions and Foundations are unchanged.

## Scope and ownership

The acceptance path is normalized relevance-qualified observation → internal
retention service → durable workspace data → authorized read-only inspection.
Fixture service/API tests cover that path. Current provider sync is **not adopted**,
no live-provider retention validation occurred, and email does **not** feed derivation.

Four new models, exported through `email_sync.models`:

| Model | Authority and protection |
|---|---|
| `MailboxLineage` | Workspace-owned stable PK/portable UUID, provider and explicit established-lineage evidence. No inference from an email address or old account. |
| `RetainedMessage` | Workspace-owned stable PK/immutable workspace-unique portable UUID, one complete strong source namespace, canonical bounded content, comparison digest, sticky conflict flag, first retention time. |
| `RetentionKey` | Workspace-scoped observation/retry key and immutable first-input digest. Key conflict is sticky. Contains no content. |
| `RetainedObservation` | Append-only bounded input variants, observed/retained times, original result state, explicit conflict reason, nullable source result and mailbox references. Unique key/digest pair. |

This slice stores the single accepted strong locator on RetainedMessage itself;
there is no speculative alias/reassignment or workflow relationship model. Content
hashes compare observations, never identify messages. Provider, established mailbox,
locator kind/value, folder and stability form the database unique namespace.
Workspace/portable UUID pairs and retry/variant keys also have database uniqueness.
There is no cross-workspace content sharing.

Every new FK uses PROTECT. New models have **no FK to EmailAccount, credentials,
Application, Discovery, matches, postings or Documents**. Deleting or disconnecting
an account therefore cannot cascade into retained state; changing/recreating an
account cannot assign lineage. Existing disconnect implementations remove credentials
and preserve the connection row; no provider lifecycle rewrite is needed. Tests also
exercise account deletion and recreation with the same address. Existing legacy
workflow/account cascade behavior is unchanged and is not the new retention policy.
Workspace/User incidental deletion is blocked when retained state exists.

Normal model saves/deletes of existing evidence are rejected. Admin provides
privileged read-only inspection, with no add/change/delete or bulk actions. Only
internal transactional service updates set sticky conflict flags. Privileged raw SQL
and QuerySet mutation are not supported identity/content editing workflows; these
are not database triggers or a new purge authority.

## Internal service and identity contract

`establish_mailbox(actor, workspace, provider, evidence)` explicitly allocates a
lineage whose proof has already been established by its internal caller. Evidence
is a bounded `{method, reference}` object; a provider principal can be preserved in
that reference. It performs no provider proof verification, reconnect or automatic
merge. Callers retain/reuse the returned lineage ID; calling the allocator again
creates a separate lineage. Current producers do not call this service. Missing
proof is represented by no lineage, not a fabricated historical registration.

`retain_observation(actor, workspace, key, observation)` is the sole new retention
writer. There is no HTTP write endpoint. It requires one explicit qualification:
`application_evidence`, `discovery_review`, or `posting_source`. This records why the
internal caller qualified the message; it neither classifies mail nor creates the
corresponding workflow record. Invalid/irrelevant input is rejected before effects.
Errors contain no supplied content. Authenticated workspace ownership is checked
before normalization and revalidated under the transaction gate.

Observation input has `reason`, aware `observed_at`, optional `mailbox_id`, optional
`source`, and `content`. Source fields are `provider`, `kind`, `value`, `folder`,
`stability`. Supported namespace declarations are:

| Provider | Kind | Namespace requirements |
|---|---|---|
| gmail | `gmail_message_id` | Nonempty opaque ID, empty folder (account-wide), stability `v1` |
| outlook | `graph_immutable_id` | Nonempty opaque **immutable** Graph ID, empty folder, stability `v1` |
| imap | `imap_uid` | Positive 32-bit UID, exact nonempty folder, `uidvalidity:<positive 32-bit value>` |

These are validated input contracts, **not provider certification**. A provider
label is mandatory when a source object exists. Missing/null namespace components
are preserved as unknown; only a complete namespace plus established mailbox can
allocate a RetainedMessage. Malformed/contradictory supplied namespaces are rejected,
not silently downgraded. No source, incomplete source, or absent lineage yields an
inspectable unresolved observation with no message identity and `eligible=false`.
The provider must match a referenced mailbox. All mailbox references are scoped and
revalidated under lock. Weak IDs, thread/conversation metadata, subjects, senders,
and hashes never supply missing identity. RFC Message-ID is optional.

Separate retry and source behavior:

- Same workspace/key and equivalent versioned input returns the same observation,
  without changing canonical data or timestamps. A different key creates a new
  observation; an equivalent strong source still reuses the retained message.
- Same key with changed material input appends an `observation_key_reused` variant,
  preserves the original binding, and marks the key and any originally bound message
  conflicted. It never allocates the changed candidate source. The variant's
  `message_id` refers to the original accepted result, **not** proof that its changed
  source belongs to that message; its payload preserves the candidate namespace.
- Same strong source with changed normalized content/provenance appends a
  `source_content_conflict` variant and marks the existing source conflicted. It
  does not overwrite canonical content or allocate a second identical source.
- Replaying any earlier observation reports current key/message conflict state.
  `recorded_state` remains the historical observation result. No resolution,
  reassignment, review decision, downstream processing or automatic retry exists.

`eligible` means **identity is resolved and unconflicted only**. It does not certify
content completeness, provider provenance, or authorize any downstream workflow.
Future consumers must also inspect availability/completeness and their own contracts.

## Representation, finite limits and comparison version 1

Content contains nullable subject; structured `from`, `sender`, `reply_to`, `to`,
`cc`, available `bcc` lists of `{name, address}`; ordered/repeated selected headers;
readable decoded text; original HTML; `header_sent` and `provider_received` claims;
bounded decoder `{method, version}` provenance; optional conversation metadata.
Allowed headers: Date, Message-ID, In-Reply-To, References, MIME-Version,
Content-Type (including charset), Content-Transfer-Encoding. Unknown keys and
arbitrary provider/authentication blobs are rejected. No MIME or attachment bodies
are retained. Available empty text differs from unavailable text.

Limits count UTF-8 bytes except collection lengths:

| Input | Limit and behavior |
|---|---|
| Serialized observation | 2 MiB; reject the entire operation if exceeded |
| Text / original HTML | Default 128 KiB / 256 KiB; deterministic UTF-8 prefix truncation |
| Settings | `RETAINED_EMAIL_TEXT_BYTES`, `RETAINED_EMAIL_HTML_BYTES`; integer 1–262144 each; defaults live in retention.py |
| Subject | 4096 bytes, nullable |
| Addresses | At most 100 per role; name/address each 1024 bytes |
| Headers | At most 100; name 64 bytes, value 8192 bytes |
| Source locator / folder / conversation ID | 512 bytes each |
| Stability / retry key | 128 bytes each |
| Decoder method/version | 128 bytes each |
| Availability reason / uncertain source time | 256 / 128 bytes |
| Mailbox evidence method/reference | 512 bytes each |

Other over-limit fields reject atomically. Null bytes and invalid Unicode are
rejected. Accepted normalized payloads remain finitely bounded by these field limits;
the input ceiling is checked before normalization. Content conflicts use exactly the
same limits. Truncation records reason, UTF-8-prefix location, retained/original
byte counts, original full-field digest and original completeness/reason. Different
truncated tails remain material conflicts. Hashes do not recover discarded content.
There is no automatic expiration or bound on a workspace's total number of relevant
observations; this is a per-operation/content policy, not a mailbox archiver.

Normalization v1 sorts mapping keys for SHA-256 comparison, lowercases selected
header names, normalizes decoded-text CRLF/CR to LF, and canonicalizes aware instants
to UTC. Header/address list order and repetition, spelling/whitespace, Unicode,
HTML bytes, uncertainty, provenance and source offset remain meaningful. Missing
optional source components normalize to null; omitted optional conversation ID
normalizes to empty. Omitting required fields is invalid. Retry digest includes
qualification, normalized observation time, namespace and all bounded content;
content comparison excludes operational observation time and qualification.
Changing observation time under the same key is changed input. A later observation
uses a new key. Limits/representation changes that alter retained representation
are conservatively material, not an implicit content rewrite or version migration.

## Source versus operational timestamps

Source claims explicitly carry precision `instant`, `date`, `uncertain`, or `unknown`,
value, and source label. Instants require an offset and are stored as UTC with the
original `source_utc_offset_seconds`; dates remain dates. Uncertain naive/historical
text remains bounded text without a fabricated timezone. Unknown has null value.
Header-sent and provider-received claims are separate from observed and retained times.

Receipt labels are limited to `gmail_internal_date`, `graph_received_datetime`,
`imap_internaldate`, or `unknown`, and checked against an established mailbox's
provider. Header Date cannot be labeled a receipt by passing `header_date`. Internal
callers remain responsible for supplying genuine source facts. Current Outlook/IMAP
providers use header Date as old `received_at`; current providers also expose RFC
Message-ID as their old sync identity. None of those fields is automatically adopted.
Retention time, import time and observation time never become Application activity.

## Read-only API

All paths start `/api/workspaces/{workspace_id}/` and use the existing session auth,
workspace-first authorization and normalized DRF error handler:

| GET/HEAD path | Result |
|---|---|
| `retained-messages/` | Stable identity/state summaries |
| `retained-messages/{id}/` | Identity, source namespace, readable content and uncertainty |
| `retained-observations/` | Observation/state summaries, including unresolved/conflicts |
| `retained-observations/{id}/` | Bounded original candidate payload and current conflict state |
| `mailbox-lineages/{id}/` | Stable lineage identity, provider and established proof reference |

Collections return `{results, next_after}` with at most 50 summaries, ascending
numeric PK. `after` is a nonnegative signed-64-bit cursor. Observation collection
optionally accepts `message_id`, which is authorized in the route workspace before
filtering. Detail/list queries also check the workspace of retained FK references.
Different users and different workspaces owned by the same user remain isolated.

Only JSON rendering is enabled. HTML value is omitted from both content and
observation payload inspection; availability/truncation metadata remains visible.
There is no raw-HTML route, provider fetch, extraction, derivation, cache creation or
hidden GET/HEAD write. Existing admin escapes source fields during privileged
inspection. No credential table is read by these endpoints. Auth failures are 401,
foreign/mismatched objects 404, invalid input/cursor 400, mutations 405; existing
normalized codes accompany DRF errors. No review or retention mutation is exposed.

## Transactions, migrations and recovery

Lock order: authorized Workspace gate → mailbox → retry binding → retained source.
The existing gate takes a SQLite write lock before transactional reads, or a
PostgreSQL workspace row lock. All effects of one operation commit atomically, with
uniqueness enforcing convergence. No provider/network access occurs inside it.
Database contention propagates to the internal caller; no hidden retry or new task
architecture is introduced. Tests allow either or both SQLite competitors to fail
admission, then explicitly reconcile the original operations and assert one source,
preserved variants and consistent flags. Injected failure rolls back source/key/
observation allocation and conflict flags. SQLite is **not** PostgreSQL lock/deadlock
or production concurrency validation.

`email_sync.0006_retained_email_foundation` depends on `email_sync.0005_imapcredential`
and `accounts.0001_initial`. It only creates the four tables and five uniqueness
constraints. No existing field is altered and no data backfill runs. In particular,
the known EmailAccount provider-choice drift is excluded from this migration.
There are no invented mailbox registrations, locators, bodies, source timestamps,
Application activity or historical relationships.

The populated disposable SQLite test builds the committed schema, seeds accounts,
all credential types, matches, discoveries/candidates, threads, postings/conversions,
Applications/overrides/history, Documents/extraction/file references, Categories/
memberships, folder metadata and request intents. It compares every original column
in every pre-existing table through the forward migration. New tables remain empty.
Re-running the already-applied plan preserves new retained references. No real
tracker database is migrated; the local plan remains unapplied.

Operational rollout rollback must disable new writers and preserve retained tables,
records and backups. Reversing this additive schema after retention would destroy
content and is **not** a safe operational recovery plan. No operational rollback or
backup restoration has been validated.

## Verification ledger

Every required final command completed on the preserved implementation tree on
2026-09-20. Results below are fresh continuation evidence. Django commands run from
`backend/`; frontend/legacy/Git from repository root. Fresh logs: `/tmp/retained-*-final.log` (temporary local verification artifacts).

| Command | Final result |
|---|---|
| `venv/bin/python manage.py test email_sync.tests.test_retention email_sync.tests.test_retention_migrations core.tests --noinput` | 36 passed, exit 0; fresh final run, including populated migration preservation |
| `venv/bin/python manage.py test email_sync accounts core applications documents postings --noinput` | 606 passed, exit 0 |
| `venv/bin/python manage.py test --noinput` | 606 passed, exit 0 |
| `venv/bin/python manage.py check` | No issues, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run email_sync` | Exit 1: known EmailAccount.provider choice AlterField only; no retained-model or unrelated drift |
| `venv/bin/python manage.py makemigrations --check --dry-run` | Exit 1: known EmailAccount.provider choice AlterField only; no retained-model or unrelated drift |
| `venv/bin/python manage.py makemigrations email_sync --dry-run --verbosity 3` | Exit 0: only EmailAccount.provider AlterField; proposed `0007_alter_emailaccount_provider`, no file written |
| `venv/bin/python manage.py showmigrations email_sync --plan` | Exit 0: graph includes 0006 after accounts.0001/email_sync.0005; all listed migrations unapplied locally |
| `/Users/dev/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --test tests/frontend/*.test.cjs` | 8 passed, exit 0 |
| `.venv/bin/python -m pytest` | 367 passed, 3 known failures, 2 warnings, exit 1 |
| `git diff --check` | Passed, exit 0 |

In the prior implementation session, the initial affected run had one expected admin smoke-test mismatch (new read-only
models correctly returned 403 on add). The test's explicit deny-list was updated;
no admin write path was opened. An initial migration fixture repeat reused a stale
MigrationExecutor and was corrected to refresh its applied-plan state. Final results
supersede those intermediate failures.

Legacy failures exactly match the supplied `120d493` checkpoint names/signatures:

1. `tests/test_overrides_portability.py::test_export_then_import_round_trips_notes_and_status`
2. `tests/test_overrides_portability.py::test_export_then_import_round_trips_hub_settings`
3. `tests/test_status_history.py::test_deleting_an_application_clears_its_status_history`

The first two raise PermissionError for `/Users/dev/Documents/JobTracker Hub`; the
third receives 500 instead of 200. No broadened real-storage permission or unrelated
fix was attempted. The comparison is against supplied checkpoint and prior recorded
clean-baseline evidence; no fresh exported-baseline suite was run in this slice.
Frontend and legacy sources/tests are unchanged. The fresh failure names, count
and signatures match all three supplied baseline failures exactly; none was fixed
or rerun with broadened real-data access. Global/scoped drift is the same provider
choice operation: Gmail/Outlook display labels lose “(legacy)”; keys, other choices,
max_length=16 and default=mail_app are unchanged. Only the proposed filename number
shifts to 0007. No provider-choice migration file exists.

## Files and remaining boundaries

Added:

- `backend/email_sync/retained_models.py`
- `backend/email_sync/retention.py`
- `backend/email_sync/retained_views.py`
- `backend/email_sync/migrations/0006_retained_email_foundation.py`
- `backend/email_sync/tests/test_retention.py`
- `backend/email_sync/tests/test_retention_migrations.py`
- `docs/DJANGO_RETAINED_EMAIL_REVIEW.md`

Changed:

- `backend/email_sync/models.py` — register/export retained models.
- `backend/email_sync/admin.py` — read-only retained evidence inspection.
- `backend/email_sync/urls.py` — explicit scoped inspection routes.
- `backend/core/tests.py` — expected admin add denial for new protected models.
- `docs/DJANGO_MIGRATION_STATUS.md` — current checkpoint/evidence and narrow historical wording correction.
- `docs/DJANGO_DERIVATION_REVIEW.md` — identify its historical pre-commit wording.

No frontend, legacy, provider, sync, account lifecycle, dependency manifest or
production settings changes. No speculative ApplicationMessage/PostingSource,
review actions, posting ingestion, generated evidence/PDFs, derivation hooks,
workers/outbox, importer/exporter, permanent purge, physical cleanup, Workspace
lifecycle, historical reconciliation or conflict resolution was implemented.

Future separately authorized work must establish/verify provider lineage and strong
locators, adopt relevant producers into this sole retention authority, and only then
connect review/posting/evidence consumers. Current metadata-only sync cannot be
silently dual-written forever or treated as authoritative retained content. Remove
superseded identity/write assumptions after adoption and validated reconciliation,
before legacy retirement. Provider locator/reconnect guarantees, PostgreSQL,
Redis/Celery, private storage, browser integration, backup/restore and cutover remain
unvalidated. Evidence regeneration artifact policy remains unresolved and unselected.

## Final continuation review

All required final runs completed; automated Django/frontend verification passes
with the documented legacy failures and provider-choice drift exceptions. This is
not a fully green repository or operational/provider validation claim. The populated
migration test passed within the focused, affected and full runs. Existing-table
columns/rows, credential fixtures, relationships and stored file references survive;
new retention tables remain empty until explicit fixture retention.

Final tracked diff and every untracked file were inspected. `git diff --check`
passes, and `git diff --summary` is empty (no tracked mode changes, renames or
removals). The final inventory is six modified tracked files and seven new files,
exactly the list above. New files are regular mode 0644. No unrelated files,
generated migration, temporary artifacts, credential material, dependency/environment
changes or provider/sync adoption were found in the changes. Verification logs live
outside the checkout. HEAD/branch/index are unchanged; nothing was committed or pushed.
