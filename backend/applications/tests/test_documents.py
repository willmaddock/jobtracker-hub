import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace
from documents.models import Document

from ..models import Application


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ApplicationDocumentsAPITestCase(APITestCase):
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


class ListApplicationDocumentsTests(ApplicationDocumentsAPITestCase):
    def test_lists_documents_for_the_application(self):
        Document.objects.create(
            workspace=self.workspace, application=self.application,
            file=SimpleUploadedFile("resume.pdf", b"abc"),
            filename="resume.pdf", doc_type="resume", ext=".pdf", content_hash="h1", size=3,
        )
        self.client.login(username="alice", password="pw123456")
        response = self.client.get(reverse("application-documents", args=[self.workspace.pk, self.application.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["filename"], "resume.pdf")

    def test_cannot_list_another_users_application_documents(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.get(reverse("application-documents", args=[self.workspace.pk, self.other_application.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class UploadApplicationDocumentsTests(ApplicationDocumentsAPITestCase):
    def test_uploads_and_classifies(self):
        self.client.login(username="alice", password="pw123456")
        upload = SimpleUploadedFile("Cover Letter.pdf", b"cover letter bytes")
        response = self.client.post(
            reverse("application-documents", args=[self.workspace.pk, self.application.id]),
            {"files": [upload]},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["documents"]), 1)
        doc = Document.objects.get(application=self.application)
        self.assertEqual(doc.doc_type, "cover_letter")
        self.assertEqual(doc.workspace_id, self.workspace.id)

    def test_uploads_multiple_files(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-documents", args=[self.workspace.pk, self.application.id]),
            {
                "files": [
                    SimpleUploadedFile("resume.pdf", b"resume bytes"),
                    SimpleUploadedFile("cover-letter.pdf", b"cover bytes"),
                ]
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Document.objects.filter(application=self.application).count(), 2)

    def test_cannot_upload_to_another_users_application(self):
        self.client.login(username="alice", password="pw123456")
        response = self.client.post(
            reverse("application-documents", args=[self.workspace.pk, self.other_application.id]),
            {"files": [SimpleUploadedFile("resume.pdf", b"x")]},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
