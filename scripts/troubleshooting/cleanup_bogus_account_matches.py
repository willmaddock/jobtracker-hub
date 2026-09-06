#!/usr/bin/env python3
"""One-off cleanup for account_matches created by the short-role-term
over-matching bug (fixed alongside this script -- see
mail_app_store.is_usable_match_term()'s docstring).

Before that fix, sync_account() OR'd a role label straight into an
AppleScript `contains` search with no minimum length or stoplist. A short,
generic role label -- "IT", "(root)", "PM", etc. -- substring-matches huge
amounts of unrelated mail (e.g. "IT" hits "wa-IT-ing", "ident-IT-y",
"recru-IT-ing"...), so those applications ended up with dozens of bogus
account_matches, and backfill_email_pdfs() dutifully turned the first one
into a saved "evidence" PDF inside the application's own folder.

The matching fix stops new bogus matches from being created. It does not
retroactively fix the ones already sitting in an existing tracker's
overrides.db, or undo a PDF that backfill already saved from one -- that's
what this script is for.

What it does, for one tracker root:
  1. Opens <root>/.jobtracker/overrides.db and reads every row in
     account_matches.
  2. For each row, re-derives the company/role terms from its item_key
     (format: "applications|<company>|<role>|<relpath>", see
     workspace.py/db.py) and re-checks whether the row's stored subject
     actually contains a *usable* term (mail_app_store.is_usable_
     match_term() -- the same rule the fixed sync_account() now applies
     going forward). account_matches never stored the original sender
     address (see backfill_email_pdfs()'s docstring in api.py), so
     subject is all there is to re-check against here -- a genuinely
     legitimate match that only ever matched via sender gets flagged too
     in that case, which is the safer direction to err in. A row that
     only ever matched because of a generic term like "IT" is flagged
     as bogus.
  3. Deletes the bogus rows from account_matches.
  4. For any item folder that lost its only match(es), checks whether its
     "Email - <subject>.pdf" evidence file (email_pdf.EMAIL_PDF_PREFIX)
     corresponds to one of the just-purged rows (by filename, via
     email_pdf.safe_email_filename() on the purged row's subject) and, if
     so, deletes that file too -- so a subsequent "Backfill missing email
     PDFs" run picks a legitimate match instead, or leaves the folder
     empty if none of its matches were ever legitimate.

Nothing here re-contacts Mail.app -- it only reads/edits the already-
synced rows and files sitting in the tracker root. Re-run "Sync now" /
"Backfill missing email PDFs" afterward (from the app) to re-populate
anything genuinely missing, now under the fixed matching logic.

Usage:
    Quit JobTracker Hub first, then:

        python3 scripts/cleanup_bogus_account_matches.py <tracker_root>            # dry run
        python3 scripts/cleanup_bogus_account_matches.py <tracker_root> --apply    # actually deletes

A timestamped backup of overrides.db is written next to the original
before anything is changed.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# So this can import the app's own modules (mail_app_store, email_pdf) for
# the exact same term-filtering and filename logic the app uses, rather
# than re-implementing (and risking drifting from) it here.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_app"))

import email_pdf  # noqa: E402
import mail_app_store as mailapp  # noqa: E402

OVERRIDES_DIRNAME = ".jobtracker"
OVERRIDES_DB_NAME = "overrides.db"


def parse_item_key(item_key: str) -> tuple[str | None, str | None, str | None]:
    """item_key shape is "applications|<company>|<role>|<relpath>" (see
    db.py/workspace.py). Returns (company, role, relpath); any part that's
    missing or the row doesn't parse comes back None."""
    parts = item_key.split("|")
    if len(parts) < 4 or parts[0] != "applications":
        return None, None, None
    company, role, relpath = parts[1], parts[2], parts[3]
    return company or None, role or None, relpath or None


