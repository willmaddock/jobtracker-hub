"""
Acceptance tests for postings/extraction.py, ported from
tests/test_posting_extract.py as part of Phase 6
(docs/DJANGO_MIGRATION_PLAN.md) -- against the REAL source email PDFs in
postings/tests/fixtures/email-source/. These are the regression fixtures
the original module's handoff doc calls out by name; do not replace them
with invented/simplified text. Assertions are unchanged from the
original -- same counts, same field extraction, now against the ported
module.

Restructured from the original's pytest module-scoped fixtures into
unittest.TestCase classes (functools.lru_cache standing in for
scope="module" fixture caching), since the rest of this Django app's
test suite runs via `manage.py test`, not pytest -- see
docs/DJANGO_MIGRATION_PLAN.md's Phase 0 note that pytest.ini's
`testpaths = tests` only covers the old _app/ suite. No assertion
content changed in this restructuring.
"""
from __future__ import annotations

import functools
from pathlib import Path

from django.test import SimpleTestCase

from postings import extraction as pe

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "email-source"


@functools.lru_cache(maxsize=None)
def _pdf_text(name: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(FIXTURE_DIR / name))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def linkedin_body() -> str:
    return _pdf_text("linkedin_job_alert_haystack.pdf")


def handshake_body() -> str:
    return _pdf_text("handshake_weekly_jobs_roundup.pdf")


def lensa_body() -> str:
    return _pdf_text("lensa_digest_worky_and_5_more.pdf")


def indeed_digest_body() -> str:
    return _pdf_text("indeed_digest_hackerearth_and_18_more.pdf")


def indeed_single_body() -> str:
    return _pdf_text("indeed_single_match_mytech_partners.pdf")


# --- LinkedIn fixture: expected = 6 (CLAUDE_HANDOFF.md section 6) -----------

class LinkedInFixtureTests(SimpleTestCase):
    def test_fixture_yields_six_postings(self):
        jobs = pe.extract_postings(
            "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
            "Software Engineer at Haystack",
            linkedin_body(),
        )
        self.assertEqual(len(jobs), 6)

    def test_fixture_titles_and_companies(self):
        jobs = pe.extract_postings(
            "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
            "Software Engineer at Haystack",
            linkedin_body(),
        )
        pairs = [(j["title"], j["company"]) for j in jobs]
        self.assertEqual(pairs, [
            ("Software Engineer", "Haystack"),
            ("Back-End Developer - WFH", "Torentify"),
            ("Backend Engineer", "Piper Companies"),
            ("Backend Software Engineer, PDP Experience", "Ladders"),
            ("Software Engineer - Work From Home", "Torentify"),
            ("Software Engineer, AI Enablement", "Ladders"),
        ])

    def test_fixture_captures_salary_when_present(self):
        jobs = pe.extract_postings(
            "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
            "Software Engineer at Haystack",
            linkedin_body(),
        )
        by_title = {j["title"]: j for j in jobs}
        self.assertEqual(
            by_title["Backend Software Engineer, PDP Experience"]["salary"],
            "$164K-$229K / year",
        )
        self.assertIsNone(by_title["Software Engineer"]["salary"])

    def test_does_not_require_job_alert_in_subject(self):
        # CLAUDE_HANDOFF.md section 7.2: real subject is "Software Engineer
        # at Haystack" -- no "job alert" phrasing at all. Confirm subject
        # wording isn't a gate the extractor relies on.
        jobs = pe.extract_postings(
            "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
            "Software Engineer at Haystack",
            linkedin_body(),
        )
        self.assertEqual(len(jobs), 6)


# --- Handshake fixture: expected >= 5 (CLAUDE_HANDOFF.md section 6) --------

class HandshakeFixtureTests(SimpleTestCase):
    def test_fixture_yields_at_least_five_postings(self):
        jobs = pe.extract_postings(
            "Handshake <handshake@g.joinhandshake.com>",
            "Will, Heartland Business Systems (HBS) sees you as a top applicant "
            "for IT Support Desk Engineer II and more",
            handshake_body(),
        )
        self.assertGreaterEqual(len(jobs), 5)

    def test_fixture_titles(self):
        jobs = pe.extract_postings(
            "Handshake <handshake@g.joinhandshake.com>",
            "weekly jobs round-up",
            handshake_body(),
        )
        titles = [j["title"] for j in jobs]
        self.assertIn("IT Support Desk Engineer II", titles)
        self.assertIn("Desktop Support Technician I, II or III", titles)
        self.assertIn("SDR - Sales Development Representative (Hybrid)", titles)
        self.assertIn("Entry Level Recruiter/Sales Trainee- Denver, CO", titles)
        # Wrapped title across two source lines should be joined into one.
        self.assertTrue(any("Unified Communications Sales Consultant" in t for t in titles))

    def test_view_more_jobs_is_not_a_posting(self):
        jobs = pe.extract_postings(
            "Handshake <handshake@g.joinhandshake.com>",
            "weekly jobs round-up",
            handshake_body(),
        )
        titles = [j["title"].lower() for j in jobs]
        self.assertFalse(any("view more jobs" in t for t in titles))


