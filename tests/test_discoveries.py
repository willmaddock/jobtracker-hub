"""
/api/discoveries/* routes added alongside the LinkedIn-job-alert false
positive fix: the lazy email-body preview endpoint and the bulk
dismiss-by-sender action. mail_app_store is mocked throughout, same as
test_accounts_api.py -- no real osascript call in this suite.

Also covers overrides_store.dismiss_pending_discoveries_by_sender()
directly (no FastAPI client needed for that one).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import overrides_store as ov

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "email-source"


def _linkedin_fixture_body() -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(FIXTURE_DIR / "linkedin_job_alert_haystack.pdf"))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@pytest.fixture
def linked(client, sample_root):
    client.post("/api/workspaces/link", json={"name": "Discoveries Test", "path": str(sample_root)})
    return sample_root


@pytest.fixture
def connected_account(client, linked, api_module):
    with patch.object(
        api_module.mailapp, "list_mail_app_accounts",
        return_value=[{"name": "hotmail", "email": "stumping123@outlook.com"}],
    ):
        resp = client.post(
            "/api/accounts/mail-app/connect",
            json={"name": "hotmail", "email": "stumping123@outlook.com"},
        )
    return resp.json()["account_id"]


def _discover_one(client, api_module, account_id, **overrides):
    candidate = {
        "message_id": "<linkedin-digest-1>",
        "subject": "Software Engineer at Skyflow",
        "sender": "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
        "received_at": "Thursday, August 27, 2026 at 11:09:47 AM",
        "guessed_company": None,
    }
    candidate.update(overrides)
    with patch.object(api_module.mailapp, "search_unmatched_messages", return_value=[candidate]):
        resp = client.post(f"/api/accounts/{account_id}/discover")
    assert resp.status_code == 200
    pending = resp.json()
    assert len(pending) == 1
    return pending[0]


# --- preview endpoint ------------------------------------------------------

def test_preview_returns_email_body(client, api_module, connected_account):
    discovery = _discover_one(client, api_module, connected_account)
    with patch.object(
        api_module.mailapp, "get_message_preview",
        return_value="Your job alert for back end developer...",
    ):
        resp = client.get(f"/api/discoveries/{discovery['id']}/preview")
    assert resp.status_code == 200
    assert resp.json() == {"body": "Your job alert for back end developer...", "posting_url": None, "posting_urls": []}


def test_preview_returns_none_body_when_message_gone(client, api_module, connected_account):
    discovery = _discover_one(client, api_module, connected_account)
    with patch.object(api_module.mailapp, "get_message_preview", return_value=None):
        resp = client.get(f"/api/discoveries/{discovery['id']}/preview")
    assert resp.status_code == 200
    assert resp.json() == {"body": None, "posting_url": None, "posting_urls": []}


def test_preview_falls_back_to_none_on_mail_app_error(client, api_module, connected_account):
    """A permission/timeout hiccup fetching the body shouldn't block
    reviewing the discovery -- the modal just falls back to
    subject/sender/date, same as before this endpoint existed."""
    discovery = _discover_one(client, api_module, connected_account)
    with patch.object(
        api_module.mailapp, "get_message_preview",
        side_effect=api_module.mailapp.MailAppError("timed out"),
    ):
        resp = client.get(f"/api/discoveries/{discovery['id']}/preview")
    assert resp.status_code == 200
    assert resp.json() == {"body": None, "posting_url": None, "posting_urls": []}


def test_preview_unknown_discovery_is_404(client, linked):
    resp = client.get("/api/discoveries/999999/preview")
    assert resp.status_code == 404


def test_preview_finds_and_persists_a_posting_url_for_a_posting_kind_discovery(client, api_module, connected_account):
    discovery = _discover_one(
        client, api_module, connected_account,
        subject="Skyflow just posted a 78% match Software Engineer",
    )
    assert discovery["kind"] == "posting"
    body = "View the role: https://boards.greenhouse.io/skyflow/jobs/999"
    with patch.object(api_module.mailapp, "get_message_preview", return_value=body):
        resp = client.get(f"/api/discoveries/{discovery['id']}/preview")
    assert resp.status_code == 200
    assert resp.json() == {
        "body": body,
        "posting_url": "https://boards.greenhouse.io/skyflow/jobs/999",
        "posting_urls": ["https://boards.greenhouse.io/skyflow/jobs/999"],
    }

    # Persisted -- a second preview call doesn't need to re-derive it, and
    # would find it even if get_message_preview failed this time.
    with patch.object(api_module.mailapp, "get_message_preview", side_effect=api_module.mailapp.MailAppError("x")):
        resp2 = client.get(f"/api/discoveries/{discovery['id']}/preview")
    assert resp2.json() == {
        "body": None,
        "posting_url": "https://boards.greenhouse.io/skyflow/jobs/999",
        "posting_urls": ["https://boards.greenhouse.io/skyflow/jobs/999"],
    }


def test_preview_posting_kind_with_no_recognizable_link_leaves_posting_url_none(client, api_module, connected_account):
    discovery = _discover_one(
        client, api_module, connected_account,
        subject="Comcast just posted a 60% match Junior DevOps",
    )
    assert discovery["kind"] == "posting"
    with patch.object(api_module.mailapp, "get_message_preview", return_value="No useful link in here."):
        resp = client.get(f"/api/discoveries/{discovery['id']}/preview")
    assert resp.json() == {"body": "No useful link in here.", "posting_url": None, "posting_urls": []}


def test_preview_persists_every_listing_link_for_a_multi_listing_digest(client, api_module, connected_account):
    """The real Haystack-digest regression case (Part 5.5b): a single
    LinkedIn Job Alerts email whose body contains six distinct listing
    links -- preview should find and persist all of them, not just the
    first, while posting_url (kept for backward compat) stays the first
    one."""
    discovery = _discover_one(
        client, api_module, connected_account,
        subject="Software Engineer at Haystack",
        sender="LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
        # This subject has zero ATS-phrase signal on its own -- LinkedIn
        # renamed it to the top-ranked listing, exactly the digest-vanishing
        # case Part 5.5a's sender whitelist exists to fix (see
        # test_search_unmatched_messages_reports_force_posting_for_a_
        # whitelisted_sender_hit, which asserts this same subject is NOT
        # is_job_posting_style_subject on its own). Mirror that: a
        # multi-listing digest like this only ever reaches the discoveries
        # queue at all because its sender was whitelisted, so force_posting
        # is how it got here for real.
        force_posting=True,
    )
    assert discovery["kind"] == "posting"
    body = (
        "Software Engineer: https://www.linkedin.com/jobs/view/1111\n"
        "Back-End Developer - WFH: https://www.linkedin.com/jobs/view/2222\n"
        "Backend Engineer: https://www.linkedin.com/jobs/view/3333\n"
    )
    with patch.object(api_module.mailapp, "get_message_preview", return_value=body):
        resp = client.get(f"/api/discoveries/{discovery['id']}/preview")
    data = resp.json()
    assert data["posting_urls"] == [
        "https://www.linkedin.com/jobs/view/1111",
        "https://www.linkedin.com/jobs/view/2222",
        "https://www.linkedin.com/jobs/view/3333",
    ]
    assert data["posting_url"] == "https://www.linkedin.com/jobs/view/1111"


# --- bulk dismiss-by-sender -------------------------------------------------

def test_dismiss_sender_dismisses_all_pending_from_that_sender(client, api_module, connected_account):
    sender = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
    d1 = _discover_one(client, api_module, connected_account, message_id="<a>", sender=sender)
    # Second discover call with a different message id from the same sender.
    with patch.object(
        api_module.mailapp, "search_unmatched_messages",
        return_value=[{
            "message_id": "<b>", "subject": "Software Engineer at Marbury AI",
            "sender": sender, "received_at": "Thursday, August 20, 2026",
            "guessed_company": None,
        }],
    ):
        resp = client.post(f"/api/accounts/{connected_account}/discover")
    assert len(resp.json()) == 2

    dismiss_resp = client.post("/api/discoveries/dismiss-sender", data={"sender": sender})
    assert dismiss_resp.status_code == 200
    body = dismiss_resp.json()
    assert body["dismissed_count"] == 2
    assert body["discoveries"] == []

    # Confirmed dismissed, not just hidden -- GET /api/discoveries agrees.
    assert client.get("/api/discoveries").json() == []


def test_dismiss_sender_does_not_touch_other_senders(client, api_module, connected_account):
    d1 = _discover_one(client, api_module, connected_account, message_id="<a>", sender="LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>")
    with patch.object(
        api_module.mailapp, "search_unmatched_messages",
        return_value=[{
            "message_id": "<c>", "subject": "Thank you for applying to Acme",
            "sender": "careers@acme.com", "received_at": "Friday, August 21, 2026",
            "guessed_company": "Acme",
        }],
    ):
        resp = client.post(f"/api/accounts/{connected_account}/discover")
    assert len(resp.json()) == 2

    dismiss_resp = client.post(
        "/api/discoveries/dismiss-sender",
        data={"sender": "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"},
    )
    assert dismiss_resp.json()["dismissed_count"] == 1
    remaining = client.get("/api/discoveries").json()
    assert len(remaining) == 1
    assert remaining[0]["sender"] == "careers@acme.com"


def test_dismiss_sender_unknown_sender_dismisses_nothing(client, linked):
    resp = client.post("/api/discoveries/dismiss-sender", data={"sender": "nobody@nowhere.com"})
    assert resp.status_code == 200
    assert resp.json()["dismissed_count"] == 0


# --- overrides_store.dismiss_pending_discoveries_by_sender directly --------

def test_dismiss_pending_discoveries_by_sender_only_touches_pending_rows(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    ov.add_discovered_match(conn, "acct1", "<msg1>", "Job alert", "linkedin.com", "2026-08-27", None)
    ov.add_discovered_match(conn, "acct1", "<msg2>", "Job alert 2", "linkedin.com", "2026-08-20", None)
    ov.add_discovered_match(conn, "acct1", "<msg3>", "Real application", "careers@acme.com", "2026-08-21", "Acme")

    # Already-accepted rows from the same sender shouldn't be re-flipped.
    ov.add_discovered_match(conn, "acct1", "<msg4>", "Already handled", "linkedin.com", "2026-08-01", None)
    ov.set_discovery_status(conn, 4, "accepted")

    count = ov.dismiss_pending_discoveries_by_sender(conn, "linkedin.com")
    assert count == 2

    remaining_pending = {d["message_id"] for d in ov.list_pending_discoveries(conn)}
    assert remaining_pending == {"<msg3>"}
    assert ov.get_discovery(conn, 4)["status"] == "accepted"  # untouched


# --- discover endpoint: kind classification ---------------------------------

def test_discover_files_job_posting_shaped_subject_as_posting_kind(client, api_module, connected_account):
    discovery = _discover_one(
        client, api_module, connected_account,
        subject="KPMG US just posted a 78% match Front End Engineer- Associate role",
        guessed_company="KPMG",
    )
    assert discovery["kind"] == "posting"
    assert discovery["candidates"] == []


def test_discover_files_ordinary_application_subject_as_application_kind(client, api_module, connected_account):
    discovery = _discover_one(
        client, api_module, connected_account,
        subject="Thank you for applying to Acme", guessed_company="Acme",
    )
    assert discovery["kind"] == "application"


# --- mark-posting endpoint ---------------------------------------------------

def test_mark_posting_relabels_a_pending_discovery(client, api_module, connected_account):
    discovery = _discover_one(client, api_module, connected_account)
    assert discovery["kind"] == "application"

    resp = client.post(f"/api/discoveries/{discovery['id']}/mark-posting")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "posting"

    pending = client.get("/api/discoveries").json()
    assert pending[0]["kind"] == "posting"
    assert pending[0]["status"] == "pending"  # relabels, doesn't resolve


def test_mark_posting_also_extracts_individual_jobs(client, api_module, connected_account):
    """A discovery the classifier missed and a human relabels via
    mark-posting should still populate /api/job-postings -- not just
    flip discovered_matches.kind -- since that's the whole point of the
    button (CLAUDE_HANDOFF.md section 4/15: the Job Postings board reads
    from job_postings, not from discoveries.filter(kind=='posting')).
    Uses the real LinkedIn fixture body (6 jobs) so this is the same
    extractor path/regression coverage as test_posting_extract.py, just
    exercised through the manual-relabel endpoint instead of sync."""
    discovery = _discover_one(client, api_module, connected_account)
    assert client.get("/api/job-postings").json() == []

    with patch.object(
        api_module.mailapp, "get_message_preview", return_value=_linkedin_fixture_body()
    ):
        resp = client.post(f"/api/discoveries/{discovery['id']}/mark-posting")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "posting"

    postings = client.get("/api/job-postings").json()
    assert len(postings) == 6
    assert {p["title"] for p in postings} == {
        "Software Engineer", "Back-End Developer - WFH", "Backend Engineer",
        "Backend Software Engineer, PDP Experience",
        "Software Engineer - Work From Home", "Software Engineer, AI Enablement",
    }


def test_mark_posting_still_succeeds_when_body_fetch_fails(client, api_module, connected_account):
    """Extraction failing (account disconnected, Mail.app timeout, etc.)
    must not block the relabel itself -- same swallow-and-continue
    behavior as the sync_account()/discover_new_applications() call
    sites, per _extract_and_store_job_postings()'s own docstring."""
    discovery = _discover_one(client, api_module, connected_account)
    with patch.object(
        api_module.mailapp, "get_message_preview",
        side_effect=api_module.mailapp.MailAppError("Mail.app didn't respond in time."),
    ):
        resp = client.post(f"/api/discoveries/{discovery['id']}/mark-posting")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "posting"
    assert client.get("/api/job-postings").json() == []


