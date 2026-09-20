# Gmail provider adoption into retained-source authority

Bounded forward-only implementation for review, 2026-09-20. Uncommitted; no push.
Repository: `/Users/dev/Documents/GitHub/jobtracker-hub`, branch `django-migration`.
Starting HEAD: `9f6627770c43fd3b3af492d2201e647af77cc53f`
(`Implement Gmail mailbox identity and durable lineage`). HEAD remains unchanged.
The initial clean working tree, fetched tracking reference, and live remote matched
that checkpoint. Continuation reconfirmed unchanged HEAD and a clean tree before edits.

## Inspection and architecture

Inspected Decisions, Foundations, Status, migration plan, retained-email/Gmail-identity
reviews, relevant derivation/Trash contracts, commits `2f0cd1f` and `9f66277`, provider,
sync, OAuth, retained service/models, caller transaction settings, and existing tests.
`mailbox_identity.py` does not exist: OAuth manages AccountMailboxBinding and
`retention.py` resolves Google principals and durable lineage. Status's old
“uncommitted” identity wording described its pre-commit review and is corrected now.
Accepted Decisions and Foundations are unchanged.

Previously, `GmailProvider.fetch_messages()` collected native IDs from `messages.list`
and used them for `messages.get(format="raw")`. `_to_fetched_message()` discarded
that locator and emitted only RFC Message-ID; absent RFC IDs discarded the message.
`threadId` was ignored. Raw MIME remained transient, plain matching used the first
nonempty text/plain part, and HTML was available only through raw MIME URL extraction.
Repeated selected headers, structured addresses and RFC Date precision were not
represented for retention. `internalDate` supplied legacy `received_at`, without a
header-Date fallback. The old certainty/receipt docstring was inaccurate.

Sync previously had no lineage lookup or retention call. Its entire fetch/write
pass used one transaction. Both legacy and retained records use the same default
Django database; no cross-store coordination or schema change is necessary.

## Implemented producer and retention handoff

`FetchedMessage` now separates `provider_message_id`, `provider_thread_id`,
`provider_internal_at`, selected headers, addresses, plain/HTML retention bodies,
header-sent precision, and observation key/time. The explicit `rfc_message_id`
property names the existing `message_id` compatibility field. Gmail still supplies
RFC identity to matching/thread logic; no native ID is substituted or fabricated.
The list locator supplies native identity if the get response omits its redundant
ID; a contradictory returned ID fails the fetch explicitly.

`sync_service._classify_message()` preserves existing classification order:
RFC thread trust → forced/posting-style notice → one application term match →
ambiguous term matches → general application-mail candidate. Provider search,
sender rules, matching body selection and posting URL heuristics are unchanged.
Irrelevant fetched messages produce no retained observation. Only newly fetched,
currently relevance-qualified messages enter this path; there is no database scan,
backfill, historical inference or widened Gmail query. Existing incremental overlap
can naturally return older mail; no historical promotion job is added.

For relevant Gmail messages, `gmail_retention.retain_gmail_message()` calls the
existing `retention.retain_observation()` before RFC duplicate suppression:

- Match qualifies as `application_evidence`; posting discovery as `posting_source`;
  ambiguous/general application discovery as `discovery_review`. These are reasons,
  not new ApplicationMessage/PostingSource relationships or generated evidence.
- Canonical source is workspace + verified durable Gmail MailboxLineage +
  `gmail_message_id` + native ID, empty folder, stability `v1`.
- AccountMailboxBinding → MailboxLineage → MailboxPrincipal is validated for the
  account's workspace, Gmail provider and `google_oidc_sub` namespace. No lookup by
  email, RFC headers or old match/discovery rows. Binding is captured before fetch
  and revalidated under the workspace gate; a changed binding fails for fresh fetch.
- Missing binding/principal/native ID yields the existing unresolved observation
  representation, never a guessed strong identity. Contradictory scope is rejected.
- Same principal reconnect, changed email, disconnect and account recreation retain
  the same canonical namespace through the existing identity service.

`threadId` is stored only as existing `content.conversation_id` metadata. It never
supplies source identity, relevance, dedupe, linking, merging or posting ownership.
Distinct native IDs remain distinct sources even with identical RFC IDs/threads.

## Content, timestamps and compatibility

Selected headers preserve order and repetition through the existing allowlist.
Addresses preserve available From/Sender/Reply-To/To/Cc/Bcc lists. Retained plain
and HTML are the first inline MIME parts of their type; available empty text stays
available. Attachment parts, named file parts and nested message bodies are excluded
from retention. Matching retains its old plain-body behavior separately. HTML-only
mail has unavailable plain text; missing parts are unavailable, never synthesized.
Raw MIME stays transient and no attachment/storage pipeline is added.

The existing normalizer owns bounds, LF normalization of plain text, unchanged HTML,
UTF-8 prefix truncation and original-length/digest metadata. The existing 2 MiB
serialized input ceiling and other metadata limits still reject atomically; this
slice does not invent additional overflow or malformed-content recovery policies.

Valid nonnegative integral `internalDate` milliseconds become an aware instant with
`gmail_internal_date` provenance, not an assertion of certain SMTP receipt. Missing,
malformed or unrepresentable internal dates remain unknown, with no fallback to RFC
Date or sync time. RFC Date is a separate header-sent instant with original offset,
validated date-only claim, uncertain raw text, or unknown. Naive dates do not gain a
timezone, and date-only claims never gain midnight. Fetch observation time, first
retention time and sync cursor remain independent. No Application derivation,
activity, status history, Document or JobPosting write is introduced.

