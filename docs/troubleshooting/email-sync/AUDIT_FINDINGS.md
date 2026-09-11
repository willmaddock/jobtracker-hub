# Email Sync — Audit Findings

Audit of the Email Sync feature (Job Postings / Needs Triage / Applications
board) against real usage: 111 tracked applications, 73 discoveries, 6
promoted job postings, across 6 connected Mail.app accounts (see
`tests/test_audit_findings.py` for the regression suite this audit produced,
and the anonymized `overrides.db` used to confirm each finding against real
data).

Findings are numbered to match the existing references in
`tests/test_audit_findings.py` and `_app/api.py`'s inline comments. Findings
1–3 predate this pass (single-item-company routing, and the URL/job
positional-count-mismatch safety net) and are already fixed — see those
files' own comments for detail. **Findings 4 and 5 below are new, from this
audit**, reported by the user as "no links on job postings" and "some emails
never load ('Couldn't load the original email'), some do."

---

## Finding 4 — Job Postings almost never get an "Open job" link

**Symptom:** every card in the Job Postings column renders with no "Open
job" button. Confirmed against the real `overrides.db`: **6/6 promoted
job_postings and all 17 posting-kind discoveries had `posting_url = NULL`**
— a 100% failure rate, not an occasional miss.

**Root cause:** `mail_app_store.extract_posting_urls()` rejected any URL
containing the substring `utm_` as a "non-posting" link (grouped with
`unsubscribe`, `optout`, `privacy`, etc.). In practice, LinkedIn — and most
ATSs — attach `utm_*`/`trk=` tracking parameters to their **real** per-job
listing links in every alert email. There is effectively no such thing as an
untracked LinkedIn job link in an email body. The filter meant to catch
tracking pixels and footer boilerplate was instead catching the one link
every job-alert email actually needs.

This also fed a secondary, compounding effect: `_extract_and_store_job_postings()`
(in `api.py`) only trusts positional URL-to-job pairing when
`len(urls) == len(jobs)` exactly (the Finding 3 safety net, working as
intended). Once `utm_` zeroed out `urls` entirely, that count was always
`0`, so even single-job emails with one obvious link got nothing — this
wasn't limited to multi-job digests.

**Fix applied** (`_app/mail_app_store.py`):
- Removed `utm_` from `_NON_POSTING_URL_HINTS`. Tracking parameters don't
  stop a URL from opening the correct job page, so they're not a reason to
  discard it.
- Added a separate, narrower `_GENERIC_COLLECTION_URL_HINTS` list
  (`/jobs/search`, `/jobs/collections`, `/jobs?`, "view all", `/alerts/`,
  `/digest/`, etc.) to filter out genuine digest-header "view all N jobs"
  links *before* the count comparison, so a digest's one extra header link
  no longer inflates the URL count and silently zeroes out every job's link
  the way Finding 3's safety net would otherwise (correctly) trigger on.
- No change to the count-mismatch safety net itself — a real, unresolvable
  mismatch still results in no link, per Finding 3's "no fake pairing" rule.

**Regression tests:** `tests/test_audit_findings.py` —
`test_extract_posting_urls_no_longer_rejects_real_links_with_tracking_params`,
`test_extract_posting_urls_still_filters_generic_view_all_link`,
`test_single_job_single_tracked_link_now_gets_a_real_posting_url_end_to_end`.

**Not fixed by this change:** postings promoted *before* this fix shipped
still have `posting_url = NULL` stored — there's no automatic backfill
for already-promoted `job_postings` rows, since extraction only ever ran
once, at sync time. `scripts/troubleshooting/backfill_job_posting_urls.py` (added in this
audit) covers that: it re-fetches each affected message, re-runs the same
extraction + count-matched URL pairing under the fixed filter, and
updates only the `posting_url` column on matching rows. Dry-run by
default; `--apply` to write, with a timestamped `overrides.db` backup
first. Smoke-tested end-to-end against a real 6-job LinkedIn digest
fixture (`tests/fixtures/email-source/linkedin_job_alert_haystack.pdf`)
with synthetic tracked links standing in for Mail.app — all 6 rows
matched and updated correctly by title, and a second run correctly found
nothing left to do.

---

## Finding 5 — "Couldn't load the original email" (some senders load, some never do)

**Symptom:** clicking to preview a discovery's email sometimes shows the
body, sometimes shows "Couldn't load the original email (it may have moved
or been deleted since this was found)" — inconsistently, seemingly by
sender (e.g. Forbes Business Council never loaded across multiple screenshots,
while KPMG loaded fine).