def test_mark_posting_unknown_discovery_is_404(client, linked):
    resp = client.post("/api/discoveries/999999/mark-posting")
    assert resp.status_code == 404


def test_mark_posting_already_decided_discovery_is_409(client, api_module, connected_account):
    discovery = _discover_one(client, api_module, connected_account)
    dismiss = client.post(f"/api/discoveries/{discovery['id']}/dismiss")
    assert dismiss.status_code == 200

    resp = client.post(f"/api/discoveries/{discovery['id']}/mark-posting")
    assert resp.status_code == 409


# --- attach endpoint (ambiguous company-only sync hits) --------------------
# Distinct from /accept above: /accept creates a brand-new item from an
# 'unmatched' discovery, while /attach links an 'ambiguous' discovery
# (see api.py's sync_account() docstring) to an item that ALREADY
# exists -- no new folder, no create_application_folder call.

@pytest.fixture
def ambiguous_discovery(client, api_module, tmp_path):
    """A two-item-same-company tracker plus one pending 'ambiguous'
    discovery against it, built the same way sync_account() would
    produce one for real -- see test_accounts_api.py's
    test_sync_routes_company_only_hit_to_ambiguous_queue... for the
    full sync-side reproduction; this fixture exists so the attach
    tests below don't have to repeat that whole setup."""
    root = tmp_path / "attach-test-tracker"
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
    client.post("/api/workspaces/link", json={"name": "Attach Test", "path": str(root)})

    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "gmail", "email": "willzaeagle@gmail.com"},
    ).json()["account_id"]

    hit = {
        "message_id": "<adams-notice-1>",
        "subject": "Notice from Adams County",
        "sender": "willzaeagle@gmail.com",
        "received_at": "2026-08-24",
        "matched_via": "text",
        "thread_message_ids": ["<adams-notice-1>"],
        "company_only": True,
    }
    with patch.object(api_module.mailapp, "search_messages", return_value=[hit]):
        client.post(f"/api/accounts/{account_id}/sync")

    discovery = client.get("/api/discoveries").json()[0]
    ehs_item_key = next(c["item_key"] for c in discovery["candidates"] if "Environmental" in c["label"])
    it_item_key = next(c["item_key"] for c in discovery["candidates"] if c["item_key"] != ehs_item_key)
    return {"discovery": discovery, "ehs_item_key": ehs_item_key, "it_item_key": it_item_key}


