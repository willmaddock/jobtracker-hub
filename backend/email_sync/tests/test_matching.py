"""
Tests for email_sync/matching.py -- the pure classification/matching
functions ported from _app/mail_app_store.py (Phase 9 scoping slice).
Only the AppleScript-independent logic is covered here; anything that
drove an AppleScript query in the original (search_messages,
search_unmatched_messages, get_message_source, ...) belongs to the
actual provider-sync slice, not this one.
"""
from django.test import SimpleTestCase

from email_sync import matching


# ---------------------------------------------------------------------------
# is_usable_match_term / term_matches_wholeword
# ---------------------------------------------------------------------------

class IsUsableMatchTermTests(SimpleTestCase):
    def test_rejects_short_terms(self):
        self.assertFalse(matching.is_usable_match_term("abc"))

    def test_rejects_generic_stoplist_terms(self):
        for term in ("IT", "HR", "PM", "root", "(root)", "TBD", "N/A"):
            self.assertFalse(matching.is_usable_match_term(term))

    def test_accepts_specific_terms(self):
        self.assertTrue(matching.is_usable_match_term("Acme Corp"))
        self.assertTrue(matching.is_usable_match_term("Tech"))

    def test_rejects_empty_or_none(self):
        self.assertFalse(matching.is_usable_match_term(None))
        self.assertFalse(matching.is_usable_match_term(""))
        self.assertFalse(matching.is_usable_match_term("   "))


class TermMatchesWholewordTests(SimpleTestCase):
    def test_rejects_midword_substring(self):
        self.assertFalse(
            matching.term_matches_wholeword("Tech", "Technical Project Manager")
        )

    def test_accepts_standalone_word(self):
        self.assertTrue(
            matching.term_matches_wholeword("Tech", "Senior Tech Lead role")
        )

    def test_checks_multiple_texts(self):
        self.assertTrue(
            matching.term_matches_wholeword(
                "Acme", "unrelated subject", "sender@acme.com Acme Recruiting"
            )
        )
        self.assertFalse(
            matching.term_matches_wholeword("Acme", "nothing here", None)
        )

    def test_multi_word_term(self):
        self.assertTrue(
            matching.term_matches_wholeword(
                "Metro Water Recovery", "Update from Metro Water Recovery"
            )
        )
        self.assertFalse(
            matching.term_matches_wholeword(
                "Metro Water Recovery", "Metro Water RecoveryX District news"
            )
        )


# ---------------------------------------------------------------------------
# extract_thread_message_ids
# ---------------------------------------------------------------------------

class ExtractThreadMessageIdsTests(SimpleTestCase):
    def test_parses_in_reply_to_and_references(self):
        headers = (
            "In-Reply-To: <abc123@mail.example.com>\n"
            "References: <zzz@mail.example.com> <abc123@mail.example.com>\n"
        )
        ids = matching.extract_thread_message_ids(headers)
        self.assertEqual(ids, {"<abc123@mail.example.com>", "<zzz@mail.example.com>"})

    def test_handles_folded_references_header(self):
        headers = (
            "References: <one@example.com>\n"
            " <two@example.com>\n"
            "\t<three@example.com>\n"
        )
        ids = matching.extract_thread_message_ids(headers)
        self.assertEqual(
            ids, {"<one@example.com>", "<two@example.com>", "<three@example.com>"}
        )

    def test_empty_or_missing_headers_returns_empty_set(self):
        self.assertEqual(matching.extract_thread_message_ids(""), set())
        self.assertEqual(matching.extract_thread_message_ids("   "), set())
        self.assertEqual(matching.extract_thread_message_ids(None), set())


# ---------------------------------------------------------------------------
# guess_company_from_email
# ---------------------------------------------------------------------------

class GuessCompanyFromEmailTests(SimpleTestCase):
    def test_prefers_subject_phrasing(self):
        guess = matching.guess_company_from_email(
            "Your application to Acme Corp", "no-reply@myworkday.com"
        )
        self.assertEqual(guess, "Acme Corp")

    def test_falls_back_to_sender_domain(self):
        guess = matching.guess_company_from_email(
            "Update on your candidacy", "recruiting@initech.com"
        )
        self.assertEqual(guess, "Initech")

    def test_skips_generic_and_ats_domains(self):
        self.assertIsNone(
            matching.guess_company_from_email("Status update", "no-reply@myworkday.com")
        )
        self.assertIsNone(
            matching.guess_company_from_email("Status update", "someone@gmail.com")
        )

    def test_returns_none_when_nothing_to_go_on(self):
        self.assertIsNone(matching.guess_company_from_email(None, None))
        self.assertIsNone(matching.guess_company_from_email("", ""))


# ---------------------------------------------------------------------------
# is_job_posting_style_subject
# ---------------------------------------------------------------------------

