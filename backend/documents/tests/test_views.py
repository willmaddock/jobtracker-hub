import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace
from applications.models import Application

from ..models import Document, DocumentOverride


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DocumentAPITestCase(APITestCase):
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

        self.document = Document.objects.create(
            workspace=self.workspace, application=self.application,
            file=SimpleUploadedFile("resume.pdf", b"fake pdf bytes"),
            filename="resume.pdf", doc_type="resume", ext=".pdf",
            content_hash="hash-a", size=14,
        )
        self.other_document = Document.objects.create(
            workspace=self.other_workspace, application=self.other_application,
            file=SimpleUploadedFile("resume.pdf", b"fake pdf bytes"),
            filename="resume.pdf", doc_type="resume", ext=".pdf",
            content_hash="hash-b", size=14,
        )


class RenameDocumentTests(DocumentAPITestCase):
    def test_renames_and_reclassifies(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("document-rename", args=[self.workspace.pk, self.document.id]),
            {"new_filename": "cover-letter.pdf"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.document.refresh_from_db()
        self.assertEqual(self.document.filename, "cover-letter.pdf")
        self.assertEqual(self.document.doc_type, "cover_letter")

    def test_unchanged_name_is_a_noop(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("document-rename", args=[self.workspace.pk, self.document.id]),
            {"new_filename": "resume.pdf"},
        )
        self.assertTrue(response.data["unchanged"])

    def test_rejects_path_separators(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("document-rename", args=[self.workspace.pk, self.document.id]),
            {"new_filename": "sub/resume.pdf"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_rename_another_users_document(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("document-rename", args=[self.workspace.pk, self.other_document.id]),
            {"new_filename": "x.pdf"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class OverrideDocumentTests(DocumentAPITestCase):
    def test_sets_doc_type_override(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("document-override", args=[self.workspace.pk, self.document.id]),
            {"doc_type_override": "cover_letter"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            DocumentOverride.objects.get(document=self.document).doc_type_override, "cover_letter"
        )
        self.assertEqual(response.data["effective_doc_type"], "cover_letter")

    def test_blank_clears_override(self):
        DocumentOverride.objects.create(document=self.document, doc_type_override="cover_letter")
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("document-override", args=[self.workspace.pk, self.document.id]), {"doc_type_override": ""}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(DocumentOverride.objects.filter(document=self.document).exists())

    def test_cannot_override_another_users_document(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("document-override", args=[self.workspace.pk, self.other_document.id]),
            {"doc_type_override": "resume"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class DeleteDocumentTests(DocumentAPITestCase):
    def test_deletes_document_and_file(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(reverse("document-delete", args=[self.document.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Document.objects.filter(id=self.document.id).exists())

    def test_cannot_delete_another_users_document(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(reverse("document-delete", args=[self.other_document.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Document.objects.filter(id=self.other_document.id).exists())
