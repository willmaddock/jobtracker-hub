from types import SimpleNamespace

from django.test import SimpleTestCase

from core.exceptions import (
    InvalidApplyStatusError,
    JobPostingAlreadyAppliedError,
    JobPostingNotFoundError,
)
from .services import build_apply_response, ensure_postable, validate_apply_status

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
