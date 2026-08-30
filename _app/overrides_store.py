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
-- ITEM7_TIMELINE_FDD_DRAFT.md).
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


def get_conn(db_path: Path) -> sqlite3.Connection:
    # overrides.db now lives inside the workspace's own root (see
    # workspace.py's _portable_ov_db_path), which — unlike this app's own
    # private storage — isn't guaranteed to already have the containing
    # folder created. A brand-new or freshly linked workspace won't have
    # a .jobtracker/ folder yet, so make sure it exists before sqlite
    # tries to create the file inside it.
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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