# --- Ordinary application mail: expected = [] --------------------------------

class NonDigestEmailTests(SimpleTestCase):
    def test_ordinary_application_email_yields_zero_postings(self):
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
        self.assertEqual(jobs, [])

    def test_unknown_sender_yields_zero_postings(self):
        jobs = pe.extract_postings(
            "Some Recruiter <recruiter@example.com>",
            "Following up",
            "Just checking in on your application.",
        )
        self.assertEqual(jobs, [])

    def test_empty_body_yields_zero_postings(self):
        self.assertEqual(
            pe.extract_postings("jobalerts-noreply@linkedin.com", "Subject", None), []
        )
        self.assertEqual(
            pe.extract_postings("jobalerts-noreply@linkedin.com", "Subject", ""), []
        )


# --- provider detection -------------------------------------------------------

class DetectProviderTests(SimpleTestCase):
    def test_detect_provider(self):
        self.assertEqual(
            pe.detect_provider("LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"),
            "linkedin",
        )
        self.assertEqual(
            pe.detect_provider("Handshake <handshake@g.joinhandshake.com>"), "handshake"
        )
        self.assertIsNone(pe.detect_provider("someone@gmail.com"))
        self.assertIsNone(pe.detect_provider(None))


# --- Lensa fixture: expected = 20 real digest jobs (CLAUDE_HANDOFF.md 6) ----
# Lensa moved from the single-job fallback (Layer 3b) to a real digest
# parser once this fixture was available -- see extraction.py's
# _parse_lensa docstring.

_LENSA_SENDER = "Lensa <jobalert@lensa.com>"
_LENSA_SUBJECT = (
    "Worky and 5 more companies are hiring Junior Developer in Commerce City, CO"
)


class LensaFixtureTests(SimpleTestCase):
    def test_fixture_yields_twenty_postings(self):
        jobs = pe.extract_postings(_LENSA_SENDER, _LENSA_SUBJECT, lensa_body())
        self.assertEqual(len(jobs), 20)
        self.assertTrue(all(j["source"] == "lensa" for j in jobs))

    def test_fixture_first_and_last_job_titles_and_companies(self):
        jobs = pe.extract_postings(_LENSA_SENDER, _LENSA_SUBJECT, lensa_body())
        self.assertEqual(jobs[0]["company"], "Worky")
        self.assertEqual(jobs[0]["title"], "Junior Software Developer Remote")
        self.assertEqual(jobs[0]["salary"], "about $95K / yr.")
        self.assertEqual(jobs[-1]["company"], "Feedinkoo")
        self.assertEqual(jobs[-1]["title"], "Senior Webﬂow Developer (Remote, Part-Time)")

    def test_fixture_no_header_leak(self):
        # Regression: an earlier version of _parse_lensa's first "job" was
        # actually the leaked From:/Subject:/Date: header block, not a real
        # listing -- CLAUDE_HANDOFF.md section 17.
        jobs = pe.extract_postings(_LENSA_SENDER, _LENSA_SUBJECT, lensa_body())
        for j in jobs:
            self.assertNotIn("From:", j["title"])
            self.assertNotIn("Subject:", j["title"])

    def test_fixture_handles_bare_location_line(self):
        # The Xcellent Technology Solutions entry has a bare "Denver, CO"
        # line between salary and the bullet-joined meta line, unlike every
        # other entry in this fixture (which is Remote-only).
        jobs = pe.extract_postings(_LENSA_SENDER, _LENSA_SUBJECT, lensa_body())
        xcellent = next(j for j in jobs if j["company"] == "Xcellent Technology Solutions (XTS)")
        self.assertEqual(xcellent["location"], "Denver, CO")

    def test_fixture_stops_before_gig_jobs_section(self):
        # Amazon Flex / Survey Junkie sit in a separate "GIG JOBS" section
        # of the same email and are never real digest jobs.
        jobs = pe.extract_postings(_LENSA_SENDER, _LENSA_SUBJECT, lensa_body())
        companies = {j["company"] for j in jobs}
        self.assertNotIn("Amazon Flex", companies)
        self.assertNotIn("Survey Junkie", companies)


