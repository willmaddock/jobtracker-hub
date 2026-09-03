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