**Root cause:** `mail_app_store.get_message_preview()` searched only the
`INBOX` mailbox — the same mailbox `search_messages()`/
`search_unmatched_messages()` use at scan time — and returned `None`
(rendered as "couldn't load") the instant the message wasn't found there,
with no fallback. Discoveries routinely sit unreviewed for months (several
in the real tracker are 5+ months old). By the time a user gets around to
reviewing one, it's entirely plausible Mail.app or the IMAP provider itself
has since filed the message elsewhere — archived, marked read and
auto-moved by a rule, or (for Gmail specifically) no longer surfaced under
the Inbox label. None of that means the message is gone; it just isn't in
`INBOX` anymore. The lookup was by exact Message-ID, not by mailbox
position, so this was pure bad luck about *when* the user got to it — not
an inherent limitation of any specific sender.

**Fix applied** (`_app/mail_app_store.py`): `get_message_preview()` now
tries `INBOX` first (unchanged, cheapest/most common case), and only if
that misses, falls back to scanning every other mailbox on the account for
the same Message-ID before giving up. This mirrors the same
"search broadly, don't assume Inbox is still where it landed" approach
already used elsewhere in this file's mailbox resolution helper.

**Regression tests:** `tests/test_audit_findings.py` —
`test_get_message_preview_falls_back_to_other_mailboxes_when_not_in_inbox`,
`test_get_message_preview_still_returns_none_when_truly_gone_from_every_mailbox`.

**Known remaining limitation:** if a message has been permanently deleted
(not just moved) since the scan, or the account itself has been
disconnected, preview will still correctly show "couldn't load" — this fix
addresses the "moved, not gone" case, which is the overwhelmingly common
one for discoveries that sit for weeks/months, not the deleted case.

---

---

## Finding 6 — Job Postings *still* got no link, even after Finding 4's fix

**Symptom:** after shipping Finding 4's `utm_` filter fix, a real 6-job
LinkedIn digest still produced zero links. Debugging showed
`extract.extract_urls()` found **0 raw URLs at all** in the message body --
not a filtering problem, a "there was never a URL here" problem.

**Root cause:** `extract_posting_urls()` (and everything upstream of it,
including Finding 4's fix) only ever operates on the string
`get_message_preview()` returns, which is AppleScript's `content of msg`
-- Mail.app's own **plain-text rendering** of the message, not the raw
email. For an HTML email, that rendering keeps a link's visible button
text ("View job") but discards the underlying `<a href="...">` URL
entirely, because the URL only ever existed in markup the plain-text
conversion strips out. Finding 4's `utm_` fix was correct on its own terms
-- it just never had a real URL to act on for an HTML email, only for the
plain-text test fixtures that happened to contain literal `http://`
strings.

Confirmed against the real message's raw MIME source (`source of msg`
instead of `content of msg`): 16 real `href="..."` values decoded fine
from quoted-printable, and the 6 job links among them
(`/comm/jobs/view/<id>`) lined up exactly with the 6 stuck `job_postings`
rows. This also explained why the domain-allowlist theory from an earlier
session was correct but for the wrong reason: LinkedIn's email links route
through `/comm/jobs/view/...`, not `/jobs/view/...`, so
`_JOB_POSTING_URL_DOMAINS`'s `"linkedin.com/jobs"` entry wouldn't have
matched even once the right body was being read.

**Fix applied** (`_app/mail_app_store.py`):
- `get_message_source()` -- AppleScript's `source of msg` (raw MIME),
  with the same "search broadly" mailbox fallback as
  `get_message_preview()`.
- `extract_html_source_urls()` -- parses the MIME structure with Python's
  `email` library (which handles quoted-printable/base64
  Content-Transfer-Encoding decoding for us), pulls every `href="..."`
  out of each `text/html` part, HTML-unescapes it, normalizes LinkedIn's
  `/comm/` redirector and strips its tracking query string, and runs the
  result through the same domain/exclusion filters as
  `extract_posting_urls()`.
