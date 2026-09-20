# Gmail mailbox identity and durable lineage foundation

Bounded implementation on `django-migration`, based on
`2f0cd1f62ae52d7a3695d05925eb9ad5353a849a` (retained-email foundation).
Implementation remains uncommitted for human review. Gmail retained-message
producer adoption is **not** part of this slice.

## Repository and authority

The initial clean root, branch, HEAD, local tracking reference and live remote
matched the supplied checkpoint. On resume, the same root/branch/HEAD held and
nine modified files plus three untracked files were present, all from this slice.
No reset, stash, checkout, data migration on a real tracker, dependency installation,
commit or push was performed. Decisions and Foundations remain unchanged.

Inspected: Decisions, Foundations, Status, migration plan, retained-email review;
Gmail OAuth/callback/provider, credential/account models, retained models/service/API,
admin, migrations, Gmail/retention/migration/core/workspace tests, sync orchestration,
and the installed Google verifier/OAuth credential-construction code.

Confirmed transitional behavior: Gmail fetches native IDs and raw MIME, but the
adapter still emits RFC Message-ID and drops messages without that header. Native
thread IDs are not durable source identity. Invalid/missing internalDate becomes
unknown, without a header-Date substitute. Sync still writes legacy account-scoped
matches/discoveries/posting discoveries; it does not call retained-email authority.

## Provider identity decision and research