# --- Indeed digest fixture: expected = 19 real jobs (CLAUDE_HANDOFF.md 6) ---
# This fixture's PDF-extracted text is genuinely scrambled by whatever
# screenshot-to-PDF process produced it (Company/Location/Salary cards
# print separately from their Title text) -- see _parse_indeed_digest's
# docstring for how the real pattern was reverse-engineered.

_INDEED_SENDER = "Indeed <donotreply@match.indeed.com>"
_INDEED_DIGEST_SUBJECT = "Software Engineer at HackerEarth in Remote and 18 more new jobs"
_INDEED_SINGLE_SUBJECT = "Sr. Engineer @ Mytech Partners"


class IndeedFixtureTests(SimpleTestCase):
    def test_digest_fixture_yields_nineteen_postings(self):
        jobs = pe.extract_postings(_INDEED_SENDER, _INDEED_DIGEST_SUBJECT, indeed_digest_body())
        self.assertEqual(len(jobs), 19)
        self.assertTrue(all(j["source"] == "indeed" for j in jobs))

    def test_digest_fixture_top_pick_and_later_pairs(self):
        # Cross-checked against the fixture's source screenshot pages.
        jobs = pe.extract_postings(_INDEED_SENDER, _INDEED_DIGEST_SUBJECT, indeed_digest_body())
        by_company = {j["company"]: j for j in jobs}
        self.assertEqual(by_company["HackerEarth"]["title"], "Software Engineer")
        self.assertEqual(by_company["HackerEarth"]["salary"], "$40 - $50 an hour")
        self.assertEqual(by_company["JSM Consulting India"]["title"], "AI Software Engineer")
        self.assertEqual(
            by_company["HURIX SYSTEMS PRIVATE LIMITED"]["title"],
            "Frontend Developer- Learning Support Specialist",
        )
        self.assertEqual(by_company["The GEO Group"]["title"], "Firmware Engineer")
        self.assertEqual(by_company["The GEO Group"]["location"], "Boulder , CO")

    def test_digest_fixture_no_page_break_echo_artifacts(self):
        # Regression: duplicate salary/location lines and an orphaned repeat
        # of a company name (both page-break artifacts of this fixture's PDF
        # extraction) must never surface as a fabricated title.
        jobs = pe.extract_postings(_INDEED_SENDER, _INDEED_DIGEST_SUBJECT, indeed_digest_body())
        titles = {j["title"] for j in jobs}
        companies = {j["company"] for j in jobs}
        self.assertNotIn("$60 - $65 an hour", titles)
        self.assertNotIn("Glocal RPO", titles)
        self.assertIn("Glocal RPO", companies)

    def test_single_fixture_yields_one_posting(self):
        jobs = pe.extract_postings(_INDEED_SENDER, _INDEED_SINGLE_SUBJECT, indeed_single_body())
        self.assertEqual(jobs, [{
            "title": "Sr. Engineer",
            "company": "Mytech Partners",
            "location": "Denver , CO 80281",
            "salary": "$70,000 - $90,000 a year",
            "employment_type": "Full-time",
            "source": "indeed",
        }])

    def test_single_vs_digest_dispatch_by_subject(self):
        # Same sender, two different body layouts -- dispatch has to go by
        # subject shape ("... and N more new jobs" vs "<Title> @ <Company>"),
        # not by sender alone.
        digest_jobs = pe.extract_postings(
            _INDEED_SENDER, _INDEED_DIGEST_SUBJECT, indeed_digest_body()
        )
        single_jobs = pe.extract_postings(
            _INDEED_SENDER, _INDEED_SINGLE_SUBJECT, indeed_single_body()
        )
        self.assertEqual(len(digest_jobs), 19)
        self.assertEqual(len(single_jobs), 1)


# --- single-job fallback providers (Layer 3b) --------------------------------
# UNVALIDATED against real fixture bodies -- no sample emails from these
# senders exist yet (see extraction.py's _SINGLE_JOB_FALLBACK_PROVIDERS
# docstring and CLAUDE_HANDOFF.md section 17). These only pin down the
# behavior as implemented, not that it's correct against a real inbox.

