"""
email_pdf.py and its two call sites in api.py:
  - accept_discovery(): saves the source email as a PDF into the new
    application folder going forward.
  - backfill-email-pdfs: sweeps existing account_matches (synced or
    accepted before this feature existed) and fills in any missing PDF.

mail_app_store is mocked throughout, same as test_discoveries.py and
test_accounts_api.py -- no real osascript call in this suite.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import email_pdf


# --- email_pdf.py unit tests ------------------------------------------------

def test_render_email_pdf_produces_nonempty_pdf_bytes():
    pdf_bytes = email_pdf.render_email_pdf(
        "Thank you for your interest",
        "jobs-noreply@linkedin.com",
        "Wed, Mar 18 2026",
        "We will not be moving forward at this time.",
    )
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 200


def test_render_email_pdf_handles_missing_body_without_raising():
    pdf_bytes = email_pdf.render_email_pdf(None, None, None, None)
    assert pdf_bytes.startswith(b"%PDF")


def test_render_email_pdf_handles_unicode_without_raising():
    pdf_bytes = email_pdf.render_email_pdf(
        "caf\u00e9 application \u2014 update", "a@b.com", None, "emoji \U0001F600 test",
    )
    assert pdf_bytes.startswith(b"%PDF")


def test_safe_email_filename_strips_unsafe_chars_and_prefixes():
    assert email_pdf.safe_email_filename("Re: Your application <weird> chars/slash") == \
        "Email - Re Your application weird charsslash"


def test_safe_email_filename_falls_back_when_subject_empty():
    assert email_pdf.safe_email_filename("") == "Email - Untitled message"
    assert email_pdf.safe_email_filename(None) == "Email - Untitled message"
    assert email_pdf.safe_email_filename("   ") == "Email - Untitled message"


# --- accept_discovery integration ------------------------------------------

@pytest.fixture
def linked(client, sample_root):
    client.post("/api/workspaces/link", json={"name": "Email PDF Test", "path": str(sample_root)})
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
        "message_id": "<rate-rejection-1>",
        "subject": "Thank you for your interest",
        "sender": "Rate <no-reply@rate.com>",
        "received_at": "Wednesday, March 18, 2026 at 7:24:36 PM",
        "guessed_company": "Rate",
    }
    candidate.update(overrides)
    with patch.object(api_module.mailapp, "search_unmatched_messages", return_value=[candidate]):
        resp = client.post(f"/api/accounts/{account_id}/discover")
    assert resp.status_code == 200
    pending = resp.json()
    assert len(pending) == 1
    return pending[0]


def test_accept_discovery_saves_email_as_pdf_in_new_folder(client, api_module, linked, connected_account):
    discovery = _discover_one(client, api_module, connected_account)

    with patch.object(
        api_module.mailapp, "get_message_preview",
        return_value="Unfortunately, we will not be moving forward at this time.",
    ):
        resp = client.post(
            f"/api/discoveries/{discovery['id']}/accept",
            data={"company": "Rate", "role_label": "Software Engineer", "status": "rejected"},
        )
    assert resp.status_code == 200
    relpath = resp.json()["relpath"]

    dest_folder = linked / relpath
    pdfs = list(dest_folder.glob("Email - *.pdf"))
    assert len(pdfs) == 1
    assert pdfs[0].read_bytes().startswith(b"%PDF")
    # The placeholder notes.txt must NOT have been created, since the
    # folder is no longer empty once the PDF lands.
    assert not (dest_folder / "notes.txt").exists()


def test_accept_discovery_still_creates_folder_when_body_fetch_fails(client, api_module, linked, connected_account):
    """A Mail.app hiccup fetching the body shouldn't block accepting the
    discovery -- it just falls back to the notes.txt placeholder, same
    as before this feature existed."""
    discovery = _discover_one(client, api_module, connected_account)

    with patch.object(
        api_module.mailapp, "get_message_preview",
        side_effect=api_module.mailapp.MailAppError("timed out"),
    ):
        resp = client.post(
            f"/api/discoveries/{discovery['id']}/accept",
            data={"company": "Rate", "role_label": "", "status": ""},
        )
    assert resp.status_code == 200
    dest_folder = linked / resp.json()["relpath"]

    # A PDF is still produced (with a "(body could not be retrieved)"
    # placeholder line) -- the fetch failing doesn't mean no PDF at all.
    pdfs = list(dest_folder.glob("Email - *.pdf"))
    assert len(pdfs) == 1


# --- backfill ---------------------------------------------------------------

def test_backfill_saves_pdf_for_a_match_that_predates_the_feature(client, api_module, linked, connected_account):
    """Simulates an application that was matched via a normal /sync
    before email_pdf.py existed: an account_match row exists, but its
    folder has no PDF. Backfill should fill the gap."""
    hits = [
        {"message_id": "<m1>", "subject": "Interview invite - Acme", "sender": "hr@acme.com", "received_at": "2026-08-24"},
    ]
    with patch.object(api_module.mailapp, "search_messages", return_value=hits):
        sync_resp = client.post(f"/api/accounts/{connected_account}/sync")
    assert sync_resp.json() == {"ok": True, "new_matches": 1, "ambiguous_matches": 0}

    # sample_root's one application (Acme Co / Backend Engineer) has no
    # email PDF yet.
    acme_folder = linked / "Applications" / "Acme Co" / "Backend Engineer"
    assert not list(acme_folder.glob("Email - *.pdf"))

    with patch.object(
        api_module.mailapp, "get_message_preview",
        return_value="We'd like to schedule an interview.",
    ):
        resp = client.post("/api/discoveries/backfill-email-pdfs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["saved"] == 1
    assert body["failed"] == 0

    pdfs = list(acme_folder.glob("Email - *.pdf"))
    assert len(pdfs) == 1


def test_backfill_is_idempotent_and_skips_already_saved_pdfs(client, api_module, linked, connected_account):
    hits = [
        {"message_id": "<m1>", "subject": "Interview invite - Acme", "sender": "hr@acme.com", "received_at": "2026-08-24"},
    ]
    with patch.object(api_module.mailapp, "search_messages", return_value=hits):
        client.post(f"/api/accounts/{connected_account}/sync")

    with patch.object(api_module.mailapp, "get_message_preview", return_value="First pass."):
        first = client.post("/api/discoveries/backfill-email-pdfs").json()
    assert first["saved"] == 1

    with patch.object(api_module.mailapp, "get_message_preview", return_value="Second pass -- should not run."):
        second = client.post("/api/discoveries/backfill-email-pdfs").json()
    assert second["saved"] == 0
    assert second["skipped_existing"] == 1

    acme_folder = linked / "Applications" / "Acme Co" / "Backend Engineer"
    assert len(list(acme_folder.glob("Email - *.pdf"))) == 1
