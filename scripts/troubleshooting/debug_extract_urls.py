#!/usr/bin/env python3
"""Debug helper for the backfill_job_posting_urls.py "counts don't match,
no link guessed" case: shows every raw URL found in a stuck message's body
and exactly which filter (if any) in mail_app_store.extract_posting_urls()
drops it, so a domain/path filter that's too narrow for a real email
(as opposed to the synthetic test fixtures) is visible instead of just
producing an empty list.

Does not touch overrides.db at all -- read-only, prints to stdout.

Usage:
    Quit JobTracker Hub first, then, from a Mac with Mail.app configured
    with the same accounts:

        python3 scripts/debug_extract_urls.py <tracker_root>

    With no further arguments, it debugs every (account_id, message_id)
    group backfill_job_posting_urls.py would report as "still no link".
    To debug one specific message instead:

        python3 scripts/debug_extract_urls.py <tracker_root> --message-id "<id>"
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_app"))

import extract  # noqa: E402
import mail_app_store as mailapp  # noqa: E402

OVERRIDES_DIRNAME = ".jobtracker"
OVERRIDES_DB_NAME = "overrides.db"


def debug_one(account_name: str, message_id: str) -> None:
    print(f"\n{'=' * 70}\nMessage: {message_id}\nAccount: {account_name}\n{'=' * 70}")

    try:
        body = mailapp.get_message_preview(account_name, message_id)
    except mailapp.MailAppError as exc:
        print(f"  Mail.app error: {exc}")
        return

    if not body:
        print("  Body not found in any mailbox.")
        return

    print(f"  Body length: {len(body)} chars")

    raw_urls = extract.extract_urls(body)
    print(f"  Raw URLs found by extract.extract_urls(): {len(raw_urls)}\n")

    if not raw_urls:
        print("  -- none at all. The body may not contain plain http(s) links")
        print("     (e.g. they're HTML href attributes stripped during body")
        print("     extraction, or wrapped some other way extract_urls'")
        print("     regex doesn't recognize).")
        return

    for url in raw_urls:
        low = url.lower()
        non_posting_hit = next((h for h in mailapp._NON_POSTING_URL_HINTS if h in low), None)
        generic_hit = next((h for h in mailapp._GENERIC_COLLECTION_URL_HINTS if h in low), None)
        domain_hit = next((d for d in mailapp._JOB_POSTING_URL_DOMAINS if d in low), None)

        if non_posting_hit:
            verdict = f"REJECTED -- matched _NON_POSTING_URL_HINTS ({non_posting_hit!r})"
        elif generic_hit:
            verdict = f"REJECTED -- matched _GENERIC_COLLECTION_URL_HINTS ({generic_hit!r})"
        elif domain_hit:
            verdict = f"KEPT -- matched _JOB_POSTING_URL_DOMAINS ({domain_hit!r})"
        else:
            verdict = "REJECTED -- no domain in _JOB_POSTING_URL_DOMAINS matched this URL at all"

        print(f"  {url}\n    -> {verdict}\n")

    kept = mailapp.extract_posting_urls(body)
    print(f"  Final extract_posting_urls() result: {len(kept)} link(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tracker_root", type=Path)
    parser.add_argument("--message-id", default=None, help="Debug only this one message-id instead of every stuck group")
    args = parser.parse_args()

    root = args.tracker_root.expanduser().resolve()
    ov_db_path = root / OVERRIDES_DIRNAME / OVERRIDES_DB_NAME
    if not ov_db_path.exists():
        print(f"No overrides.db found at {ov_db_path} -- is this a tracker root?", file=sys.stderr)
        return 1

    conn = sqlite3.connect(ov_db_path)
    conn.row_factory = sqlite3.Row

    accounts_by_id = {
        r["id"]: (r["account_name"] or r["email"])
        for r in conn.execute("SELECT id, email, account_name FROM accounts").fetchall()
    }

    if args.message_id:
        # account_id unknown up front -- look it up from any row referencing it.
        row = conn.execute(
            "SELECT account_id FROM job_postings WHERE message_id = ? LIMIT 1", (args.message_id,)
        ).fetchone()
        if not row:
            print(f"No job_postings row references message_id {args.message_id!r}.", file=sys.stderr)
            return 1
        account_name = accounts_by_id.get(row["account_id"])
        if not account_name:
            print("That row's account is no longer connected.", file=sys.stderr)
            return 1
        debug_one(account_name, args.message_id)
        conn.close()
        return 0

    missing = conn.execute(
        "SELECT * FROM job_postings WHERE posting_url IS NULL OR posting_url = ''"
    ).fetchall()
    conn.close()

    if not missing:
        print("No job_postings rows are missing a link -- nothing to debug.")
        return 0

    groups: dict[tuple[str, str], None] = {}
    for row in missing:
        groups[(row["account_id"], row["message_id"])] = None

    for account_id, message_id in groups:
        account_name = accounts_by_id.get(account_id)
        if not account_name:
            print(f"\nSkipping message {message_id}: account {account_id} no longer connected.")
            continue
        debug_one(account_name, message_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
