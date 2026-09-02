"""
Local-only "overrides" store — everything here is YOUR data, not inferred
from filenames, and it lives in its own file (overrides.db) separate from
jobtracker.db. That separation matters: jobtracker.db is fully dropped and
rebuilt every time you click "Rebuild index", but overrides.db never is —
your notes, manual status corrections, applied dates, next actions, and
company merges survive every rebuild.

Nothing in this file ever reads from or writes to your JobTracker folder.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS item_overrides (
    item_key TEXT PRIMARY KEY,
    manual_status TEXT,          -- overrides the auto-inferred status when set
    notes TEXT,
    date_applied TEXT,           -- ISO date, set by you (mtime is unreliable — see README)
    date_applied_source TEXT,    -- Checkpoint 6: how date_applied got its value --
                                  -- "confirmation" or "posting" when it was accepted from a
                                  -- detected-date suggestion (dossier.py's evidence tier),
                                  -- NULL when you typed it yourself. Display-only provenance;
                                  -- never affects which date wins. Cleared automatically
                                  -- whenever date_applied is set WITHOUT this field also being
                                  -- sent (see api.py's save_override) -- a manual retype makes
                                  -- the old provenance label stale, so it goes away with it.
    next_action TEXT,
    next_action_date TEXT,       -- ISO date
    archived INTEGER NOT NULL DEFAULT 0,  -- hide from Needs Attention without deleting
    snoozed_until TEXT,          -- ISO date; hide from Needs Attention until this date passes
    activity_override TEXT,      -- ISO date; "Reset activity clock" — takes priority over
                                  -- date_applied/last_activity for the staleness countdown,
                                  -- without changing date_applied itself (e.g. confirming an
                                  -- interview happened shouldn't rewrite when you first applied)
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS company_aliases (
    alias TEXT PRIMARY KEY,      -- raw company/folder name as it appears in JobTracker.db
    canonical TEXT NOT NULL      -- the display name you want it grouped/shown under
);

CREATE TABLE IF NOT EXISTS document_overrides (
    relpath TEXT PRIMARY KEY,    -- path relative to JobTracker root, same as documents.relpath
    doc_type_override TEXT,      -- your correction when a filename gives classify.py no real signal
                                  -- (e.g. the AWS "2894707.pdf" resume-vs-cover-letter case) — never
                                  -- guessed automatically, and never changes the file on disk
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS hub_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- single-row table, one per workspace
    role TEXT,
    location TEXT,
    custom_links TEXT,    -- JSON: { [linkName]: {title?, url?} } — edits to built-in cards
    custom_cards TEXT,    -- JSON: { [categoryId]: [{id, title, url, note}] } — cards you've added
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS folder_overrides (
    folder TEXT PRIMARY KEY,     -- the physical top-level folder name this row controls (e.g.
                                  -- "Certifications", "Degree and Transcrips"), or, for the
                                  -- compliance-only nested-in-Applications case, the two-part
                                  -- path to that subfolder (e.g.
                                  -- "Applications/Workforce Center Compliance",
                                  -- if you've enabled a nested-application
                                  -- marker in classify_config.json). Folder-scoped rather
                                  -- than section-scoped because several physical folders can
                                  -- share one Browse tab (e.g. Certifications and
                                  -- "Degree and Transcrips" both live under the "Credentials"
                                  -- tab) and archiving/deleting needs to target just one of them
                                  -- without touching its siblings.
    section TEXT NOT NULL,       -- the Browse-tab section id this folder currently resolves to
                                  -- (see classify.classify_section) — stored for display/lookup
                                  -- convenience only; not used to determine identity, since a
                                  -- folder name is already unique on disk.
    archived INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS document_extractions (
    content_hash TEXT PRIMARY KEY,   -- same SHA-256 as documents.content_hash (db.py's
                                      -- duplicate-detection hash) -- keying the cache on
                                      -- content rather than relpath means an identical
                                      -- resume filed under two applications is only ever
                                      -- run through extraction once.
    extractor_version TEXT NOT NULL, -- extract.EXTRACTOR_VERSION at the time this row was
                                      -- written; a stale version is treated as a cache miss
                                      -- rather than reused, so logic changes take effect
                                      -- without a manual cache-clear step.
    extracted_json TEXT NOT NULL,    -- JSON: {extraction_ok, error, text_length, emails,
                                      -- phones, urls, ...} -- see extract.py.
    extracted_at TEXT NOT NULL
);

-- Item 7: append-only status-change log. item_overrides.manual_status only
-- ever stores the CURRENT value (overwritten in place on every save), so
-- there was previously no way to answer "when did this become rejected" --
-- this table exists solely to answer that question, going forward. Rows
-- are only ever inserted, never updated or overwritten (see
-- append_status_history's no-op-on-repeat-save behavior below), so the
-- most recent row matching a given status is that status's transition
-- date. Only covers changes made after this table shipped -- it cannot
-- retroactively recover a date for a status set earlier (see
-- docs/specs/ITEM7_TIMELINE_FDD_DRAFT.md).
CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT NOT NULL,
    status TEXT NOT NULL,        -- the resulting EFFECTIVE status (manual_status if set,
                                  -- else the item's auto-detected status) -- so a "reset
                                  -- to auto" action is still a real, findable transition,
                                  -- not a NULL gap.
    changed_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual'
);

CREATE INDEX IF NOT EXISTS idx_status_history_item_key ON status_history(item_key);

-- Connected email accounts. Every row is a Mail.app account the user
-- already configured in System Settings -> Internet Accounts -- no
-- credentials of any kind live here or anywhere else in this app. See
-- mail_app_store.py for the AppleScript handshake.
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,          -- uuid4, generated at connect time
    provider TEXT NOT NULL,       -- always 'mail_app' now; old rows may say 'gmail'/'outlook'/'icloud'/'imap' from before this app went macOS-only, see _migrate()
    email TEXT NOT NULL,
    account_name TEXT,            -- Mail.app's own account name (what mail_app_store.search_messages() queries by) -- may differ from `email`, e.g. an account named "hotmail" whose address is a different alias
    status TEXT NOT NULL DEFAULT 'connected',  -- 'connected' | 'blocked' | 'disconnected'  ('blocked' = last sync hit a denied Automation permission)
    last_synced_at TEXT,
    matched_email_count INTEGER NOT NULL DEFAULT 0,
    connected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- One row per email matched to an application item, so the dossier/
-- timeline can cite "via which account" without re-fetching the inbox.
-- Only extracted text is ever stored (mirrors document_extractions in
-- db.py) -- never the raw message.
CREATE TABLE IF NOT EXISTS account_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    message_id TEXT NOT NULL,     -- provider's message id, for de-dupe on re-sync
    subject TEXT,
    received_at TEXT,
    matched_at TEXT NOT NULL,
    UNIQUE(account_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_account_matches_item_key ON account_matches(item_key);

-- Discovery review queue ("Possible new applications"): a message that
-- *looks* application-related (mail_app_store.search_unmatched_messages'
-- ATS heuristics) but doesn't match any currently-tracked item. Distinct
-- from account_matches, which only ever links a message to an item that
-- already exists -- a row here means "maybe log a new application from
-- this", and nothing becomes a real item (or an account_match) until the
-- user explicitly accepts it via /api/discoveries/{id}/accept. Rejecting
-- (status='dismissed') is remembered too, so a dismissed message doesn't
-- keep resurfacing on every later scan.
CREATE TABLE IF NOT EXISTS discovered_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    subject TEXT,
    sender TEXT,
    received_at TEXT,
    guessed_company TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'accepted' | 'dismissed'
    created_at TEXT NOT NULL,
    -- 'unmatched' (default): search_unmatched_messages() found mail that
    -- doesn't look like it belongs to anything tracked yet -- accepting
    -- one of these creates a brand-new item (see /api/discoveries/{id}/accept).
    -- 'ambiguous': sync_account() found a company-only text match (see
    -- mail_app_store.search_messages()'s "company_only" field) against a
    -- company with more than one open item, so which specific item this
    -- email actually belongs to can't be inferred automatically --
    -- accepting one of these attaches it to an EXISTING item instead of
    -- creating a new one (see /api/discoveries/{id}/attach).
    match_kind TEXT NOT NULL DEFAULT 'unmatched',
    -- JSON-encoded list of item_keys sharing the guessed company, for
    -- 'ambiguous' rows only (NULL for 'unmatched' rows). The frontend
    -- offers these as the picker options for /attach.
    candidate_item_keys TEXT,
    -- Orthogonal to match_kind above: match_kind is about *matching
    -- confidence* (does this clearly belong to one item, or could it be
    -- several?); `kind` is about *what the email itself is*.
    -- 'application' (default): this is mail about an application --
    -- current behavior, unchanged, still goes through the
    -- unmatched/ambiguous triage above.
    -- 'posting': subject/body reads as a job-alert/listing notice (e.g.
    -- "KPMG just posted a 78% match Front End Engineer...") rather than
    -- confirmation that the user applied to anything -- see
    -- mail_app_store.is_job_posting_style_subject(). These are routed
    -- straight past the ambiguous-application queue regardless of any
    -- company-name overlap (see api.py's sync_account() and
    -- discover_new_applications()); candidate_item_keys is always empty
    -- for these rows since there's no application to attach to.
    kind TEXT NOT NULL DEFAULT 'application',
    -- Best-effort job-board/careers-page URL pulled from the message body
    -- the first time it's previewed (see mail_app_store.guess_posting_url()
    -- and api.py's preview_discovery()). NULL until a preview has run, and
    -- stays NULL forever if no recognizable link was found in the body --
    -- the frontend shows nothing rather than a fake link in that case.
    -- Populated lazily (on preview), not at scan time, for the same reason
    -- the body itself is fetched lazily: cheap scans, cost paid only for
    -- discoveries the user actually opens.
    posting_url TEXT,
    -- Every job-board/listing URL found in the message body (JSON array),
    -- for digest emails that bundle several distinct postings into one
    -- message (see mail_app_store.extract_posting_urls() and
    -- discoveries-sender-classification-and-digests-spec.md Part 5.5b).
    -- posting_url above is kept for backward compat and always mirrors
    -- posting_urls[0] once this is populated; posting_urls is the richer
    -- field new code should read. Same lazy-on-preview population as
    -- posting_url -- NULL until a preview has run.
    posting_urls TEXT,
    UNIQUE(account_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_discovered_matches_status ON discovered_matches(status);

-- Senders the user has explicitly taught this app to always treat as
-- job-posting mail, regardless of subject phrasing -- the escape hatch
-- for a digest sender whose subject shape search_unmatched_messages()'s
-- heuristics don't recognize (e.g. LinkedIn renaming the subject to
-- whatever listing ranks first, so it never contains an ATS phrase). See
-- discoveries-sender-classification-and-digests-spec.md Part 5.5a. Keyed
-- on the exact sender string (mirrors dismiss_pending_discoveries_by_
-- sender's keying), not domain, so a human recruiter at the same domain
-- (e.g. a real person @linkedin.com) is never accidentally swept in.
CREATE TABLE IF NOT EXISTS job_posting_senders (
    sender TEXT PRIMARY KEY,
    added_at TEXT
);

-- Every Message-ID known to belong to a given item's email thread --
-- both messages that were themselves confirmed matches, and any
-- Message-ID their In-Reply-To/References headers cited (see
-- mail_app_store.search_messages()'s thread_ids parameter). A future
-- sync passes this set back in, so a reply whose subject/sender share
-- nothing textually with the item (e.g. "Re: your submission") still
-- attaches deterministically once its headers cite an id already here.
-- Purely additive -- rows are only ever inserted, never removed except
-- via the item's own deletion cleanup.
CREATE TABLE IF NOT EXISTS thread_identifiers (
    item_key TEXT NOT NULL,
    message_id TEXT NOT NULL,
    PRIMARY KEY (item_key, message_id)
);

CREATE INDEX IF NOT EXISTS idx_thread_identifiers_item_key ON thread_identifiers(item_key);

-- First-class job-posting records (CLAUDE_HANDOFF.md section 8) -- the
-- replacement for counting discovered_matches rows with kind='posting'
-- as "Job Postings". One row per individual job, not per email: a
-- single digest message can (and usually does) produce several of
-- these, all sharing the same message_id but with different dedupe_key
-- values (see posting_extract.compute_dedupe_key()).
CREATE TABLE IF NOT EXISTS job_postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    source TEXT,                    -- 'linkedin' | 'handshake' | ...
    title TEXT,
    company TEXT,
    location TEXT,
    salary TEXT,
    employment_type TEXT,
    posting_url TEXT,
    received_at TEXT,
    email_subject TEXT,
    sender TEXT,
    -- 'new' (default) | 'dismissed' -- dismissing hides a job from the
    -- board without deleting it, same UX shape as discovered_matches.
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL,
    -- See posting_extract.compute_dedupe_key(): account_id + normalized
    -- posting URL when available, else account_id + message_id +
    -- normalized title + normalized company. UNIQUE here is what makes
    -- add_job_posting() safe to call repeatedly across syncs -- a
    -- repeated sync re-extracting the same digest is a no-op, not a
    -- duplicate row (CLAUDE_HANDOFF.md section 9).
    dedupe_key TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_job_postings_status ON job_postings(status);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the original schema, for existing
    overrides.db files that predate them. sqlite's ALTER TABLE ADD COLUMN
    has no IF NOT EXISTS, so check pragma table_info first."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(item_overrides)")}
    if "activity_override" not in cols:
        conn.execute("ALTER TABLE item_overrides ADD COLUMN activity_override TEXT")
        conn.commit()
    if "date_applied_source" not in cols:
        conn.execute("ALTER TABLE item_overrides ADD COLUMN date_applied_source TEXT")
        conn.commit()

    acct_cols = {r["name"] for r in conn.execute("PRAGMA table_info(accounts)")}
    if "account_name" not in acct_cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN account_name TEXT")
        conn.commit()

    disc_cols = {r["name"] for r in conn.execute("PRAGMA table_info(discovered_matches)")}
    if "match_kind" not in disc_cols:
        conn.execute("ALTER TABLE discovered_matches ADD COLUMN match_kind TEXT NOT NULL DEFAULT 'unmatched'")
        conn.commit()
    if "candidate_item_keys" not in disc_cols:
        conn.execute("ALTER TABLE discovered_matches ADD COLUMN candidate_item_keys TEXT")
        conn.commit()
    if "kind" not in disc_cols:
        conn.execute("ALTER TABLE discovered_matches ADD COLUMN kind TEXT NOT NULL DEFAULT 'application'")
        conn.commit()
    if "posting_url" not in disc_cols:
        conn.execute("ALTER TABLE discovered_matches ADD COLUMN posting_url TEXT")
        conn.commit()
    if "posting_urls" not in disc_cols:
        conn.execute("ALTER TABLE discovered_matches ADD COLUMN posting_urls TEXT")
        conn.commit()


def get_conn(db_path: Path) -> sqlite3.Connection:
    # overrides.db now lives inside the workspace's own root (see
    # workspace.py's _portable_ov_db_path), which — unlike this app's own
    # private storage — isn't guaranteed to already have the containing
    # folder created. A brand-new or freshly linked workspace won't have
    # a .jobtracker/ folder yet, so make sure it exists before sqlite
    # tries to create the file inside it.
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # busy_timeout widens how long a writer retries before giving up
    # (Python's sqlite3 default is only 5s) so concurrent writers -- e.g.
    # two "Sync now" calls, or a sync overlapping a disconnect -- queue and
    # retry instead of surfacing "database is locked" under heavier
    # contention. WAL additionally lets readers proceed without blocking
    # on a writer at all, and survives this same class of failure better
    # under load than the default rollback journal.
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- item overrides ----------------------------------------------------------
def get_override(conn: sqlite3.Connection, item_key: str) -> dict:
    row = conn.execute("SELECT * FROM item_overrides WHERE item_key = ?", (item_key,)).fetchone()
    return dict(row) if row else {}


def get_all_overrides(conn: sqlite3.Connection) -> dict[str, dict]:
    return {r["item_key"]: dict(r) for r in conn.execute("SELECT * FROM item_overrides")}


def upsert_override(conn: sqlite3.Connection, item_key: str, **fields) -> None:
    """Merge `fields` into any existing override row for this item_key."""
    existing = get_override(conn, item_key)
    merged = {
        "manual_status": existing.get("manual_status"),
        "notes": existing.get("notes"),
        "date_applied": existing.get("date_applied"),
        "date_applied_source": existing.get("date_applied_source"),
        "next_action": existing.get("next_action"),
        "next_action_date": existing.get("next_action_date"),
        "archived": existing.get("archived", 0),
        "snoozed_until": existing.get("snoozed_until"),
        "activity_override": existing.get("activity_override"),
        **fields,
    }
    conn.execute(
        """
        INSERT INTO item_overrides
            (item_key, manual_status, notes, date_applied, date_applied_source, next_action, next_action_date, archived, snoozed_until, activity_override, updated_at)
        VALUES (:item_key, :manual_status, :notes, :date_applied, :date_applied_source, :next_action, :next_action_date, :archived, :snoozed_until, :activity_override, :updated_at)
        ON CONFLICT(item_key) DO UPDATE SET
            manual_status=excluded.manual_status,
            notes=excluded.notes,
            date_applied=excluded.date_applied,
            date_applied_source=excluded.date_applied_source,
            next_action=excluded.next_action,
            next_action_date=excluded.next_action_date,
            archived=excluded.archived,
            snoozed_until=excluded.snoozed_until,
            activity_override=excluded.activity_override,
            updated_at=excluded.updated_at
        """,
        {
            "item_key": item_key,
            "manual_status": merged["manual_status"] or None,
            "notes": merged["notes"] or None,
            "date_applied": merged["date_applied"] or None,
            "date_applied_source": merged["date_applied_source"] or None,
            "next_action": merged["next_action"] or None,
            "next_action_date": merged["next_action_date"] or None,
            "archived": int(merged["archived"] or 0),
            "snoozed_until": merged["snoozed_until"] or None,
            "activity_override": merged["activity_override"] or None,
            "updated_at": now_iso(),
        },
    )
    conn.commit()


# --- company aliases (merge tool) --------------------------------------------
def get_aliases(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["alias"]: r["canonical"] for r in conn.execute("SELECT * FROM company_aliases")}


def set_alias(conn: sqlite3.Connection, alias: str, canonical: str) -> None:
    conn.execute(
        "INSERT INTO company_aliases (alias, canonical) VALUES (?, ?) "
        "ON CONFLICT(alias) DO UPDATE SET canonical=excluded.canonical",
        (alias, canonical),
    )
    conn.commit()


def remove_alias(conn: sqlite3.Connection, alias: str) -> None:
    conn.execute("DELETE FROM company_aliases WHERE alias = ?", (alias,))
    conn.commit()


# --- document-level overrides (manual doc-type correction) -------------------
# For the handful of files a filename genuinely can't disambiguate (e.g.
# Applications/AWS Job 2894707/2894707.pdf, which could be the resume or the
# cover letter — see classify.py's docstring). Purely a display correction:
# never renames, moves, or touches the file on disk, and — like every other
# override — survives a full index rebuild because it's keyed by relpath in
# this separate database, not in the disposable jobtracker.db.
def get_document_overrides(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        r["relpath"]: r["doc_type_override"]
        for r in conn.execute("SELECT * FROM document_overrides")
        if r["doc_type_override"]
    }


def set_document_override(conn: sqlite3.Connection, relpath: str, doc_type_override: str | None) -> None:
    if doc_type_override:
        conn.execute(
            "INSERT INTO document_overrides (relpath, doc_type_override, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(relpath) DO UPDATE SET doc_type_override=excluded.doc_type_override, updated_at=excluded.updated_at",
            (relpath, doc_type_override, now_iso()),
        )
    else:
        conn.execute("DELETE FROM document_overrides WHERE relpath = ?", (relpath,))
    conn.commit()


def delete_override(conn: sqlite3.Connection, item_key: str) -> None:
    """Drops an application's whole item_overrides row (notes, manual
    status, dates, archived flag, everything). Used when an application is
    permanently deleted — item_key is gone for good, so a leftover row here
    would just be a ghost with nothing to ever attach itself back to."""
    conn.execute("DELETE FROM item_overrides WHERE item_key = ?", (item_key,))
    conn.commit()


# --- status history (Item 7: append-only log behind the Timeline's
# "Current status" entry) -----------------------------------------------------
def append_status_history(conn: sqlite3.Connection, item_key: str, status: str, source: str = "manual") -> None:
    """Append one status-change row, but only when `status` actually differs
    from the most recently recorded value for this item — saving the same
    status again (e.g. re-saving an already-"applied" item) must not create
    a duplicate transition. Called from api.py's save_override/bulk_override
    whenever manual_status changes (including a reset back to the
    auto-detected status)."""
    last = conn.execute(
        "SELECT status FROM status_history WHERE item_key = ? ORDER BY id DESC LIMIT 1",
        (item_key,),
    ).fetchone()
    if last and last["status"] == status:
        return
    conn.execute(
        "INSERT INTO status_history (item_key, status, changed_at, source) VALUES (?, ?, ?, ?)",
        (item_key, status, now_iso(), source),
    )
    conn.commit()


def get_status_history(conn: sqlite3.Connection, item_key: str) -> list[dict]:
    """Every recorded transition for this item, oldest first."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM status_history WHERE item_key = ? ORDER BY id ASC",
            (item_key,),
        )
    ]


