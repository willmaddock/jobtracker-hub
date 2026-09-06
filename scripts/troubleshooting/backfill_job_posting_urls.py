#!/usr/bin/env python3
"""One-off backfill for job_postings rows stuck with posting_url = NULL
from before AUDIT_FINDINGS.md Findings 4 and 6's fixes.

Before Finding 4's fix, mail_app_store.extract_posting_urls() rejected any
URL containing "utm_" as a non-posting link -- which is exactly how
LinkedIn (and most ATSs) tag their real per-job listing links in alert
emails, so essentially every job ever extracted came out with
posting_url = NULL. Before Finding 6's fix, extraction only ever read
Mail.app's plain-text rendering of a message (`content of msg`), which
throws away every <a href="..."> URL in an HTML email entirely -- so even
after Finding 4, an HTML digest still had nothing to extract. Both fixes
stop new extractions from losing their link, but neither can retroactively
touch rows already sitting in an existing tracker's job_postings table --
extraction only ever runs once, at sync time (see api.py's
_extract_and_store_job_postings docstring). That's what this script is
for.

What it does, for one tracker root:
  1. Opens <root>/.jobtracker/overrides.db and finds every job_postings
     row with posting_url IS NULL.
  2. Groups them by (account_id, message_id) -- a multi-job digest email
     produces one row per job, all sharing the same source message, so
     they have to be re-extracted together to redo the same
     count-matched positional URL-to-job pairing
     _extract_and_store_job_postings uses (see AUDIT_FINDINGS.md's "no
     fake pairing" note) rather than one row at a time.
  3. Re-fetches each group's plain-text preview via mail_app_store.
     get_message_preview() (now with Finding 5's every-mailbox fallback,
     so a message that's since moved out of Inbox is still found), then
     runs posting_extract.extract_postings() on that body and
     mail_app_store.get_posting_urls_for_message() for the links -- the
     exact same calls _extract_and_store_job_postings makes at sync time,
     now benefiting from both the Finding 4 and Finding 6 fixes (the
     latter tries the message's raw HTML source first, falling back to
     the plain-text body only if that finds nothing).
  4. Matches freshly-extracted jobs back to this group's existing rows
     by title (case-insensitive). A group where that match is ambiguous
     (e.g. two rows share a title) is skipped and reported rather than
     guessed at.
  5. Updates only the posting_url column on matched rows. Nothing else
     about a row (status, dedupe_key, received_at, etc.) is touched.

Rows whose message is still unreachable (deleted, or the account's own
Mail.app entry is gone) are reported as "still no link" and left alone --
safe to re-run this script later.

Usage:
    Quit JobTracker Hub first, then, from a Mac with Mail.app configured
    with the same accounts:

        python3 scripts/backfill_job_posting_urls.py <tracker_root>            # dry run
        python3 scripts/backfill_job_posting_urls.py <tracker_root> --apply    # actually updates rows

A timestamped backup of overrides.db is written next to the original
before anything is changed.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# So this can import the app's own modules for the exact same extraction
# logic the app uses at sync time, rather than re-implementing (and
# risking drifting from) it here.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_app"))

import mail_app_store as mailapp  # noqa: E402
import posting_extract  # noqa: E402

OVERRIDES_DIRNAME = ".jobtracker"
OVERRIDES_DB_NAME = "overrides.db"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tracker_root", type=Path, help="Path to the tracker root folder (contains Applications/ and .jobtracker/)")
    parser.add_argument("--apply", action="store_true", help="Actually update rows (default is a dry run)")
    args = parser.parse_args()

    root = args.tracker_root.expanduser().resolve()
    ov_db_path = root / OVERRIDES_DIRNAME / OVERRIDES_DB_NAME
    if not ov_db_path.exists():
        print(f"No overrides.db found at {ov_db_path} -- is this a tracker root?", file=sys.stderr)
        return 1

    conn = sqlite3.connect(ov_db_path)
    conn.row_factory = sqlite3.Row

    missing = conn.execute(
        "SELECT * FROM job_postings WHERE posting_url IS NULL OR posting_url = ''"
    ).fetchall()

    if not missing:
        print("No job_postings rows are missing a link -- nothing to do.")
        conn.close()
        return 0

    print(f"Found {len(missing)} job_postings row(s) with no link.\n")

    accounts_by_id = {
        r["id"]: (r["account_name"] or r["email"])
        for r in conn.execute("SELECT id, email, account_name FROM accounts").fetchall()
    }

    groups: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in missing:
        groups[(row["account_id"], row["message_id"])].append(row)

    updates: list[tuple[int, str, str]] = []  # (job_id, title, posting_url)
    still_missing: list[str] = []
    ambiguous: list[str] = []

    for (account_id, message_id), rows in groups.items():
        account_name = accounts_by_id.get(account_id)
        if not account_name:
            still_missing.append(f"  [{message_id}] account {account_id} no longer connected -- skipped")
            continue

        try:
            body = mailapp.get_message_preview(account_name, message_id)
        except mailapp.MailAppError as exc:
            still_missing.append(f"  [{message_id}] Mail.app error ({exc}) -- skipped")
            continue

        if not body:
            still_missing.append(f"  [{message_id}] message not found in any mailbox -- skipped")
            continue

        subject = rows[0]["email_subject"]
        sender = rows[0]["sender"]
        jobs = posting_extract.extract_postings(sender, subject, body)
        # AUDIT_FINDINGS.md Finding 6: extract_posting_urls(body) alone only
        # ever sees Mail.app's plain-text rendering, which has no URL at all
        # for an HTML digest -- get_posting_urls_for_message() tries the raw
        # MIME source first (recovering the real per-job links) and falls
        # back to the plain-text body extraction, same as sync time now does.
        urls = mailapp.get_posting_urls_for_message(account_name, message_id, fallback_body=body)
        urls_for_jobs = urls if len(urls) == len(jobs) else []

        if not urls_for_jobs:
            still_missing.append(
                f"  [{message_id}] re-extracted {len(jobs)} job(s), {len(urls)} link(s) -- "
                f"counts don't match, no link guessed (same safety rule as sync time)"
            )
            continue

        by_title = defaultdict(list)
        for row in rows:
            by_title[(row["title"] or "").strip().lower()].append(row)

        for i, job in enumerate(jobs):
            title_key = (job.get("title") or "").strip().lower()
            candidates = by_title.get(title_key)
            if not candidates:
                continue  # this re-extracted job doesn't match any row we're backfilling
            if len(candidates) > 1:
                ambiguous.append(
                    f"  [{message_id}] {len(candidates)} existing rows share the title "
                    f"{job.get('title')!r} -- skipped, can't tell them apart"
                )
                continue
            updates.append((candidates[0]["id"], job.get("title") or "(untitled)", urls_for_jobs[i]))

    print(f"Would update {len(updates)} row(s):\n")
    for job_id, title, url in updates:
        print(f"  #{job_id} {title!r} -> {url}")

    if still_missing:
        print(f"\n{len(still_missing)} row-group(s) still have no link:\n")
        for line in still_missing:
            print(line)

    if ambiguous:
        print(f"\n{len(ambiguous)} group(s) skipped as ambiguous:\n")
        for line in ambiguous:
            print(line)

    if not updates:
        print("\nNothing to apply.")
        conn.close()
        return 0

    if not args.apply:
        print("\nDry run only -- nothing was changed. Re-run with --apply to make these updates.")
        conn.close()
        return 0

    backup_path = ov_db_path.with_name(
        f"{OVERRIDES_DB_NAME}.bak-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    )
    shutil.copy2(ov_db_path, backup_path)

    for job_id, _title, url in updates:
        conn.execute("UPDATE job_postings SET posting_url = ? WHERE id = ?", (url, job_id))
    conn.commit()
    conn.close()

    print(f"\nDone. {len(updates)} row(s) updated. Database backup saved to {backup_path}.")
    print("Restart JobTracker Hub to see the links on the board.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
