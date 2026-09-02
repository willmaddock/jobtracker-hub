"""
Acceptance tests for posting_extract.py, against the REAL source email
PDFs in tests/fixtures/email-source/ -- see CLAUDE_HANDOFF.md sections 6
and 17. These are the two regression fixtures the handoff doc calls out
by name; do not replace them with invented/simplified text.
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
