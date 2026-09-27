"""Portable posting identity is independent of descriptive/dedupe fields."""
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import User, Workspace
from email_sync.models import EmailAccount
from postings.models import JobPosting
from postings.serializers import JobPostingSerializer


class PostingIdentityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="identity")
        self.ws = Workspace.objects.create(owner=self.user, name="A")
        self.other = Workspace.objects.create(owner=self.user, name="B")
        self.account = EmailAccount.objects.create(workspace=self.ws, email="fixture@example.test")
        self.other_account = EmailAccount.objects.create(workspace=self.other, email="fixture@example.test")

    def posting(self, **values):
        return JobPosting.objects.create(**{"workspace": self.ws, "account": self.account,
            "message_id": "same", "company": "Same", "title": "Same",
            "dedupe_key": uuid.uuid4().hex, **values})

    def test_new_rows_have_distinct_uuids_and_integer_pks(self):
        first, second = self.posting(), self.posting()
        self.assertIsInstance(first.pk, int)
        self.assertIsInstance(first.portable_id, uuid.UUID)
        self.assertIsInstance(second.portable_id, uuid.UUID)
        self.assertNotEqual(first.portable_id, second.portable_id)

    def test_metadata_status_saved_updates_preserve_identity(self):
        row = self.posting()
        original = row.portable_id
        for field, value in (("title", "Better title"), ("company", "Better company"),
                             ("posting_url", "https://example.test/job"), ("status", "dismissed"),
                             ("saved", True), ("status", "new")):
            setattr(row, field, value)
            row.save(update_fields=[field])
            row.refresh_from_db()
            self.assertEqual(row.portable_id, original)
            self.assertEqual(getattr(row, field), value)

    def test_identity_and_existing_ownership_reparenting_reject(self):
        row = self.posting()
        original = row.portable_id
        for field, value in (("portable_id", uuid.uuid4()), ("workspace", self.other),
                             ("account", self.other_account)):
            setattr(row, field, value)
            with self.assertRaises(ValidationError):
                row.save()
            row.refresh_from_db()
            self.assertEqual((row.portable_id, row.workspace_id, row.account_id),
                             (original, self.ws.pk, self.account.pk))
        with self.assertRaises(ValidationError):
            JobPosting(pk=row.pk, workspace=self.ws, account=self.account,
                       message_id="same", dedupe_key=row.dedupe_key).save()

    def test_uuid_uniqueness_is_workspace_scoped(self):
        identity = uuid.UUID("11111111-1111-4111-8111-111111111111")
        self.posting(portable_id=identity)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.posting(portable_id=identity)
        other = self.posting(workspace=self.other, account=self.other_account, portable_id=identity)
        self.assertEqual(other.portable_id, identity)

    def test_serializer_exposes_read_only_uuid_beside_integer_id(self):
        row = self.posting()
        serializer = JobPostingSerializer(row)
        self.assertEqual(list(serializer.fields)[:2], ["id", "portable_id"])
        self.assertEqual(serializer.data["id"], row.pk)
        self.assertEqual(serializer.data["portable_id"], str(row.portable_id))
        self.assertTrue(serializer.fields["portable_id"].read_only)
        attempted = JobPostingSerializer(row, data={"portable_id": str(uuid.uuid4())}, partial=True)
        self.assertTrue(attempted.is_valid(), attempted.errors)
        self.assertNotIn("portable_id", attempted.validated_data)
