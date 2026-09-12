"""applications API tests.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md) -- exercises the DRF surface
in applications/views.py end-to-end (auth, ownership scoping, and
each of list/create/override/bulk-override/delete/bulk-delete), as
opposed to test_services.py's unit-level coverage of the underlying
field-diffing rules.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace
from applications.models import Application, Override, StatusHistory


class ApplicationsAPITestCase(APITestCase):
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


class ListApplicationsTests(ApplicationsAPITestCase):
    def test_requires_auth(self):
        response = self.client.get(reverse("application-list", args=[self.workspace.pk]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_lists_only_own_applications(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.get(reverse("application-list", args=[self.workspace.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data]
        self.assertIn(self.application.id, ids)
        self.assertNotIn(self.other_application.id, ids)

    def test_effective_status_falls_back_to_auto_status(self):
        self.application.status = "applied"
        self.application.save()
        self.client.login(username="alice", password="pw123456")
        response = self.client.get(reverse("application-list", args=[self.workspace.pk]))
        row = next(item for item in response.data if item["id"] == self.application.id)
        self.assertEqual(row["effective_status"], "applied")

    def test_effective_status_prefers_manual_override(self):
        self.application.status = "applied"
        self.application.save()
        Override.objects.create(application=self.application, manual_status="interviewing")
        self.client.login(username="alice", password="pw123456")
        response = self.client.get(reverse("application-list", args=[self.workspace.pk]))
        row = next(item for item in response.data if item["id"] == self.application.id)
        self.assertEqual(row["effective_status"], "interviewing")


class CreateApplicationTests(ApplicationsAPITestCase):
    def test_create_minimal(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-list", args=[self.workspace.pk]),
            {"company": "Globex", "role_label": "PM"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["company"], "Globex")

    def test_create_with_status_writes_override_and_history(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-list", args=[self.workspace.pk]),
            {"company": "Globex", "role_label": "PM", "status": "interviewing"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        app_id = response.data["id"]
        override = Override.objects.get(application_id=app_id)
        self.assertEqual(override.manual_status, "interviewing")
        self.assertTrue(StatusHistory.objects.filter(application_id=app_id, status="interviewing").exists())

    def test_create_with_invalid_status_is_rejected(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-list", args=[self.workspace.pk]),
            {"company": "Globex", "role_label": "PM", "status": "bogus"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_company_role_in_same_workspace_is_rejected(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-list", args=[self.workspace.pk]),
            {"company": "Acme Robotics", "role_label": "Backend Engineer"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_with_custom_section_becomes_a_category(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-list", args=[self.workspace.pk]),
            {"company": "AWS", "section": "credentials"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["section"], "credentials")

    def test_cannot_create_in_another_users_workspace(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-list", args=[self.workspace.pk]),
            {"workspace": self.other_workspace.id, "company": "Globex", "role_label": "PM"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class OverrideApplicationTests(ApplicationsAPITestCase):
    def test_sets_notes(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-override", args=[self.workspace.pk, self.application.id]), {"notes": "called back"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Override.objects.get(application=self.application).notes, "called back")

    def test_fields_not_sent_are_left_alone(self):
        Override.objects.create(application=self.application, notes="original")
        self.client.login(username="alice", password="pw123456")
        self.client.post(
            reverse("application-override", args=[self.workspace.pk, self.application.id]), {"next_action": "follow up"}
        )
        override = Override.objects.get(application=self.application)
        self.assertEqual(override.notes, "original")
        self.assertEqual(override.next_action, "follow up")

    def test_manual_status_logs_status_history(self):
        self.client.login(username="alice", password="pw123456")
        self.client.post(
            reverse("application-override", args=[self.workspace.pk, self.application.id]), {"manual_status": "interviewing"}
        )
        self.assertTrue(
            StatusHistory.objects.filter(application=self.application, status="interviewing").exists()
        )

    def test_reset_status_clears_manual_status_and_logs_auto_status(self):
        Override.objects.create(application=self.application, manual_status="interviewing")
        self.application.status = "applied"
        self.application.save()
        self.client.login(username="alice", password="pw123456")
        self.client.post(
            reverse("application-override", args=[self.workspace.pk, self.application.id]), {"reset_status": True}
        )
        override = Override.objects.get(application=self.application)
        self.assertIsNone(override.manual_status)
        self.assertTrue(
            StatusHistory.objects.filter(application=self.application, status="applied").exists()
        )

    def test_date_applied_without_source_clears_stale_provenance(self):
        Override.objects.create(
            application=self.application, date_applied="2026-01-01", date_applied_source="confirmation"
        )
        self.client.login(username="alice", password="pw123456")
        self.client.post(
            reverse("application-override", args=[self.workspace.pk, self.application.id]), {"date_applied": "2026-02-01"}
        )
        override = Override.objects.get(application=self.application)
        self.assertEqual(str(override.date_applied), "2026-02-01")
        self.assertIsNone(override.date_applied_source)

    def test_cannot_override_another_users_application(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-override", args=[self.workspace.pk, self.other_application.id]), {"notes": "x"}
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class BulkOverrideApplicationTests(ApplicationsAPITestCase):
    def test_bulk_archives_owned_applications(self):
        second = Application.objects.create(
            workspace=self.workspace, section="applications", company="Initech", role_label="QA", source_relpath="",
        )
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-bulk-override", args=[self.workspace.pk]),
            {"item_ids": [self.application.id, second.id], "archived": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertTrue(Override.objects.get(application=self.application).archived)
        self.assertTrue(Override.objects.get(application=second).archived)

    def test_notes_is_not_a_bulk_field(self):
        """notes isn't part of BulkOverrideWriteSerializer's field set,
        so DRF silently drops it rather than rejecting the request --
        it must never reach the Override row.
        """
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-bulk-override", args=[self.workspace.pk]),
            {"item_ids": [self.application.id], "notes": "should be ignored", "archived": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        override = Override.objects.get(application=self.application)
        self.assertTrue(override.archived)
        self.assertIsNone(override.notes)

    def test_rejects_ids_from_another_users_workspace(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-bulk-override", args=[self.workspace.pk]),
            {"item_ids": [self.application.id, self.other_application.id], "archived": True},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(Override.objects.exists())
        self.assertFalse(StatusHistory.objects.exists())
        self.assertFalse(hasattr(self.other_application, "override") and self.other_application.override.archived)


class DeleteApplicationTests(ApplicationsAPITestCase):
    def test_delete_removes_application(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(reverse("application-delete", args=[self.application.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Application.objects.filter(id=self.application.id).exists())

    def test_delete_works_without_archiving_first(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(reverse("application-delete", args=[self.application.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_cascades_override_and_status_history(self):
        Override.objects.create(application=self.application, notes="x")
        StatusHistory.objects.create(application=self.application, status="applied", changed_at="2026-01-01T00:00:00Z")
        self.client.login(username="alice", password="pw123456")
        self.client.post(reverse("application-delete", args=[self.application.id]))
        self.assertFalse(Override.objects.filter(application_id=self.application.id).exists())
        self.assertFalse(StatusHistory.objects.filter(application_id=self.application.id).exists())

    def test_cannot_delete_another_users_application(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(reverse("application-delete", args=[self.other_application.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class BulkDeleteApplicationTests(ApplicationsAPITestCase):
    def test_deletes_only_archived_applications(self):
        Override.objects.create(application=self.application, archived=True)
        second = Application.objects.create(
            workspace=self.workspace, section="applications", company="Initech", role_label="QA", source_relpath="",
        )
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-bulk-delete"), {"item_ids": [self.application.id, second.id]}
        )
        self.assertTrue(response.data["ok"] is False)
        self.assertEqual(response.data["deleted"], [self.application.id])
        self.assertFalse(Application.objects.filter(id=self.application.id).exists())
        self.assertTrue(Application.objects.filter(id=second.id).exists())

    def test_reports_not_found_for_missing_id(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-bulk-delete"), {"item_ids": [999999]}
        )
        self.assertEqual(response.data["deleted"], [])
        self.assertEqual(response.data["failed"][0]["id"], 999999)

    def test_cannot_bulk_delete_another_users_application(self):
        Override.objects.create(application=self.other_application, archived=True)
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-bulk-delete"), {"item_ids": [self.other_application.id]}
        )
        self.assertEqual(response.data["deleted"], [])
        self.assertTrue(Application.objects.filter(id=self.other_application.id).exists())
