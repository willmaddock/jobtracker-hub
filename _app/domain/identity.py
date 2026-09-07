"""
Identity resolution: numeric items.id (what the frontend/URLs use) -> the
stable item_key that overrides.db is actually keyed by.

Extracted from api.py verbatim (previous name: item_key_for), moved here
because this is a domain identity rule, not connection plumbing -- see
domain-model.md's finding that item_key, not the AUTOINCREMENT id, is
JobTracker's real identity. It was previously sitting next to get_conns()
in api.py as if it were infrastructure.

The only functional change from the original: raises ItemNotFoundError
instead of fastapi.HTTPException, so this is callable (and testable) with
a bare sqlite3 connection and no FastAPI import anywhere in the call chain.
"""

from __future__ import annotations

from domain.errors import ItemNotFoundError


def item_key_for(jt_conn, app_id: int) -> str:
    """Resolve a numeric `items.id` to the stable `item_key`. Ids come from
    an AUTOINCREMENT column that gets reset on every /api/rebuild, so
    they're convenient/clean for routes and URLs but are NOT what overrides
    should be stored against -- item_key (section|company|role|relpath) is
    the thing that survives a rebuild."""
    row = jt_conn.execute("SELECT item_key FROM items WHERE id = ?", (app_id,)).fetchone()
    if row is None:
        raise ItemNotFoundError(app_id)
    return row["item_key"]
