"""
Combines the disposable, auto-built jobtracker.db index with your durable
overrides.db (notes, manual status, dates, company merges) into the
"effective" view the app actually renders. Nothing here writes to your
JobTracker folder — only to the two local SQLite files.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import overrides_store as ov

# _app/ (this file's directory) lives one level inside the JobTracker root
# it indexes — see build_index.py's DEFAULT_ROOT. Exposed here too since
# api.py needs it to safely resolve "open"/"serve" requests without ever
# asking for a path.
APP_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = APP_DIR.parent

STATUS_ORDER = ["drafted", "applied", "interviewing", "rejected", "unknown"]

STATUS_COLORS = {
    "applied": "#4a9eff",
    "interviewing": "#3ddc84",
    "rejected": "#ff5c5c",
    "drafted": "#9aa4b2",
    "unknown": "#5b6472",
}

STATUS_ICONS = {
    "applied": "🔵",
    "interviewing": "🟢",
    "rejected": "🔴",
    "drafted": "⚪",
    "unknown": "⚫",
}

STALE_APPLIED_DAYS = 21   # applied/interviewing with no update in this long -> needs attention
STALE_DRAFTED_DAYS = 14   # drafted/unknown untouched this long -> needs attention


def get_jt_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _days_since(iso_str: str | None) -> int | None:
    dt = _parse_iso(iso_str)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).days


def load_applications(jt_conn: sqlite3.Connection, ov_conn: sqlite3.Connection) -> list[dict]:
    """Every Applications/ item, enriched with overrides. One dict per item."""
    rows = jt_conn.execute("SELECT * FROM items WHERE section = 'applications'").fetchall()
    overrides = ov.get_all_overrides(ov_conn)
    aliases = ov.get_aliases(ov_conn)

    out = []
    for r in rows:
        d = dict(r)
        o = overrides.get(d["item_key"], {})
        d["manual_status"] = o.get("manual_status")
        d["notes"] = o.get("notes")
        d["date_applied"] = o.get("date_applied")
        d["next_action"] = o.get("next_action")
        d["next_action_date"] = o.get("next_action_date")
        d["archived"] = bool(o.get("archived", 0))
        d["snoozed_until"] = o.get("snoozed_until")
        d["activity_override"] = o.get("activity_override")

        d["effective_status"] = d["manual_status"] or d["status"]
        d["effective_company"] = aliases.get(d["company"], d["company"])

        # Reference date for "how long has this been sitting" — activity_override
        # wins first (explicit "Reset activity clock", e.g. after an interview or
        # a follow-up, without touching date_applied itself), then the date you
        # set as date_applied, then the (unreliable) file mtime as a last resort.
        reference_date = d["activity_override"] or d["date_applied"] or d["last_activity"]
        d["days_since_activity"] = _days_since(reference_date)
        d["date_is_manual"] = bool(d["date_applied"])
        d["activity_is_reset"] = bool(d["activity_override"])

        d["is_stale"] = False
        if not d["archived"] and d["days_since_activity"] is not None:
            if d["effective_status"] in ("applied", "interviewing") and d["days_since_activity"] >= STALE_APPLIED_DAYS:
                d["is_stale"] = True
            elif d["effective_status"] in ("drafted", "unknown") and d["days_since_activity"] >= STALE_DRAFTED_DAYS:
                d["is_stale"] = True

        # A next action dated today-or-earlier also surfaces in Needs Attention.
        next_due = _parse_iso(d["next_action_date"])
        d["next_action_due"] = bool(next_due and next_due <= datetime.now(timezone.utc))

        snoozed_until = _parse_iso(d["snoozed_until"])
        d["is_snoozed"] = bool(snoozed_until and snoozed_until > datetime.now(timezone.utc))

        out.append(d)
    return out


def load_documents(jt_conn: sqlite3.Connection, item_id: int, ov_conn: sqlite3.Connection | None = None) -> list[dict]:
    rows = jt_conn.execute(
        "SELECT * FROM documents WHERE item_id = ? ORDER BY doc_type, filename", (item_id,)
    ).fetchall()
    docs = [dict(r) for r in rows]
    if ov_conn is not None:
        docs = apply_document_overrides(ov_conn, docs)
    return annotate_duplicates(jt_conn, docs)


def apply_document_overrides(ov_conn: sqlite3.Connection, docs: list[dict]) -> list[dict]:
    """Overlays your manual doc-type corrections (overrides.db) onto the
    auto-classified `doc_type`, same pattern as manual_status on
    applications: `doc_type` stays the auto-guess, `effective_doc_type` is
    what the UI should show/group by."""
    overrides = ov.get_document_overrides(ov_conn)
    for d in docs:
        d["doc_type_override"] = overrides.get(d["relpath"])
        d["effective_doc_type"] = d["doc_type_override"] or d["doc_type"]
    return docs


def annotate_duplicates(jt_conn: sqlite3.Connection, docs: list[dict]) -> list[dict]:
    """Adds `duplicate_count` (how many OTHER indexed documents share this
    file's exact content) to each doc dict, using the content_hash computed
    at index time. Never merges, hides, or deletes anything — purely an
    informational badge so identical copies filed under different
    applications are visible as the same underlying document. A NULL/blank
    hash (unreadable file) is never treated as a match."""
    hashes = [d["content_hash"] for d in docs if d.get("content_hash")]
    if not hashes:
        for d in docs:
            d["duplicate_count"] = 0
        return docs
    placeholders = ",".join("?" for _ in set(hashes))
    counts = dict(
        jt_conn.execute(
            f"SELECT content_hash, COUNT(*) FROM documents "
            f"WHERE content_hash IN ({placeholders}) GROUP BY content_hash",
            list(set(hashes)),
        ).fetchall()
    )
    for d in docs:
        h = d.get("content_hash")
        d["duplicate_count"] = max(0, counts.get(h, 1) - 1) if h else 0
    return docs


def find_duplicate_groups(jt_conn: sqlite3.Connection) -> list[dict]:
    """Every content_hash shared by 2+ documents, with each document's
    location (company/role/relpath) — powers a 'Duplicates' list in Manage.
    Read-only; never used to delete or merge physical files."""
    rows = jt_conn.execute(
        """
        SELECT d.content_hash, d.filename, d.relpath, d.doc_type, i.company, i.role_label
        FROM documents d JOIN items i ON i.id = d.item_id
        WHERE d.content_hash IN (
            SELECT content_hash FROM documents
            WHERE content_hash IS NOT NULL GROUP BY content_hash HAVING COUNT(*) > 1
        )
        ORDER BY d.content_hash, i.company, i.role_label
        """
    ).fetchall()
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["content_hash"], []).append(dict(r))
    return [{"content_hash": h, "documents": docs} for h, docs in groups.items()]


def compute_metrics(apps: list[dict]) -> dict:
    active = [a for a in apps if not a["archived"]]
    total = len(active)
    by_status = {s: 0 for s in STATUS_ORDER}
    for a in active:
        by_status[a["effective_status"]] = by_status.get(a["effective_status"], 0) + 1

    # "Responded" = got any signal back at all (interview or rejection).
    responded = by_status.get("interviewing", 0) + by_status.get("rejected", 0)
    sent = by_status.get("applied", 0) + by_status.get("interviewing", 0) + by_status.get("rejected", 0)
    response_rate = (responded / sent * 100) if sent else 0.0
    interview_rate = (by_status.get("interviewing", 0) / sent * 100) if sent else 0.0

    # Time-to-response, for items where we have both a date_applied and a
    # last_activity after it (best-effort — only meaningful when date_applied
    # was set manually, since mtime-based last_activity is unreliable).
    lags = []
    for a in active:
        if a["date_applied"] and a["effective_status"] in ("interviewing", "rejected") and a["last_activity"]:
            applied_dt = _parse_iso(a["date_applied"])
            last_dt = _parse_iso(a["last_activity"])
            if applied_dt and last_dt and last_dt > applied_dt:
                lags.append((last_dt - applied_dt).days)
    avg_response_days = round(sum(lags) / len(lags)) if lags else None

    return {
        "total": total,
        "by_status": by_status,
        "response_rate": response_rate,
        "interview_rate": interview_rate,
        "avg_response_days": avg_response_days,
        "lag_sample_size": len(lags),
    }


def needs_attention(apps: list[dict]) -> list[dict]:
    return sorted(
        [
            a for a in apps
            if not a["archived"] and not a["is_snoozed"] and (a["is_stale"] or a["next_action_due"])
        ],
        key=lambda a: (-1 if a["next_action_due"] else 0, -(a["days_since_activity"] or 0)),
    )


def suggest_duplicate_companies(apps: list[dict]) -> dict[str, list[str]]:
    """Group raw company names that normalize to the same loose key, minus
    ones you've already aliased. Returns {loose_key: [raw_name, raw_name, ...]}
    for any group with 2+ distinct raw names — surfaced in Manage as merge
    suggestions, never applied automatically."""
    from classify import normalize_company_key

    groups: dict[str, set[str]] = {}
    for a in apps:
        key = normalize_company_key(a["company"])
        groups.setdefault(key, set()).add(a["company"])
    return {k: sorted(v) for k, v in groups.items() if len(v) > 1}