- `get_posting_urls_for_message()` -- the function callers should use:
  tries the raw-source path first, falls back to the old
  `extract_posting_urls(body)` plain-text path if the source fetch fails
  (`MailAppError`) or the HTML source has no matching links (e.g. a
  plain-text-only email).
- Wired into both call sites that used to call `extract_posting_urls(body)`
  directly: `api.py`'s `_extract_and_store_job_postings()` (sync-time
  extraction) and `preview_discovery()` (lazy on-demand extraction for a
  posting-kind discovery that doesn't have a stored link yet).

**Regression tests:** `tests/test_audit_findings.py` --
`test_extract_html_source_urls_recovers_real_job_links_from_html_email`,
`test_extract_html_source_urls_handles_missing_or_garbage_input`,
`test_get_message_source_uses_source_of_msg_not_content_of_msg`,
`test_get_message_source_returns_none_when_not_found`,
`test_get_posting_urls_for_message_prefers_html_source_over_plaintext_fallback`,
`test_get_posting_urls_for_message_falls_back_when_source_has_no_links`,
`test_get_posting_urls_for_message_falls_back_on_mail_app_error`,
`test_get_posting_urls_for_message_empty_when_nothing_found_anywhere`,
`test_linkedin_digest_end_to_end_now_recovers_all_six_job_links`.

**Not fixed by this change:** same caveat as Finding 4 -- postings
promoted before this fix shipped still have `posting_url = NULL` stored
if their message's raw HTML source genuinely has no matching link either
(a plain-text-only email, or an ATS whose links this app doesn't
recognize). `scripts/troubleshooting/backfill_job_posting_urls.py` was itself calling
`extract_posting_urls(body)` directly (the old plain-text-only path) and
has been updated in this same pass to call
`get_posting_urls_for_message()` instead, so it now benefits from the
raw-source path too -- re-run it (dry-run first, `--apply` to write) to
pick up your 6 existing NULL `job_postings` rows now that both this fix
and its own update are in place.

---

## Finding 7 — Intermittent "database is locked" right after opening the app

**Symptom:** `/api/discoveries` and `/api/job-postings` occasionally
return `500 sqlite3.OperationalError: database is locked`, specifically
inside `overrides_store.get_conn()` at `PRAGMA journal_mode=WAL` --
observed right after a workspace import/switch/rebuild, when the SPA
frontend fires its usual burst of near-simultaneous requests
(`/api/discoveries`, `/api/job-postings`, `/api/applications`,
`/api/accounts`, `/api/status`) on page load. Never seen once the app had
been running a few seconds.

**Root cause:** `api.py`'s `get_conns()` opens a brand-new sqlite3
connection per request rather than reusing one, and `get_conn()`
unconditionally ran `PRAGMA journal_mode=WAL` on every single call.
Switching a database's journal mode to WAL for the *first* time requires
SQLite to briefly get exclusive access to the file; two near-simultaneous
first connections against a freshly created/rebuilt database can collide
on that PRAGMA specifically, and the resulting `SQLITE_BUSY` surfaced as
`database is locked` rather than being retried the way ordinary row reads
and writes already are via `busy_timeout`.

**Fix applied** (`_app/overrides_store.py`): `get_conn()` now checks the
database's current `journal_mode` first and skips the `PRAGMA
journal_mode=WAL` call entirely once it's already `"wal"` -- true for
every request after the very first against a given file, which is also
the only place the race can occur. For the one remaining first-time
switch, `_ensure_wal_mode()` retries a `sqlite3.OperationalError`
containing "locked" with a short backoff (up to 5 attempts) instead of
letting it fail the request outright; any other `OperationalError` (e.g.
a genuine disk error) still raises immediately.

**Regression tests:** `tests/test_audit_findings.py` --
`test_ensure_wal_mode_skips_pragma_when_already_wal`,
`test_ensure_wal_mode_retries_transient_lock_instead_of_raising`,
`test_ensure_wal_mode_reraises_non_lock_errors_immediately`.

**Not fixed by this change:** `get_conns()` still opens a fresh
connection (and re-runs schema/migration statements) on every request --
this fix removes the one operation that could exclusive-lock the file,
but a connection-pooling or per-process-singleton-connection change would
be a larger, separate refactor if per-request connection overhead itself
becomes a problem.

---

## Finding 8 — Attaching an email to an *existing* application crashed mid-flow, and even fixed, saved no evidence PDF

**Symptom (part A — crash):** Using "Pick application…" in Needs Triage to
attach a Needs-Triage email to an existing item (as opposed to accepting it
as a brand-new discovery) threw a `ReferenceError` in the browser console
mid-click. The item's status override *did* get written (the fetch to
`/api/discoveries/{id}/attach` completed), but the UI never bumped the row
out of Needs Triage or refreshed the applications/status views, so the app
looked stuck/broken even though the backend call had actually succeeded.

**Root cause:** `_app/frontend/index.html`'s `quickAttach()` had a stray
`setResolvingIntent(null)` call left over from an earlier refactor —
`resolvingIntent`/`setResolvingIntent` isn't a declared state setter
anywhere in the component. Calling it throws immediately, which aborted
the rest of `quickAttach()` before it reached the status-override write,
`refreshApps()`, and `refreshStatus()` calls that follow it.

**Fix applied:** Deleted the stray `setResolvingIntent(null)` line. No
other code in the file references that name, so this is a clean one-line
removal — the rest of `quickAttach()` (status override, history entry,
refreshApps/refreshStatus) already existed and runs correctly once nothing
throws before it.

**Symptom (part B — missing evidence, found while verifying the fix):**
Once the crash no longer interrupted the flow, the item's status updated
correctly, but the source email never showed up as an attached PDF on the
item — "Attached Documents" count didn't increase.

**Root cause:** `attach_discovery()` (the existing-item path) only ever
called `ov.add_thread_identifiers()` and `ov.set_discovery_status()` — it
recorded the match and cleared the row from Needs Triage, but never called
`_save_email_evidence_pdf()`. `accept_discovery()` (the brand-new-item
path) has always called that helper. Attaching to an existing application
was simply never wired up to produce evidence; this is unrelated to the
Finding-8-part-A crash and would have existed even without it.

**Fix applied** (`_app/api.py`): `attach_discovery()` now calls the same
`_save_email_evidence_pdf()` helper `accept_discovery()` already used,
writing an `Email - <subject>.pdf` into the existing item's folder and
indexing it immediately (documents + documents_fts) so it appears without
needing a manual rebuild. Best-effort and non-blocking, matching the
existing-item flow's tolerance for a missing/renamed folder or a Mail.app
hiccup — a save failure there logs but does not undo the match that
already succeeded.

**Regression tests** (`tests/test_email_pdf.py`):
`test_attach_discovery_saves_email_as_pdf_on_existing_item`,
`test_attach_discovery_still_links_when_pdf_save_fails`. Full suite run
by the user on their machine: 370/370 passed.

**Not fixed by this change:** matches made via "Pick application…"
*before* this fix shipped still have no evidence PDF on file. The existing
"Backfill missing email PDFs" button (Email Sync page) covers this, but
only for folders with zero existing `Email - …` PDFs, and it needs a live
Mail.app on the user's machine to re-fetch the body (can't be run from a
sandboxed Claude session). For the one real case hit this session
(American Systemes / `willzaeagle@gmail.com`), the actual uploaded
`FollowUp__Java_Developer_l.pdf` was renamed to the app's convention and
indexed directly into the working DB rather than waiting on Backfill.

**Branches:** Fixed on `main` (`2621fff` crash, `c4dd50e` evidence-PDF) and
cherry-picked onto `django-migration` (`810b5c7` crash, `e4fbd7a`
evidence-PDF). `django-migration`'s `_app/` tree is the same single-user
FastAPI app as `main`'s — see the scope note at the top of
`CLAUDE_HANDOFF.md` on that branch — so this bug and fix apply there
identically. It does **not** apply to that branch's separate `backend/`
Django/Gmail-OAuth email-sync rewrite, which has its own attach flow and
its own handoff (`docs/DJANGO_BACKEND_HANDOFF.md`) and was not touched.

---

## Finding 9 — "database is locked" on `/override` saves, persisting well past `busy_timeout` (root cause still open)

**Symptom:** `POST /api/applications/{id}/override` intermittently returns
`500 sqlite3.OperationalError: database is locked` from inside
`upsert_override()` → `_execute_with_retry()`, across several different
item IDs in the same run. Unlike Finding 7, this isn't confined to the
first few requests after startup — it was observed well into a session,
after `get_conns()` had already been called successfully many times.

**What's different from Finding 7:** Finding 7's race is bounded by
design — `busy_timeout=30000` plus `_execute_with_retry()`'s own backoff
(4 attempts) should together absorb any ordinary in-process contention
long before either gives up. In the session that surfaced this finding,
the lock survived *both* of those, repeatedly. That duration doesn't
match contention between two of this app's own SQLite connections —
something else was holding the file.

**Fixed this session (real bugs, but partial mitigations — see below):**
- `_app/overrides_store.py` `get_conn()`: implements the fix Finding 7
  explicitly flagged as *not* done — `executescript(SCHEMA)` and
  `_migrate()` no longer re-run on every request. They're idempotent but
  each still briefly needs a write lock; re-acquiring it on every single
  API call added up during request bursts. Now gated by `_SCHEMA_READY`
  (a per-process set of already-migrated db paths), so it only runs once
  per db path per process.
- `_app/api.py` `save_override()`: `jt_conn`/`ov_conn` are now closed in
  a `finally` block. Previously they were only closed on the success
  path — every failed save (including every "database is locked" 500)
  leaked both connections. An accumulating pile of open, uncommitted
  connections against the same file is exactly the kind of thing that
  can make a lock outlast what a single well-behaved writer would
  produce, so this is a plausible contributor even though it wasn't
  confirmed as *the* root cause.

**Investigated and ruled out:** iCloud Drive's "Desktop & Documents
Folders" sync was suspected, since the project lives under
`~/Documents/GitHub/jobtracker-hub` and that sync daemon is a
well-documented cause of exactly this symptom (long OS-level file holds
outside SQLite's control). Checked directly in System Settings on the
affected Mac — the toggle is off. Ruled out.

**Still open — not root-caused.** The two fixes above are real
inefficiency fixes but neither was confirmed to be the actual cause of a
lock outlasting both `busy_timeout` and the retry loop. **Next step
(handed to the user, not yet done):** the moment "database is locked"
appears in the `uvicorn` terminal, run `lsof | grep overrides.db` in a
second terminal to see every process currently holding the file open —
PID and process name will say definitively whether it's a second
Python/uvicorn process, Spotlight's `mdworker`, `backupd` (Time Machine),
or something else. Do this before making further code changes here;
guessing again without that data isn't worth it.

**Regression tests:** none added this session — the two fixes above are
untested by `tests/test_audit_findings.py` or `tests/test_overrides_store.py`
as of this writing. Worth adding once the underlying cause is confirmed,
so the fix that actually matters gets a real regression pin instead of
being inferred from a code diff.

---

## Verification

Findings 4 and 5 were verified against the real testing `overrides.db`
extracted from the field-reported symptoms, and against the full test
suite:

```
$ python3 -m pytest tests/ -q
313 passed
```

(304 pre-existing + 9 new/updated in `tests/test_audit_findings.py` for
Findings 4 and 5.)

Findings 6 and 7 add 14 more tests to `tests/test_audit_findings.py`
(11 exercising `mail_app_store` / `overrides_store` functions directly --
all confirmed passing by running them standalone, since this environment
had no network access to install `fastapi`/`pytest`; and 3 end-to-end
tests that go through the FastAPI `TestClient` fixture, which need
`pytest -q` run on a machine with those packages installed to confirm).
**Run the full suite once more on your machine before considering this
audit closed:**

```
$ cd _app && pip install -r requirements.txt && pip install -r ../requirements-dev.txt
$ cd .. && python3 -m pytest tests/ -q
```

## What's not a bug

- The "Loading email…" placeholder briefly shown before either a body or
  the "couldn't load" message appears is expected — `preview_discovery()`
  is deliberately lazy/on-demand (fetches on open, not at scan time), so
  there's always a brief round-trip.
- Discoveries and promoted Job Postings are separate tables
  (`discovered_matches` vs `job_postings`); a posting still appearing in
  Needs Triage after being marked as a posting, or vice versa, is a
  display/lifecycle question outside this audit's scope, not related to
  either finding above.