def test_attach_ambiguous_discovery_records_match_on_chosen_item(client, api_module, ambiguous_discovery):
    discovery_id = ambiguous_discovery["discovery"]["id"]
    ehs_item_key = ambiguous_discovery["ehs_item_key"]

    resp = client.post(f"/api/discoveries/{discovery_id}/attach", data={"item_key": ehs_item_key})
    assert resp.status_code == 200
    assert resp.json()["discoveries"] == []  # no longer pending

    _, ov_conn = api_module.get_conns()
    matches = api_module.ov.get_matches_for_item(ov_conn, ehs_item_key)
    assert len(matches) == 1
    assert matches[0]["message_id"] == "<adams-notice-1>"

    # The OTHER candidate item got nothing.
    it_matches = api_module.ov.get_matches_for_item(ov_conn, ambiguous_discovery["it_item_key"])
    assert it_matches == []

    assert api_module.ov.get_discovery(ov_conn, discovery_id)["status"] == "accepted"


def test_attach_rejects_unknown_item_key(client, ambiguous_discovery):
    discovery_id = ambiguous_discovery["discovery"]["id"]
    resp = client.post(f"/api/discoveries/{discovery_id}/attach", data={"item_key": "not-a-real-item-key"})
    assert resp.status_code == 400


def test_attach_already_decided_discovery_is_409(client, ambiguous_discovery):
    discovery_id = ambiguous_discovery["discovery"]["id"]
    ehs_item_key = ambiguous_discovery["ehs_item_key"]
    first = client.post(f"/api/discoveries/{discovery_id}/attach", data={"item_key": ehs_item_key})
    assert first.status_code == 200

    second = client.post(f"/api/discoveries/{discovery_id}/attach", data={"item_key": ehs_item_key})
    assert second.status_code == 409


