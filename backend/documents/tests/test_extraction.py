import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import Workspace
from applications.models import Application

from ..extraction import (
    EXTRACTOR_VERSION,
    extract_contacts,
    extract_document,
    extract_emails,
    extract_phones,
    extract_text_from_document,
    extract_urls,
    get_or_extract,
)
from ..models import Document, DocumentExtraction

User = get_user_model()

_JOB_POSTING_TXT = """Job Description
We build widgets for a living.

Responsibilities
Write code. Review code.

Qualifications
5+ years experience. contact us at jobs@acme.example or (303) 555-1234.
See more at https://acme.example/careers.

Preferred Qualifications
A CS degree is nice to have.
"""

_CONFIRMATION_TXT = """From: no-reply@us.greenhouse-mail.io
Subject: Thank you for applying to Extend
Date: July 10, 2025 at 10:56 AM
To: candidate@example.com

Thanks for applying!
"""


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DocumentExtractionTestCase(TestCase):
    def setUp(self):
        owner = User.objects.create_user(username="alice", password="x")
        self.workspace = Workspace.objects.create(owner=owner, name="Alice's tracker")
        self.application = Application.objects.create(
            workspace=self.workspace, section="applications",
            company="Acme", role_label="Backend Engineer", source_relpath="",
        )

    def _make_document(self, filename: str, content: bytes, content_hash: str, ext: str = ".txt") -> Document:
        return Document.objects.create(
            workspace=self.workspace,
            application=self.application,
            file=SimpleUploadedFile(filename, content),
            filename=filename,
            doc_type="job_posting",
            ext=ext,
            content_hash=content_hash,
            size=len(content),
        )


class TextExtractionTests(DocumentExtractionTestCase):
    def test_reads_txt_file_content(self):
        document = self._make_document("posting.txt", _JOB_POSTING_TXT.encode("utf-8"), "hash1")
        text, ok, error = extract_text_from_document(document)
        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertIn("Responsibilities", text)

    def test_unsupported_extension_reports_error_not_exception(self):
        document = self._make_document("resume.docx", b"whatever", "hash2", ext=".docx")
        text, ok, error = extract_text_from_document(document)
        self.assertFalse(ok)
        self.assertEqual(text, "")
        self.assertIn("Unsupported file type", error)

    def test_unparseable_pdf_reports_error_not_exception(self):
        document = self._make_document("resume.pdf", b"not a real pdf", "hash3", ext=".pdf")
        text, ok, error = extract_text_from_document(document)
        self.assertFalse(ok)
        self.assertIsNotNone(error)


class ContactExtractionTests(TestCase):
    def test_extract_emails_dedupes_case_insensitively(self):
        text = "Reach me at Jane@Acme.example or jane@acme.example."
        self.assertEqual(extract_emails(text), ["Jane@Acme.example"])

    def test_extract_phones_dedupes_on_digits(self):
        text = "Call (303) 555-1234 or 303-555-1234."
        self.assertEqual(extract_phones(text), ["(303) 555-1234"])

    def test_extract_urls(self):
        text = "See https://acme.example/careers for details."
        self.assertEqual(extract_urls(text), ["https://acme.example/careers"])

    def test_extract_contacts_shape(self):
        result = extract_contacts("jane@acme.example, (303) 555-1234, https://acme.example")
        self.assertEqual(set(result.keys()), {"emails", "phones", "urls"})


class ExtractDocumentTests(DocumentExtractionTestCase):
    def test_full_extraction_over_job_posting_text(self):
        document = self._make_document("posting.txt", _JOB_POSTING_TXT.encode("utf-8"), "hash4")
        result = extract_document(document)
        self.assertTrue(result["extraction_ok"])
        self.assertEqual(result["emails"], ["jobs@acme.example"])
        self.assertIn("(303) 555-1234", result["phones"])
        self.assertIn("https://acme.example/careers", result["urls"])
        self.assertIn("Write code", result["duties"])
        self.assertIn("A CS degree", result["preferred_qualifications"])

    def test_detects_application_date_from_confirmation_email(self):
        document = self._make_document(
            "confirmation.txt", _CONFIRMATION_TXT.encode("utf-8"), "hash5"
        )
        result = extract_document(document)
        self.assertEqual(result["detected_date_applied"], "2025-07-10")

    def test_failed_extraction_returns_well_formed_dict(self):
        document = self._make_document("resume.docx", b"x", "hash6", ext=".docx")
        result = extract_document(document)
        self.assertFalse(result["extraction_ok"])
        self.assertEqual(result["emails"], [])
        self.assertEqual(result["role_summary"], "Not detected")


class GetOrExtractCachingTests(DocumentExtractionTestCase):
    def test_caches_result_keyed_by_content_hash(self):
        document = self._make_document("posting.txt", _JOB_POSTING_TXT.encode("utf-8"), "shared-hash")
        get_or_extract(document)
        self.assertEqual(
            DocumentExtraction.objects.filter(
                workspace=self.workspace, content_hash="shared-hash"
            ).count(),
            1,
        )
        cached = DocumentExtraction.objects.get(workspace=self.workspace, content_hash="shared-hash")
        self.assertEqual(cached.extractor_version, EXTRACTOR_VERSION)

    def test_second_document_same_content_hash_hits_cache_not_reextracted(self):
        doc_a = self._make_document("posting.txt", _JOB_POSTING_TXT.encode("utf-8"), "dup-hash")
        get_or_extract(doc_a)
        # A different Document row, same workspace, same content_hash --
        # simulating the same file uploaded under a second application.
        doc_b = self._make_document("posting-copy.txt", b"different bytes entirely", "dup-hash")
        result = get_or_extract(doc_b)
        # Cache hit means doc_b's own (different) bytes were never read --
        # the cached job-posting extraction from doc_a comes back instead.
        self.assertIn("Write code", result["duties"])
        self.assertEqual(
            DocumentExtraction.objects.filter(workspace=self.workspace, content_hash="dup-hash").count(),
            1,
        )

    def test_force_bypasses_cache(self):
        document = self._make_document("posting.txt", _JOB_POSTING_TXT.encode("utf-8"), "force-hash")
        get_or_extract(document)
        result = get_or_extract(document, force=True)
        self.assertTrue(result["extraction_ok"])

    def test_no_content_hash_never_cached(self):
        document = self._make_document("posting.txt", _JOB_POSTING_TXT.encode("utf-8"), "")
        get_or_extract(document)
        self.assertEqual(
            DocumentExtraction.objects.filter(workspace=self.workspace).count(), 0
        )
