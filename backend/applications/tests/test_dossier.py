"""applications dossier tests.

Phase 8 slice (docs/DJANGO_MIGRATION_PLAN.md) -- exercises the
GET /api/applications/{id}/dossier action end-to-end (applications/
views.py's dossier action + applications/dossier.assemble_dossier()
+ documents/extraction.py), as opposed to documents/tests/
test_extraction.py's unit-level coverage of the extraction pipeline
itself.
"""
from __future__ import annotations

import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace
from email_sync.models import AccountMatch, EmailAccount

from ..models import Application, Override, StatusHistory
from documents.models import Document

_JOB_POSTING_A = b"""Job Description
Widget engineering role.

Responsibilities
Build widgets.

Qualifications
Some experience required. Reach recruiter at recruiter@acme.example.
"""

_JOB_POSTING_B = b"""Job Description
A second, alphabetically-later posting file.
"""

_CONFIRMATION = b"""From: no-reply@us.greenhouse-mail.io
Subject: Thank you for applying to Acme
Date: July 10, 2025 at 10:56 AM
To: candidate@example.com

Thanks for applying to Acme!
"""

_INTERVIEW_NOTICE = b"""From: recruiter@acme.example
Subject: Interview request
Date: July 15, 2025 at 9:00 AM
To: candidate@example.com

We would like to schedule an interview.
"""


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DossierAPITestCase(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.other_user = User.objects.create_user(username="bob", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.other_workspace = Workspace.objects.create(owner=self.other_user, name="Bob's workspace")

        self.application = Application.objects.create(
            workspace=self.workspace, section="applications",
            company="Acme Robotics", role_label="Backend Engineer", source_relpath="",
        )
        self.other_application = Application.objects.create(
            workspace=self.other_workspace, section="applications",
            company="Bob's Co", role_label="Frontend Engineer", source_relpath="",
        )
        self.client.login(username="alice", password="pw123456")

    def _add_document(self, filename, content, doc_type, application=None, ext=".txt", content_hash=None):
        application = application or self.application
        return Document.objects.create(
            workspace=application.workspace,
            application=application,
            file=SimpleUploadedFile(filename, content),
            filename=filename,
            doc_type=doc_type,
            ext=ext,
            content_hash=content_hash or filename,
            size=len(content),
        )

    def _get_dossier(self, application=None):
        application = application or self.application
        return self.client.get(reverse("application-dossier", args=[application.id]))


class OwnershipTests(DossierAPITestCase):
    def test_cannot_view_another_users_dossier(self):
        response = self._get_dossier(self.other_application)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class RoleSectionsAndContactsTests(DossierAPITestCase):
    def test_picks_job_posting_alphabetically_first_on_tie(self):
        self._add_document("posting-b.txt", _JOB_POSTING_B, "job_posting")
        self._add_document("posting-a.txt", _JOB_POSTING_A, "job_posting")
        response = self._get_dossier()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # "posting-a.txt" sorts before "posting-b.txt".
        self.assertIn("Build widgets", response.data["duties"])

    def test_contacts_aggregate_across_documents(self):
        self._add_document("posting.txt", _JOB_POSTING_A, "job_posting")
        self._add_document(
            "confirmation.txt", _CONFIRMATION, "application_confirmation", content_hash="conf-hash"
        )
        response = self._get_dossier()
        self.assertIn("recruiter@acme.example", response.data["contacts"]["emails"])

    def test_extraction_failure_reported_not_raised(self):
        self._add_document("resume.docx", b"binary junk", "resume", ext=".docx")
        response = self._get_dossier()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["extraction_errors"]), 1)
        self.assertEqual(response.data["extraction_errors"][0]["filename"], "resume.docx")

    def test_no_documents_returns_not_detected_everywhere(self):
        response = self._get_dossier()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["role_summary"], "Not detected")
        self.assertEqual(response.data["contacts"]["emails"], [])


