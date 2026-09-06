# Email Sync — troubleshooting

Start here if the Email Sync feature (Mail.app discovery → Needs Triage →
Job Postings board) is misbehaving for a real user, or if you're an AI
session picking up work on it cold. This folder exists so that starting
point doesn't require reading the full living handoff first.

## Quick diagnosis table

| Symptom | Look at |
|---|---|
| Job Postings cards have no "Open job" link | [`AUDIT_FINDINGS.md`](AUDIT_FINDINGS.md) Finding 4 (and Finding 6, a second regression of the same symptom) |
| "Couldn't load the original email" on some/all discoveries | [`AUDIT_FINDINGS.md`](AUDIT_FINDINGS.md) Finding 5 |
| Intermittent "database is locked" right after launch | [`AUDIT_FINDINGS.md`](AUDIT_FINDINGS.md) Finding 7 |
| A tracker's existing data has stale `posting_url = NULL` rows from before a fix | `scripts/troubleshooting/backfill_job_posting_urls.py` |
| Flood of bogus account matches from short role-term over-matching (e.g. "IT", "PM") | `scripts/troubleshooting/cleanup_bogus_account_matches.py` |
| `extract_posting_urls()` finds zero/wrong links for a specific real email | `scripts/troubleshooting/debug_extract_urls.py`, then `debug_raw_source.py` if that finds zero raw URLs too |
| Need to wipe Email Sync state without touching applications/documents | `overrides_store.reset_email_sync()` / `/api/accounts/reset-email-sync`, covered by `tests/test_reset_email_sync.py` |

## Documents in this repo, in reading order

1. **[`AUDIT_FINDINGS.md`](AUDIT_FINDINGS.md)** (this folder) — numbered,
   symptom-first writeups of real bugs found against real user data
   (111 applications / 73 discoveries / 6 accounts). Each finding names
   its root cause, the fix, and the regression test that pins it down.
   This is the fastest path from "user reported X" to "here's why and
   here's the test."
2. **[`../../specs/discoveries-board-v2-spec.md`](../../specs/discoveries-board-v2-spec.md)**
   — the original design spec for the Email Sync / discoveries board.
   Background on *why* the board is shaped the way it is, not a bug log.
3. **[`../CLAUDE_HANDOFF.md`](../CLAUDE_HANDOFF.md)** — the
   single living handoff for this feature (and the project generally).
   It's long (2000+ lines) but authoritative and current; code comments
   across `_app/` cite specific section numbers from it (e.g. "section
   8", "section 15"). If a code comment cites a section that doesn't
   seem to match, the handoff has moved on since — search it by keyword
   rather than trusting an old section number.
4. **[`../../archive/handoffs/HANDOFF.md`](../../archive/handoffs/HANDOFF.md)**
   and **[`HANDOFF_SESSION16_LEGACY.md`](../../archive/handoffs/HANDOFF_SESSION16_LEGACY.md)**
   — superseded handoffs, kept only for history. Not the active doc.

## Known documentation gap

Several `_app/*.py` and `_app/frontend/index.html` comments cite
`EMAIL_SYNC_REDESIGN_HANDOFF.md` and `EMAIL_SYNC_TABS_HANDOFF.md` by name
(e.g. "undo-on-dismiss toast, `EMAIL_SYNC_REDESIGN_HANDOFF.md` section 4").
**Neither file exists in this repository.** Their content was folded into
`CLAUDE_HANDOFF.md` at some point, but the inline comments weren't updated
to match. If you're chasing one of those citations and can't find the
section in `CLAUDE_HANDOFF.md`, that's why — search the handoff for the
concept described in the surrounding code (e.g. "undo-on-dismiss") rather
than a section number, and consider updating the comment to cite
`CLAUDE_HANDOFF.md` directly once you've located it.

## Relevant source files

- `_app/mail_app_store.py` — Mail.app handshake (AppleScript/`osascript`,
  no OAuth/IMAP), message preview, and URL extraction/filtering
  (`extract_posting_urls`, the `_NON_POSTING_URL_HINTS` /
  `_GENERIC_COLLECTION_URL_HINTS` lists central to Findings 4 and 6).
- `_app/posting_extract.py` — layered job-posting extraction from a
  digest/alert email body; see `CLAUDE_HANDOFF.md` sections 1–11 for the
  design rationale cited throughout this file.
- `_app/overrides_store.py` — `job_postings` table (section 8),
  `reset_email_sync()`, and the `get_conns()` connection-locking note
  behind Finding 7.
- `_app/email_pdf.py` — saves a discovered/matched email as a PDF into
  the application folder.
- `_app/api.py` — the Job Postings and accounts/reset-email-sync
  endpoints.
- `tests/test_audit_findings.py` — regression suite for every numbered
  finding in `AUDIT_FINDINGS.md`.
- `tests/test_reset_email_sync.py`, `tests/test_posting_extract.py`,
  `tests/test_discoveries.py`, `tests/test_job_postings_store.py` —
  broader Email Sync test coverage.

## Reorganization note (2026-09-06)

`AUDIT_FINDINGS.md` and the stub `HANDOFF.md` used to sit at the repo
root. They were moved here (and to `docs/archive/handoffs/`,
respectively) to keep the root focused on the top-level `README.md`,
`CHANGES.md`, and the living `CLAUDE_HANDOFF.md`, and to give Email Sync
troubleshooting a single, discoverable entry point. No file content was
changed, only location — internal links were updated to match.
