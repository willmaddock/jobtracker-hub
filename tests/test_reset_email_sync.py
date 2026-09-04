"""
Tests for the deliberate "Reset Email Sync" action: overrides_store.
reset_email_sync() directly, and the /api/accounts/reset-email-sync route
that wraps it. Covers both what gets wiped (accounts, account_matches,
discovered_matches, job_postings) and what's deliberately left alone
(job_posting_senders, thread_identifiers, and all application data).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import overrides_store as ov


def _seed(conn):
    """Populates one of everything reset_email_sync touches (or should
    leave alone), so a single reset call can be checked against all of
    it at once."""
    ov.upsert_account(conn, "acct-1", "mail_app", "me@example.com", account_name="hotmail")
    ov.add_account_match(conn, "acct-1", "Acme/Backend Engineer", "<m1>", "Interview invite", "2026-08-24")
    ov.add_discovered_match(conn, "acct-1", "<m2>", "New role at Globex", "hr@globex.com", "2026-08-25", "Globex")
    ov.add_job_posting(
        conn, "acct-1", "<m3>", "dedupe-1", "linkedin",
        "Backend Engineer", "Initech", "Remote", None, "Full-time",
        "https://example.com/job/1", "2026-08-26", "Job alert", "jobs-noreply@linkedin.com",
    )
    ov.add_job_posting_sender(conn, "jobs-noreply@linkedin.com")
    ov.add_thread_identifiers(conn, "Acme/Backend Engineer", ["<m1>", "<m1-reply>"])
    ov.upsert_override(conn, "Acme/Backend Engineer", manual_status="applied", notes="great fit")


def test_reset_email_sync_clears_accounts_matches_discoveries_and_postings(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    _seed(conn)

    counts = ov.reset_email_sync(conn)

    assert counts == {
        "accounts": 1,
        "account_matches": 1,
        "discovered_matches": 1,
        "job_postings": 1,
    }
    assert ov.list_accounts(conn) == []
    assert ov.list_all_account_matches(conn) == []
    assert ov.list_pending_discoveries(conn) == []
    assert ov.list_job_postings(conn, status="new") == []


def test_reset_email_sync_preserves_taught_senders_and_thread_identifiers(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    _seed(conn)

    ov.reset_email_sync(conn)

    assert ov.list_job_posting_senders(conn) == ["jobs-noreply@linkedin.com"]
    thread_ids = ov.get_all_thread_ids_by_item(conn)
    assert set(thread_ids.get("Acme/Backend Engineer", [])) == {"<m1>", "<m1-reply>"}


def test_reset_email_sync_never_touches_application_data(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    _seed(conn)

    ov.reset_email_sync(conn)

    override = conn.execute(
        "SELECT manual_status, notes FROM item_overrides WHERE item_key = ?",
        ("Acme/Backend Engineer",),
    ).fetchone()
    assert override["manual_status"] == "applied"
    assert override["notes"] == "great fit"


def test_reset_email_sync_on_empty_db_is_a_safe_no_op(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    assert ov.reset_email_sync(conn) == {
        "accounts": 0, "account_matches": 0, "discovered_matches": 0, "job_postings": 0,
    }


@pytest.fixture
def linked(client, sample_root):
    client.post("/api/workspaces/link", json={"name": "Reset Test", "path": str(sample_root)})
    return sample_root


def test_reset_endpoint_clears_accounts_and_reports_counts(client, linked, api_module):
    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "hotmail", "email": "stumping123@outlook.com"},
    ).json()["account_id"]

    hits = [{"message_id": "<m1>", "subject": "Interview invite - Acme", "sender": "hr@acme.com", "received_at": "2026-08-24"}]
    with patch.object(api_module.mailapp, "search_messages", return_value=hits):
        client.post(f"/api/accounts/{account_id}/sync")

    resp = client.post("/api/accounts/reset-email-sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["deleted"]["accounts"] == 1
    assert body["deleted"]["account_matches"] == 1

    assert client.get("/api/accounts").json() == []


def test_reset_endpoint_on_empty_state_still_succeeds(client, linked):
    resp = client.post("/api/accounts/reset-email-sync")
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "deleted": {"accounts": 0, "account_matches": 0, "discovered_matches": 0, "job_postings": 0},
    }