def get_latest_status_change(conn: sqlite3.Connection, item_key: str, status: str) -> dict | None:
    """Most recent status_history row recording a transition TO `status` for
    this item — powers the Item 7 Timeline's "Current status" date. Returns
    None when no such transition has ever been logged, which happens both
    for a status that hasn't changed since this table shipped and for one
    set entirely before it existed; either way, the Timeline should show
    that date as unknown rather than guess."""
    row = conn.execute(
        "SELECT * FROM status_history WHERE item_key = ? AND status = ? ORDER BY id DESC LIMIT 1",
        (item_key, status),
    ).fetchone()
    return dict(row) if row else None


def delete_status_history(conn: sqlite3.Connection, item_key: str) -> None:
    """Drops all status_history rows for a permanently-deleted item — same
    ghost-row reasoning as delete_override/delete_folder_override above."""
    conn.execute("DELETE FROM status_history WHERE item_key = ?", (item_key,))
    conn.commit()


# --- folder overrides (archive/delete one folder behind a Browse tab) --------
def get_folder_override(conn: sqlite3.Connection, folder: str) -> dict:
    row = conn.execute(
        "SELECT * FROM folder_overrides WHERE folder = ?", (folder,)
    ).fetchone()
    return dict(row) if row else {}


def get_all_folder_overrides(conn: sqlite3.Connection) -> dict[str, dict]:
    return {r["folder"]: dict(r) for r in conn.execute("SELECT * FROM folder_overrides")}


