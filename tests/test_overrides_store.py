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


def test_fresh_db_has_discovered_matches_kind_column(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(discovered_matches)")}
    assert "kind" in cols


def test_migration_adds_kind_column_to_a_pre_kanban_db(tmp_path):
    # Simulate an overrides.db written before discovered_matches.kind
    # existed -- build the table by hand without it (but with the
    # earlier match_kind/candidate_item_keys columns, which already
    # predate this change), then confirm _migrate() adds it.
    db_path = tmp_path / "legacy_overrides.db"
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        """
        CREATE TABLE discovered_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            subject TEXT,
            sender TEXT,
            received_at TEXT,
            guessed_company TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            match_kind TEXT NOT NULL DEFAULT 'unmatched',
            candidate_item_keys TEXT,
            UNIQUE(account_id, message_id)
        )
        """
    )
    legacy.execute(
        "INSERT INTO discovered_matches (account_id, message_id, created_at) VALUES (?, ?, ?)",
        ("acct-1", "msg-1", "2025-01-01T00:00:00+00:00"),
    )
    legacy.commit()
    legacy.close()

    conn = ov.get_conn(db_path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(discovered_matches)")}
    assert "kind" in cols

    # Pre-existing row survives the migration, defaulted to 'application'.
    row = ov.get_discovery(conn, 1)
    assert row["kind"] == "application"


def test_add_discovered_match_defaults_to_application_kind(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    ov.add_discovered_match(conn, "acct-1", "msg-1", "Your application to Acme", "hr@acme.com", "2025-01-01", "Acme")
    row = ov.get_discovery(conn, 1)
    assert row["kind"] == "application"


def test_add_discovered_match_accepts_posting_kind(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    ov.add_discovered_match(
        conn, "acct-1", "msg-1", "KPMG just posted a 78% match", "hr@kpmg.com",
        "2025-01-01", "KPMG", kind="posting",
    )
    row = ov.get_discovery(conn, 1)
    assert row["kind"] == "posting"
    assert row["candidate_item_keys"] == []


def test_set_discovery_kind_marks_a_discovery_as_posting_and_clears_candidates(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    ov.add_discovered_match(
        conn, "acct-1", "msg-1", "KPMG just posted a 78% match", "hr@kpmg.com", "2025-01-01", "KPMG",
        match_kind="ambiguous", candidate_item_keys=["applications|KPMG|Role1|x", "applications|KPMG|Role2|y"],
    )
    ov.set_discovery_kind(conn, 1, "posting")
    row = ov.get_discovery(conn, 1)
    assert row["kind"] == "posting"
    assert row["candidate_item_keys"] == []


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


# --- Part 5.5: job_posting_senders whitelist + posting_urls -----------------

def test_fresh_db_has_job_posting_senders_table_and_posting_urls_column(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "job_posting_senders" in tables
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(discovered_matches)")}
    assert "posting_urls" in cols


def test_migration_adds_posting_urls_column_to_a_pre_5_5_db(tmp_path):
    # Simulate an overrides.db written before posting_urls/job_posting_senders
    # existed -- build discovered_matches by hand without posting_urls (but
    # with the earlier posting_url column, which already predates this
    # change), then confirm _migrate() adds it without choking.
    db_path = tmp_path / "legacy_overrides.db"
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        """
        CREATE TABLE discovered_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            subject TEXT,
            sender TEXT,
            received_at TEXT,
            guessed_company TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            match_kind TEXT NOT NULL DEFAULT 'unmatched',
            candidate_item_keys TEXT,
            kind TEXT NOT NULL DEFAULT 'application',
            posting_url TEXT,
            UNIQUE(account_id, message_id)
        )
        """
    )
    legacy.execute(
        "INSERT INTO discovered_matches (account_id, message_id, created_at, posting_url) VALUES (?, ?, ?, ?)",
        ("acct-1", "msg-1", "2025-01-01T00:00:00+00:00", "https://boards.greenhouse.io/acme/jobs/1"),
    )
    legacy.commit()
    legacy.close()

    conn = ov.get_conn(db_path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(discovered_matches)")}
    assert "posting_urls" in cols
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "job_posting_senders" in tables

    # Pre-existing row survives the migration; posting_url is untouched,
    # posting_urls defaults to an empty list until a preview re-derives it.
    row = ov.get_discovery(conn, 1)
    assert row["posting_url"] == "https://boards.greenhouse.io/acme/jobs/1"
    assert row["posting_urls"] == []


def test_add_and_list_job_posting_senders(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    sender = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
    ov.add_job_posting_sender(conn, sender)
    assert ov.list_job_posting_senders(conn) == [sender]
    # Idempotent -- re-adding the same sender doesn't duplicate it.
    ov.add_job_posting_sender(conn, sender)
    assert ov.list_job_posting_senders(conn) == [sender]


def test_remove_job_posting_sender(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    sender = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
    ov.add_job_posting_sender(conn, sender)
    ov.remove_job_posting_sender(conn, sender)
    assert ov.list_job_posting_senders(conn) == []


def test_set_discovery_posting_urls_persists_list_and_keeps_posting_url_in_sync(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    ov.add_discovered_match(
        conn, "acct-1", "msg-1", "Software Engineer at Haystack",
        "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", "2026-09-01", None, kind="posting",
    )
    urls = [
        "https://www.linkedin.com/jobs/view/1111",
        "https://www.linkedin.com/jobs/view/2222",
        "https://www.linkedin.com/jobs/view/3333",
    ]
    ov.set_discovery_posting_urls(conn, 1, urls)
    row = ov.get_discovery(conn, 1)
    assert row["posting_urls"] == urls
    assert row["posting_url"] == urls[0]
