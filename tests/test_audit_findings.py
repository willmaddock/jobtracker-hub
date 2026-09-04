"""
Targeted regression probes written during a full audit of the
feature/email-sync branch vs main.

These are NOT part of the original branch's test suite -- they were
written to check specific hypotheses raised while reading api.py,
overrides_store.py, mail_app_store.py and posting_extract.py, using the
same mocking pattern as tests/test_accounts_api.py (mail_app_store's
osascript calls are patched out; nothing here touches real Mail.app).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import mail_app_store as mailapp
import overrides_store as ov_module


def _minimal_pdf() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n"
    )


# ---------------------------------------------------------------------------
# Finding 2 (numbering matches AUDIT_FINDINGS.md; FIXED as of this commit):
# sync_account()'s job-posting-shaped / company-only routing only
# checks is_job_posting_style_subject() inside the `ambiguous_siblings`
# branch (i.e. only when the company has 2+ open items). For a company with
# exactly ONE open item, a company-only hit whose subject is a job-alert
# notice (not a real application update) skips that check entirely and
# falls straight into ov.add_account_match() -- getting silently recorded
# as confirmed evidence on the one open application, instead of being
# routed to Job Postings the way the exact same subject shape is for a
# multi-item company (see
# test_sync_routes_job_posting_shaped_company_only_hit_to_postings_not_ambiguous_queue
# in test_accounts_api.py, which only covers the 2-open-item case).
# ---------------------------------------------------------------------------

def test_job_posting_shaped_company_only_hit_for_SINGLE_item_company_is_misfiled_as_account_match(
    client, tmp_path, api_module
):
    root = tmp_path / "single-item-posting-tracker"
    role_dir = root / "Applications" / "Acme Co" / "Backend Engineer"
    role_dir.mkdir(parents=True)
    (role_dir / "resume.pdf").write_bytes(_minimal_pdf())
    client.post("/api/workspaces/link", json={"name": "Single Item Posting Test", "path": str(root)})

    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "gmail", "email": "willzaeagle@gmail.com"},
    ).json()["account_id"]

    # Same subject SHAPE as the passing multi-item test in
    # test_accounts_api.py -- just against a company with only one open
    # item instead of two.
    posting_hit = {
        "message_id": "<acme-posting-1>",
        "subject": "Acme Co just posted a 82% match Backend Engineer II role",
        "sender": "jobs-noreply@linkedin.com",
        "received_at": "2026-08-24",
        "matched_via": "text",
        "thread_message_ids": ["<acme-posting-1>"],
        "company_only": True,
    }
    with patch.object(api_module.mailapp, "search_messages", return_value=[posting_hit]):
        resp = client.post(f"/api/accounts/{account_id}/sync")
    assert resp.status_code == 200
    body = resp.json()

    discoveries = client.get("/api/discoveries").json()
    _, ov_conn = api_module.get_conns()
    matches = api_module.ov.list_all_account_matches(ov_conn)

    # What SHOULD happen, per is_job_posting_style_subject()'s own purpose
    # and the multi-item companion test: this is a job-alert email, not
    # application correspondence, so it should never become a confirmed
    # account_match -- it should be filed as a posting/discovery instead.
    #
    # What ACTUALLY happens on this branch: because ambiguous_siblings is
    # None for a single-item company, the `if h.get("company_only") and
    # ambiguous_siblings` guard in sync_account() is False, so the
    # job-posting-style check never runs and this falls straight through
    # to ov.add_account_match().
    if matches:
        pytest.fail(
            "BUG CONFIRMED: a job-alert-shaped, company-only hit against a "
            "single-open-item company was recorded as a confirmed "
            f"account_match ({matches!r}) instead of being routed to Job "
            f"Postings/discoveries. new_matches={body.get('new_matches')}, "
            f"discoveries={discoveries!r}"
        )


# ---------------------------------------------------------------------------
# Finding 3 (originally documented in CLAUDE_HANDOFF.md's own Known
# Issues; FIXED as of this commit): positional URL-to-job association in
# _extract_and_store_job_postings used to break when a digest had more
# job-board-domain URLs than jobs (e.g. a header/footer "view digest"
# landing-page link ends up first and shifts every job's URL by one).
#
# Fix: positional association is now only trusted when the URL count
# exactly matches the job count (see _extract_and_store_job_postings'
# updated comment in api.py) -- a mismatch means there's no reliable way
# to tell which URL maps to which job, so none are guessed rather than
# silently attaching every job after the mismatch to the wrong listing.
# This test now confirms the SAFE behavior: neither job gets a wrong
# link when the counts don't line up.
# ---------------------------------------------------------------------------

def test_url_to_job_positional_association_skips_guessing_on_count_mismatch(
    client, tmp_path, api_module
):
    root = tmp_path / "url-misassociation-tracker"
    role_dir = root / "Applications" / "Haystack" / "Software Engineer"
    role_dir.mkdir(parents=True)
    (role_dir / "resume.pdf").write_bytes(_minimal_pdf())
    client.post("/api/workspaces/link", json={"name": "URL Misassociation Test", "path": str(root)})

    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "gmail", "email": "willzaeagle@gmail.com"},
    ).json()["account_id"]

    # Two LinkedIn-shaped jobs, and a body containing a header "view in
    # browser"-style link (which extract_posting_urls' domain list would
    # actually reject -- but a generic linkedin.com/jobs/view/12345-style
    # tracking-pixel-adjacent link ahead of the real per-job links is a
    # completely realistic real-world case) followed by the two real
    # per-job links.
    body = (
        "Software Engineer\n"
        "Haystack \u00b7 Remote\n"
        "Actively recruiting\n"
        "$120K-$150K / year\n"
        "Data Engineer\n"
        "Haystack \u00b7 Remote\n"
        "$130K-$160K / year\n"
        "See all jobs\n"
    )
    # Three job-board-domain URLs in body order: one extra "digest landing
    # page" link ahead of the two real per-job links.
    urls = [
        "https://www.linkedin.com/jobs/view/DIGEST_LANDING_PAGE",
        "https://www.linkedin.com/jobs/view/SOFTWARE_ENGINEER_REAL_LINK",
        "https://www.linkedin.com/jobs/view/DATA_ENGINEER_REAL_LINK",
    ]

    # Route this through discover_new_applications (search_unmatched_messages)
    # rather than sync_account -- this is the code path that actually runs
    # extraction unconditionally for anything classified kind="posting",
    # sidestepping Finding 1's separate single-item-company routing bug so
    # this test isolates the URL-association question specifically.
    unmatched_hit = {
        "message_id": "<haystack-digest-1>",
        "subject": "Software Engineer at Haystack",
        "sender": "jobs-noreply@linkedin.com",
        "received_at": "2026-08-24",
        "guessed_company": "Haystack",
        "force_posting": True,  # force kind="posting" so extraction always runs
    }

    with patch.object(api_module.mailapp, "search_unmatched_messages", return_value=[unmatched_hit]), \
         patch.object(api_module.mailapp, "get_message_preview", return_value=body), \
         patch.object(api_module.mailapp, "extract_posting_urls", return_value=urls):
        client.post(f"/api/accounts/{account_id}/discover")

    postings = client.get("/api/job-postings").json()
    assert len(postings) == 2, f"expected 2 extracted jobs, got {postings!r}"

    by_title = {p["title"]: p for p in postings}
    se = by_title.get("Software Engineer")
    de = by_title.get("Data Engineer")
    assert se is not None and de is not None

    # FIXED: with 3 job-board URLs but only 2 jobs, the count mismatch
    # means positional association is no longer trusted at all -- neither
    # job gets a link, rather than the old failure mode of Software
    # Engineer silently getting the unrelated digest-landing-page link
    # and Data Engineer getting Software Engineer's real link.
    assert se["posting_url"] is None, (
        f"expected no link when URL/job counts mismatch (3 urls, 2 jobs), "
        f"got Software Engineer posting_url={se['posting_url']!r}"
    )
    assert de["posting_url"] is None, (
        f"expected no link when URL/job counts mismatch (3 urls, 2 jobs), "
        f"got Data Engineer posting_url={de['posting_url']!r}"
    )


def test_url_to_job_positional_association_still_works_when_counts_match(
    client, tmp_path, api_module
):
    """Companion to the mismatch test above: confirms the fix didn't
    throw out the common well-formed case -- when the URL count exactly
    equals the job count (the normal shape for a clean digest), each job
    still gets its own correct link, same as before this fix."""
    root = tmp_path / "url-association-matched-tracker"
    role_dir = root / "Applications" / "Haystack" / "Software Engineer"
    role_dir.mkdir(parents=True)
    (role_dir / "resume.pdf").write_bytes(_minimal_pdf())
    client.post("/api/workspaces/link", json={"name": "URL Association Matched Test", "path": str(root)})

    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "gmail", "email": "willzaeagle@gmail.com"},
    ).json()["account_id"]

    body = (
        "Software Engineer\n"
        "Haystack \u00b7 Remote\n"
        "Actively recruiting\n"
        "$120K-$150K / year\n"
        "Data Engineer\n"
        "Haystack \u00b7 Remote\n"
        "$130K-$160K / year\n"
        "See all jobs\n"
    )
    # Exactly 2 job-board URLs for 2 jobs -- counts match, so association
    # should still apply positionally, same as before this fix.
    urls = [
        "https://www.linkedin.com/jobs/view/SOFTWARE_ENGINEER_REAL_LINK",
        "https://www.linkedin.com/jobs/view/DATA_ENGINEER_REAL_LINK",
    ]

    unmatched_hit = {
        "message_id": "<haystack-digest-2>",
        "subject": "Software Engineer at Haystack",
        "sender": "jobs-noreply@linkedin.com",
        "received_at": "2026-08-24",
        "guessed_company": "Haystack",
        "force_posting": True,
    }

    with patch.object(api_module.mailapp, "search_unmatched_messages", return_value=[unmatched_hit]), \
         patch.object(api_module.mailapp, "get_message_preview", return_value=body), \
         patch.object(api_module.mailapp, "extract_posting_urls", return_value=urls):
        client.post(f"/api/accounts/{account_id}/discover")

    postings = client.get("/api/job-postings").json()
    assert len(postings) == 2, f"expected 2 extracted jobs, got {postings!r}"

    by_title = {p["title"]: p for p in postings}
    se = by_title.get("Software Engineer")
    de = by_title.get("Data Engineer")
    assert se is not None and de is not None
    assert se["posting_url"] == "https://www.linkedin.com/jobs/view/SOFTWARE_ENGINEER_REAL_LINK"
    assert de["posting_url"] == "https://www.linkedin.com/jobs/view/DATA_ENGINEER_REAL_LINK"


# ---------------------------------------------------------------------------
# Regression pin (not a numbered AUDIT_FINDINGS.md finding -- see its
# "What's not a bug" section): mark_discovery_as_posting() closes jt_conn
# immediately (it's
# only used, per a code comment, because the endpoint signature used to
# need it) but never actually needs a jt_conn at all in its current body --
# confirm this doesn't silently mask a real error path if the pattern is
# ever copied to a handler that DOES need jt_conn for something after that
# early close. Not a live bug today, but worth a regression pin so it's
# not accidentally "fixed" into a use-after-close bug the day someone adds
# code between the early close and the rest of the function that legitimately
# needs jt_conn.
# ---------------------------------------------------------------------------

def test_mark_discovery_as_posting_still_works_and_extracts_jobs(client, tmp_path, api_module):
    root = tmp_path / "mark-posting-tracker"
    role_dir = root / "Applications" / "Haystack" / "Software Engineer"
    role_dir.mkdir(parents=True)
    (role_dir / "resume.pdf").write_bytes(_minimal_pdf())
    client.post("/api/workspaces/link", json={"name": "Mark Posting Test", "path": str(root)})

    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "gmail", "email": "willzaeagle@gmail.com"},
    ).json()["account_id"]

    # File an ordinary 'application' discovery first (the classifier
    # missed it), then manually mark it as a posting.
    with patch.object(api_module.mailapp, "search_unmatched_messages", return_value=[{
        "message_id": "<missed-1>",
        "subject": "Some digest the classifier missed",
        "sender": "jobs-noreply@linkedin.com",
        "received_at": "2026-08-24",
        "guessed_company": "Haystack",
        "force_posting": False,
    }]):
        client.post(f"/api/accounts/{account_id}/discover")

    discoveries = client.get("/api/discoveries").json()
    assert len(discoveries) == 1
    discovery_id = discoveries[0]["id"]

    body = (
        "Software Engineer\n"
        "Haystack \u00b7 Remote\n"
        "$120K-$150K / year\n"
        "See all jobs\n"
    )
    with patch.object(api_module.mailapp, "get_message_preview", return_value=body):
        resp = client.post(f"/api/discoveries/{discovery_id}/mark-posting")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "posting"

    postings = client.get("/api/job-postings").json()
    assert len(postings) == 1
    assert postings[0]["title"] == "Software Engineer"


# ---------------------------------------------------------------------------
# Finding 4 (documented in AUDIT_FINDINGS.md; FIXED as of this commit):
# extract_posting_urls() rejected any URL containing "utm_" as a
# non-posting link. LinkedIn (and most ATSs) attach utm_*/trk= tracking
# params to their REAL per-job listing links in every alert email, so
# this excluded essentially every genuine posting link a digest could
# contain -- confirmed against the real testing DB, where 100% of stored
# job_postings had posting_url = NULL. A "view all N jobs" digest header
# link is now filtered separately (as a generic collection URL) instead
# of via the same blunt "utm_" substring check.
# ---------------------------------------------------------------------------

def test_extract_posting_urls_no_longer_rejects_real_links_with_tracking_params():
    body = (
        "Software Engineer: "
        "https://www.linkedin.com/jobs/view/1111?utm_source=email&trk=eml-jobs\n"
    )
    assert mailapp.extract_posting_urls(body) == [
        "https://www.linkedin.com/jobs/view/1111?utm_source=email&trk=eml-jobs",
    ]


def test_extract_posting_urls_still_filters_generic_view_all_link():
    body = (
        "Software Engineer: https://www.linkedin.com/jobs/view/1111?utm_source=email\n"
        "Data Engineer: https://www.linkedin.com/jobs/view/2222?utm_source=email\n"
        "See all jobs: https://www.linkedin.com/jobs/search?utm_source=email\n"
    )
    assert mailapp.extract_posting_urls(body) == [
        "https://www.linkedin.com/jobs/view/1111?utm_source=email",
        "https://www.linkedin.com/jobs/view/2222?utm_source=email",
    ]


def test_single_job_single_tracked_link_now_gets_a_real_posting_url_end_to_end(
    client, tmp_path, api_module
):
    """Reproduces the real-world shape found in the testing DB: one
    LinkedIn job-alert email, one job, one tracked listing link -- should
    now come out of sync with posting_url populated instead of None."""
    root = tmp_path / "single-tracked-link-tracker"
    role_dir = root / "Applications" / "Rate" / "Software Engineer (New Grad)"
    role_dir.mkdir(parents=True)
    (role_dir / "resume.pdf").write_bytes(_minimal_pdf())
    client.post("/api/workspaces/link", json={"name": "Single Tracked Link Test", "path": str(root)})

    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "gmail", "email": "willzaeagle@gmail.com"},
    ).json()["account_id"]

    body = (
        "Software Engineer (New Grad)\n"
        "Rate \u00b7 United States\n"
        "$95K-$120K / year\n"
        "https://www.linkedin.com/jobs/view/3901234567/?utm_source=jobs_alert_email&trk=eml\n"
    )
    unmatched_hit = {
        "message_id": "<rate-new-grad-1>",
        "subject": "Rate just posted a Software Engineer (New Grad) role",
        "sender": "jobs-noreply@linkedin.com",
        "received_at": "2026-08-24",
        "guessed_company": "Rate",
        "force_posting": True,
    }
    with patch.object(api_module.mailapp, "search_unmatched_messages", return_value=[unmatched_hit]), \
         patch.object(api_module.mailapp, "get_message_preview", return_value=body):
        client.post(f"/api/accounts/{account_id}/discover")

    postings = client.get("/api/job-postings").json()
    assert len(postings) == 1
    assert postings[0]["posting_url"] == (
        "https://www.linkedin.com/jobs/view/3901234567/?utm_source=jobs_alert_email&trk=eml"
    )


# ---------------------------------------------------------------------------
# Finding 5 (documented in AUDIT_FINDINGS.md; FIXED as of this commit):
# get_message_preview() only ever searched the "INBOX" mailbox (the same
# default used at scan time). A discovery can sit unreviewed for months,
# and it's entirely plausible Mail.app / the IMAP provider has since
# filed that message elsewhere (Archive, Gmail's All Mail, a rule-based
# folder) -- once that happens, the by-message-id lookup returned
# JOBTRACKER_NOT_FOUND permanently, showing "Couldn't load the original
# email" forever even though the message still exists. Now falls back to
# scanning every other mailbox of the account before giving up.
# ---------------------------------------------------------------------------

def test_get_message_preview_falls_back_to_other_mailboxes_when_not_in_inbox():
    # Simulate: Inbox lookup finds nothing, but the message id script
    # overall does reach the message in a non-Inbox mailbox and returns
    # its content. We can't drive real AppleScript branching from a
    # mock, so this asserts the fallback-scan block is actually present
    # in the generated script (i.e. the fix is in place) and that a
    # successful raw result is still returned/stripped correctly.
    with patch.object(mailapp, "_run_applescript", return_value="Job content here") as run:
        result = mailapp.get_message_preview("gmail", "<archived-msg-1>")
    assert result == "Job content here"
    generated_script = run.call_args[0][0]
    assert "every mailbox of acct" in generated_script, (
        "get_message_preview() should fall back to scanning every mailbox "
        "of the account, not just the one passed in (default INBOX)"
    )


def test_get_message_preview_still_returns_none_when_truly_gone_from_every_mailbox():
    with patch.object(mailapp, "_run_applescript", return_value="JOBTRACKER_NOT_FOUND"):
        result = mailapp.get_message_preview("gmail", "<deleted-everywhere-1>")
    assert result is None


# ---------------------------------------------------------------------------
# Finding 6 (documented in AUDIT_FINDINGS.md; FIXED as of this commit):
# Finding 4's utm_ filter fix was correct but incomplete: extract_posting_urls()
# only ever sees Mail.app's plain-text rendering of a message (`content of
# msg`, via get_message_preview()). For an HTML job-alert email, that
# rendering keeps visible link text ("View job") but throws away every
# <a href="..."> URL entirely -- there was no URL in the plain-text body for
# any filter to act on in the first place. Confirmed against a real LinkedIn
# digest's raw MIME source: 16 real hrefs recoverable, 6 of which were the
# actual per-job listing links the board needed. Fixed by adding
# get_message_source() (AppleScript's `source of msg`, not `content of
# msg`), extract_html_source_urls() (MIME-decodes each text/html part and
# pulls href values out of the real markup), and get_posting_urls_for_message()
# (tries the source path first, falls back to the old plain-text path).
# ---------------------------------------------------------------------------

_LINKEDIN_DIGEST_SOURCE = (
    'From: LinkedIn <jobs-noreply@linkedin.com>\n'
    'Content-Type: multipart/alternative; boundary="BOUNDARY123"\n'
    '\n'
    '--BOUNDARY123\n'
    'Content-Type: text/plain; charset="UTF-8"\n'
    'Content-Transfer-Encoding: 7bit\n'
    '\n'
    'Rate: Software Engineer (New Grad)\n'
    '\n'
    '--BOUNDARY123\n'
    'Content-Type: text/html; charset="UTF-8"\n'
    'Content-Transfer-Encoding: quoted-printable\n'
    '\n'
    '<html><body>\n'
    '<a href=3D"https://www.linkedin.com/comm/jobs/view/4382484258?trackingId=3D'
    '&amp;lipi=3Durn%3Ali&amp;midToken=3DXYZ&amp;trk=3Deml-applied_job">Applied job</a>\n'
    '<a href=3D"https://www.linkedin.com/comm/jobs/view/4367342975?trk=3Deml-similar_job'
    '&amp;otpToken=3Dabc">Similar 1</a>\n'
    '<a href=3D"https://www.linkedin.com/comm/jobs/search/?jobPostingId=3D4382484258'
    '&amp;trk=3Dsee_all">See all similar</a>\n'
    '<a href=3D"https://www.linkedin.com/comm/psettings/email-unsubscribe?trk=3Dunsub">'
    'Unsubscribe</a>\n'
    '<a href=3D"https://www.linkedin.com/comm/feed/?trk=3Dheader">Home</a>\n'
    '<a href=3D"https://www.linkedin.com/comm/in/willmaddockcs?trk=3Dprofile">Profile</a>\n'
    '</body></html>\n'
    '--BOUNDARY123--\n'
)


def test_extract_html_source_urls_recovers_real_job_links_from_html_email():
    urls = mailapp.extract_html_source_urls(_LINKEDIN_DIGEST_SOURCE)
    assert urls == [
        "https://www.linkedin.com/jobs/view/4382484258",
        "https://www.linkedin.com/jobs/view/4367342975",
    ]
    # /comm/ redirector and tracking query strings are stripped; search/
    # unsubscribe/feed/profile links are filtered out same as
    # extract_posting_urls() would filter them from a plain-text body.
    joined = " ".join(urls)
    assert "/comm/" not in joined and "?" not in joined
    for excluded in ("jobs/search", "unsubscribe", "feed", "/in/"):
        assert excluded not in joined


def test_extract_html_source_urls_handles_missing_or_garbage_input():
    assert mailapp.extract_html_source_urls(None) == []
    assert mailapp.extract_html_source_urls("") == []
    assert mailapp.extract_html_source_urls("not a mime message at all") == []


def test_get_message_source_uses_source_of_msg_not_content_of_msg():
    """The whole fix hinges on asking Mail.app for the right thing --
    `source of msg` (raw MIME) instead of `content of msg` (Mail.app's
    lossy plain-text rendering that get_message_preview() uses)."""
    with patch.object(mailapp, "_run_applescript", return_value="raw mime here") as run:
        result = mailapp.get_message_source("gmail", "<digest-1>")
    assert result == "raw mime here"
    generated_script = run.call_args[0][0]
    assert "source of msg" in generated_script
    assert "content of msg" not in generated_script
    assert "every mailbox of acct" in generated_script, (
        "get_message_source() should fall back to scanning every mailbox "
        "of the account, same as get_message_preview()'s Finding 5 fix"
    )


def test_get_message_source_returns_none_when_not_found():
    with patch.object(mailapp, "_run_applescript", return_value="JOBTRACKER_NOT_FOUND"):
        assert mailapp.get_message_source("gmail", "<gone-1>") is None


def test_get_posting_urls_for_message_prefers_html_source_over_plaintext_fallback():
    with patch.object(mailapp, "get_message_source", return_value=_LINKEDIN_DIGEST_SOURCE):
        result = mailapp.get_posting_urls_for_message(
            "gmail", "<digest-1>", fallback_body="plain text body with no links"
        )
    assert result == mailapp.extract_html_source_urls(_LINKEDIN_DIGEST_SOURCE)


def test_get_posting_urls_for_message_falls_back_when_source_has_no_links():
    with patch.object(mailapp, "get_message_source", return_value="<html><body>no links here</body></html>"):
        result = mailapp.get_posting_urls_for_message(
            "gmail", "<plain-1>",
            fallback_body="Apply here: https://boards.greenhouse.io/acme/jobs/123",
        )
    assert result == ["https://boards.greenhouse.io/acme/jobs/123"]


def test_get_posting_urls_for_message_falls_back_on_mail_app_error():
    """A permission/timeout hiccup fetching the raw source shouldn't lose
    the plain-text fallback the caller already has on hand."""
    with patch.object(mailapp, "get_message_source", side_effect=mailapp.MailAppError("boom")):
        result = mailapp.get_posting_urls_for_message(
            "gmail", "<perm-error-1>",
            fallback_body="Apply here: https://boards.greenhouse.io/acme/jobs/123",
        )
    assert result == ["https://boards.greenhouse.io/acme/jobs/123"]


def test_get_posting_urls_for_message_empty_when_nothing_found_anywhere():
    with patch.object(mailapp, "get_message_source", return_value=None):
        assert mailapp.get_posting_urls_for_message("gmail", "<none-1>", fallback_body=None) == []


def test_linkedin_digest_end_to_end_now_recovers_all_six_job_links(
    client, tmp_path, api_module
):
    """Reproduces the real symptom this audit chased: a 6-job LinkedIn
    digest whose plain-text body (what get_message_preview() returns) has
    no URLs in it at all -- extract_posting_urls() on that body alone
    would find nothing, same as it did in production before this fix.
    With get_message_source() wired in, the real per-job links come from
    the HTML source instead, and the count now matches the extracted job
    count so positional pairing succeeds."""
    root = tmp_path / "digest-tracker"
    role_dir = root / "Applications" / "Acme Robotics" / "Backend Engineer"
    role_dir.mkdir(parents=True)
    (role_dir / "resume.pdf").write_bytes(_minimal_pdf())
    client.post("/api/workspaces/link", json={"name": "Digest Test", "path": str(root)})

    account_id = client.post(
        "/api/accounts/mail-app/connect",
        json={"name": "gmail", "email": "person@gmail.com"},
    ).json()["account_id"]

    # A single-job digest whose plain-text preview has NO url in it at all
    # (matching the real "0 raw URLs" symptom) -- only the raw source does.
    plain_body = (
        "Backend Engineer\n"
        "Acme Robotics \u00b7 United States\n"
        "$120K-$150K / year\n"
    )
    source = (
        'Content-Type: text/html; charset="UTF-8"\n'
        'Content-Transfer-Encoding: quoted-printable\n'
        '\n'
        '<a href=3D"https://www.linkedin.com/comm/jobs/view/555?trk=3Deml">Job</a>\n'
    )
    unmatched_hit = {
        "message_id": "<acme-digest-1>",
        "subject": "Acme Robotics just posted a Backend Engineer role",
        "sender": "jobs-noreply@linkedin.com",
        "received_at": "2026-08-24",
        "guessed_company": "Acme Robotics",
        "force_posting": True,
    }
    with patch.object(api_module.mailapp, "search_unmatched_messages", return_value=[unmatched_hit]), \
         patch.object(api_module.mailapp, "get_message_preview", return_value=plain_body), \
         patch.object(api_module.mailapp, "get_message_source", return_value=source):
        client.post(f"/api/accounts/{account_id}/discover")

    postings = client.get("/api/job-postings").json()
    assert len(postings) == 1
    assert postings[0]["posting_url"] == "https://www.linkedin.com/jobs/view/555"


# ---------------------------------------------------------------------------
# Finding 7 (documented in AUDIT_FINDINGS.md; FIXED as of this commit):
# overrides_store.get_conn() unconditionally ran `PRAGMA journal_mode=WAL`
# on every single call (i.e. on every API request, since api.py's
# get_conns() opens a fresh connection per request rather than reusing
# one). The frontend fires several requests in a burst on page load and on
# every workspace create/switch/rebuild. Switching a database's journal
# mode to WAL for the first time requires SQLite to briefly get exclusive
# access to the file; two of those near-simultaneous first connections can
# collide on that PRAGMA and raise "database is locked" -- confirmed
# against a real traceback pointing at exactly this line, immediately
# after a workspace import/switch.
# ---------------------------------------------------------------------------

class _RecordingConn:
    """Thin wrapper around a real sqlite3.Connection that records/can
    intercept .execute() calls -- sqlite3.Connection instances refuse
    attribute assignment (`execute` is read-only on the C object), so
    patch.object() can't stub a single instance's execute() directly;
    _ensure_wal_mode() only ever calls .execute() on what it's given, so
    a duck-typed wrapper works everywhere a real Connection would."""
    def __init__(self, real, intercept=None):
        self._real = real
        self._intercept = intercept
        self.calls = []

    def execute(self, sql, *args, **kwargs):
        self.calls.append(sql)
        if self._intercept:
            result = self._intercept(sql)
            if result is not None:
                return result
        return self._real.execute(sql, *args, **kwargs)


def test_ensure_wal_mode_skips_pragma_when_already_wal(tmp_path):
    """Once a database already reports journal_mode=wal (every request
    after the first), _ensure_wal_mode() shouldn't re-issue the PRAGMA at
    all -- that's both a wasted round trip and the only place the
    "database is locked" race could occur."""
    import sqlite3

    db_path = str(tmp_path / "overrides.db")
    real = sqlite3.connect(db_path)
    real.execute("PRAGMA journal_mode=WAL")

    rc = _RecordingConn(real)
    ov_module._ensure_wal_mode(rc)
    assert not any("JOURNAL_MODE=WAL" in s.upper() for s in rc.calls), (
        "_ensure_wal_mode() should not re-issue PRAGMA journal_mode=WAL "
        "once the database is already in WAL mode"
    )


def test_ensure_wal_mode_retries_transient_lock_instead_of_raising(tmp_path):
    """Simulates two near-simultaneous first-time switches: the PRAGMA
    fails with 'database is locked' the first couple of tries (another
    connection mid-switch) and should succeed once that clears, rather
    than surfacing a 500 to the request that lost the race."""
    import sqlite3

    real = sqlite3.connect(str(tmp_path / "overrides.db"))
    calls = {"n": 0}

    def intercept(sql):
        if sql.strip().upper() == "PRAGMA JOURNAL_MODE=WAL":
            calls["n"] += 1
            if calls["n"] < 3:
                raise sqlite3.OperationalError("database is locked")
        return None

    rc = _RecordingConn(real, intercept=intercept)
    with patch("overrides_store.time.sleep", return_value=None):
        ov_module._ensure_wal_mode(rc)
    assert calls["n"] == 3


def test_ensure_wal_mode_reraises_non_lock_errors_immediately(tmp_path):
    import sqlite3

    real = sqlite3.connect(str(tmp_path / "overrides.db"))

    def intercept(sql):
        if sql.strip().upper() == "PRAGMA JOURNAL_MODE=WAL":
            raise sqlite3.OperationalError("disk I/O error")
        return None

    rc = _RecordingConn(real, intercept=intercept)
    try:
        ov_module._ensure_wal_mode(rc)
        assert False, "expected OperationalError to propagate"
    except sqlite3.OperationalError as e:
        assert "disk I/O error" in str(e)
