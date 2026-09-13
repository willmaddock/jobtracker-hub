"""
accounts API tests (Phase 8, docs/DJANGO_MIGRATION_PLAN.md).

Auth coverage (login/logout/me) already lives in core/tests_api.py
since those are cross-cutting, framework-level concerns exercised
there alongside GET /api/health. This module covers the Workspace CRUD
surface: list/create/rename/delete, all ownership-scoped.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace


class WorkspaceAPITestCase(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.other_user = User.objects.create_user(username="bob", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.other_workspace = Workspace.objects.create(owner=self.other_user, name="Bob's workspace")
        self.client.force_authenticate(self.user)

    def detail_url(self, workspace_id):
        return reverse("workspace-detail", args=[workspace_id])

    def rename_url(self, workspace_id):
        return reverse("workspace-rename", args=[workspace_id])


class ListWorkspacesTests(WorkspaceAPITestCase):
    def test_lists_only_own_workspaces(self):
        response = self.client.get(reverse("workspace-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [w["name"] for w in response.data]
        self.assertIn("Alice's workspace", names)
        self.assertNotIn("Bob's workspace", names)

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        response = self.client.get(reverse("workspace-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class CreateWorkspaceTests(WorkspaceAPITestCase):
    def test_create_assigns_current_user_as_owner(self):
        response = self.client.post(reverse("workspace-list"), {"name": "New tracker"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        workspace = Workspace.objects.get(id=response.data["id"])
        self.assertEqual(workspace.owner, self.user)
        self.assertEqual(workspace.name, "New tracker")

    def test_blank_name_is_rejected(self):
        response = self.client.post(reverse("workspace-list"), {"name": "   "})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_owner_cannot_be_set_by_client(self):
        # owner isn't even a field on WorkspaceWriteSerializer -- extra
        # keys are just ignored, not an error, matching DRF's default
        # serializer behavior for unknown input fields.
        response = self.client.post(
            reverse("workspace-list"), {"name": "New tracker", "owner": self.other_user.id},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        workspace = Workspace.objects.get(id=response.data["id"])
        self.assertEqual(workspace.owner, self.user)


class RenameWorkspaceTests(WorkspaceAPITestCase):
    def test_rename_updates_name(self):
        response = self.client.post(self.rename_url(self.workspace.id), {"name": "Renamed"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.name, "Renamed")

    def test_cannot_rename_another_users_workspace(self):
        response = self.client.post(self.rename_url(self.other_workspace.id), {"name": "Hijacked"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.other_workspace.refresh_from_db()
        self.assertEqual(self.other_workspace.name, "Bob's workspace")


class DeleteWorkspaceTests(WorkspaceAPITestCase):
    def test_delete_removes_workspace(self):
        response = self.client.delete(self.detail_url(self.workspace.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Workspace.objects.filter(id=self.workspace.id).exists())

    def test_cannot_delete_another_users_workspace(self):
        response = self.client.delete(self.detail_url(self.other_workspace.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Workspace.objects.filter(id=self.other_workspace.id).exists())

    def test_deleting_workspace_cascades_to_job_postings(self):
        from email_sync.models import EmailAccount
        from postings.models import JobPosting

        account = EmailAccount.objects.create(workspace=self.workspace, email="alice@example.com")
        posting = JobPosting.objects.create(
            workspace=self.workspace, account=account, message_id="msg-1", dedupe_key="key-1",
        )
        self.client.delete(self.detail_url(self.workspace.id))
        self.assertFalse(JobPosting.objects.filter(id=posting.id).exists())