class DateAppliedAutoFillTests(DossierAPITestCase):
    def test_autofills_date_applied_from_confirmation_evidence(self):
        self._add_document(
            "confirmation.txt", _CONFIRMATION, "application_confirmation", content_hash="conf-hash-2"
        )
        response = self._get_dossier()
        self.assertTrue(response.data["date_applied_auto_filled"])
        self.application.refresh_from_db()
        self.assertEqual(self.application.override.date_applied.isoformat(), "2025-07-10")
        self.assertEqual(self.application.override.date_applied_source, "confirmation")

    def test_never_overwrites_an_existing_date_applied(self):
        Override.objects.create(
            application=self.application, date_applied="2020-01-01", date_applied_source=None
        )
        self._add_document(
            "confirmation.txt", _CONFIRMATION, "application_confirmation", content_hash="conf-hash-3"
        )
        response = self._get_dossier()
        self.assertFalse(response.data["date_applied_auto_filled"])
        self.application.override.refresh_from_db()
        self.assertEqual(self.application.override.date_applied.isoformat(), "2020-01-01")

    def test_posting_only_evidence_is_suggested_not_autofilled(self):
        self._add_document("posting.txt", _JOB_POSTING_A, "job_posting", content_hash="posting-hash")
        # _JOB_POSTING_A has no detectable date, so add a posting doc
        # whose text happens to carry a keyworded date pattern instead.
        posting_with_date = (
            b"Job Description\nApply now.\n\nWe received applications submitted 07/10/2025 for this role."
        )
        self._add_document(
            "posting2.txt", posting_with_date, "job_posting", content_hash="posting-hash-2"
        )
        response = self._get_dossier()
        self.assertEqual(response.data["detected_date_evidence_tier"], "posting")
        self.assertFalse(response.data["date_applied_auto_filled"])
        self.application.refresh_from_db()
        self.assertFalse(hasattr(self.application, "override") and self.application.override.date_applied)


class CurrentStatusTests(DossierAPITestCase):
    def test_current_status_falls_back_to_auto_status_with_no_history(self):
        response = self._get_dossier()
        self.assertEqual(response.data["current_status"], self.application.status)
        self.assertFalse(response.data["current_status_date_known"])
        self.assertIsNone(response.data["current_status_date"])

    def test_current_status_date_from_latest_matching_status_history(self):
        Override.objects.create(application=self.application, manual_status="interviewing")
        StatusHistory.objects.create(
            application=self.application, status="interviewing",
            changed_at=timezone.datetime(2025, 6, 1, tzinfo=timezone.get_current_timezone()),
            source="manual",
        )
        StatusHistory.objects.create(
            application=self.application, status="interviewing",
            changed_at=timezone.datetime(2025, 6, 15, tzinfo=timezone.get_current_timezone()),
            source="manual",
        )
        response = self._get_dossier()
        self.assertEqual(response.data["current_status"], "interviewing")
        self.assertTrue(response.data["current_status_date_known"])
        self.assertEqual(response.data["current_status_date"], "2025-06-15")


class TimelineEventsTests(DossierAPITestCase):
    def test_confirmation_and_interview_notice_each_produce_an_event(self):
        self._add_document(
            "confirmation.txt", _CONFIRMATION, "application_confirmation", content_hash="tl-conf"
        )
        self._add_document(
            "interview.txt", _INTERVIEW_NOTICE, "interview_notice", content_hash="tl-interview"
        )
        response = self._get_dossier()
        events = response.data["timeline_events"]
        self.assertEqual(len(events), 2)
        self.assertEqual([e["date"] for e in events], ["2025-07-10", "2025-07-15"])


class AccountMatchesTests(DossierAPITestCase):
    def test_empty_when_no_account_connected(self):
        response = self._get_dossier()
        self.assertEqual(response.data["account_matches"], [])

    def test_includes_matches_for_a_connected_account(self):
        account = EmailAccount.objects.create(
            workspace=self.workspace, provider="mail_app", email="alice@example.com",
        )
        AccountMatch.objects.create(
            account=account, application=self.application, message_id="msg-1",
            subject="Re: Backend Engineer application",
        )
        response = self._get_dossier()
        matches = response.data["account_matches"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["account_email"], "alice@example.com")
        self.assertEqual(matches[0]["account_provider"], "mail_app")