class SingleJobFallbackTests(SimpleTestCase):
    def test_detects_new_sender_domains(self):
        self.assertEqual(pe.detect_provider("noreply@honeywell.com"), "honeywell")
        self.assertEqual(
            pe.detect_provider("McDonald's <mcdonalds-jobnotification@noreply.jobs2web.com>"),
            "jobs2web",
        )
        self.assertEqual(pe.detect_provider("support@awseducate.com"), "awseducate")
        self.assertEqual(pe.detect_provider("jobalert@lensa.com"), "lensa")
        self.assertEqual(pe.detect_provider("support@builtin.com"), "builtin")
        self.assertEqual(
            pe.detect_provider("NSLS-noreply@csm.symplicity.com"), "symplicity"
        )

    def test_splits_title_at_company_subject(self):
        jobs = pe.extract_postings(
            "noreply@honeywell.com", "Software Engineer at Honeywell",
            "Apply now: https://careers.honeywell.com/job/12345",
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Software Engineer")
        self.assertEqual(jobs[0]["company"], "Honeywell")
        self.assertEqual(jobs[0]["source"], "honeywell")

    def test_falls_back_to_known_employer_name(self):
        # Subject doesn't parse as "<title> at <company>" -- known-employer
        # domain still supplies a real company rather than leaving it blank.
        jobs = pe.extract_postings(
            "support@awseducate.com", "New opportunity waiting for you", "See details online.",
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["company"], "AWS Educate")

    def test_leaves_company_none_for_generic_ats_without_at_pattern(self):
        # jobs2web is a shared multi-tenant ATS, not an employer -- no
        # domain fallback should fabricate a fake company name for it
        # (mirrors mail_app_store.py's _GENERIC_SENDER_DOMAINS philosophy).
        jobs = pe.extract_postings(
            "mcdonalds-jobnotification@noreply.jobs2web.com", "New job opportunity",
            "See details online.",
        )
        self.assertEqual(len(jobs), 1)
        self.assertIsNone(jobs[0]["company"])

    def test_yields_zero_without_a_subject(self):
        self.assertEqual(pe.extract_postings("noreply@honeywell.com", None, "Apply now."), [])
        self.assertEqual(pe.extract_postings("noreply@honeywell.com", "", "Apply now."), [])

    def test_does_not_affect_supported_providers(self):
        # linkedin.com is not in _SINGLE_JOB_FALLBACK_PROVIDERS -- confirms
        # the fallback branch doesn't shadow the existing multi-job parsers.
        self.assertEqual(pe.detect_provider("jobalerts-noreply@linkedin.com"), "linkedin")


# --- dedupe key (CLAUDE_HANDOFF.md section 9) --------------------------------

class DedupeKeyTests(SimpleTestCase):
    def test_stable_for_same_url(self):
        k1 = pe.compute_dedupe_key(
            "acct1", "msg1", "https://linkedin.com/jobs/123?utm_source=x", "Engineer", "Acme"
        )
        k2 = pe.compute_dedupe_key(
            "acct1", "msg2", "https://linkedin.com/jobs/123/", "Different Title", "Different Co"
        )
        # same normalized URL -> same identity, regardless of message/title
        self.assertEqual(k1, k2)

    def test_differs_across_accounts(self):
        k1 = pe.compute_dedupe_key("acct1", "msg1", "https://linkedin.com/jobs/123", None, None)
        k2 = pe.compute_dedupe_key("acct2", "msg1", "https://linkedin.com/jobs/123", None, None)
        self.assertNotEqual(k1, k2)

    def test_falls_back_to_message_title_company_without_url(self):
        k1 = pe.compute_dedupe_key("acct1", "msg1", None, "Software Engineer", "Haystack")
        k2 = pe.compute_dedupe_key("acct1", "msg1", None, "Software Engineer", "Haystack")
        k3 = pe.compute_dedupe_key("acct1", "msg1", None, "Backend Engineer", "Haystack")
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)

    def test_two_linkless_jobs_in_one_email_both_survive(self):
        # CLAUDE_HANDOFF.md section 9: "one linkless email containing two
        # different jobs -> both survive".
        k1 = pe.compute_dedupe_key("acct1", "msg1", None, "Software Engineer", "Haystack")
        k2 = pe.compute_dedupe_key("acct1", "msg1", None, "Backend Engineer", "Haystack")
        self.assertNotEqual(k1, k2)
