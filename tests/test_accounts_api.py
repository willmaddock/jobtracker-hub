"""
/api/accounts/* routes -- the Mail.app-backed connect/sync/disconnect
flow in api.py. mail_app_store itself is mocked throughout (no real
osascript call in this suite, per test_mail_app_store.py's own
docstring), so these exercise api.py's plumbing: the accounts table,
the available/connect picker flow, and sync's per-item matching.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def linked(client, sample_root):
    client.post("/api/workspaces/link", json={"name": "Accounts Test", "path": str(sample_root)})
    return sample_root


def test_no_accounts_connected_initially(client, linked):
    resp = client.get("/api/accounts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_available_accounts_lists_mail_app_accounts(client, linked, api_module):
    with patch.object(
        api_module.mailapp, "list_mail_app_accounts",
        return_value=[{"name": "hotmail", "email": "stumping123@outlook.com"}],
    ):
        resp = client.get("/api/accounts/mail-app/available")
    assert resp.status_code == 200
    assert resp.json() == [{"name": "hotmail", "email": "stumping123@outlook.com"}]


def test_available_accounts_surfaces_permission_error(client, linked, api_module):
    with patch.object(
        api_module.mailapp, "list_mail_app_accounts",
        side_effect=api_module.mailapp.MailAppError("enable Mail for JobTracker Hub"),
    ):
        resp = client.get("/api/accounts/mail-app/available")
    assert resp.status_code == 400
    assert "enable Mail" in resp.json()["detail"]


def test_connect_then_it_no_longer_appears_as_available(client, linked, api_module):
    connect = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "hotmail", "email": "stumping123@outlook.com"},
    )
    assert connect.status_code == 200
    account_id = connect.json()["account_id"]

    listed = client.get("/api/accounts").json()
    assert len(listed) == 1
    assert listed[0]["id"] == account_id
    assert listed[0]["email"] == "stumping123@outlook.com"
    assert listed[0]["account_name"] == "hotmail"
    assert listed[0]["status"] == "connected"

    with patch.object(
        api_module.mailapp, "list_mail_app_accounts",
        return_value=[{"name": "hotmail", "email": "stumping123@outlook.com"}],
    ):
        available = client.get("/api/accounts/mail-app/available").json()
    assert available == []


def test_disconnect_removes_the_account(client, linked):
    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "hotmail", "email": "stumping123@outlook.com"},
    ).json()["account_id"]

    resp = client.delete(f"/api/accounts/{account_id}")
    assert resp.status_code == 200
    assert client.get("/api/accounts").json() == []


def test_sync_matches_against_the_one_open_application(client, linked, api_module):
    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "hotmail", "email": "stumping123@outlook.com"},
    ).json()["account_id"]

    # sample_root has exactly one application: Acme Co / Backend Engineer.
    hits = [
        {"message_id": "<m1>", "subject": "Interview invite - Acme", "sender": "hr@acme.com", "received_at": "2026-08-24"},
    ]
    with patch.object(api_module.mailapp, "search_messages", return_value=hits) as search:
        resp = client.post(f"/api/accounts/{account_id}/sync")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "new_matches": 1, "ambiguous_matches": 0}
    search.assert_called_once()
    call_args = search.call_args
    assert call_args[0][0] == "hotmail"  # queried by account_name, not email
    assert "Acme Co" in call_args[0][1]  # effective_company was in the search terms

    account = client.get("/api/accounts").json()[0]
    assert account["matched_email_count"] == 1
    assert account["last_synced_at"] is not None
    assert account["status"] == "connected"


def test_sync_drops_generic_role_term_but_keeps_company(client, tmp_path, api_module):
    """Regression test: a role label this short/generic (e.g. "IT") used
    to be OR'd straight into the AppleScript `contains` search and matched
    huge amounts of unrelated mail -- see mail_app_store.is_usable_match_term.
    The company term should still be searched; only the unusable role term
    gets dropped."""
    root = tmp_path / "generic-role-tracker"
    role_dir = root / "Applications" / "Adams County" / "IT"
    role_dir.mkdir(parents=True)
    minimal_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n"
    )
    (role_dir / "resume.pdf").write_bytes(minimal_pdf)
    client.post("/api/workspaces/link", json={"name": "Generic Role Test", "path": str(root)})

    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "hotmail", "email": "stumping123@outlook.com"},
    ).json()["account_id"]

    with patch.object(api_module.mailapp, "search_messages", return_value=[]) as search:
        resp = client.post(f"/api/accounts/{account_id}/sync")
    assert resp.status_code == 200
    search.assert_called_once()
    terms = search.call_args[0][1]
    assert "IT" not in terms
    assert "Adams County" in terms


def test_sync_routes_company_only_hit_to_ambiguous_queue_when_company_has_two_open_items(
    client, tmp_path, api_module
):
    """Regression test for the Adams County / Public Health Department
    misattribution: a company with two open items and a role label too
    generic to search on (e.g. "IT") used to auto-attach any company-
    only text hit to whichever item search_messages() happened to be
    called for, with nothing confirming which specific role the email
    was actually about. A company-only hit against a multi-item company
    should now land in the discoveries queue as 'ambiguous' with both
    item_keys offered as candidates, and NOT be recorded as a confirmed
    account_match on either item."""
    root = tmp_path / "ambiguous-company-tracker"
    minimal_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n"
    )
    for role in ("IT", "Environmental Health Specialist"):
        role_dir = root / "Applications" / "Adams County" / role
        role_dir.mkdir(parents=True)
        (role_dir / "resume.pdf").write_bytes(minimal_pdf)
    client.post("/api/workspaces/link", json={"name": "Ambiguous Company Test", "path": str(root)})

    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "gmail", "email": "willzaeagle@gmail.com"},
    ).json()["account_id"]

    # A company-only hit: matches "Adams County" as a whole word, but
    # never confirms "IT" (dropped as generic) or "Environmental Health
    # Specialist" (not present in this subject at all).
    company_only_hit = {
        "message_id": "<adams-notice-1>",
        "subject": "Notice from Adams County",
        "sender": "willzaeagle@gmail.com",
        "received_at": "2026-08-24",
        "matched_via": "text",
        "thread_message_ids": ["<adams-notice-1>"],
        "company_only": True,
    }
    with patch.object(api_module.mailapp, "search_messages", return_value=[company_only_hit]):
        resp = client.post(f"/api/accounts/{account_id}/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body["new_matches"] == 0
    assert body["ambiguous_matches"] == 1

    discoveries = client.get("/api/discoveries").json()
    assert len(discoveries) == 1
    d = discoveries[0]
    assert d["match_kind"] == "ambiguous"
    assert d["guessed_company"] == "Adams County"
    candidate_labels = {c["label"] for c in d["candidates"]}
    assert candidate_labels == {"Adams County — IT", "Adams County — Environmental Health Specialist"}

    # Not auto-attached to either item as a confirmed match.
    matches = api_module.ov.list_all_account_matches(
        api_module.get_conns()[1]
    )
    assert matches == []


def test_sync_routes_job_posting_shaped_company_only_hit_to_postings_not_ambiguous_queue(
    client, tmp_path, api_module
):
    """Companion to the ambiguous-routing test above: a company-only hit
    whose subject reads as a job-alert/listing notice (e.g. "KPMG US
    just posted a 78% match...") must never enter the ambiguous-
    application queue, even against a multi-item company -- it should
    be filed as kind='posting' instead, with no candidates, since
    there's no application it could belong to. Regression for the exact
    case seen in practice (discoveries-kanban-spec.md)."""
    root = tmp_path / "posting-vs-ambiguous-tracker"
    minimal_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n"
    )
    for role in ("Front End Engineer", "Backend Engineer"):
        role_dir = root / "Applications" / "KPMG" / role
        role_dir.mkdir(parents=True)
        (role_dir / "resume.pdf").write_bytes(minimal_pdf)
    client.post("/api/workspaces/link", json={"name": "Posting vs Ambiguous Test", "path": str(root)})

    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "gmail", "email": "willzaeagle@gmail.com"},
    ).json()["account_id"]

    posting_hit = {
        "message_id": "<kpmg-posting-1>",
        "subject": "KPMG US just posted a 78% match Front End Engineer- Associate role",
        "sender": "willzaeagle@gmail.com",
        "received_at": "2026-08-24",
        "matched_via": "text",
        "thread_message_ids": ["<kpmg-posting-1>"],
        "company_only": True,
    }
    with patch.object(api_module.mailapp, "search_messages", return_value=[posting_hit]):
        resp = client.post(f"/api/accounts/{account_id}/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body["new_matches"] == 0
    assert body["ambiguous_matches"] == 0

    discoveries = client.get("/api/discoveries").json()
    assert len(discoveries) == 1
    d = discoveries[0]
    assert d["kind"] == "posting"
    assert d["candidates"] == []


def test_sync_still_auto_attaches_when_role_term_also_confirms(client, tmp_path, api_module):
    """Companion to the ambiguous-routing test above: when the SAME
    multi-item company produces a hit whose role term also matched
    (company_only=False), it should still auto-attach as an ordinary
    confirmed account_match, same as before this change -- the
    ambiguity check only ever intercepts company-only hits."""
    root = tmp_path / "ambiguous-company-tracker-2"
    minimal_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n"
    )
    for role in ("IT", "Environmental Health Specialist"):
        role_dir = root / "Applications" / "Adams County" / role
        role_dir.mkdir(parents=True)
        (role_dir / "resume.pdf").write_bytes(minimal_pdf)
    client.post("/api/workspaces/link", json={"name": "Ambiguous Company Test 2", "path": str(root)})

    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "gmail", "email": "willzaeagle@gmail.com"},
    ).json()["account_id"]

    role_confirmed_hit = {
        "message_id": "<adams-ehs-interview-1>",
        "subject": "Interview: Environmental Health Specialist at Adams County",
        "sender": "hr@adamscountyco.gov",
        "received_at": "2026-08-24",
        "matched_via": "text",
        "thread_message_ids": ["<adams-ehs-interview-1>"],
        "company_only": False,
    }

    def fake_search(account_name, terms, **kwargs):
        # Only return the hit for the item whose terms include the role
        # this message is actually about -- role_terms is how api.py
        # tells search_messages() which of `terms` is the role label.
        if "Environmental Health Specialist" in terms:
            return [role_confirmed_hit]
        return []

    with patch.object(api_module.mailapp, "search_messages", side_effect=fake_search):
        resp = client.post(f"/api/accounts/{account_id}/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body["new_matches"] == 1
    assert body["ambiguous_matches"] == 0
    assert client.get("/api/discoveries").json() == []


def test_sync_is_idempotent_on_repeat_message_ids(client, linked, api_module):
    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "hotmail", "email": "stumping123@outlook.com"},
    ).json()["account_id"]

    hits = [{"message_id": "<m1>", "subject": "s", "sender": "x", "received_at": "2026-08-24"}]
    with patch.object(api_module.mailapp, "search_messages", return_value=hits):
        client.post(f"/api/accounts/{account_id}/sync")
        second = client.post(f"/api/accounts/{account_id}/sync")

    assert second.json()["new_matches"] == 0
    account = client.get("/api/accounts").json()[0]
    assert account["matched_email_count"] == 1


def test_sync_surfaces_denied_permission_and_marks_account_blocked(client, linked, api_module):
    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "hotmail", "email": "stumping123@outlook.com"},
    ).json()["account_id"]

    with patch.object(
        api_module.mailapp, "search_messages",
        side_effect=api_module.mailapp.MailAppPermissionError("enable Mail for JobTracker Hub"),
    ):
        resp = client.post(f"/api/accounts/{account_id}/sync")
    assert resp.status_code == 400
    assert "enable Mail" in resp.json()["detail"]

    account = client.get("/api/accounts").json()[0]
    assert account["status"] == "blocked"


def test_sync_failure_other_than_permission_denial_does_not_mark_blocked(client, linked, api_module):
    # A timeout or a mailbox-lookup error is a failed attempt, not a
    # persistent permission problem -- retrying might just work, and
    # marking the account 'blocked' would (incorrectly) point the user
    # at the Automation settings pane for nothing. Regression test for
    # exactly this happening against a real account during testing.
    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "hotmail", "email": "stumping123@outlook.com"},
    ).json()["account_id"]

    with patch.object(
        api_module.mailapp, "search_messages",
        side_effect=api_module.mailapp.MailAppError("Mail.app didn't respond in time."),
    ):
        resp = client.post(f"/api/accounts/{account_id}/sync")
    assert resp.status_code == 400
    assert "didn't respond" in resp.json()["detail"]

    account = client.get("/api/accounts").json()[0]
    assert account["status"] == "connected"


def test_sync_unknown_account_is_404(client, linked):
    resp = client.post("/api/accounts/not-a-real-id/sync")
    assert resp.status_code == 404


# --- header-threading wiring -------------------------------------------------
# search_messages() now accepts a thread_ids kwarg and every hit can report
# its own thread_message_ids -- these confirm sync_account() actually wires
# that through both directions: known ids in, new ids persisted and reused.

def test_sync_passes_no_known_thread_ids_on_first_sync(client, linked, api_module):
    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "hotmail", "email": "stumping123@outlook.com"},
    ).json()["account_id"]

    with patch.object(api_module.mailapp, "search_messages", return_value=[]) as search:
        client.post(f"/api/accounts/{account_id}/sync")
    search.assert_called_once()
    assert search.call_args.kwargs["thread_ids"] is None


def test_sync_persists_thread_message_ids_from_a_confirmed_hit(client, linked, api_module):
    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "hotmail", "email": "stumping123@outlook.com"},
    ).json()["account_id"]

    hits = [{
        "message_id": "<m1>", "subject": "Interview invite - Acme", "sender": "hr@acme.com",
        "received_at": "2026-08-24", "matched_via": "text",
        "thread_message_ids": ["<m1>", "<earlier@acme.com>"],
    }]
    with patch.object(api_module.mailapp, "search_messages", return_value=hits):
        resp = client.post(f"/api/accounts/{account_id}/sync")
    assert resp.json() == {"ok": True, "new_matches": 1, "ambiguous_matches": 0}

    ov_conn = api_module.ov.get_conn(api_module.current_ov_db_path())
    stored = api_module.ov.get_all_thread_ids_by_item(ov_conn)
    ov_conn.close()
    assert len(stored) == 1
    item_key, ids = next(iter(stored.items()))
    assert set(ids) == {"<m1>", "<earlier@acme.com>"}


def test_sync_passes_previously_confirmed_thread_ids_into_the_next_sync(client, linked, api_module):
    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "hotmail", "email": "stumping123@outlook.com"},
    ).json()["account_id"]

    first_hits = [{
        "message_id": "<m1>", "subject": "Interview invite - Acme", "sender": "hr@acme.com",
        "received_at": "2026-08-24", "matched_via": "text",
        "thread_message_ids": ["<m1>", "<earlier@acme.com>"],
    }]
    with patch.object(api_module.mailapp, "search_messages", return_value=first_hits):
        client.post(f"/api/accounts/{account_id}/sync")

    with patch.object(api_module.mailapp, "search_messages", return_value=[]) as search:
        client.post(f"/api/accounts/{account_id}/sync")
    search.assert_called_once()
    passed_ids = search.call_args.kwargs["thread_ids"]
    assert passed_ids is not None
    assert set(passed_ids) == {"<m1>", "<earlier@acme.com>"}


def test_sync_hit_missing_thread_message_ids_key_does_not_break(client, linked, api_module):
    # A hit shaped like the older (pre-threading) mock format used
    # throughout this file's other tests -- no "thread_message_ids" key
    # at all -- must not raise; api.py's .get(...) or [] handles it.
    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "hotmail", "email": "stumping123@outlook.com"},
    ).json()["account_id"]

    hits = [{"message_id": "<m1>", "subject": "s", "sender": "x", "received_at": "2026-08-24"}]
    with patch.object(api_module.mailapp, "search_messages", return_value=hits):
        resp = client.post(f"/api/accounts/{account_id}/sync")
    assert resp.json() == {"ok": True, "new_matches": 1, "ambiguous_matches": 0}
