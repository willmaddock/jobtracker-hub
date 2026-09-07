from django.test import SimpleTestCase

from ..services import classify_doc_type


class ClassifyDocTypeTests(SimpleTestCase):
    def test_resume(self):
        self.assertEqual(classify_doc_type("John_Smith_Resume.pdf"), "resume")

    def test_cover_letter(self):
        self.assertEqual(classify_doc_type("cover-letter-acme.docx"), "cover_letter")

    def test_rejection_notice(self):
        self.assertEqual(classify_doc_type("Application Rejected.pdf"), "rejection_notice")

    def test_interview_notice_beats_generic_naming(self):
        self.assertEqual(classify_doc_type("Interview Schedule.pdf"), "interview_notice")

    def test_application_confirmation(self):
        self.assertEqual(classify_doc_type("Thank you for applying.eml"), "application_confirmation")

    def test_job_posting(self):
        self.assertEqual(classify_doc_type("Job Description - SRE.pdf"), "job_posting")

    def test_certificate(self):
        self.assertEqual(classify_doc_type("Coursera Certificate.pdf"), "certificate")

    def test_readme_only_matches_at_start(self):
        self.assertEqual(classify_doc_type("README.txt"), "readme")
        self.assertNotEqual(classify_doc_type("not-a-readme.txt"), "readme")

    def test_unrecognized_filename_is_other(self):
        self.assertEqual(classify_doc_type("misc-file-xyz.pdf"), "other")
