"""
Direct unit tests for overrides_store.py's job_postings table -- the
first-class job-posting record introduced for the Email Sync redesign
(CLAUDE_HANDOFF.md section 8). Exercises the module directly, same
pattern as test_overrides_store.py.
"""

from __future__ import annotations

import overrides_store as ov


def _add(conn, **overrides):
    fields = dict(
        account_id="acct1",
        message_id="msg1",
        dedupe_key="key1",
        source="linkedin",
        title="Software Engineer",
        company="Haystack",
        location="Colorado, United States (Remote)",
        salary=None,
        employment_type=None,
        posting_url=None,
        received_at="2026-09-01T13:09:00",
        email_subject="Software Engineer at Haystack",
        sender="LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
    )
    fields.update(overrides)
    return ov.add_job_posting(conn, **fields)


def test_fresh_db_has_job_postings_table(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(job_postings)")}
    assert {"title", "company", "dedupe_key", "status"} <= cols


def test_add_job_posting_inserts(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    assert _add(conn) is True
    rows = ov.list_job_postings(conn)
    assert len(rows) == 1
    assert rows[0]["title"] == "Software Engineer"
    assert rows[0]["status"] == "new"


def test_add_job_posting_same_dedupe_key_is_noop(tmp_path):
    # CLAUDE_HANDOFF.md section 9: re-scanning the same email must not
    # duplicate jobs.
    conn = ov.get_conn(tmp_path / "overrides.db")
    assert _add(conn) is True
    assert _add(conn) is False
    assert len(ov.list_job_postings(conn)) == 1


def test_multiple_jobs_same_message_different_dedupe_keys(tmp_path):
    # One email -> many job postings (CLAUDE_HANDOFF.md section 2/6).
    conn = ov.get_conn(tmp_path / "overrides.db")
    for i in range(6):
        assert _add(conn, dedupe_key=f"key{i}", title=f"Job {i}") is True
    assert len(ov.list_job_postings(conn)) == 6


def test_dismiss_hides_from_default_listing(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    _add(conn)
    job = ov.list_job_postings(conn)[0]
    ov.set_job_posting_status(conn, job["id"], "dismissed")
    assert ov.list_job_postings(conn, status="new") == []
    assert len(ov.list_job_postings(conn, status="dismissed")) == 1
    assert len(ov.list_job_postings(conn, status=None)) == 1


def test_count_job_postings(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    assert ov.count_job_postings(conn) == 0
    _add(conn, dedupe_key="a")
    _add(conn, dedupe_key="b")
    assert ov.count_job_postings(conn) == 2


def test_fresh_db_job_postings_saved_column_defaults_false(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(job_postings)")}
    assert "saved" in cols
    _add(conn)
    assert ov.list_job_postings(conn)[0]["saved"] == 0


def test_set_job_posting_saved_toggles_independently_of_status(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    _add(conn)
    job = ov.list_job_postings(conn)[0]
    ov.set_job_posting_saved(conn, job["id"], True)
    assert ov.get_job_posting(conn, job["id"])["saved"] == 1

    # Saved survives a dismiss -- these are independent flags.
    ov.set_job_posting_status(conn, job["id"], "dismissed")
    dismissed = ov.get_job_posting(conn, job["id"])
    assert dismissed["status"] == "dismissed"
    assert dismissed["saved"] == 1

    ov.set_job_posting_saved(conn, job["id"], False)
    assert ov.get_job_posting(conn, job["id"])["saved"] == 0


def test_fresh_db_job_postings_applied_item_key_column_defaults_null(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(job_postings)")}
    assert "applied_item_key" in cols
    _add(conn)
    assert ov.list_job_postings(conn)[0]["applied_item_key"] is None


def test_set_job_posting_applied_links_item_key(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    _add(conn)
    job = ov.list_job_postings(conn)[0]
    ov.set_job_posting_applied(conn, job["id"], "Applications|Haystack|Software Engineer")
    assert ov.get_job_posting(conn, job["id"])["applied_item_key"] == "Applications|Haystack|Software Engineer"

    # Independent of status/saved, same as the other job_postings flags.
    ov.set_job_posting_status(conn, job["id"], "dismissed")
    ov.set_job_posting_saved(conn, job["id"], True)
    still_linked = ov.get_job_posting(conn, job["id"])
    assert still_linked["applied_item_key"] == "Applications|Haystack|Software Engineer"
    assert still_linked["status"] == "dismissed"
    assert still_linked["saved"] == 1


def test_get_job_posting_by_id(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    _add(conn)
    job = ov.list_job_postings(conn)[0]
    fetched = ov.get_job_posting(conn, job["id"])
    assert fetched["title"] == "Software Engineer"
    assert ov.get_job_posting(conn, 99999) is None