def set_folder_archived(conn: sqlite3.Connection, folder: str, section: str, archived: bool) -> None:
    conn.execute(
        "INSERT INTO folder_overrides (folder, section, archived, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(folder) DO UPDATE SET section=excluded.section, archived=excluded.archived, "
        "updated_at=excluded.updated_at",
        (folder, section, int(archived), now_iso()),
    )
    conn.commit()


def delete_folder_override(conn: sqlite3.Connection, folder: str) -> None:
    """Drops a folder's override row entirely. Used when the folder is
    permanently deleted — same reasoning as delete_override above: a
    leftover row for a folder that no longer exists on disk is just a
    ghost."""
    conn.execute("DELETE FROM folder_overrides WHERE folder = ?", (folder,))
    conn.commit()


# --- search hub settings (role, location, and your custom cards/links) ------
# Previously lived only in the browser's localStorage, which meant Search
# Hub customization was tied to one device/browser profile and never
# traveled with the tracker the way notes/statuses/aliases do. Moving it
# in here (single-row table, same overrides.db every other override
# lives in) makes it portable and multi-device, like everything else in
# this file — see the module docstring at the top.
def get_hub_settings(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT * FROM hub_settings WHERE id = 1").fetchone()
    if not row:
        return {"role": "", "location": "", "custom_links": {}, "custom_cards": {}}
    try:
        custom_links = json.loads(row["custom_links"]) if row["custom_links"] else {}
    except (TypeError, ValueError):
        custom_links = {}
    try:
        custom_cards = json.loads(row["custom_cards"]) if row["custom_cards"] else {}
    except (TypeError, ValueError):
        custom_cards = {}
    return {
        "role": row["role"] or "",
        "location": row["location"] or "",
        "custom_links": custom_links,
        "custom_cards": custom_cards,
    }


def set_hub_settings(conn: sqlite3.Connection, **fields) -> dict:
    """Merges `fields` (any of role/location/custom_links/custom_cards)
    into the single hub_settings row and returns the merged result —
    same partial-update shape as upsert_override above, so the frontend
    can save just the field that changed (e.g. typing in the role box)
    without having to resend everything else."""
    existing = get_hub_settings(conn)
    merged = {**existing, **{k: v for k, v in fields.items() if v is not None}}
    conn.execute(
        """
        INSERT INTO hub_settings (id, role, location, custom_links, custom_cards, updated_at)
        VALUES (1, :role, :location, :custom_links, :custom_cards, :updated_at)
        ON CONFLICT(id) DO UPDATE SET
            role=excluded.role,
            location=excluded.location,
            custom_links=excluded.custom_links,
            custom_cards=excluded.custom_cards,
            updated_at=excluded.updated_at
        """,
        {
            "role": merged["role"] or None,
            "location": merged["location"] or None,
            "custom_links": json.dumps(merged["custom_links"] or {}),
            "custom_cards": json.dumps(merged["custom_cards"] or {}),
            "updated_at": now_iso(),
        },
    )
    conn.commit()
    return merged


# --- document extraction cache (Item 6 foundation) ---------------------------
# Deliberately just get/set, no "merge partial fields" behavior like the
# tables above: a cached extraction result is a single opaque JSON blob
# produced entirely by extract.py, not something built up field-by-field
# from separate API calls.

def get_extraction(conn: sqlite3.Connection, content_hash: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM document_extractions WHERE content_hash = ?", (content_hash,)
    ).fetchone()
    return dict(row) if row else None


def set_extraction(
    conn: sqlite3.Connection, content_hash: str, extractor_version: str, data: dict
) -> None:
    conn.execute(
        """
        INSERT INTO document_extractions (content_hash, extractor_version, extracted_json, extracted_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(content_hash) DO UPDATE SET
            extractor_version=excluded.extractor_version,
            extracted_json=excluded.extracted_json,
            extracted_at=excluded.extracted_at
        """,
        (content_hash, extractor_version, json.dumps(data), now_iso()),
    )
    conn.commit()


# --- connected accounts (Item 8 foundation) -----------------------------------
# Row lifecycle only -- never touches credentials, because there are
# none: mail_app_store.py just asks Mail.app questions over
# AppleScript. This module persists the display-facing rows those
# calls produce.

def list_accounts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM accounts ORDER BY connected_at").fetchall()
    return [dict(r) for r in rows]


def get_account(conn: sqlite3.Connection, account_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    return dict(row) if row else None


def upsert_account(
    conn: sqlite3.Connection,
    account_id: str,
    provider: str,
    email: str,
    status: str = "connected",
    account_name: str | None = None,
) -> None:
    """Called once when the user picks a Mail.app account to connect,
    and again whenever its status changes (e.g. back to 'connected'
    after a sync that used to be 'blocked' succeeds)."""
    existing = get_account(conn, account_id)
    now = now_iso()
    conn.execute(
        """
        INSERT INTO accounts (id, provider, email, account_name, status, connected_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status=excluded.status,
            account_name=COALESCE(excluded.account_name, accounts.account_name),
            updated_at=excluded.updated_at
        """,
        (
            account_id, provider, email,
            account_name or (existing.get("account_name") if existing else None),
            status,
            existing.get("connected_at") if existing else now,
            now,
        ),
    )
    conn.commit()


def mark_account_status(conn: sqlite3.Connection, account_id: str, status: str) -> None:
    """status in {'connected','blocked','disconnected'} -- flip to 'blocked'
    when a sync hits a denied macOS Automation permission, so the accounts
    list can surface that instead of silently going stale."""
    conn.execute(
        "UPDATE accounts SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_iso(), account_id),
    )
    conn.commit()


def record_sync(conn: sqlite3.Connection, account_id: str, new_match_count: int) -> None:
    conn.execute(
        """
        UPDATE accounts
        SET last_synced_at = ?, matched_email_count = matched_email_count + ?, updated_at = ?
        WHERE id = ?
        """,
        (now_iso(), new_match_count, now_iso(), account_id),
    )
    conn.commit()


def delete_account(conn: sqlite3.Connection, account_id: str) -> None:
    conn.execute("DELETE FROM account_matches WHERE account_id = ?", (account_id,))
    conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()


def add_account_match(
    conn: sqlite3.Connection,
    account_id: str,
    item_key: str,
    message_id: str,
    subject: str | None,
    received_at: str | None,
) -> bool:
    """Returns False (no-op) on a duplicate message_id for this account --
    that's the re-sync de-dupe, not an error."""
    try:
        conn.execute(
            """
            INSERT INTO account_matches (account_id, item_key, message_id, subject, received_at, matched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (account_id, item_key, message_id, subject, received_at, now_iso()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def list_all_account_matches(conn: sqlite3.Connection) -> list[dict]:
    """Every matched email across every item, regardless of account --
    the sweep list for api.backfill_email_pdfs(), which needs to check
    each one's on-disk folder for a missing evidence PDF (see that
    endpoint's docstring). Unlike get_matches_for_item, not scoped to a
    single item_key."""
    rows = conn.execute("SELECT * FROM account_matches ORDER BY matched_at").fetchall()
    return [dict(r) for r in rows]


def get_matches_for_item(conn: sqlite3.Connection, item_key: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM account_matches WHERE item_key = ? ORDER BY received_at",
        (item_key,),
    ).fetchall()
    return [dict(r) for r in rows]


# --- thread identifiers (deterministic reply-matching) -----------------------

def add_thread_identifiers(conn: sqlite3.Connection, item_key: str, message_ids: list[str]) -> None:
    """Record any of `message_ids` not already known for this item.
    Silently ignores blank/None entries and repeats (INSERT OR IGNORE
    against the (item_key, message_id) primary key) -- a no-op call
    with an empty or all-blank list is fine, callers don't need to
    pre-filter."""
    clean = {m.strip() for m in (message_ids or []) if m and m.strip()}
    if not clean:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO thread_identifiers (item_key, message_id) VALUES (?, ?)",
        [(item_key, m) for m in clean],
    )
    conn.commit()


def get_all_thread_ids_by_item(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Every known thread id, grouped by item_key -- one query for the
    whole sync rather than one query per item, since sync_account()
    needs this map for every open application up front before it can
    call search_messages() at all."""
    rows = conn.execute("SELECT item_key, message_id FROM thread_identifiers").fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["item_key"], []).append(r["message_id"])
    return out


def delete_thread_identifiers(conn: sqlite3.Connection, item_key: str) -> None:
    conn.execute("DELETE FROM thread_identifiers WHERE item_key = ?", (item_key,))
    conn.commit()


# --- discovery review queue ("Possible new applications") --------------------

def add_discovered_match(
    conn: sqlite3.Connection,
    account_id: str,
    message_id: str,
    subject: str | None,
    sender: str | None,
    received_at: str | None,
    guessed_company: str | None,
    match_kind: str = "unmatched",
    candidate_item_keys: list[str] | None = None,
    kind: str = "application",
) -> bool:
    """Returns False (no-op) if this (account_id, message_id) is already
    in the table, at ANY status -- including 'accepted' or 'dismissed'.
    That's what makes an accepted/dismissed discovery never resurface on
    a later scan: this only ever inserts, it never resets a decided row
    back to 'pending'.

    `match_kind`/`candidate_item_keys`: see the discovered_matches schema
    comment. Pass match_kind='ambiguous' with the sibling item_keys when
    filing a company-only sync hit against a multi-item company (see
    api.py's sync_account()); left at the 'unmatched' default for the
    ordinary inbox-scan discovery flow, which doesn't need candidates.

    `kind`: 'application' (default) or 'posting' -- see the schema
    comment. Callers should pass kind='posting' (and leave
    candidate_item_keys unset) whenever
    mail_app_store.is_job_posting_style_subject() matches, regardless of
    what match_kind would otherwise have been -- a job-alert email never
    belongs in the ambiguous-application queue even if its company name
    happens to overlap an existing item."""
    encoded_candidates = json.dumps(candidate_item_keys) if candidate_item_keys else None
    try:
        conn.execute(
            """
            INSERT INTO discovered_matches
                (account_id, message_id, subject, sender, received_at, guessed_company,
                 status, created_at, match_kind, candidate_item_keys, kind)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (account_id, message_id, subject, sender, received_at, guessed_company,
             now_iso(), match_kind, encoded_candidates, kind),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def _decode_discovery(row: sqlite3.Row) -> dict:
    d = dict(row)
    raw = d.get("candidate_item_keys")
    try:
        d["candidate_item_keys"] = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        d["candidate_item_keys"] = []
    raw_urls = d.get("posting_urls")
    try:
        d["posting_urls"] = json.loads(raw_urls) if raw_urls else []
    except (TypeError, ValueError):
        d["posting_urls"] = []
    return d


def list_pending_discoveries(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM discovered_matches WHERE status = 'pending' ORDER BY received_at DESC, id DESC"
    ).fetchall()
    return [_decode_discovery(r) for r in rows]


def get_discovery(conn: sqlite3.Connection, discovery_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM discovered_matches WHERE id = ?", (discovery_id,)).fetchone()
    return _decode_discovery(row) if row else None


def set_discovery_posting_url(conn: sqlite3.Connection, discovery_id: int, posting_url: str) -> None:
    """Persists the job-board link found in a posting's body on first
    preview (see mail_app_store.guess_posting_url()), so later loads of
    /api/discoveries don't need to re-fetch the email to show the link on
    the card. Never overwrites with an empty guess -- callers should only
    call this once a real URL was found."""
    conn.execute(
        "UPDATE discovered_matches SET posting_url = ? WHERE id = ?",
        (posting_url, discovery_id),
    )
    conn.commit()


def set_discovery_posting_urls(conn: sqlite3.Connection, discovery_id: int, posting_urls: list[str]) -> None:
    """Persists every job-board/listing link found in a digest email's
    body (see mail_app_store.extract_posting_urls()) on first preview --
    same lazy-cache timing as set_discovery_posting_url(). Keeps the
    single-value posting_url column in sync as posting_urls[0], so any
    code that still only reads posting_url continues to work unchanged.
    Never call with an empty list -- callers should only call this once
    at least one real URL was found."""
    conn.execute(
        "UPDATE discovered_matches SET posting_urls = ?, posting_url = ? WHERE id = ?",
        (json.dumps(posting_urls), posting_urls[0] if posting_urls else None, discovery_id),
    )
    conn.commit()


def set_discovery_status(conn: sqlite3.Connection, discovery_id: int, status: str) -> None:
    """status in {'pending', 'accepted', 'dismissed'}."""
    conn.execute(
        "UPDATE discovered_matches SET status = ? WHERE id = ?",
        (status, discovery_id),
    )
    conn.commit()


def set_discovery_kind(conn: sqlite3.Connection, discovery_id: int, kind: str) -> None:
    """kind in {'application', 'posting'}. Used by the board's "mark as
    posting" action (drag or click a Needs-Triage card onto Job
    Postings) -- relabels a discovery without touching its status, so it
    moves columns without being resolved/dismissed. Also clears
    candidate_item_keys when moving to 'posting', since a posting never
    has an application to attach to."""
    if kind == "posting":
        conn.execute(
            "UPDATE discovered_matches SET kind = ?, candidate_item_keys = NULL WHERE id = ?",
            (kind, discovery_id),
        )
    else:
        conn.execute(
            "UPDATE discovered_matches SET kind = ? WHERE id = ?",
            (kind, discovery_id),
        )
    conn.commit()


def dismiss_pending_discoveries_by_sender(conn: sqlite3.Connection, sender: str) -> int:
    """Bulk-dismisses every currently-pending discovery from an exact
    `sender` value (the same string list_pending_discoveries() returns
    per row, e.g. \"LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>\")
    -- the review queue's escape hatch for a single noisy recurring
    sender that would otherwise mean clicking Dismiss one row at a time.
    Uses the same 'dismissed' status as a single dismiss, so add_discovered_match's
    de-dupe check keeps these from resurfacing on a later scan just like
    any other dismissed row. Returns the number of rows affected."""
    cur = conn.execute(
        "UPDATE discovered_matches SET status = 'dismissed' WHERE status = 'pending' AND sender = ?",
        (sender,),
    )
    conn.commit()
    return cur.rowcount


# --- job-posting sender whitelist --------------------------------------------
# See discoveries-sender-classification-and-digests-spec.md Part 5.5a: the
# user-taught alternative to hardcoding a new digest sender's domain into
# mail_app_store.py's _MIXED_SIGNAL_SENDER_DOMAINS.

def add_job_posting_sender(conn: sqlite3.Connection, sender: str) -> None:
    """Idempotent -- re-adding an already-whitelisted sender is a no-op,
    not an error."""
    conn.execute(
        "INSERT OR IGNORE INTO job_posting_senders (sender, added_at) VALUES (?, ?)",
        (sender, now_iso()),
    )
    conn.commit()


def remove_job_posting_sender(conn: sqlite3.Connection, sender: str) -> None:
    conn.execute("DELETE FROM job_posting_senders WHERE sender = ?", (sender,))
    conn.commit()


def list_job_posting_senders(conn: sqlite3.Connection) -> list[str]:
    """Every whitelisted exact sender string, oldest first -- fetched by
    api.py before each discover_new_applications() call and passed into
    mail_app_store.search_unmatched_messages() as `always_posting_senders`."""
    rows = conn.execute("SELECT sender FROM job_posting_senders ORDER BY added_at").fetchall()
    return [r["sender"] for r in rows]


# --- job_postings: first-class job records (CLAUDE_HANDOFF.md section 8) -----

def add_job_posting(
    conn: sqlite3.Connection,
    account_id: str,
    message_id: str,
    dedupe_key: str,
    source: str | None,
    title: str | None,
    company: str | None,
    location: str | None,
    salary: str | None,
    employment_type: str | None,
    posting_url: str | None,
    received_at: str | None,
    email_subject: str | None,
    sender: str | None,
) -> bool:
    """Returns False (no-op) if a job with this exact dedupe_key already
    exists -- see the job_postings.dedupe_key UNIQUE constraint and
    posting_extract.compute_dedupe_key(). This is what makes re-running
    extraction over the same digest on a later sync safe (CLAUDE_HANDOFF.md
    section 9's "same email scanned twice -> no duplicates")."""
    try:
        conn.execute(
            """
            INSERT INTO job_postings
                (account_id, message_id, source, title, company, location, salary,
                 employment_type, posting_url, received_at, email_subject, sender,
                 status, created_at, dedupe_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
            """,
            (account_id, message_id, source, title, company, location, salary,
             employment_type, posting_url, received_at, email_subject, sender,
             now_iso(), dedupe_key),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def list_job_postings(conn: sqlite3.Connection, status: str = "new") -> list[dict]:
    """All job postings at the given status (default 'new', i.e. not
    dismissed), newest first. Pass status=None for every row regardless
    of status."""
    if status is None:
        rows = conn.execute(
            "SELECT * FROM job_postings ORDER BY received_at DESC, id DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM job_postings WHERE status = ? ORDER BY received_at DESC, id DESC",
            (status,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_job_posting(conn: sqlite3.Connection, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM job_postings WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def set_job_posting_status(conn: sqlite3.Connection, job_id: int, status: str) -> None:
    """status in {'new', 'dismissed'}."""
    conn.execute("UPDATE job_postings SET status = ? WHERE id = ?", (status, job_id))
    conn.commit()


def count_job_postings(conn: sqlite3.Connection, status: str = "new") -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM job_postings WHERE status = ?", (status,)
    ).fetchone()
    return row["n"] if row else 0
