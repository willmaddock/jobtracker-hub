"""
Acceptance tests for posting_extract.py, against the REAL source email
PDFs in tests/fixtures/email-source/ -- see CLAUDE_HANDOFF.md sections 6
and 17. These are the regression fixtures the handoff doc calls out by
name; do not replace them with invented/simplified text.
"""

from __future__ import annotations

from pathlib import Path

import posting_extract as pe
import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "email-source"


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@pytest.fixture(scope="module")
def linkedin_body() -> str:
    return _pdf_text(FIXTURE_DIR / "linkedin_job_alert_haystack.pdf")


@pytest.fixture(scope="module")
def handshake_body() -> str:
    return _pdf_text(FIXTURE_DIR / "handshake_weekly_jobs_roundup.pdf")


@pytest.fixture(scope="module")
def lensa_body() -> str:
    return _pdf_text(FIXTURE_DIR / "lensa_digest_worky_and_5_more.pdf")


@pytest.fixture(scope="module")
def indeed_digest_body() -> str:
    return _pdf_text(FIXTURE_DIR / "indeed_digest_hackerearth_and_18_more.pdf")


@pytest.fixture(scope="module")
def indeed_single_body() -> str:
    return _pdf_text(FIXTURE_DIR / "indeed_single_match_mytech_partners.pdf")


# --- LinkedIn fixture: expected = 6 (CLAUDE_HANDOFF.md section 6) -----------

def test_linkedin_fixture_yields_six_postings(linkedin_body):
    jobs = pe.extract_postings(
        "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
        "Software Engineer at Haystack",
        linkedin_body,
    )
    assert len(jobs) == 6


def test_linkedin_fixture_titles_and_companies(linkedin_body):
    jobs = pe.extract_postings(
        "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
        "Software Engineer at Haystack",
        linkedin_body,
    )
    pairs = [(j["title"], j["company"]) for j in jobs]
    assert pairs == [
        ("Software Engineer", "Haystack"),
        ("Back-End Developer - WFH", "Torentify"),
        ("Backend Engineer", "Piper Companies"),
        ("Backend Software Engineer, PDP Experience", "Ladders"),
        ("Software Engineer - Work From Home", "Torentify"),
        ("Software Engineer, AI Enablement", "Ladders"),
    ]


def test_linkedin_fixture_captures_salary_when_present(linkedin_body):
    jobs = pe.extract_postings(
        "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
        "Software Engineer at Haystack",
        linkedin_body,
    )
    by_title = {j["title"]: j for j in jobs}
    assert by_title["Backend Software Engineer, PDP Experience"]["salary"] == "$164K-$229K / year"
    assert by_title["Software Engineer"]["salary"] is None


def test_linkedin_does_not_require_job_alert_in_subject(linkedin_body):
    # CLAUDE_HANDOFF.md section 7.2: real subject is "Software Engineer at
    # Haystack" -- no "job alert" phrasing at all. Confirm subject wording
    # isn't a gate the extractor relies on.
    jobs = pe.extract_postings(
        "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
        "Software Engineer at Haystack",
        linkedin_body,
    )
    assert len(jobs) == 6


# --- Handshake fixture: expected >= 5 (CLAUDE_HANDOFF.md section 6) --------

def test_handshake_fixture_yields_at_least_five_postings(handshake_body):
    jobs = pe.extract_postings(
        "Handshake <handshake@g.joinhandshake.com>",
        "Will, Heartland Business Systems (HBS) sees you as a top applicant "
        "for IT Support Desk Engineer II and more",
        handshake_body,
    )
    assert len(jobs) >= 5


def test_handshake_fixture_titles(handshake_body):
    jobs = pe.extract_postings(
        "Handshake <handshake@g.joinhandshake.com>",
        "weekly jobs round-up",
        handshake_body,
    )
    titles = [j["title"] for j in jobs]
    assert "IT Support Desk Engineer II" in titles
    assert "Desktop Support Technician I, II or III" in titles
    assert "SDR - Sales Development Representative (Hybrid)" in titles
    assert "Entry Level Recruiter/Sales Trainee- Denver, CO" in titles
    # Wrapped title across two source lines should be joined into one.
    assert any("Unified Communications Sales Consultant" in t for t in titles)


