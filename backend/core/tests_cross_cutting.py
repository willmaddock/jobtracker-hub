"""
core cross-cutting views API tests.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md) -- API-level coverage for
attention/insights/search/browse/manage(+merge/unmerge)/hub-settings,
kept separate from core/tests_services.py's unit tests the same way
core/tests_api.py (auth/health) is kept separate from core/tests.py
(the Phase 7 admin smoke tests).
"""
from __future__ import annotations

import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace
from applications.models import Application, CompanyAlias, Override
from documents.models import Document, FolderOverride

from .models import HubSettings
from .services import STALE_APPLIED_DAYS


def _make_app(workspace, **kwargs):
    defaults = {
        "section": "applications",
        "company": "Acme",
        "role_label": "SWE",
        "source_relpath": "",
    }
    defaults.update(kwargs)
    return Application.objects.create(workspace=workspace, **defaults)


class CrossCuttingAPITestCase(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.other_user = User.objects.create_user(username="bob", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.other_workspace = Workspace.objects.create(owner=self.other_user, name="Bob's workspace")
        self.client.login(username="alice", password="pw123456")


class AttentionTests(CrossCuttingAPITestCase):
    def test_returns_stale_application(self):
        stale = timezone.now() - timedelta(days=STALE_APPLIED_DAYS + 1)
        _make_app(self.workspace, status="applied", company="Stale Co", last_activity=stale)
        response = self.client.get(reverse("attention", args=[self.workspace.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        companies = [row["company"] for row in response.data]
        self.assertIn("Stale Co", companies)

    def test_fresh_application_is_excluded(self):
        _make_app(self.workspace, status="applied", company="Fresh Co", last_activity=timezone.now())
        response = self.client.get(reverse("attention", args=[self.workspace.pk]))
        companies = [row["company"] for row in response.data]
        self.assertNotIn("Fresh Co", companies)

    def test_never_returns_other_users_applications(self):
        stale = timezone.now() - timedelta(days=STALE_APPLIED_DAYS + 1)
        _make_app(self.other_workspace, status="applied", company="Bob Co", last_activity=stale)
        response = self.client.get(reverse("attention", args=[self.workspace.pk]))
        companies = [row["company"] for row in response.data]
        self.assertNotIn("Bob Co", companies)

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.get(reverse("attention", args=[self.workspace.pk]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class InsightsTests(CrossCuttingAPITestCase):
    def test_reflects_only_own_applications(self):
        _make_app(self.workspace, status="applied", company="A")
        _make_app(self.other_workspace, status="applied", company="Bob's")
        response = self.client.get(reverse("insights", args=[self.workspace.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 1)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SearchTests(CrossCuttingAPITestCase):
    def test_empty_query_returns_empty_list(self):
        response = self.client.get(reverse("search", args=[self.workspace.pk]))
        self.assertEqual(response.data, [])

    def test_matches_by_filename(self):
        application = _make_app(self.workspace, company="Acme")
        Document.objects.create(
            workspace=self.workspace, application=application, file=SimpleUploadedFile("r.pdf", b"x"),
            filename="resume_v2.pdf", doc_type="resume", ext=".pdf",
            content_hash="h1", size=1,
        )
        response = self.client.get(reverse("search", args=[self.workspace.pk]), {"q": "resume"})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["filename"], "resume_v2.pdf")

    def test_matches_by_company(self):
        application = _make_app(self.workspace, company="Globex Corp")
        Document.objects.create(
            workspace=self.workspace, application=application, file=SimpleUploadedFile("r.pdf", b"x"),
            filename="notes.txt", doc_type="other", ext=".txt", content_hash="h2", size=1,
        )
        response = self.client.get(reverse("search", args=[self.workspace.pk]), {"q": "globex"})
        self.assertEqual(len(response.data), 1)

    def test_excludes_personal_section_by_default(self):
        application = _make_app(self.workspace, section="personal", company="Me")
        Document.objects.create(
            workspace=self.workspace, application=application, file=SimpleUploadedFile("r.pdf", b"x"),
            filename="passport.pdf", doc_type="other", ext=".pdf", content_hash="h3", size=1,
        )
        response = self.client.get(reverse("search", args=[self.workspace.pk]), {"q": "passport"})
        self.assertEqual(response.data, [])
        response = self.client.get(reverse("search", args=[self.workspace.pk]), {"q": "passport", "show_personal": "true"})
        self.assertEqual(len(response.data), 1)

    def test_excludes_archived_category(self):
        application = _make_app(self.workspace, section="credentials", company="AWS")
        Document.objects.create(
            workspace=self.workspace, application=application, file=SimpleUploadedFile("c.pdf", b"x"),
            filename="certificate.pdf", doc_type="certificate", ext=".pdf",
            content_hash="h4", size=1,
        )
        FolderOverride.objects.create(
            workspace=self.workspace, folder="credentials", section="credentials", archived=True,
        )
        response = self.client.get(reverse("search", args=[self.workspace.pk]), {"q": "certificate"})
        self.assertEqual(response.data, [])

    def test_never_returns_other_users_documents(self):
        application = _make_app(self.other_workspace, company="Bob Inc")
        Document.objects.create(
            workspace=self.other_workspace, application=application, file=SimpleUploadedFile("r.pdf", b"x"),
            filename="bob_resume.pdf", doc_type="resume", ext=".pdf", content_hash="h5", size=1,
        )
        response = self.client.get(reverse("search", args=[self.workspace.pk]), {"q": "bob_resume"})
        self.assertEqual(response.data, [])


class BrowseTests(CrossCuttingAPITestCase):
    def test_groups_by_section(self):
        _make_app(self.workspace, section="applications", company="Acme")
        _make_app(self.workspace, section="credentials", company="AWS")
        response = self.client.get(reverse("browse", args=[self.workspace.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("applications", response.data)
        self.assertIn("credentials", response.data)

    def test_excludes_personal_by_default(self):
        _make_app(self.workspace, section="personal", company="Me")
        response = self.client.get(reverse("browse", args=[self.workspace.pk]))
        self.assertNotIn("personal", response.data)
        response = self.client.get(reverse("browse", args=[self.workspace.pk]), {"show_personal": "true"})
        self.assertIn("personal", response.data)

    def test_excludes_archived_applications_by_default(self):
        application = _make_app(self.workspace, company="Archived Co")
        Override.objects.create(application=application, archived=True)
        response = self.client.get(reverse("browse", args=[self.workspace.pk]))
        companies = [row["company"] for row in response.data.get("applications", [])]
        self.assertNotIn("Archived Co", companies)
        response = self.client.get(reverse("browse", args=[self.workspace.pk]), {"show_archived": "true"})
        companies = [row["company"] for row in response.data.get("applications", [])]
        self.assertIn("Archived Co", companies)

    def test_excludes_archived_category_by_default(self):
        _make_app(self.workspace, section="network", company="Jane Doe")
        FolderOverride.objects.create(
            workspace=self.workspace, folder="network", section="network", archived=True,
        )
        response = self.client.get(reverse("browse", args=[self.workspace.pk]))
        self.assertNotIn("network", response.data)
        response = self.client.get(reverse("browse", args=[self.workspace.pk]), {"show_archived": "true"})
        self.assertIn("network", response.data)

    def test_query_filters_by_label(self):
        _make_app(self.workspace, company="Acme", role_label="SWE")
        _make_app(self.workspace, company="Globex", role_label="PM")
        response = self.client.get(reverse("browse", args=[self.workspace.pk]), {"q": "acme"})
        companies = [row["company"] for row in response.data.get("applications", [])]
        self.assertEqual(companies, ["Acme"])

    def test_never_returns_other_users_applications(self):
        _make_app(self.other_workspace, company="Bob Co")
        response = self.client.get(reverse("browse", args=[self.workspace.pk]))
        companies = [row["company"] for row in response.data.get("applications", [])]
        self.assertNotIn("Bob Co", companies)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ManageTests(CrossCuttingAPITestCase):
    def test_unaliased_duplicate_names_are_suggested(self):
        _make_app(self.workspace, company="Bet365")
        _make_app(self.workspace, company="BET 365")
        response = self.client.get(reverse("manage", args=[self.workspace.pk]))
        self.assertIn("bet365", response.data["duplicate_suggestions"])

    def test_already_aliased_names_are_not_suggested(self):
        _make_app(self.workspace, company="Bet365")
        _make_app(self.workspace, company="BET 365")
        CompanyAlias.objects.create(workspace=self.workspace, alias="BET 365", canonical="Bet365")
        response = self.client.get(reverse("manage", args=[self.workspace.pk]))
        self.assertNotIn("bet365", response.data["duplicate_suggestions"])

    def test_archived_applications_are_listed(self):
        application = _make_app(self.workspace, company="Archived Co")
        Override.objects.create(application=application, archived=True)
        response = self.client.get(reverse("manage", args=[self.workspace.pk]))
        companies = [row["company"] for row in response.data["archived"]]
        self.assertIn("Archived Co", companies)

    def test_duplicate_documents_are_grouped(self):
        application = _make_app(self.workspace, company="Acme")
        Document.objects.create(
            workspace=self.workspace, application=application, file=SimpleUploadedFile("a.pdf", b"x"),
            filename="resume.pdf", doc_type="resume", ext=".pdf", content_hash="dupe", size=1,
        )
        Document.objects.create(
            workspace=self.workspace, application=application, file=SimpleUploadedFile("b.pdf", b"x"),
            filename="resume-copy.pdf", doc_type="resume", ext=".pdf", content_hash="dupe", size=1,
        )
        response = self.client.get(reverse("manage", args=[self.workspace.pk]))
        self.assertEqual(len(response.data["duplicate_documents"]), 1)


class MergeUnmergeTests(CrossCuttingAPITestCase):
    def test_merge_creates_aliases_for_every_name_except_canonical(self):
        response = self.client.post(reverse("manage-merge", args=[self.workspace.pk]), {
            "names": ["Bet365", "BET 365"], "canonical": "Bet365",
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            CompanyAlias.objects.get(workspace=self.workspace, alias="BET 365").canonical, "Bet365",
        )
        self.assertFalse(CompanyAlias.objects.filter(workspace=self.workspace, alias="Bet365").exists())

    def test_merge_rejects_workspace_not_owned(self):
        response = self.client.post(reverse("manage-merge", args=[self.workspace.pk]), {
            "names": ["A", "B"], "canonical": "A", "workspace": self.other_workspace.id,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unmerge_removes_alias(self):
        CompanyAlias.objects.create(workspace=self.workspace, alias="BET 365", canonical="Bet365")
        response = self.client.post(reverse("manage-unmerge", args=[self.workspace.pk]), {
            "alias": "BET 365",
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(CompanyAlias.objects.filter(workspace=self.workspace, alias="BET 365").exists())


class HubSettingsTests(CrossCuttingAPITestCase):
    def test_get_creates_default_settings(self):
        response = self.client.get(reverse("hub-settings", args=[self.workspace.pk]), {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["role"], "")
        self.assertTrue(HubSettings.objects.filter(workspace=self.workspace).exists())

    def test_post_partial_update_merges(self):
        self.client.post(
            reverse("hub-settings", args=[self.workspace.pk]), {"role": "Engineer"},
        )
        response = self.client.post(
            reverse("hub-settings", args=[self.workspace.pk]), {"location": "Remote"},
        )
        self.assertEqual(response.data["role"], "Engineer")
        self.assertEqual(response.data["location"], "Remote")

    def test_requires_workspace_owned_by_caller(self):
        response = self.client.get(reverse("hub-settings", args=[self.workspace.pk]), {"workspace": self.other_workspace.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
