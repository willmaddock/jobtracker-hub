import uuid
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.contrib.admin.sites import site
from rest_framework.test import APIClient
from accounts.models import User, Workspace
from applications.models import Application, Override, StatusHistory, CompanyAlias
from documents.models import Document
from django.utils import timezone


class IdentityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="identity")
        self.ws = Workspace.objects.create(owner=self.user, name="A")
        self.fields = dict(workspace=self.ws, company="Same", role_label="Role", section="applications", source_relpath="legacy/path")
        self.a = Application.objects.create(**self.fields)
        self.b = Application.objects.create(**self.fields)

    def test_uuid_scope_and_immutability(self):
        self.assertNotEqual(self.a.portable_id, self.b.portable_id)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Application.objects.create(**self.fields, portable_id=self.a.portable_id)
        other = Workspace.objects.create(owner=self.user, name="B")
        restored = Application.objects.create(**{**self.fields, "workspace": other}, portable_id=self.a.portable_id)
        self.assertEqual(restored.portable_id, self.a.portable_id)
        self.a.portable_id = uuid.uuid4()
        with self.assertRaises(ValidationError):
            self.a.save()
        with self.assertRaises(ValidationError):
            Application(pk=self.a.pk, **self.fields).save()
        self.a.refresh_from_db()
        self.a.company = "Rename"
        self.a.save()
        original = self.a.portable_id
        self.a.refresh_from_db()
        self.assertEqual(self.a.portable_id, original)

    def test_admin_cannot_allocate_or_edit_identity(self):
        admin = site._registry[Application]
        self.assertFalse(admin.has_add_permission(None))
        self.assertIn("portable_id", admin.readonly_fields)
        self.assertIn("workspace", admin.readonly_fields)

    def test_attempt_children_and_reads_stay_separate_and_aliases_do_not_merge(self):
        client = APIClient()
        client.force_authenticate(self.user)
        for app, text in ((self.a, "one"), (self.b, "two")):
            Override.objects.create(application=app, notes=text)
            StatusHistory.objects.create(application=app, status=text, changed_at=timezone.now())
            # Metadata-only fixture; no storage writes or extraction required.
            Document.objects.create(application=app, workspace=self.ws, filename=text+".txt",
                file="fixture/"+text, content_hash="same-bytes", size=1, ext=".txt")
        for app, text in ((self.a, "one"), (self.b, "two")):
            rows = client.get(f"/api/workspaces/{self.ws.pk}/applications/{app.pk}/documents/").data
            self.assertEqual([row["filename"] for row in rows], [text+".txt"])
            with patch("applications.views.assemble_dossier", side_effect=lambda docs: {"fixture_document_ids": [d.pk for d in docs]}):
                dossier = client.get(f"/api/workspaces/{self.ws.pk}/applications/{app.pk}/dossier/")
            self.assertEqual(dossier.status_code, 200)
            self.assertEqual(dossier.data["fixture_document_ids"], list(app.documents.values_list("pk", flat=True)))
            self.assertEqual(app.override.notes, text)
            self.assertEqual(list(app.status_history.values_list("status", flat=True)), [text])
        CompanyAlias.objects.create(workspace=self.ws, alias="Same", canonical="Canonical")
        CompanyAlias.objects.all().delete()
        self.assertEqual(Application.objects.count(), 2)
        self.a.delete()
        self.assertEqual(self.b.documents.count(), 1)
        self.assertEqual(self.b.status_history.count(), 1)
        self.assertEqual(self.b.override.notes, "two")

    def test_identical_attempts_are_ambiguous_email_candidates(self):
        from email_sync.tests.test_sync_service import FakeProvider, FetchedMessage
        from email_sync.sync_service import sync_account
        from email_sync.models import EmailAccount, Discovery
        account = EmailAccount.objects.create(workspace=self.ws, email="fixture@example.test", provider="gmail")
        message = FetchedMessage(message_id="fixture", subject="Update from Same", sender="fixture@example.test", body="Your application at Same for Role")
        sync_account(account, FakeProvider([message]))
        discovery = Discovery.objects.get(account=account, message_id="fixture")
        self.assertEqual(discovery.match_kind, "ambiguous")
        self.assertCountEqual(discovery.candidate_applications.all(), [self.a, self.b])

    def test_override_apis_reject_identity_assignment(self):
        client = APIClient()
        client.force_authenticate(self.user)
        for suffix, body in ((f"{self.a.pk}/override/", {}), ("bulk-override/", {"item_ids": [self.a.pk]})):
            for field in ("portable_id", "source_relpath", "id"):
                response = client.post(f"/api/workspaces/{self.ws.pk}/applications/{suffix}",
                    {**body, field: "untrusted", "notes": "must not write"}, format="json")
                self.assertEqual(response.status_code, 400)
        self.assertFalse(Override.objects.exists())
