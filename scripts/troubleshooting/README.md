# Troubleshooting scripts

Moved here (2026-09-06) to keep `scripts/` focused on build/packaging.
These are one-off data-repair and read-only debug tools, each written
for a specific real bug found in the wild — kept because that class of
bug (or an existing tracker still carrying its symptoms) can resurface.
Each file's own docstring has full usage instructions; this is just an
index so you don't have to open all five to find the right one. For the
symptoms these scripts fix (and the Email Sync bugs behind them), see
[`docs/troubleshooting/email-sync/`](../../docs/troubleshooting/email-sync/).

| Script | Use when |
|---|---|
| `backfill_job_posting_urls.py` | Existing tracker has `job_postings` rows with `posting_url = NULL` from before the `utm_`-filter / HTML-link fixes (see [`docs/troubleshooting/email-sync/AUDIT_FINDINGS.md`](../../docs/troubleshooting/email-sync/AUDIT_FINDINGS.md), Findings 4 & 6). Rewrites those rows in place. |
| `cleanup_bogus_account_matches.py` | Existing tracker has a flood of bogus `account_matches` (and stray "evidence" PDFs) from the short-role-term over-matching bug (e.g. a role label like "IT" or "PM" substring-matching unrelated mail). |
| `debug_extract_urls.py` | `extract_posting_urls()` finds zero/wrong links for a real email. Read-only — prints every raw URL in the message body and which filter drops it, without touching any database. |
| `debug_raw_source.py` | `debug_extract_urls.py` finds *zero* raw URLs at all. Reads Mail.app's raw RFC822 source instead of the plain-text rendering, since plain text drops `<a href>` links entirely. Read-only. |
| `fix_doubled_tracker_names.py` | A tracker folder/registry entry got double-prefixed (`JobTracker — JobTracker — <name>`) from the old re-import naming bug. Safe to run — only touches app-owned workspaces. |

All five expect a real tracker root and/or a Mac with Mail.app
configured — they're for troubleshooting an actual user's data, not
part of the automated test suite (`tests/` is separate and still runs
under pytest as before).
