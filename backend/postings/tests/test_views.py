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
        return reverse("job-posting-list", args=[self.workspace.pk])

    def detail_action_url(self, posting_id, action_name):
        return reverse(f"job-posting-{action_name}", args=[self.workspace.pk, posting_id])


class UnauthenticatedAccessTests(JobPostingAPITestCase):
    def test_list_requires_auth(self):
        response = self.client.get(self.list_url())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


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
        self.client.credentials(HTTP_IDEMPOTENCY_KEY="test-posting-key-0001")
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
        self.assertEqual(self.posting.conversions.get().application_id, application.id)

    def test_apply_falls_back_to_posting_company_and_title(self):
        response = self.client.post(self.detail_action_url(self.posting.id, "apply"), {})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        application = Application.objects.get(id=response.data["application_id"])
        self.assertEqual(application.company, "Acme Corp")
        self.assertEqual(application.role_label, "Software Engineer")

    def test_apply_same_key_replays_original(self):
        self.client.post(self.detail_action_url(self.posting.id, "apply"), {})
        response = self.client.post(self.detail_action_url(self.posting.id, "apply"), {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

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


class PostingOwnershipTests(JobPostingAPITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def test_terminal_conversion_cannot_be_bypassed_by_model_reparenting(self):
        from django.core.exceptions import ValidationError
        first = self.client.post(self.detail_action_url(self.posting.pk, "apply"), {},
                                 HTTP_IDEMPOTENCY_KEY="ownership-original-key")
        self.assertEqual(first.status_code, 201)
        Application.objects.get(pk=first.data["application_id"]).delete()
        conversion = self.posting.conversions.get()
        self.assertIsNone(conversion.application_id)
        portable_id = conversion.application_portable_id
        for fields in ({"workspace": self.other_workspace}, {"account": self.other_account},
                       {"workspace": self.other_workspace, "account": self.other_account}):
            for field, value in fields.items():
                setattr(self.posting, field, value)
            with self.assertRaises(ValidationError):
                self.posting.save()
            self.posting.refresh_from_db()
        self.assertEqual(self.posting.workspace_id, self.workspace.pk)
        self.assertEqual(self.posting.account_id, self.account.pk)
        conversion.refresh_from_db()
        self.assertEqual(conversion.workspace_id, self.workspace.pk)
        self.assertEqual(conversion.application_portable_id, portable_id)
        self.assertIsNone(conversion.application_id)
        # Even the destination owner cannot apply this posting in workspace B.
        self.client.force_authenticate(self.other_user)
        foreign = reverse("job-posting-apply", args=[self.other_workspace.pk, self.posting.pk])
        self.assertEqual(self.client.post(foreign, {}, HTTP_IDEMPOTENCY_KEY="ownership-new-key-b").status_code, 404)
        self.client.force_authenticate(self.user)
        warning = self.client.post(self.detail_action_url(self.posting.pk, "apply"), {},
                                   HTTP_IDEMPOTENCY_KEY="ownership-new-key-a")
        self.assertEqual(warning.status_code, 409)
        self.assertEqual(warning.data["code"], "new_attempt_confirmation_required")
        self.assertEqual(warning.data["prior_conversion_count"], 1)
        self.assertEqual(Application.objects.count(), 0)
        self.assertEqual(self.posting.conversions.count(), 1)

    def test_admin_keeps_ownership_on_forged_edit_and_allows_metadata(self):
        from django.contrib import admin
        from django.test import RequestFactory
        first = self.client.post(self.detail_action_url(self.posting.pk, "apply"), {},
                                 HTTP_IDEMPOTENCY_KEY="admin-original-key")
        self.assertEqual(first.status_code, 201)
        Application.objects.get(pk=first.data["application_id"]).delete()
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        request = RequestFactory().get("/admin/")
        request.user = self.user
        model_admin = admin.site._registry[JobPosting]
        add_form = model_admin.get_form(request)
        change_form = model_admin.get_form(request, obj=self.posting)
        for field in ("workspace", "account"):
            self.assertIn(field, add_form.base_fields)
            self.assertNotIn(field, change_form.base_fields)
        response = self.client.post(reverse("admin:postings_jobposting_change", args=[self.posting.pk]), {
            "message_id": self.posting.message_id, "status": "new", "title": "Edited title",
            "company": "Edited company", "saved": "on", "_save": "Save",
            "workspace": self.other_workspace.pk, "account": self.other_account.pk,
        })
        self.assertEqual(response.status_code, 302)
        self.posting.refresh_from_db()
        self.assertEqual(self.posting.title, "Edited title")
        self.assertTrue(self.posting.saved)
        self.assertEqual(self.posting.workspace_id, self.workspace.pk)
        self.assertEqual(self.posting.account_id, self.account.pk)

        conversion = self.posting.conversions.get()
        self.assertEqual(conversion.workspace_id, self.workspace.pk)
        self.assertIsNone(conversion.application_id)
        warning = self.client.post(self.detail_action_url(self.posting.pk, "apply"), {},
                                   HTTP_IDEMPOTENCY_KEY="admin-new-key-0001")
        self.assertEqual(warning.status_code, 409)
        self.assertEqual(warning.data["prior_conversion_count"], 1)
        self.assertEqual(Application.objects.count(), 0)

    def test_new_posting_establishes_ownership_but_existing_account_is_fixed(self):
        from django.core.exceptions import ValidationError
        new = JobPosting.objects.create(workspace=self.other_workspace, account=self.other_account,
                                        message_id="new", dedupe_key="new-owned-posting")
        new.title = "Metadata edit"
        new.save(update_fields=["title"])
        self.assertEqual(JobPosting.objects.get(pk=new.pk).title, "Metadata edit")
        same_workspace_account = EmailAccount.objects.create(workspace=self.workspace, email="second@example.com")
        self.posting.account = same_workspace_account
        with self.assertRaises(ValidationError):
            self.posting.save(update_fields=["account"])
        # Supplying an existing PK on a fresh instance must not evade the guard.
        with self.assertRaises(ValidationError):
            JobPosting(pk=new.pk, workspace=self.workspace, account=self.account,
                       message_id="replacement", dedupe_key="replacement").save()