def test_handshake_view_more_jobs_is_not_a_posting(handshake_body):
    jobs = pe.extract_postings(
        "Handshake <handshake@g.joinhandshake.com>",
        "weekly jobs round-up",
        handshake_body,
    )
    titles = [j["title"].lower() for j in jobs]
    assert not any("view more jobs" in t for t in titles)


# --- Ordinary application mail: expected = [] --------------------------------

def test_ordinary_application_email_yields_zero_postings():
    body = (
        "Thank you for applying to the Assoc Engineer, Software role at "
        "T-Mobile. We received your application (REQ356124) and will be in "
        "touch if there's a match."
    )
    jobs = pe.extract_postings(
        "T-Mobile Careers <careers@t-mobile.com>",
        "Application received for REQ356124 Assoc Engineer Software",
        body,
    )
    assert jobs == []


def test_unknown_sender_yields_zero_postings():
    jobs = pe.extract_postings(
        "Some Recruiter <recruiter@example.com>",
        "Following up",
        "Just checking in on your application.",
    )
    assert jobs == []


def test_empty_body_yields_zero_postings():
    assert pe.extract_postings("jobalerts-noreply@linkedin.com", "Subject", None) == []
    assert pe.extract_postings("jobalerts-noreply@linkedin.com", "Subject", "") == []


# --- provider detection -------------------------------------------------------

def test_detect_provider():
    assert pe.detect_provider("LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>") == "linkedin"
    assert pe.detect_provider("Handshake <handshake@g.joinhandshake.com>") == "handshake"
    assert pe.detect_provider("someone@gmail.com") is None
    assert pe.detect_provider(None) is None


# --- Lensa fixture: expected = 20 real digest jobs (CLAUDE_HANDOFF.md 6) ----
# Lensa moved from the single-job fallback (Layer 3b) to a real digest
# parser once this fixture was available -- see posting_extract.py's
# _parse_lensa docstring.

def test_lensa_fixture_yields_twenty_postings(lensa_body):
    jobs = pe.extract_postings(
        "Lensa <jobalert@lensa.com>",
        "Worky and 5 more companies are hiring Junior Developer in Commerce City, CO",
        lensa_body,
    )
    assert len(jobs) == 20
    assert all(j["source"] == "lensa" for j in jobs)


def test_lensa_fixture_first_and_last_job_titles_and_companies(lensa_body):
    jobs = pe.extract_postings(
        "Lensa <jobalert@lensa.com>",
        "Worky and 5 more companies are hiring Junior Developer in Commerce City, CO",
        lensa_body,
    )
    assert jobs[0]["company"] == "Worky"
    assert jobs[0]["title"] == "Junior Software Developer Remote"
    assert jobs[0]["salary"] == "about $95K / yr."
    assert jobs[-1]["company"] == "Feedinkoo"
    assert jobs[-1]["title"] == "Senior Webﬂow Developer (Remote, Part-Time)"


def test_lensa_fixture_no_header_leak(lensa_body):
    # Regression: an earlier version of _parse_lensa's first "job" was
    # actually the leaked From:/Subject:/Date: header block, not a real
    # listing -- CLAUDE_HANDOFF.md section 17.
    jobs = pe.extract_postings(
        "Lensa <jobalert@lensa.com>",
        "Worky and 5 more companies are hiring Junior Developer in Commerce City, CO",
        lensa_body,
    )
    for j in jobs:
        assert "From:" not in j["title"] and "Subject:" not in j["title"]


def test_lensa_fixture_handles_bare_location_line(lensa_body):
    # The Xcellent Technology Solutions entry has a bare "Denver, CO" line
    # between salary and the bullet-joined meta line, unlike every other
    # entry in this fixture (which is Remote-only).
    jobs = pe.extract_postings(
        "Lensa <jobalert@lensa.com>",
        "Worky and 5 more companies are hiring Junior Developer in Commerce City, CO",
        lensa_body,
    )
    xcellent = next(j for j in jobs if j["company"] == "Xcellent Technology Solutions (XTS)")
    assert xcellent["location"] == "Denver, CO"