Google OIDC `sub` is the principal, under the fixed `google_oidc_sub` namespace
and `gmail` provider. Google documents it as case-sensitive, unique across Google
Accounts, never reused and unchanged across email changes. It is therefore account
identity across refresh and reauthorization, not the token's identity. See the
[Google OIDC reference](https://developers.google.com/identity/openid-connect/reference).

Google's [discovery metadata](https://accounts.google.com/.well-known/openid-configuration)
advertises public subjects and RS256 ID tokens. This supports using a Google Account
subject rather than a client-specific subject. Client changes still require the new
configured audience to validate and may require fresh authorization; existing grants
are not silently transferred. Workspace/domain accounts use the same account subject
contract; neither email domain nor `hd` establishes continuity. Account recreation is
not inferred from a reused address. Domain/account edge cases remain live-validation work.

Gmail [users.getProfile](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile)
returns email, counts and current history ID, not a stable account principal. Email,
OAuth credential IDs/tokens, RFC metadata, and Gmail message/history IDs were rejected
as principal substitutes. UserInfo was considered, but adds another identity request;
the code exchange already exposes an ID token through the installed library.

New authorization requests exactly `openid`, `email`, and
`https://www.googleapis.com/auth/gmail.readonly`. Previously only the last scope was
requested. The user explicitly approved the two identity scopes; `profile` was not
added. The [Google server-flow guide](https://developers.google.com/identity/openid-connect/openid-connect)
documents `openid email` and the authorization-code exchange. Consent/Cloud Console
configuration, organization policies and actual responses remain operational checks.

## Assertion validation and credential handling

`google-auth-oauthlib` exposes the exchange's `id_token` on `Credentials`; it does
not itself verify that assertion. `_verified_google_sub` calls the installed
`google.oauth2.id_token.verify_oauth2_token` with the configured client ID. The
[Google library verifier](https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.id_token.html)
validates signature, Google issuer, audience and token times using Google's keys.
The implementation also requires integer iat/exp, an unexpired assertion, the exact
client audience, matching azp if present, and a nonempty ASCII subject of at most
255 characters. NUL is rejected as an invalid storage value. Subjects are never
trimmed, case-folded, parsed as numbers or hashed.

The required server-flow `at_hash` is checked against the access token used for
Gmail `users/me`, using the RS256 SHA-256 half-digest rule. Missing/mismatching
binding fails before database writes. Gmail's profile email is validated as metadata.
No email equality check stands in for assertion or access-token verification.

The existing authorization-code flow retains state and PKCE; it requests no OIDC
nonce (optional for this response_type=code flow). Callback state is consumed and
saved before exchange, including 5xx outcomes for which Django session middleware
would otherwise skip saving. Verification errors return a generic 400
`gmail_identity_unverified`; ambiguous/conflicting account state returns 409
`gmail_identity_conflict`. SQLite lock contention returns 503
`gmail_connection_busy`, requiring a new authorization rather than replaying a used
code. No principal or provider secrets appear in those responses.

Tokens remain only in the existing encrypted credential store; ID tokens are not
persisted. Lineage stores only principal and fixed provenance, with first-verification
and first-binding timestamps. No credentials, token claims blob, authorization code,
client secret, or email history is stored as lineage identity.

## Schema and authority

`email_sync.0007_gmail_mailbox_identity` contains two CreateModel operations only:

- `MailboxPrincipal`: protected Workspace and one-to-one MailboxLineage references,
  provider, namespace, opaque value, first `verified_at`. Database uniqueness covers
  `(workspace, provider, namespace, value)` and one principal extension per lineage.
- `AccountMailboxBinding`: one-to-one current EmailAccount and MailboxLineage
  references, with first `bound_at`. Account deletion cascades only the binding;
  the mailbox reference is protected. One current account binding per lineage.

The migration depends on `accounts.0001_initial` and
`email_sync.0006_retained_email_foundation`; it does not depend on unrelated
derivation fields. No old table/column is changed and no backfill runs. Absence of
principal/binding rows is the safe legacy-unverified representation. The known
EmailAccount.provider choice drift is deliberately outside this migration.

The existing `retention.py` authority resolves the verified principal and allocates
through `establish_mailbox` only when necessary. It does not authenticate arbitrary
strings: its internal OAuth caller must first verify the assertion. Existing
unverified lineages are not searched or merged using email/provenance resemblance.
No public principal-write endpoint or parallel mailbox authority was introduced.

New identity/binding rows reject ordinary edits, including writes through a fresh
model instance with an existing PK. Model guards check workspace/provider consistency.
Admin add/change/delete is disabled for both models. Bound EmailAccount workspace and
provider are read-only in admin and protected on ordinary model saves. Privileged
bulk ORM/raw SQL remain maintenance surfaces, not supported identity-edit workflows.

## Connection and lifecycle behavior

| Situation | Implemented outcome |
|---|---|
| First verified principal in workspace | One durable lineage/principal and prospective account binding; no retained message |
| Same principal, new credentials | Same lineage and account; credentials replaced atomically |
| Same principal, changed email | Same identity; account email changes; email-derived display name follows, custom name remains |
| Different principal, same already-bound email | Deterministic conflict; prior identity, account and credentials untouched |
| Different principals and nonconflicting addresses | Separate lineages/accounts |
| Multiple legacy accounts at matching address | Conflict, all preserved; no arbitrary winner |
| Single unbound legacy account | May be bound prospectively using current verified identity and a fresh refresh token; history is neither promoted nor reconciled |
| Changed email collides with another account | Conflict; no account/history merge |
| Same principal in different workspaces | Independent lineages and account bindings; no retained-content sharing |
| Disconnect/credential replacement | Principal, lineage, binding and retained evidence survive |
| Account deletion and later recreation | Binding disappears; principal/lineage/evidence survive and future authorization resolves them |

Existing accounts are not forced through reauthorization or guessed into identity.
A new binding requires a newly supplied offline refresh token: an unverified legacy
refresh token cannot be carried forward as proven identity. An already-verified
binding can retain its existing refresh token when Google omits a replacement.

Routine refresh honors recorded scopes. Empty historical scope metadata falls back
only to gmail.readonly, never the new identity scopes. Refresh does not establish
identity even if a response happens to expose an ID token. A slow refresh compares
its original credential episode under the workspace/credential locks before storing;
reconnect replacement or disconnect causes a temporary failure without overwriting
or recreating credentials, and without marking the current account blocked.

## Idempotency, concurrency and preservation

Connection identity/account/credential writes commit together under the existing
Workspace transaction gate. PostgreSQL workspace row locking serializes same-workspace
allocations; SQLite takes its existing write gate. Database uniqueness backs principal
and binding convergence. Retry does not churn lineage portable IDs, establishment or
verification/binding timestamps, account creation time, or unchanged account metadata.
Credential timestamps may change when refreshed/replaced.

Deterministic tests cover repeated and competing same-principal establishment and
connection binding, explicit retry after SQLite lock refusal, mismatch rollback,
credential-write failure rollback, and stale refresh interleavings. These are logical
contracts, **not PostgreSQL operational validation** of uniqueness races, reconnect
races, row-lock behavior or account/binding updates.

Isolated populated forward migration checks compare every pre-existing table column
and row, including credentials and retained lineages/messages/observations. New identity
and binding tables remain empty; forward replay is a no-op. Migration reversal is not
used for validation: dropping these new tables after adoption would lose new identity
metadata and is not a real-data rollback authorization.

## Verification

Final verification on 2026-09-20, after all code/migration/test corrections. Django
commands ran from `backend/`; other commands ran from repository root. Existing
virtual environments and bundled Node were reused. No dependency changes.

| Command | Final result |
|---|---|
| `venv/bin/python manage.py test email_sync.tests.test_gmail_identity email_sync.tests.test_gmail_identity_migrations email_sync.tests.test_oauth email_sync.tests.test_gmail_oauth_views email_sync.tests.test_gmail_provider email_sync.tests.test_retention email_sync.tests.test_retention_migrations core.tests core.tests_lifecycle_migrations applications.tests.test_derivation_migrations --noinput` | **125 passed**, exit 0, 28.985s |
| `venv/bin/python manage.py test email_sync accounts core applications documents postings --noinput` | **641 passed**, exit 0, 95.016s |
| `venv/bin/python manage.py test --noinput` | **641 passed**, exit 0, 95.628s |
| `venv/bin/python manage.py check` | No issues, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run --verbosity 3` | Exit 1: only known EmailAccount.provider choice AlterField, proposed as `0008_alter_emailaccount_provider`; not written |
| `/Users/dev/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --test tests/frontend/*.test.cjs` | **8 passed**, exit 0 |
| `.venv/bin/python -m pytest` | **367 passed, 3 known failures**, 2 warnings, exit 1, 7.21s |
| `git diff --check` | Passed, exit 0 |
| Local Markdown link check for this report and Status | Passed |

The 35 new tests (34 identity/security/lifecycle/concurrency and one populated
migration test) are included in those successful runs. Migration preservation
checks passed against isolated populated temporary SQLite databases, including the
existing retained-foundation preservation test and earlier lifecycle/derivation
upgrade checks. No real tracker was migrated. New-table contents remain empty at
upgrade; no principal or binding is invented from old accounts or email addresses.

Legacy failures exactly match the supplied baseline:

1. `tests/test_overrides_portability.py::test_export_then_import_round_trips_notes_and_status`
2. `tests/test_overrides_portability.py::test_export_then_import_round_trips_hub_settings`
3. `tests/test_status_history.py::test_deleting_an_application_clears_its_status_history`

The first two still fail with the real-path PermissionError; the third still returns
500 rather than 200. No new legacy failure appeared; no escalation to modify real
tracker data was attempted. These results do not claim a fully green repository.

Tests use isolated fixtures, generated synthetic signing keys and synthetic subjects.
The complete tracked diff, new migration/tests/report and final status were inspected.
No new real credentials, ID tokens, provider identifiers or authentication secrets
were added. Gmail producer identity/content code, `_app/`, frontend and dependencies
are unchanged.

## File inventory and resume history

Already modified on resume:
`backend/config/settings/base.py`, `backend/email_sync/admin.py`,
`backend/email_sync/models.py`, `backend/email_sync/oauth.py`,
`backend/email_sync/retained_models.py`, `backend/email_sync/retention.py`,
`backend/email_sync/views.py`, `backend/email_sync/tests/test_oauth.py`,
`backend/email_sync/tests/test_gmail_oauth_views.py`.

Already untracked on resume:
`backend/email_sync/migrations/0007_gmail_mailbox_identity.py`,
`backend/email_sync/tests/test_gmail_identity.py`,
`backend/email_sync/tests/test_gmail_identity_migrations.py`.

Resume work added `backend/core/tests.py` to the changed-file set for intentional
read-only admin expectations, this report, and `docs/DJANGO_MIGRATION_STATUS.md`.
It completed assertion/immutability guards, callback state persistence, legacy refresh
regressions and stale-write protection, connection concurrency tests, and narrowed the
new migration's dependency. No existing migration was rewritten.


Final `git status --short` (all changes unstaged):

```text
 M backend/config/settings/base.py
 M backend/core/tests.py
 M backend/email_sync/admin.py
 M backend/email_sync/models.py
 M backend/email_sync/oauth.py
 M backend/email_sync/retained_models.py
 M backend/email_sync/retention.py
 M backend/email_sync/tests/test_gmail_oauth_views.py
 M backend/email_sync/tests/test_oauth.py
 M backend/email_sync/views.py
 M docs/DJANGO_MIGRATION_STATUS.md
?? backend/email_sync/migrations/0007_gmail_mailbox_identity.py
?? backend/email_sync/tests/test_gmail_identity.py
?? backend/email_sync/tests/test_gmail_identity_migrations.py
?? docs/DJANGO_GMAIL_IDENTITY_REVIEW.md
```

Final scope is **15 files: 11 tracked modifications and 4 new files**. The tracked
`git diff --stat` reports 285 insertions and 55 deletions; it excludes the four
untracked files listed above. No unrelated change entered the final tree.

## Remaining gates

Gmail retained-source producer adoption is pending: no native message/thread-ID
propagation, retained content/observation writes from sync, historical reconciliation,
review relationships, posting bridge, evidence generation, or frontend work. Outlook
and IMAP identity/adoption are unchanged and pending. Retained GET/HEAD remains
read-only, makes no Google calls, and does not expose the principal value.

No live Google consent, identity response, refresh/revocation, reconnect, Workspace-domain
edge cases or account-stability experiment was performed. No PostgreSQL, worker,
production-storage, restore or cutover validation is claimed. Existing migration-stage
and three legacy test limitations remain; this slice is not production readiness.
