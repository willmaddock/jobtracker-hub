#!/usr/bin/env python3
"""Debug helper, step 2: get_message_preview()/debug_extract_urls.py found
ZERO raw URLs in a real LinkedIn digest body -- because that body comes
from AppleScript's `content of msg`, which is Mail.app's own plain-text
rendering of an HTML email. Plain-text rendering keeps visible button
labels ("View job") but drops the underlying <a href="..."> URL entirely,
since that only exists in the HTML markup, not the rendered text.

This script instead asks Mail.app for `source of msg` -- the raw RFC822
MIME source, headers and all encodings included -- and extracts every
href="..." value it can find after best-effort quoted-printable/base64
decoding of the HTML part. It does NOT print the raw source itself (that
includes your headers/routing info); it only prints counts and the
decoded href values, which are just outbound URLs.

Read-only. Doesn't touch overrides.db. Doesn't modify mail_app_store.py.

Usage:
    python3 scripts/debug_raw_source.py <tracker_root> --message-id "<id>"

    (message-id required this time -- run debug_extract_urls.py first to
    get exact ids, or pass none to walk every stuck job_postings group
    the same way debug_extract_urls.py does)
"""

from __future__ import annotations

import argparse
import base64
import quopri
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_app"))

import mail_app_store as mailapp  # noqa: E402

OVERRIDES_DIRNAME = ".jobtracker"
OVERRIDES_DB_NAME = "overrides.db"

_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.I)


def _get_raw_source(account_name: str, message_id: str, mailbox: str = "INBOX", max_chars: int = 300_000) -> str | None:
    """Same message-lookup shape as mail_app_store.get_message_preview(),
    but requests `source of msg` instead of `content of msg`."""
    resolve_box = mailapp._resolve_mailbox_script(mailbox)
    escaped_id = mailapp._escape_applescript_string(message_id)
    escaped_account = mailapp._escape_applescript_string(account_name)

    script = f"""
    tell application "Mail"
        set acct to account "{escaped_account}"
        set msg to missing value
        try
            {resolve_box}
            set matchedMsgs to (messages of targetBox whose message id is "{escaped_id}")
            if (count of matchedMsgs) > 0 then set msg to item 1 of matchedMsgs
        end try
        if msg is missing value then
            repeat with mb in (every mailbox of acct)
                try
                    set otherMsgs to (messages of mb whose message id is "{escaped_id}")
                    if (count of otherMsgs) > 0 then
                        set msg to item 1 of otherMsgs
                        exit repeat
                    end if
                end try
            end repeat
        end if
        if msg is missing value then return "JOBTRACKER_NOT_FOUND"
        set msgSource to ""
        try
            set msgSource to source of msg
        end try
        if (count of msgSource) > {int(max_chars)} then
            set msgSource to (text 1 thru {int(max_chars)} of msgSource)
        end if
        return msgSource
    end tell
    """
    raw = mailapp._run_applescript(script, timeout=45)
    if not raw or raw == "JOBTRACKER_NOT_FOUND":
        return None
    return raw


def _decode_body_parts(raw_source: str) -> list[str]:
    """Very rough MIME split: find each part's Content-Transfer-Encoding
    and decode it, so href="..." shows up in the decoded text even when
    quoted-printable (=3D style escaping) or base64 hid it in the raw
    source. Not a full MIME parser -- good enough to locate hrefs for
    debugging, not to reconstruct the email."""
    decoded_chunks = []

    # Split on MIME boundaries if present; otherwise treat whole thing as one chunk.
    boundary_match = re.search(r'boundary="?([^"\s;]+)"?', raw_source, re.I)
    if boundary_match:
        boundary = boundary_match.group(1)
        parts = raw_source.split(f"--{boundary}")
    else:
        parts = [raw_source]

    for part in parts:
        cte_match = re.search(r"Content-Transfer-Encoding:\s*([\w-]+)", part, re.I)
        cte = cte_match.group(1).lower() if cte_match else ""
        # crude header/body split on first blank line
        body = part.split("\n\n", 1)[-1] if "\n\n" in part else part
        try:
            if cte == "quoted-printable":
                decoded_chunks.append(quopri.decodestring(body.encode("utf-8", "ignore")).decode("utf-8", "ignore"))
            elif cte == "base64":
                cleaned = re.sub(r"\s+", "", body)
                # pad to multiple of 4
                cleaned += "=" * (-len(cleaned) % 4)
                decoded_chunks.append(base64.b64decode(cleaned, validate=False).decode("utf-8", "ignore"))
            else:
                decoded_chunks.append(body)
        except Exception:
            decoded_chunks.append(body)  # fall back to raw if decode fails

    return decoded_chunks


def debug_one(account_name: str, message_id: str) -> None:
    print(f"\n{'=' * 70}\nMessage: {message_id}\nAccount: {account_name}\n{'=' * 70}")

    raw_source = _get_raw_source(account_name, message_id)
    if raw_source is None:
        print("  Could not fetch raw source (message not found, or Mail.app error).")
        return

    print(f"  Raw source length: {len(raw_source)} chars")

    cte_hits = re.findall(r"Content-Transfer-Encoding:\s*([\w-]+)", raw_source, re.I)
    print(f"  Content-Transfer-Encoding header(s) seen: {cte_hits or 'none'}")

    decoded_chunks = _decode_body_parts(raw_source)
    all_hrefs: list[str] = []
    for chunk in decoded_chunks:
        all_hrefs.extend(_HREF_RE.findall(chunk))

    # de-dupe, keep order
    seen = set()
    deduped = []
    for h in all_hrefs:
        if h not in seen:
            seen.add(h)
            deduped.append(h)

    print(f"\n  href=\"...\" values found after decoding: {len(deduped)}\n")
    for h in deduped[:30]:
        print(f"    {h}")
    if len(deduped) > 30:
        print(f"    ... and {len(deduped) - 30} more")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tracker_root", type=Path)
    parser.add_argument("--message-id", default=None)
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
