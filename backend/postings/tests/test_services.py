from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from accounts.models import Workspace
from core.exceptions import (
    InvalidApplyStatusError,
)
from email_sync.models import EmailAccount
from postings.models import JobPosting

from ..services import (
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

    def test_linkless_reingestion_preserves_pk_uuid_and_dedupe(self):
        first = ingest_extracted_postings(self.account, "stable", self.LINKEDIN_SENDER,
            "Jobs", self.LINKEDIN_BODY)[0]
        second = ingest_extracted_postings(self.account, "stable", self.LINKEDIN_SENDER,
            "Jobs", self.LINKEDIN_BODY.replace("$100K-$120K", "$140K-$160K"))[0]
        self.assertEqual((second.pk, second.portable_id, second.dedupe_key),
                         (first.pk, first.portable_id, first.dedupe_key))
        self.assertEqual(second.salary, "$140K-$160K / year")
        self.assertEqual(JobPosting.objects.count(), 1)

    def test_url_reingestion_preserves_identity_and_positional_compatibility(self):
        from unittest.mock import patch
        jobs = [{"title": "First", "company": "One"}, {"title": "Second", "company": "Two"}]
        urls = ["https://example.test/jobs/1?tracking=old", "https://example.test/jobs/2"]
        with patch("postings.extraction.extract_postings", return_value=jobs):
            first = ingest_extracted_postings(self.account, "old", "sender", "subject", "body", posting_urls=urls)
        self.assertEqual([p.posting_url for p in first], urls)
        self.assertEqual([p.title for p in first], ["First", "Second"])
        revised = [{"title": "Revised second", "company": "Two"}, {"title": "Revised first", "company": "One"}]
        new_urls = ["https://example.test/jobs/1?tracking=new", urls[1]]
        with patch("postings.extraction.extract_postings", return_value=revised):
            second = ingest_extracted_postings(self.account, "new", "sender", "new subject", "body", posting_urls=new_urls)
        # Preserve the existing positional association, even when descriptions reorder.
        self.assertEqual([(p.pk, p.portable_id, p.dedupe_key) for p in first],
                         [(p.pk, p.portable_id, p.dedupe_key) for p in second])
        self.assertEqual([p.title for p in second], ["Revised second", "Revised first"])
        self.assertEqual([p.message_id for p in second], ["new", "new"])
        self.assertEqual([p.posting_url for p in second], new_urls)
        self.assertEqual(JobPosting.objects.count(), 2)


from postings.tests.test_job_posting_projections import Fixtures as ProjectionFixtures


class ProjectionIngestionTests(ProjectionFixtures, TestCase):
    def ingest(self, **changes):
        from unittest.mock import patch
        from postings.extraction import compute_dedupe_key
        from postings.tests.test_retained_extractions import fields
        url = "https://example.test/job?tracking=new"
        JobPosting.objects.filter(pk=self.p.pk).update(dedupe_key=compute_dedupe_key(
            str(self.account.pk), "new", url, "incoming", "Incoming company"))
        with patch("postings.extraction.extract_postings", return_value=[fields("incoming") | {"company": "Incoming company"}]):
            return ingest_extracted_postings(self.account, **dict(message_id="new", sender="new sender",
                subject="new subject", body="body", posting_urls=[url]) | changes)[0]

    def test_projected_preserves_six_while_updating_metadata(self):
        self.project()
        result = self.ingest()
        from postings.job_posting_projections import descriptor_snapshot
        self.assertEqual(descriptor_snapshot(result), self.outputs[0].fields)
        self.assertEqual((result.pk, result.portable_id), (self.p.pk, self.p.portable_id))
        self.assertEqual((result.message_id, result.sender, result.email_subject), ("new", "new sender", "new subject"))
        self.assertEqual(result.posting_url, "https://example.test/job?tracking=new")
        self.assertEqual(JobPosting.objects.count(), 2)

    def test_unprojected_keeps_existing_updates(self):
        result = self.ingest()
        self.assertEqual((result.title, result.company), ("incoming", "Incoming company"))

    def test_withdrawal_and_corrupt_history_do_not_release_ingestion_ownership(self):
        from postings.models import JobPostingDescriptorProjection
        self.project()
        self.remove()
        JobPostingDescriptorProjection.objects.update(snapshot={})
        result = self.ingest()
        self.assertEqual(result.title, self.outputs[0].fields["title"])

    def test_workspace_gate_precedes_row_lookup_and_no_update_or_create(self):
        from unittest.mock import patch
        from django.db.models.query import QuerySet
        from postings import models
        trace = []
        real_gate = models._lock_descriptor_workspace
        real_select = QuerySet.select_for_update
        def gate(*args):
            trace.append("workspace")
            return real_gate(*args)
        def select(query, *args, **kwargs):
            if query.model is JobPosting:
                trace.append("posting")
            return real_select(query, *args, **kwargs)
        with patch.object(models, "_lock_descriptor_workspace", gate), patch.object(QuerySet, "select_for_update", select), patch.object(QuerySet, "update_or_create", side_effect=AssertionError("row-first writer")):
            self.ingest()
        self.assertEqual(trace[:2], ["workspace", "posting"])

    def test_no_hidden_retry_on_database_error(self):
        from unittest.mock import patch
        from django.db import OperationalError
        with patch("postings.models._lock_descriptor_workspace", side_effect=OperationalError("busy")) as gate:
            with self.assertRaises(OperationalError):
                self.ingest()
        self.assertEqual(gate.call_count, 1)


from postings.tests.test_job_posting_allocations import Fixtures as AllocationFixtures


class AllocationIngestionTests(AllocationFixtures, TestCase):
    def test_allocation_existence_preserves_descriptors_and_allows_metadata(self):
        from unittest.mock import patch
        import uuid
        from postings.models import JobPostingAllocation
        from postings.tests.test_retained_extractions import fields
        row = JobPosting.objects.get(pk=self.allocate().allocation.posting_id)
        for projected in (False, True):
            if projected:
                self.projected(row.pk)
            row.refresh_from_db()
            before = {name: getattr(row, name) for name in fields()}
            # The reserved key normally cannot be emitted by ingestion. Inject a
            # matching key to test defense-in-depth independently of its algorithm.
            with patch("postings.extraction.compute_dedupe_key", return_value=row.dedupe_key), patch(
                    "postings.extraction.extract_postings", return_value=[fields("incoming")]):
                result = ingest_extracted_postings(self.account, "fresh", "sender", "subject", "body",
                    posting_urls=["https://example.test/new"])[0]
            self.assertEqual({name: getattr(result, name) for name in before}, before)
            self.assertEqual((result.message_id, result.sender, result.email_subject, result.posting_url),
                ("fresh", "sender", "subject", "https://example.test/new"))
        JobPostingAllocation.objects.filter(posting=row).update(operation_id=uuid.UUID(int=0))
        with patch("postings.extraction.compute_dedupe_key", return_value=row.dedupe_key), patch(
                "postings.extraction.extract_postings", return_value=[fields("incoming")]):
            result = ingest_extracted_postings(self.account, "fresh", "sender", "subject", "body")[0]
        self.assertEqual(result.title, before["title"])

    def test_malformed_unprojected_allocation_still_excludes_ingestion(self):
        import uuid
        from unittest.mock import patch
        from postings.models import JobPostingAllocation, JobPostingDescriptorProjection
        from postings.tests.test_retained_extractions import fields
        row = JobPosting.objects.get(pk=self.allocate().allocation.posting_id)
        row.title = "manual before projection"
        row.save(update_fields=["title"])
        JobPostingAllocation.objects.filter(posting=row).update(operation_id=uuid.UUID(int=0))
        self.assertFalse(JobPostingDescriptorProjection.objects.filter(posting=row).exists())
        with patch("postings.extraction.compute_dedupe_key", return_value=row.dedupe_key), patch(
                "postings.extraction.extract_postings", return_value=[fields("incoming")]):
            result = ingest_extracted_postings(self.account, "new-metadata", "sender", "subject", "body")[0]
        self.assertEqual(result.title, "manual before projection")
        self.assertEqual(result.message_id, "new-metadata")
