"""
Direct unit tests for overrides_store.py's Checkpoint 6 addition:
the `date_applied_source` column and its migration for pre-existing
overrides.db files. These exercise the module directly (no FastAPI
client needed) -- conftest.py already puts _app/ on sys.path.
"""

from __future__ import annotations

import sqlite3

import overrides_store as ov


def test_fresh_db_has_date_applied_source_column(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(item_overrides)")}
    assert "date_applied_source" in cols


def test_migration_adds_column_to_a_pre_checkpoint6_db(tmp_path):
    # Simulate an overrides.db written before date_applied_source existed --
    # build the table by hand without that column, then confirm get_conn's
    # _migrate() step adds it (and doesn't choke on the missing column).
    db_path = tmp_path / "legacy_overrides.db"
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        """
        CREATE TABLE item_overrides (
            item_key TEXT PRIMARY KEY,
            manual_status TEXT,
            notes TEXT,
            date_applied TEXT,
            next_action TEXT,
            next_action_date TEXT,
            archived INTEGER NOT NULL DEFAULT 0,
            snoozed_until TEXT,
            updated_at TEXT
        )
        """
    )
    legacy.execute(
        "INSERT INTO item_overrides (item_key, date_applied, updated_at) VALUES (?, ?, ?)",
        ("applications|Acme|Role|x", "2025-01-01", "2025-01-01T00:00:00+00:00"),
    )
    legacy.commit()
    legacy.close()

    conn = ov.get_conn(db_path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(item_overrides)")}
    assert "date_applied_source" in cols
    assert "activity_override" in cols  # the earlier migration still applies too

    # Pre-existing row survives the migration, with the new column NULL.
    row = ov.get_override(conn, "applications|Acme|Role|x")
    assert row["date_applied"] == "2025-01-01"
    assert row["date_applied_source"] is None


def test_upsert_override_round_trips_date_applied_source(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    ov.upsert_override(conn, "k1", date_applied="2025-07-10", date_applied_source="confirmation")
    row = ov.get_override(conn, "k1")
    assert row["date_applied"] == "2025-07-10"
    assert row["date_applied_source"] == "confirmation"


def test_upsert_override_without_source_clears_it(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    ov.upsert_override(conn, "k1", date_applied="2025-07-10", date_applied_source="confirmation")
    # A manual retype -- caller passes date_applied_source=None explicitly,
    # same as api.py's save_override does for a plain date_applied write.
    ov.upsert_override(conn, "k1", date_applied="2025-08-01", date_applied_source=None)
    row = ov.get_override(conn, "k1")
    assert row["date_applied"] == "2025-08-01"
    assert row["date_applied_source"] is None


def test_upsert_override_preserves_date_applied_source_when_untouched(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    ov.upsert_override(conn, "k1", date_applied="2025-07-10", date_applied_source="confirmation")
    # Updating an unrelated field (e.g. notes) must not disturb provenance --
    # upsert_override's merge-from-existing default keeps it as-is.
    ov.upsert_override(conn, "k1", notes="Follow up next week")
    row = ov.get_override(conn, "k1")
    assert row["date_applied"] == "2025-07-10"
    assert row["date_applied_source"] == "confirmation"
    assert row["notes"] == "Follow up next week"