class IsJobPostingStyleSubjectTests(SimpleTestCase):
    def test_matches_percent_match_phrasing(self):
        self.assertTrue(
            matching.is_job_posting_style_subject(
                "KPMG just posted a 78% match Front End Engineer role"
            )
        )

    def test_matches_new_jobs_open_phrasing(self):
        self.assertTrue(
            matching.is_job_posting_style_subject(
                "Just in: Comcast has new Junior Developer jobs open"
            )
        )

    def test_false_for_ordinary_application_subject(self):
        self.assertFalse(
            matching.is_job_posting_style_subject("Thank you for applying to Acme")
        )

    def test_false_for_none_or_empty(self):
        self.assertFalse(matching.is_job_posting_style_subject(None))
        self.assertFalse(matching.is_job_posting_style_subject(""))


# ---------------------------------------------------------------------------
# looks_like_untracked_application (Django-native replacement for the
# AppleScript whose-clause search_unmatched_messages() used to build)
# ---------------------------------------------------------------------------

class LooksLikeUntrackedApplicationTests(SimpleTestCase):
    def test_ats_only_domain_sender_alone_is_enough(self):
        is_candidate, force_posting = matching.looks_like_untracked_application(
            "Your interview is confirmed", "no-reply@icims.com"
        )
        self.assertTrue(is_candidate)
        self.assertFalse(force_posting)

    def test_mixed_signal_domain_requires_ats_subject(self):
        is_candidate, _ = matching.looks_like_untracked_application(
            "New jobs in Denver match your preferences",
            "jobalerts-noreply@linkedin.com",
        )
        self.assertFalse(is_candidate)

        is_candidate, _ = matching.looks_like_untracked_application(
            "Thank you for applying to a role", "jobalerts-noreply@linkedin.com"
        )
        self.assertTrue(is_candidate)

    def test_excludes_digest_style_subjects(self):
        is_candidate, _ = matching.looks_like_untracked_application(
            "Job alert: 5 new jobs for you", "no-reply@icims.com"
        )
        self.assertFalse(is_candidate)

    def test_whitelisted_sender_forces_posting_and_bypasses_digest_exclusion(self):
        is_candidate, force_posting = matching.looks_like_untracked_application(
            "Job alert: 5 new jobs for you",
            "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
            always_posting_senders={"jobalerts-noreply@linkedin.com"},
        )
        self.assertTrue(is_candidate)
        self.assertTrue(force_posting)

    def test_non_whitelisted_hit_reports_force_posting_false(self):
        _, force_posting = matching.looks_like_untracked_application(
            "Thank you for applying", "no-reply@icims.com"
        )
        self.assertFalse(force_posting)

    def test_ordinary_unrelated_mail_is_not_a_candidate(self):
        is_candidate, _ = matching.looks_like_untracked_application(
            "Your Amazon order has shipped", "no-reply@amazon.com"
        )
        self.assertFalse(is_candidate)


# ---------------------------------------------------------------------------
# extract_posting_urls / guess_posting_url
# ---------------------------------------------------------------------------

class ExtractPostingUrlsTests(SimpleTestCase):
    def test_returns_every_matching_link_in_body_order(self):
        body = (
            "Check out https://www.linkedin.com/jobs/view/111?utm_source=x "
            "and https://www.greenhouse.io/jobs/222 "
            "and https://boards.example.com/not-a-known-domain"
        )
        urls = matching.extract_posting_urls(body)
        self.assertEqual(
            urls,
            [
                "https://www.linkedin.com/jobs/view/111?utm_source=x",
                "https://www.greenhouse.io/jobs/222",
            ],
        )

    def test_dedupes_while_preserving_order(self):
        body = (
            "https://www.lever.co/acme/123 "
            "https://www.lever.co/acme/123"
        )
        self.assertEqual(
            matching.extract_posting_urls(body), ["https://www.lever.co/acme/123"]
        )

    def test_returns_empty_list_for_empty_or_none_body(self):
        self.assertEqual(matching.extract_posting_urls(None), [])
        self.assertEqual(matching.extract_posting_urls(""), [])

    def test_returns_empty_list_when_nothing_recognizable(self):
        self.assertEqual(
            matching.extract_posting_urls("https://example.com/not-a-job-board"), []
        )

    def test_does_not_reject_utm_tagged_real_links(self):
        urls = matching.extract_posting_urls(
            "https://www.linkedin.com/jobs/view/999?utm_campaign=alert&trk=eml"
        )
        self.assertEqual(
            urls, ["https://www.linkedin.com/jobs/view/999?utm_campaign=alert&trk=eml"]
        )

    def test_filters_generic_view_all_link(self):
        self.assertEqual(
            matching.extract_posting_urls(
                "https://www.linkedin.com/jobs/search/?keywords=engineer"
            ),
            [],
        )