def test_lensa_fixture_stops_before_gig_jobs_section(lensa_body):
    # Amazon Flex / Survey Junkie sit in a separate "GIG JOBS" section of
    # the same email and are never real digest jobs.
    jobs = pe.extract_postings(
        "Lensa <jobalert@lensa.com>",
        "Worky and 5 more companies are hiring Junior Developer in Commerce City, CO",
        lensa_body,
    )
    companies = {j["company"] for j in jobs}
    assert "Amazon Flex" not in companies
    assert "Survey Junkie" not in companies


# --- Indeed digest fixture: expected = 19 real jobs (CLAUDE_HANDOFF.md 6) ---
# This fixture's PDF-extracted text is genuinely scrambled by whatever
# screenshot-to-PDF process produced it (Company/Location/Salary cards
# print separately from their Title text) -- see _parse_indeed_digest's
# docstring for how the real pattern was reverse-engineered.

def test_indeed_digest_fixture_yields_nineteen_postings(indeed_digest_body):
    jobs = pe.extract_postings(
        "Indeed <donotreply@match.indeed.com>",
        "Software Engineer at HackerEarth in Remote and 18 more new jobs",
        indeed_digest_body,
    )
    assert len(jobs) == 19
    assert all(j["source"] == "indeed" for j in jobs)


def test_indeed_digest_fixture_top_pick_and_later_pairs(indeed_digest_body):
    # Cross-checked against the fixture's source screenshot pages.
    jobs = pe.extract_postings(
        "Indeed <donotreply@match.indeed.com>",
        "Software Engineer at HackerEarth in Remote and 18 more new jobs",
        indeed_digest_body,
    )
    by_company = {j["company"]: j for j in jobs}
    assert by_company["HackerEarth"]["title"] == "Software Engineer"
    assert by_company["HackerEarth"]["salary"] == "$40 - $50 an hour"
    assert by_company["JSM Consulting India"]["title"] == "AI Software Engineer"
    assert by_company["HURIX SYSTEMS PRIVATE LIMITED"]["title"] == (
        "Frontend Developer- Learning Support Specialist"
    )
    assert by_company["The GEO Group"]["title"] == "Firmware Engineer"
    assert by_company["The GEO Group"]["location"] == "Boulder , CO"


def test_indeed_digest_fixture_no_page_break_echo_artifacts(indeed_digest_body):
    # Regression: duplicate salary/location lines and an orphaned repeat
    # of a company name (both page-break artifacts of this fixture's PDF
    # extraction) must never surface as a fabricated title.
    jobs = pe.extract_postings(
        "Indeed <donotreply@match.indeed.com>",
        "Software Engineer at HackerEarth in Remote and 18 more new jobs",
        indeed_digest_body,
    )
    titles = {j["title"] for j in jobs}
    companies = {j["company"] for j in jobs}
    assert "$60 - $65 an hour" not in titles
    assert "Glocal RPO" not in titles
    assert "Glocal RPO" in companies


def test_indeed_single_fixture_yields_one_posting(indeed_single_body):
    jobs = pe.extract_postings(
        "Indeed <donotreply@match.indeed.com>",
        "Sr. Engineer @ Mytech Partners",
        indeed_single_body,
    )
    assert jobs == [{
        "title": "Sr. Engineer",
        "company": "Mytech Partners",
        "location": "Denver , CO 80281",
        "salary": "$70,000 - $90,000 a year",
        "employment_type": "Full-time",
        "source": "indeed",
    }]


def test_indeed_single_vs_digest_dispatch_by_subject(indeed_digest_body, indeed_single_body):
    # Same sender, two different body layouts -- dispatch has to go by
    # subject shape ("... and N more new jobs" vs "<Title> @ <Company>"),
    # not by sender alone.
    digest_jobs = pe.extract_postings(
        "Indeed <donotreply@match.indeed.com>",
        "Software Engineer at HackerEarth in Remote and 18 more new jobs",
        indeed_digest_body,
    )
    single_jobs = pe.extract_postings(
        "Indeed <donotreply@match.indeed.com>",
        "Sr. Engineer @ Mytech Partners",
        indeed_single_body,
    )
    assert len(digest_jobs) == 19
    assert len(single_jobs) == 1


# --- single-job fallback providers (Layer 3b) --------------------------------
# UNVALIDATED against real fixture bodies -- no sample emails from these
# senders exist yet (see posting_extract.py's _SINGLE_JOB_FALLBACK_PROVIDERS
# docstring and CLAUDE_HANDOFF.md section 17). These only pin down the
# behavior as implemented, not that it's correct against a real inbox.

