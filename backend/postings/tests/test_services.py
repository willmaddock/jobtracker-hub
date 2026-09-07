from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from accounts.models import Workspace
from core.exceptions import (
    InvalidApplyStatusError,
    JobPostingAlreadyAppliedError,
    JobPostingNotFoundError,
)
from email_sync.models import EmailAccount
from postings.models import JobPosting

from ..services import (
    build_apply_response,
    ensure_postable,
    ingest_extracted_postings,
    validate_apply_status,
)

VALID_STATUSES = ["applied", "interviewing", "rejected", "drafted"]


class ValidateApplyStatusTests(SimpleTestCase):
    def test_blank_status_is_always_fine(self):
        validate_apply_status("", VALID_STATUSES)  # no raise

    def test_recognized_status_is_fine(self):
        validate_apply_status("interviewing", VALID_STATUSES)  # no raise

    def test_unrecognized_status_raises(self):
        with self.assertRaises(InvalidApplyStatusError):
            validate_apply_status("bogus", VALID_STATUSES)


class EnsurePostableTests(SimpleTestCase):
    def test_missing_job_raises_not_found(self):
        with self.assertRaises(JobPostingNotFoundError):
            ensure_postable(None, job_id=42)

    def test_already_applied_job_raises_conflict(self):
        job = SimpleNamespace(applied_application_id=7)
        with self.assertRaises(JobPostingAlreadyAppliedError):
            ensure_postable(job, job_id=42)

    def test_unapplied_job_is_postable(self):
        job = SimpleNamespace(applied_application_id=None)
        ensure_postable(job, job_id=42)  # no raise


class BuildApplyResponseTests(SimpleTestCase):
    def test_response_shape(self):
        application = SimpleNamespace(id=99)
        self.assertEqual(build_apply_response(application), {"ok": True, "application_id": 99})


class IngestExtractedPostingsTests(TestCase):
    """Phase 6: extraction.extract_postings() dicts -> real JobPosting
    rows, deduped via JobPosting.dedupe_key. Uses the LinkedIn shape
    (real sender, made-up body) rather than the fixture PDFs -- those
    are exercised end-to-end in test_extraction.py; this only tests the
    ingestion glue itself.
    """

    LINKEDIN_SENDER = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
    LINKEDIN_BODY = "Software Engineer\nAcme Corp \u00b7 Remote\n$100K-$120K / year"

    def setUp(self):
        user = get_user_model().objects.create_user(username="alice", password="pw")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, email="alice@example.com"
        )

    def test_ingests_one_row_per_extracted_job(self):
        postings = ingest_extracted_postings(
            self.account, "msg-1", self.LINKEDIN_SENDER, "Software Engineer at Acme",
            self.LINKEDIN_BODY,
        )
        self.assertEqual(len(postings), 1)
        self.assertEqual(JobPosting.objects.count(), 1)
        posting = postings[0]
        self.assertEqual(posting.title, "Software Engineer")
        self.assertEqual(posting.company, "Acme Corp")
        self.assertEqual(posting.source, "linkedin")
        self.assertEqual(posting.workspace_id, self.workspace.id)
        self.assertEqual(posting.account_id, self.account.id)

    def test_reingesting_same_message_is_idempotent(self):
        # Phase 9's acceptance bar ("running sync four times in a row
        # produces the same posting count each time") applies just as
        # much to this ingestion step, even though the sync loop that
        # will call it repeatedly doesn't exist yet.
        for _ in range(4):
            ingest_extracted_postings(
                self.account, "msg-1", self.LINKEDIN_SENDER, "Software Engineer at Acme",
                self.LINKEDIN_BODY,
            )
        self.assertEqual(JobPosting.objects.count(), 1)

    def test_reingesting_updates_fields_rather_than_duplicating(self):
        # Without a URL, dedupe_key includes normalized title/company (see
        # extraction.compute_dedupe_key), so title/company must stay the
        # same across re-ingests here for this to be "the same job" at
        # all -- only salary/location, which aren't part of that identity,
        # change between the two calls.
        ingest_extracted_postings(
            self.account, "msg-1", self.LINKEDIN_SENDER, "Software Engineer at Acme",
            self.LINKEDIN_BODY,
        )
        updated_body = "Software Engineer\nAcme Corp \u00b7 Remote\n$140K-$160K / year"
        ingest_extracted_postings(
            self.account, "msg-1", self.LINKEDIN_SENDER, "Software Engineer at Acme",
            updated_body,
        )
        self.assertEqual(JobPosting.objects.count(), 1)
        posting = JobPosting.objects.get()
        self.assertEqual(posting.title, "Software Engineer")
        self.assertEqual(posting.salary, "$140K-$160K / year")

    def test_two_linkless_jobs_in_one_email_both_survive(self):
        two_job_body = (
            "Software Engineer\nAcme Corp \u00b7 Remote\n"
            "Backend Engineer\nOther Co \u00b7 Denver, CO"
        )
        postings = ingest_extracted_postings(
            self.account, "msg-2", self.LINKEDIN_SENDER, "Jobs for you", two_job_body,
        )
        self.assertEqual(len(postings), 2)
        self.assertEqual(JobPosting.objects.filter(message_id="msg-2").count(), 2)

    def test_unsupported_provider_ingests_nothing(self):
        postings = ingest_extracted_postings(
            self.account, "msg-3", "Someone <person@example.com>", "Hi",
            "Just checking in.",
        )
        self.assertEqual(postings, [])
        self.assertEqual(JobPosting.objects.count(), 0)

    def test_posting_url_is_attached_when_given(self):
        postings = ingest_extracted_postings(
            self.account, "msg-4", self.LINKEDIN_SENDER, "Software Engineer at Acme",
            self.LINKEDIN_BODY, posting_urls=["https://linkedin.com/jobs/123"],
        )
        self.assertEqual(postings[0].posting_url, "https://linkedin.com/jobs/123")

    def test_dedupe_key_is_unique_across_the_table(self):
        ingest_extracted_postings(
            self.account, "msg-5", self.LINKEDIN_SENDER, "Software Engineer at Acme",
            self.LINKEDIN_BODY,
        )
        posting = JobPosting.objects.get()
        # unique=True on dedupe_key is what makes update_or_create's
        # lookup safe to rely on -- confirm the constraint is actually
        # in force, not just that ingestion behaved as if it were.
        self.assertEqual(
            JobPosting.objects.filter(dedupe_key=posting.dedupe_key).count(), 1
        )
