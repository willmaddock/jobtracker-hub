"""
postings API tests.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md) -- exercises the DRF surface
in postings/views.py end-to-end (auth, ownership scoping, and each of
list/dismiss/restore/save/apply), as opposed to test_services.py's
unit-level coverage of the underlying eligibility rules.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace
from applications.models import Application
from email_sync.models import EmailAccount
from postings.models import JobPosting


class JobPostingAPITestCase(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.other_user = User.objects.create_user(username="bob", password="pw123456")

        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.other_workspace = Workspace.objects.create(owner=self.other_user, name="Bob's workspace")

        self.account = EmailAccount.objects.create(
            workspace=self.workspace, email="alice@example.com"
        )
        self.other_account = EmailAccount.objects.create(
            workspace=self.other_workspace, email="bob@example.com"
        )

        self.posting = JobPosting.objects.create(
            workspace=self.workspace, account=self.account, message_id="msg-1",
            source="linkedin", title="Software Engineer", company="Acme Corp",
            dedupe_key="key-1",
        )
        self.dismissed_posting = JobPosting.objects.create(
            workspace=self.workspace, account=self.account, message_id="msg-2",
            source="linkedin", title="Backend Engineer", company="Other Co",
            status="dismissed", dedupe_key="key-2",
        )
        self.other_posting = JobPosting.objects.create(
            workspace=self.other_workspace, account=self.other_account, message_id="msg-3",
            source="linkedin", title="Frontend Engineer", company="Bob's Co",
            dedupe_key="key-3",
        )

    def list_url(self):
        return reverse("job-posting-list")

    def detail_action_url(self, posting_id, action_name):
        return reverse(f"job-posting-{action_name}", args=[posting_id])


class UnauthenticatedAccessTests(JobPostingAPITestCase):
    def test_list_requires_auth(self):
        response = self.client.get(self.list_url())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ListJobPostingsTests(JobPostingAPITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def test_lists_only_new_postings(self):
        response = self.client.get(self.list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [p["title"] for p in response.data]
        self.assertIn("Software Engineer", titles)
        self.assertNotIn("Backend Engineer", titles)  # dismissed, excluded

    def test_does_not_leak_other_users_postings(self):
        response = self.client.get(self.list_url())
        titles = [p["title"] for p in response.data]
        self.assertNotIn("Frontend Engineer", titles)


class DismissRestoreTests(JobPostingAPITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def test_dismiss_hides_from_list(self):
        response = self.client.post(self.detail_action_url(self.posting.id, "dismiss"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.posting.refresh_from_db()
        self.assertEqual(self.posting.status, "dismissed")

    def test_restore_brings_back_to_list(self):
        response = self.client.post(self.detail_action_url(self.dismissed_posting.id, "restore"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.dismissed_posting.refresh_from_db()
        self.assertEqual(self.dismissed_posting.status, "new")

    def test_cannot_dismiss_another_users_posting(self):
        response = self.client.post(self.detail_action_url(self.other_posting.id, "dismiss"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.other_posting.refresh_from_db()
        self.assertEqual(self.other_posting.status, "new")


class SaveJobPostingTests(JobPostingAPITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def test_save_defaults_to_true(self):
        response = self.client.post(self.detail_action_url(self.posting.id, "save"), {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.posting.refresh_from_db()
        self.assertTrue(self.posting.saved)

    def test_save_false_unstars(self):
        self.posting.saved = True
        self.posting.save(update_fields=["saved"])
        response = self.client.post(
            self.detail_action_url(self.posting.id, "save"), {"saved": False}, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.posting.refresh_from_db()
        self.assertFalse(self.posting.saved)

    def test_save_returns_refreshed_board_list(self):
        response = self.client.post(self.detail_action_url(self.posting.id, "save"), {})
        titles = [p["title"] for p in response.data]
        self.assertIn("Software Engineer", titles)


class ApplyJobPostingTests(JobPostingAPITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def test_apply_creates_application_and_links_posting(self):
        response = self.client.post(
            self.detail_action_url(self.posting.id, "apply"),
            {"company": "Acme Corp", "role_label": "Software Engineer", "status": "applied"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("application_id", response.data)
        application = Application.objects.get(id=response.data["application_id"])
        self.assertEqual(application.company, "Acme Corp")
        self.assertEqual(application.override.manual_status, "applied")
        self.posting.refresh_from_db()
        self.assertEqual(self.posting.applied_application_id, application.id)

    def test_apply_falls_back_to_posting_company_and_title(self):
        response = self.client.post(self.detail_action_url(self.posting.id, "apply"), {})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        application = Application.objects.get(id=response.data["application_id"])
        self.assertEqual(application.company, "Acme Corp")
        self.assertEqual(application.role_label, "Software Engineer")

    def test_apply_twice_is_rejected(self):
        self.client.post(self.detail_action_url(self.posting.id, "apply"), {})
        response = self.client.post(self.detail_action_url(self.posting.id, "apply"), {})
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_apply_with_invalid_status_is_rejected(self):
        response = self.client.post(
            self.detail_action_url(self.posting.id, "apply"), {"status": "not-a-real-status"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Application.objects.count(), 0)

    def test_apply_with_blank_status_skips_override(self):
        response = self.client.post(
            self.detail_action_url(self.posting.id, "apply"), {"status": ""},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        application = Application.objects.get(id=response.data["application_id"])
        self.assertFalse(hasattr(application, "override"))

    def test_cannot_apply_to_another_users_posting(self):
        response = self.client.post(self.detail_action_url(self.other_posting.id, "apply"), {})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