def test_single_job_fallback_detects_new_sender_domains():
    assert pe.detect_provider("noreply@honeywell.com") == "honeywell"
    assert pe.detect_provider("McDonald's <mcdonalds-jobnotification@noreply.jobs2web.com>") == "jobs2web"
    assert pe.detect_provider("support@awseducate.com") == "awseducate"
    assert pe.detect_provider("jobalert@lensa.com") == "lensa"
    assert pe.detect_provider("support@builtin.com") == "builtin"
    assert pe.detect_provider("NSLS-noreply@csm.symplicity.com") == "symplicity"


def test_single_job_fallback_splits_title_at_company_subject():
    jobs = pe.extract_postings(
        "noreply@honeywell.com", "Software Engineer at Honeywell",
        "Apply now: https://careers.honeywell.com/job/12345",
    )
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Software Engineer"
    assert jobs[0]["company"] == "Honeywell"
    assert jobs[0]["source"] == "honeywell"


def test_single_job_fallback_falls_back_to_known_employer_name():
    # Subject doesn't parse as "<title> at <company>" -- known-employer
    # domain still supplies a real company rather than leaving it blank.
    jobs = pe.extract_postings(
        "support@awseducate.com", "New opportunity waiting for you", "See details online.",
    )
    assert len(jobs) == 1
    assert jobs[0]["company"] == "AWS Educate"


def test_single_job_fallback_leaves_company_none_for_generic_ats_without_at_pattern():
    # jobs2web is a shared multi-tenant ATS, not an employer -- no domain
    # fallback should fabricate a fake company name for it (mirrors
    # mail_app_store.py's _GENERIC_SENDER_DOMAINS philosophy).
    jobs = pe.extract_postings(
        "mcdonalds-jobnotification@noreply.jobs2web.com", "New job opportunity", "See details online.",
    )
    assert len(jobs) == 1
    assert jobs[0]["company"] is None


def test_single_job_fallback_yields_zero_without_a_subject():
    assert pe.extract_postings("noreply@honeywell.com", None, "Apply now.") == []
    assert pe.extract_postings("noreply@honeywell.com", "", "Apply now.") == []


def test_single_job_fallback_does_not_affect_supported_providers():
    # linkedin.com is not in _SINGLE_JOB_FALLBACK_PROVIDERS -- confirms
    # the new branch doesn't shadow the existing multi-job parsers.
    assert pe.detect_provider("jobalerts-noreply@linkedin.com") == "linkedin"


# --- dedupe key (CLAUDE_HANDOFF.md section 9) --------------------------------

def test_dedupe_key_stable_for_same_url():
    k1 = pe.compute_dedupe_key("acct1", "msg1", "https://linkedin.com/jobs/123?utm_source=x", "Engineer", "Acme")
    k2 = pe.compute_dedupe_key("acct1", "msg2", "https://linkedin.com/jobs/123/", "Different Title", "Different Co")
    assert k1 == k2  # same normalized URL -> same identity, regardless of message/title


def test_dedupe_key_differs_across_accounts():
    k1 = pe.compute_dedupe_key("acct1", "msg1", "https://linkedin.com/jobs/123", None, None)
    k2 = pe.compute_dedupe_key("acct2", "msg1", "https://linkedin.com/jobs/123", None, None)
    assert k1 != k2


def test_dedupe_key_falls_back_to_message_title_company_without_url():
    k1 = pe.compute_dedupe_key("acct1", "msg1", None, "Software Engineer", "Haystack")
    k2 = pe.compute_dedupe_key("acct1", "msg1", None, "Software Engineer", "Haystack")
    k3 = pe.compute_dedupe_key("acct1", "msg1", None, "Backend Engineer", "Haystack")
    assert k1 == k2
    assert k1 != k3


def test_dedupe_key_two_linkless_jobs_in_one_email_both_survive():
    # CLAUDE_HANDOFF.md section 9: "one linkless email containing two
    # different jobs -> both survive".
    k1 = pe.compute_dedupe_key("acct1", "msg1", None, "Software Engineer", "Haystack")
    k2 = pe.compute_dedupe_key("acct1", "msg1", None, "Backend Engineer", "Haystack")
    assert k1 != k2
