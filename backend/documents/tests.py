import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import TestCase, override_settings

from accounts.models import Workspace
from applications.models import Application
from .models import Document
from .services import get_owned_document

User = get_user_model()


# Files written here are throwaway test fixtures, not real dev
# uploads -- redirect MEDIA_ROOT so Document.file writes here instead
# of dev.py's backend/media/. tmp dir isn't cleaned up afterwards,
# same as any other pytest/manage.py test run's tmp artifacts.
@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class GetOwnedDocumentTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user(username="alice", password="x")
        other_owner = User.objects.create_user(username="mallory", password="x")
        self.workspace = Workspace.objects.create(owner=owner, name="Alice's tracker")
        other_workspace = Workspace.objects.create(owner=other_owner, name="Mallory's tracker")

        application = Application.objects.create(
            workspace=self.workspace,
            section="applications",
            company="Acme",
            role_label="Backend Engineer",
            source_relpath="Applications/Acme/Backend Engineer",
        )
        other_application = Application.objects.create(
            workspace=other_workspace,
            section="applications",
            company="Globex",
            role_label="SRE",
            source_relpath="Applications/Globex/SRE",
        )

        upload = SimpleUploadedFile("resume.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        self.document = Document.objects.create(
            workspace=self.workspace,
            application=application,
            file=upload,
            filename="resume.pdf",
            doc_type="resume",
            ext=".pdf",
            content_hash="abc123",
            size=13,
        )
        other_upload = SimpleUploadedFile("resume.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        self.other_workspace = other_workspace
        self.other_document = Document.objects.create(
            workspace=other_workspace,
            application=other_application,
            file=other_upload,
            filename="resume.pdf",
            doc_type="resume",
            ext=".pdf",
            content_hash="def456",
            size=13,
        )

    def test_owner_can_fetch_their_document(self):
        fetched = get_owned_document(self.workspace, self.document.id)
        self.assertEqual(fetched.id, self.document.id)

    def test_wrong_workspace_gets_404_not_someone_elses_document(self):
        with self.assertRaises(Http404):
            get_owned_document(self.workspace, self.other_document.id)

    def test_nonexistent_id_gets_404(self):
        with self.assertRaises(Http404):
            get_owned_document(self.workspace, 999999)