The single `_project_message()` path retains legacy match/discovery/posting-discovery
writes, RFC thread hints and URL extraction. They are compatibility projections,
not source identity. Missing RFC ID permits canonical retention with no projection.
Existing/dismissed projections are not recreated or resurrected. Two native IDs with
one RFC ID can retain two sources while the legacy UI still has one projection.
Conflicted retained observations cause no new projection. Unresolved observations
preserve pre-existing legacy compatibility behavior; that behavior does not establish
canonical identity or authorize any new retained-source downstream workflow.
Remove these projections when retained-backed review/relationship consumers replace
them, before legacy retirement. No second projection writer is introduced.

## Transactions, retry and concurrency

Gmail fetch/decode and relevance classification occur outside persistence transactions.
Each relevant message acquires the existing Workspace gate, revalidates binding,
retains source/observation/content, checks legacy duplicates and projects within one
atomic database transaction. Retention keeps its existing workspace → mailbox → key
→ source lock order. No provider I/O is performed there. Other providers retain their
prior whole-pass transaction and are not adopted into retention.

A fetch DTO gets a random observation key and actual observation time. Retrying that
same DTO preserves both; a fresh fetch gets a new observation, not a false key-reuse
conflict. Durable source uniqueness, not that key or content hashes, converges fresh
attempts to one canonical source. Same-key changed input and same-source changed
content keep the existing append-only conflict semantics and immutable canonical
content. No Gmail dedupe table, durable task/outbox or automatic retry loop is added.

A failed per-message persistence unit rolls back retention and projection together.
Earlier units remain committed and replay-safe. Cursor advancement waits for the
complete pass; retry can refetch safely. Final Gmail bookkeeping preserves a current
disconnected status rather than reviving it. Existing workspace gate plus uniqueness
serializes admitted same-workspace operations; SQLite may reject either/both competing
attempts. Tests explicitly retry original logical attempts after such refusal.

## Verification

Final verification on the implementation tree, including 30 new adoption tests.
All Django commands below ran from `backend/` with the existing `venv/`. No dependency installation,
real tracker migration or provider network operation is performed.

| Command | Result |
|---|---|
| `venv/bin/python manage.py test email_sync core.tests_workspace_scope core.tests applications.tests.test_derivation --noinput` | **394 passed**, exit 0, 48.369s |
| `venv/bin/python manage.py test --noinput` | **671 passed**, exit 0, 96.369s |
| `venv/bin/python manage.py check` | No issues, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run --verbosity 3` | Exit 1: only existing `0008_alter_emailaccount_provider` choice drift; no file written |
| `git diff --check` (repository root) | Passed, exit 0 |
| Local Markdown-link and new-file whitespace/mode checks (repository root) | Passed |

Focused coverage includes Gmail producer/adoption, identity/OAuth/credential lifecycle,
retained source/API/admin, sync matching/discovery/posting compatibility, workspace
isolation, deterministic derivation, migration preservation and logical concurrency.
The full Django run covers all installed applications. No Django failures remain.
The initial fixture failures were corrected to use actual accepted relevance phrases
and independent RFC references; no classifier relaxation was made.

The migration dry run was also executed before code edits on the exact checkpoint:
exit 1 solely for `0008_alter_emailaccount_provider`, changing EmailAccount.provider
choices. No file was generated. Final verification showed the identical proposal
and no retained-model drift. This known exception prevents claiming a clean global
migration check; fixing it is outside this slice.

The three legacy failures in the identity review are historical evidence only, not a
fresh legacy test run here:
`test_export_then_import_round_trips_notes_and_status`,
`test_export_then_import_round_trips_hub_settings` (both in
`tests/test_overrides_portability.py`, real-path PermissionErrors), and
`tests/test_status_history.py::test_deleting_an_application_clears_its_status_history`
(500 versus 200). `_app/` and frontend are unchanged. This slice's affected
legacy compatibility behavior is exercised by the Django email-sync regression suite.

## Changed files and remaining work

- `backend/email_sync/providers.py`: explicit native identity/content/observation DTO.
- `backend/email_sync/gmail_provider.py`: native locator propagation, MIME metadata,
  missing-RFC support and honest internal/header timestamp parsing.
- `backend/email_sync/gmail_retention.py` (new): verified binding/retention bridge.
- `backend/email_sync/sync_service.py`: unchanged relevance order, one compatibility
  writer and bounded Gmail persistence transaction.
- `backend/email_sync/tests/test_gmail_provider.py`: updated missing-RFC expectation.
- `backend/email_sync/tests/test_gmail_adoption.py` (new): synthetic adoption tests.
- `docs/DJANGO_MIGRATION_STATUS.md`: current checkpoint and verification/limits.
- `docs/DJANGO_GMAIL_ADOPTION_REVIEW.md` (new): this review and exact evidence.

No migration/model/schema, OAuth architecture, dependency, frontend, Outlook/IMAP
provider, real data or generated environment file changes. No secrets or personal
mail fixtures. Retained inspection and admin remain read-only.

Next dependency unlocked: relevant Gmail sources are available through existing
read-only retained inspection for a separately authorized review/relationship slice.
Historical reconciliation, retained review mutations, ApplicationMessage, PostingSource,
JobPosting ingestion, generated evidence and its unresolved replacement/supersession
policy, Outlook/IMAP adoption, frontend integration, import/export and cutover remain
pending. This is not completion of the broader email migration.

SQLite verifies deterministic application behavior and logical replay, not PostgreSQL
row locking/isolation, contention, deadlocks, pools or production worker concurrency.
Synthetic Gmail fixtures do not certify live consent/reconnect/refresh/revocation,
pagination, rate limiting, network interruptions, all MIME variants, migrated-mail
edge cases or long-running sync. PostgreSQL, live Gmail, storage, Redis/Celery/Beat,
backup/restore and operational cutover remain separate gates.