def row_is_legitimate(company: str | None, role: str | None, subject: str | None) -> bool:
    """Mirrors the fixed sync_account()/search_messages() logic: a match
    is legitimate only if a *usable* term (mail_app_store.is_usable_
    match_term -- long/specific enough not to be a substring-matching
    accident) is actually present in the row's subject *as a whole word*
    (mail_app_store._term_matches_wholeword() -- not merely a substring,
    since a term like "Tech" would otherwise still count a hit inside
    "Technical" even though it passes is_usable_match_term() on its own;
    see that helper's docstring). (account_matches never stores the
    original sender address -- see backfill_email_pdfs()'s docstring in
    api.py -- so subject is all there is to re-check against; a genuine
    false negative here just means a legitimate match gets flagged for
    review rather than silently kept, which is the safer direction to
    err in.)"""
    for term in (company, role):
        if term and mailapp.is_usable_match_term(term) and mailapp._term_matches_wholeword(term, subject):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tracker_root", type=Path, help="Path to the tracker root folder (contains Applications/ and .jobtracker/)")
    parser.add_argument("--apply", action="store_true", help="Actually delete bogus rows/files (default is a dry run)")
    parser.add_argument(
        "--only-company", action="append", default=None, metavar="NAME",
        help="Restrict cleanup to item_keys whose company matches NAME (case-insensitive, repeatable). "
             "IMPORTANT: since account_matches never stored the sender address, this script can only "
             "re-check a row's SUBJECT for a usable term -- a row that only ever matched via the sender "
             "(a totally normal, legitimate way for a real company's ATS mail to match) gets flagged too, "
             "with no way to tell it apart here from an actual bogus match. Review the dry-run listing "
             "yourself: a company whose flagged rows all name obviously unrelated employers (the Adams "
             "County / Apple / Honeywell / MongoDB case that triggered this fix) is safe to clean up with "
             "confidence; a company whose flagged rows read like real correspondence (interview emails, "
             "'Response to Job Inquiry', calendar invites) probably matched via sender and should likely "
             "be left alone. Use --only-company to scope --apply to just the companies you've confirmed.",
    )
    args = parser.parse_args()

    root = args.tracker_root.expanduser().resolve()
    ov_db_path = root / OVERRIDES_DIRNAME / OVERRIDES_DB_NAME
    if not ov_db_path.exists():
        print(f"No overrides.db found at {ov_db_path} -- is this a tracker root?", file=sys.stderr)
        return 1

    conn = sqlite3.connect(ov_db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM account_matches").fetchall()

    only_companies = {c.strip().lower() for c in args.only_company} if args.only_company else None

    bogus_by_item: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        company, role, _relpath = parse_item_key(r["item_key"])
        if only_companies is not None and (company or "").strip().lower() not in only_companies:
            continue
        if row_is_legitimate(company, role, r["subject"]):
            continue
        bogus_by_item.setdefault(r["item_key"], []).append(r)

    total_bogus = sum(len(v) for v in bogus_by_item.values())
    if total_bogus == 0:
        print("No bogus account_matches found -- nothing to clean up.")
        conn.close()
        return 0

    print(f"Found {total_bogus} bogus match(es) across {len(bogus_by_item)} application(s):\n")

    files_to_remove: list[Path] = []
    for item_key, bad_rows in sorted(bogus_by_item.items()):
        company, role, relpath = parse_item_key(item_key)
        label = f"{company or '?'} / {role or '(root)'}"
        print(f"  {label}  ({relpath})")
        for r in bad_rows:
            print(f"      - {r['subject'] or '(no subject)'!r}  (received {r['received_at'] or 'unknown date'})")

        if relpath is None:
            continue
        folder = root / relpath
        if not folder.is_dir():
            continue

        # Does this folder's existing evidence PDF correspond to one of
        # the rows we're about to purge? If every one of this folder's
        # matches turned out bogus, or the specific match that produced
        # the saved PDF did, remove the file so a later re-backfill picks
        # a legitimate match instead of leaving a wrong one in place.
        bad_subjects = {email_pdf.safe_email_filename(r["subject"]) + ".pdf" for r in bad_rows}
        for f in folder.iterdir():
            if not f.is_file() or f.suffix.lower() != ".pdf":
                continue
            if not f.name.startswith(email_pdf.EMAIL_PDF_PREFIX):
                continue
            if f.name in bad_subjects:
                files_to_remove.append(f)
                print(f"      -> would remove wrongly-attached file: {f.relative_to(root)}")
        print()

    if not args.apply:
        print(f"Dry run only -- {total_bogus} match row(s) and {len(files_to_remove)} file(s) would be removed.")
        print("Re-run with --apply to actually make these changes.")
        conn.close()
        return 0

    backup_path = ov_db_path.with_name(f"overrides.db.bak-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
    shutil.copy2(ov_db_path, backup_path)
    print(f"Backed up overrides.db to {backup_path.name}")

    for f in files_to_remove:
        f.unlink()

    ids = [r["id"] for bad_rows in bogus_by_item.values() for r in bad_rows]
    conn.executemany("DELETE FROM account_matches WHERE id = ?", [(i,) for i in ids])
    conn.commit()
    conn.close()

    print(f"Removed {total_bogus} bogus match row(s) and {len(files_to_remove)} wrongly-attached file(s).")
    print("Open JobTracker Hub, click \"Rebuild index\", then re-run \"Backfill missing email PDFs\" if you want a legitimate replacement PDF for any affected application.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