# --- sender-classification endpoint (Part 5.5a whitelist) -------------------

def test_sender_classification_endpoint_whitelists_a_sender(client, api_module, connected_account):
    sender = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
    resp = client.post("/api/discoveries/sender-classification", data={"sender": sender})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    _, ov_conn = api_module.get_conns()
    assert sender in api_module.ov.list_job_posting_senders(ov_conn)


def test_sender_classification_makes_a_future_scan_force_posting_regardless_of_subject(
    client, api_module, connected_account
):
    """The whole point of the whitelist: once a sender is taught, a
    future message from that exact sender is filed kind='posting' even
    though its subject has no recognizable job-alert phrasing at all --
    the exact Haystack-digest failure mode (LinkedIn renames the subject
    to whatever listing ranks first, so it never contains an ATS
    phrase)."""
    sender = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
    client.post("/api/discoveries/sender-classification", data={"sender": sender})

    candidate = {
        "message_id": "<haystack-digest-1>",
        "subject": "Software Engineer at Haystack",
        "sender": sender,
        "received_at": "Tuesday, September 1, 2026 at 1:09:00 PM",
        "guessed_company": None,
        "force_posting": True,
    }
    with patch.object(api_module.mailapp, "search_unmatched_messages", return_value=[candidate]) as mocked:
        resp = client.post(f"/api/accounts/{connected_account}/discover")
    assert resp.status_code == 200
    # The whitelist was actually passed through to the search call.
    assert mocked.call_args.kwargs.get("always_posting_senders") == [sender]

    pending = resp.json()
    assert len(pending) == 1
    assert pending[0]["kind"] == "posting"