class GuessPostingUrlTests(SimpleTestCase):
    def test_picks_known_ats_link(self):
        self.assertEqual(
            matching.guess_posting_url("See https://www.greenhouse.io/jobs/42 for details"),
            "https://www.greenhouse.io/jobs/42",
        )

    def test_skips_unsubscribe_even_on_a_known_domain(self):
        self.assertIsNone(
            matching.guess_posting_url(
                "https://www.greenhouse.io/unsubscribe?id=1"
            )
        )

    def test_returns_none_when_nothing_recognizable(self):
        self.assertIsNone(matching.guess_posting_url("https://example.com/page"))

    def test_returns_none_for_empty_or_none_body(self):
        self.assertIsNone(matching.guess_posting_url(None))
        self.assertIsNone(matching.guess_posting_url(""))


class ExtractPrimaryCtaUrlTests(SimpleTestCase):
    def test_picks_an_unrecognized_employer_domain(self):
        url = matching.extract_primary_cta_url(
            "Apply now: https://careers.honeywell.com/apply/123"
        )
        self.assertEqual(url, "https://careers.honeywell.com/apply/123")

    def test_returns_first_candidate_in_body_order(self):
        body = (
            "https://careers.example.com/first "
            "https://careers.example.com/second"
        )
        self.assertEqual(
            matching.extract_primary_cta_url(body), "https://careers.example.com/first"
        )

    def test_skips_unsubscribe_preference_and_tracking_links(self):
        body = (
            "https://mail.example.com/unsubscribe "
            "https://mail.example.com/track/open "
            "https://careers.example.com/apply/1"
        )
        self.assertEqual(
            matching.extract_primary_cta_url(body), "https://careers.example.com/apply/1"
        )

    def test_skips_social_and_app_store_footer_links(self):
        body = (
            "https://facebook.com/example "
            "https://apps.apple.com/app/example "
            "https://careers.example.com/apply/2"
        )
        self.assertEqual(
            matching.extract_primary_cta_url(body), "https://careers.example.com/apply/2"
        )

    def test_skips_generic_collection_links(self):
        body = (
            "https://boards.example.com/jobs/search?x=1 "
            "https://careers.example.com/apply/3"
        )
        self.assertEqual(
            matching.extract_primary_cta_url(body), "https://careers.example.com/apply/3"
        )

    def test_returns_none_when_nothing_survives_filtering(self):
        body = "https://mail.example.com/unsubscribe https://facebook.com/example"
        self.assertIsNone(matching.extract_primary_cta_url(body))

    def test_returns_none_for_empty_or_none_body(self):
        self.assertIsNone(matching.extract_primary_cta_url(None))
        self.assertIsNone(matching.extract_primary_cta_url(""))


# ---------------------------------------------------------------------------
# normalize_linkedin_comm_url / extract_html_source_urls
# ---------------------------------------------------------------------------

# A trimmed real-shape LinkedIn "Job Alerts" digest MIME source: one
# text/plain part and one quoted-printable text/html part whose <a href>
# values need MIME decoding + /comm/ + tracking-query cleanup before
# they're recognizable as job-posting links. Mirrors the fixture the
# original app's audit-findings regression test used.
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


class NormalizeLinkedinCommUrlTests(SimpleTestCase):
    def test_strips_comm_segment_and_query_string(self):
        url = "https://www.linkedin.com/comm/jobs/view/123?trk=eml&lipi=abc"
        self.assertEqual(
            matching.normalize_linkedin_comm_url(url),
            "https://www.linkedin.com/jobs/view/123",
        )

    def test_leaves_non_linkedin_urls_unchanged(self):
        url = "https://www.greenhouse.io/jobs/42?utm_source=x"
        self.assertEqual(matching.normalize_linkedin_comm_url(url), url)


class ExtractHtmlSourceUrlsTests(SimpleTestCase):
    def test_recovers_real_job_links_from_html_email(self):
        urls = matching.extract_html_source_urls(_LINKEDIN_DIGEST_SOURCE)
        self.assertEqual(
            urls,
            [
                "https://www.linkedin.com/jobs/view/4382484258",
                "https://www.linkedin.com/jobs/view/4367342975",
            ],
        )
        joined = " ".join(urls)
        self.assertNotIn("/comm/", joined)
        self.assertNotIn("?", joined)
        for excluded in ("jobs/search", "unsubscribe", "feed", "/in/"):
            self.assertNotIn(excluded, joined)

    def test_handles_missing_or_garbage_input(self):
        self.assertEqual(matching.extract_html_source_urls(None), [])
        self.assertEqual(matching.extract_html_source_urls(""), [])
        self.assertEqual(
            matching.extract_html_source_urls("not a mime message at all"), []
        )
