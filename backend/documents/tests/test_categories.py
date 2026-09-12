from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace
from applications.models import Application

from ..models import FolderOverride


class CategoryAPITestCase(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.other_user = User.objects.create_user(username="bob", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.other_workspace = Workspace.objects.create(owner=self.other_user, name="Bob's workspace")

        Application.objects.create(
            workspace=self.workspace, section="applications", company="Acme", role_label="SWE", source_relpath="",
        )
        self.cert = Application.objects.create(
            workspace=self.workspace, section="credentials", company="AWS", role_label="", source_relpath="",
        )
        self.contact = Application.objects.create(
            workspace=self.workspace, section="network", company="Jane Doe", role_label="", source_relpath="",
        )
        Application.objects.create(
            workspace=self.other_workspace, section="credentials", company="GCP", role_label="", source_relpath="",
        )


class ListCategoriesTests(CategoryAPITestCase):
    def test_excludes_applications_section(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.get(reverse("category-list", args=[self.workspace.pk]))
        sections = [row["section"] for row in response.data]
        self.assertNotIn("applications", sections)
        self.assertIn("credentials", sections)
        self.assertIn("network", sections)

    def test_only_shows_own_workspace_categories(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.get(reverse("category-list", args=[self.workspace.pk]))
        # Bob's "credentials" category has its own row too, but alice's
        # request should never reflect Bob's counts.
        credentials_row = next(row for row in response.data if row["section"] == "credentials")
        self.assertEqual(credentials_row["item_count"], 1)


class CategoryOverrideTests(CategoryAPITestCase):
    def test_archives_a_category(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("category-override", args=[self.workspace.pk, "credentials"]),
            {"archived": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            FolderOverride.objects.get(workspace=self.workspace, folder="credentials").archived
        )

    def test_404_for_empty_category(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("category-override", args=[self.workspace.pk, "misc"]),
            {"archived": True},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_rejects_workspace_not_owned(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("category-override", args=[self.workspace.pk, "credentials"]),
            {"workspace": self.other_workspace.id, "archived": True},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CategoryDeleteTests(CategoryAPITestCase):
    def test_requires_archived_first(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("category-delete", args=["credentials"]), {"workspace": self.workspace.id}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Application.objects.filter(id=self.cert.id).exists())

    def test_deletes_all_items_in_an_archived_category(self):
        FolderOverride.objects.create(
            workspace=self.workspace, folder="network", section="network", archived=True
        )
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("category-delete", args=["network"]), {"workspace": self.workspace.id}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["deleted_count"], 1)
        self.assertFalse(Application.objects.filter(id=self.contact.id).exists())
        self.assertFalse(FolderOverride.objects.filter(workspace=self.workspace, folder="network").exists())
