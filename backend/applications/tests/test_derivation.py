"""Workflow tests for deterministic source semantics, retention and atomicity."""
import tempfile
from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import User, Workspace
from applications.derivation import derive_application, effective_date
from applications.models import Application, Override, StatusHistory
from core.lifecycle import set_trash
from core.services import annotate_application, needs_attention
from documents.models import Category, CategoryMembership, Document, DocumentExtraction

UTC = dt_timezone.utc


class DerivationTests(APITestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        settings = override_settings(MEDIA_ROOT=temp.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = User.objects.create_user(username="derive")
        self.ws = Workspace.objects.create(owner=self.user, name="One")
        self.app = Application.objects.create(workspace=self.ws, section="applications", company="Same", role_label="Role")
        self.client.force_authenticate(self.user)

    def document(self, kind="resume", text=b"retained", **fields):
        number = Document.objects.count()
        return Document.objects.create(workspace=self.ws, application=self.app,
            file=SimpleUploadedFile(f"evidence{number}.txt", text), filename=f"evidence{number}.txt",
            doc_type=kind, ext=".txt", content_hash=f"hash{number}", size=len(text), **fields)

    def derive(self, **kwargs):
        self.app = derive_application(actor=self.user, workspace=self.ws, application_id=self.app.pk, **kwargs)
        return self.app

    def post(self, suffix, data=None):
        return self.client.post(f"/api/workspaces/{self.ws.pk}/{suffix}", data or {}, format="json")

    def trash(self, obj, state=True):
        obj.refresh_from_db()
        return set_trash(actor=self.user, workspace=self.ws,
            kind="documents" if isinstance(obj, Document) else "applications",
            pk=obj.pk, trashed=state, expected_revision=obj.lifecycle_revision)

    def snapshot(self):
        return (Application.objects.values().get(pk=self.app.pk), list(StatusHistory.objects.values()),
                list(DocumentExtraction.objects.order_by("pk").values()))

    def test_priority_and_replay_no_churn(self):
        for kind, expected in (("other", "unknown"), ("cover_letter", "drafted"),
                               ("application_confirmation", "applied"), ("interview_notice", "interviewing"),
                               ("rejection_notice", "rejected"), ("resume", "rejected")):
            self.document(kind)
            self.assertEqual(self.derive().status, expected)
        before = self.snapshot()
        self.derive()
        self.derive()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(list(self.app.status_history.values_list("status", flat=True)),
                         ["drafted", "applied", "interviewing", "rejected"])
        self.assertEqual(self.app.lifecycle_revision, 0)
        self.assertEqual(self.app.category_revision, 0)

    def test_empty_and_nonpipeline_clear_only_automatic_state(self):
        self.app.last_activity = timezone.now()
        self.app.status = "rejected"
        self.app.save()
        self.derive()
        self.assertEqual(self.app.status, "unknown")
        self.assertIsNone(self.app.last_activity)
        self.assertIsNone(self.app.last_activity_date)
        self.assertEqual(self.app.activity_provenance["last"]["precision"], "unknown")
        self.app.section = "credentials"
        self.app.save()
        self.document("rejection_notice")
        self.assertEqual(self.derive().status, "n/a")

    def test_manual_hidden_transitions_and_reset(self):
        self.document("resume")
        self.derive()
        response = self.post(f"applications/{self.app.pk}/override/", {"manual_status": "ghosted"})
        self.assertEqual(response.status_code, 200)
        rejection = self.document("rejection_notice")
        self.derive()
        self.assertEqual(self.app.status, "rejected")
        self.assertEqual(self.app.override.manual_status, "ghosted")
        count = self.app.status_history.count()
        self.post(f"applications/{self.app.pk}/override/", {"manual_status": "ghosted"})
        self.assertEqual(self.app.status_history.count(), count)
        self.post(f"applications/{self.app.pk}/override/", {"reset_status": True})
        self.assertEqual(self.app.status_history.latest("pk").status, "rejected")
        self.assertEqual(self.app.status_history.count(), count + 1)
        self.post(f"applications/{self.app.pk}/override/", {"reset_status": True})
        self.assertEqual(self.app.status_history.count(), count + 1)

    def test_retained_direct_trash_restore_reuses_original_dates_and_bytes(self):
        self.document("resume", verified_legacy_mtime=datetime(2020, 1, 1, tzinfo=UTC))
        decisive = self.document("rejection_notice", evidence_event_date=date(2021, 2, 3))
        self.derive()
        filename, original = decisive.file.name, decisive.file.read()
        self.trash(decisive)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "drafted")
        self.assertEqual(self.app.last_activity, datetime(2020, 1, 1, tzinfo=UTC))
        self.trash(decisive, False)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "rejected")
        self.assertEqual(self.app.last_activity_date, date(2021, 2, 3))
        self.assertEqual(Document.objects.count(), 2)
        decisive.refresh_from_db()
        self.assertEqual(decisive.file.name, filename)
        self.assertEqual(decisive.file.read(), original)
        self.assertEqual(decisive.evidence_event_date, date(2021, 2, 3))
        before = self.snapshot()
        self.trash(decisive, False)
        self.assertEqual(self.snapshot(), before)

    def test_parent_snapshot_no_artificial_transition_and_independent_child(self):
        self.document("resume")
        rejection = self.document("rejection_notice")
        self.derive()
        self.trash(rejection)
        before = self.snapshot()
        self.trash(self.app)
        self.assertFalse(Document.objects.live().exists())
        self.derive()
        self.trash(self.app, False)
        after = self.snapshot()
        for snapshot in (before, after):
            snapshot[0].pop("lifecycle_revision")
            snapshot[0].pop("trashed_at")
        self.assertEqual(before, after)
        rejection.refresh_from_db()
        self.assertTrue(rejection.is_trashed)

    def test_child_change_during_parent_trash_reconciles_once_on_restore(self):
        rejection = self.document("rejection_notice")
        self.derive()
        self.trash(self.app)
        count = self.app.status_history.count()
        self.trash(rejection)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "rejected")
        self.assertEqual(self.app.derivation_state, "needs_reconciliation")
        self.assertEqual(self.app.status_history.count(), count)
        self.trash(self.app, False)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "unknown")
        self.assertEqual(self.app.status_history.count(), count + 1)
        self.trash(self.app, False)
        self.assertEqual(self.app.status_history.count(), count + 1)

    def test_category_changes_never_derive(self):
        self.document("resume")
        self.derive()
        before = self.snapshot()
        cat = Category.objects.create(workspace=self.ws, name="Shelf", section="misc")
        response = self.client.put(f"/api/workspaces/{self.ws.pk}/applications/{self.app.pk}/category/",
            {"category_id": cat.pk, "expected_revision": 0}, format="json")
        self.assertEqual(response.status_code, 200)
        set_trash(actor=self.user, workspace=self.ws, kind="categories", pk=cat.pk, trashed=True, expected_revision=0)
        after = self.snapshot()
        before[0].pop("category_revision")
        after[0].pop("category_revision")
        self.assertEqual(before, after)

    def test_source_hierarchy_and_mixed_precision(self):
        self.document("resume", original_upload_at=datetime(2025, 1, 1, tzinfo=UTC),
                      verified_legacy_mtime=datetime(2020, 1, 1, 10, tzinfo=UTC))
        self.document("interview_notice", evidence_event_date=date(2020, 1, 1),
                      original_upload_at=timezone.now())
        self.derive()
        self.assertEqual(self.app.first_activity_date, date(2020, 1, 1))
        self.assertEqual(self.app.last_activity_date, date(2020, 1, 1))
        self.assertIsNone(self.app.first_activity)
        self.assertIsNone(self.app.last_activity)
        self.assertEqual(len(self.app.activity_provenance["last"]["documents"]), 2)

    def test_source_event_beats_legacy_and_genuine_upload(self):
        self.document("application_confirmation", b"Date: July 10, 2025\n", evidence_event_at=datetime(2020, 1, 1, 12, tzinfo=UTC),
                      verified_legacy_mtime=datetime(2021, 1, 1, tzinfo=UTC), original_upload_at=timezone.now())
        self.derive()
        self.assertEqual(self.app.last_activity, datetime(2020, 1, 1, 12, tzinfo=UTC))
        self.assertEqual(self.app.automatic_date_applied, date(2020, 1, 1))

    def test_historical_upload_and_random_dates_are_not_activity(self):
        self.document("resume", b"Born 01/01/2000. Date: July 10, 2025")
        self.derive()
        self.assertIsNone(self.app.last_activity)
        self.assertIsNone(self.app.last_activity_date)
        self.assertEqual(self.app.derivation_state, "incomplete")
        self.assertIsNone(self.app.automatic_date_applied)

    def test_real_upload_extracts_and_rename_changes_status_not_activity(self):
        response = self.client.post(f"/api/workspaces/{self.ws.pk}/applications/{self.app.pk}/documents/",
            {"files": [SimpleUploadedFile("resume.txt", b"new user upload")]})
        self.assertEqual(response.status_code, 201, response.data)
        document = Document.objects.get()
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "drafted")
        original = self.app.last_activity
        self.assertEqual(original, document.original_upload_at)
        response = self.post(f"documents/{document.pk}/rename/", {"new_filename": "rejection.txt"})
        self.assertEqual(response.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "rejected")
        self.assertEqual(self.app.last_activity, original)
        self.post(f"documents/{document.pk}/override/", {"doc_type_override": "application_confirmation"})
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "applied")
        before = self.snapshot()
        override_before = document.override.updated_at
        self.post(f"documents/{document.pk}/override/", {"doc_type_override": "application_confirmation"})
        self.assertEqual(self.snapshot(), before)
        document.override.refresh_from_db()
        self.assertEqual(document.override.updated_at, override_before)

    def test_confirmation_candidate_conflict_retraction_manual_and_suppression(self):
        first = self.document("application_confirmation", b"Date: July 10, 2025\n")
        self.derive()
        self.assertEqual(effective_date(self.app), date(2025, 7, 10))
        second = self.document("application_confirmation", b"Date: July 11, 2025\n")
        self.derive()
        self.assertIsNone(effective_date(self.app))
        self.assertEqual(self.app.date_candidate["state"], "conflicted")
        self.trash(second)
        self.app.refresh_from_db()
        self.assertEqual(effective_date(self.app), date(2025, 7, 10))
        self.post(f"applications/{self.app.pk}/override/", {"date_applied": "2019-01-01", "date_applied_source": "posting"})
        self.trash(first)
        self.app.refresh_from_db()
        self.assertEqual(effective_date(self.app), date(2019, 1, 1))
        self.post(f"applications/{self.app.pk}/override/", {"date_applied": None})
        self.trash(first, False)
        self.app.refresh_from_db()
        self.assertIsNone(effective_date(self.app))
        self.assertEqual(self.app.override.date_applied_mode, "suppressed")
        self.post(f"applications/{self.app.pk}/override/", {"reset_date_applied": True})
        self.app.refresh_from_db()
        self.assertEqual(effective_date(self.app), date(2025, 7, 10))

    def test_conflict_within_single_document_and_posting_not_automatic(self):
        doc = self.document("application_confirmation", b"Date: July 10, 2025\nDate: July 11, 2025\n",
                            original_upload_at=timezone.now())
        self.derive()
        self.assertEqual(self.app.date_candidate["state"], "conflicted")
        self.assertIsNone(self.app.last_activity)
        self.assertIsNone(self.app.automatic_date_applied)
        self.trash(doc)
        self.document("job_posting", b"Date: July 10, 2025\n")
        self.derive()
        self.assertIsNone(self.app.automatic_date_applied)
        self.assertIsNone(self.app.last_activity_date)

    def test_readonly_get_with_missing_cache_and_after_derivation(self):
        self.document("application_confirmation", b"Date: July 10, 2025\n")
        before = self.snapshot()
        response = self.client.get(f"/api/workspaces/{self.ws.pk}/applications/{self.app.pk}/dossier/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["derivation_state"], "pending")
        self.assertEqual(self.snapshot(), before)
        response = self.post(f"applications/{self.app.pk}/derive/")
        self.assertEqual(response.status_code, 200)
        before = self.snapshot()
        with patch("documents.extraction.extract_document", side_effect=AssertionError("GET extracted")):
            self.client.get(f"/api/workspaces/{self.ws.pk}/applications/{self.app.pk}/dossier/")
            self.client.get(f"/api/workspaces/{self.ws.pk}/applications/{self.app.pk}/documents/")
        self.assertEqual(self.snapshot(), before)

    def test_foreign_workspace_and_malformed_document_cannot_contribute(self):
        foreign = Workspace.objects.create(owner=User.objects.create_user(username="other"), name="Other")
        document = self.document("rejection_notice")
        Document.objects.filter(pk=document.pk).update(workspace=foreign)
        self.assertEqual(self.derive().status, "unknown")
        response = self.client.post(f"/api/workspaces/{foreign.pk}/applications/{self.app.pk}/derive/", {}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.post(f"documents/{document.pk}/rename/", {"new_filename": "resume.txt"}).status_code, 404)

    def test_failed_derivation_rolls_back_metadata_and_lifecycle(self):
        document = self.document("resume")
        self.derive()
        before = self.snapshot()
        with patch("applications.derivation._derive_locked", side_effect=RuntimeError("rollback")):
            with self.assertRaises(RuntimeError):
                self.post(f"documents/{document.pk}/rename/", {"new_filename": "rejection.txt"})
            with self.assertRaises(RuntimeError):
                self.trash(document)
        document.refresh_from_db()
        self.assertEqual(document.filename, "evidence0.txt")
        self.assertFalse(document.is_trashed)
        self.assertEqual(document.lifecycle_revision, 0)
        self.assertEqual(self.snapshot(), before)

    def test_history_recording_time_is_not_evidence_time_and_repair_can_suppress(self):
        self.document("application_confirmation", evidence_event_date=date(1999, 1, 2))
        start = timezone.now()
        self.derive()
        self.assertGreaterEqual(self.app.status_history.get().changed_at, start)
        self.document("rejection_notice")
        self.derive(record_history=False)
        self.assertEqual(self.app.status_history.count(), 1)
        self.derive()
        self.assertEqual(self.app.status_history.count(), 1)

    def test_workspace_calendar_attention_precedence_and_ordering(self):
        self.ws.calendar_timezone = "America/Denver"
        self.ws.save()
        self.document("application_confirmation", evidence_event_date=date(2025, 1, 1))
        self.derive()
        override = Override.objects.create(application=self.app, activity_override=date(2025, 1, 20),
            next_action_date=date(2025, 2, 1), snoozed_until=date(2025, 2, 1))
        with patch("core.services.dj_timezone.now", return_value=datetime(2025, 2, 1, 1, tzinfo=UTC)):
            self.app.refresh_from_db()
            row = annotate_application(self.app)
            self.assertEqual(row["days_since_activity"], 11)  # Jan 31 in Denver
            self.assertFalse(row["next_action_due"])
            self.assertTrue(row["is_snoozed"])
        override.activity_override = None
        override.snoozed_until = None
        override.save()
        with patch("core.services.dj_timezone.now", return_value=datetime(2025, 2, 1, 12, tzinfo=UTC)):
            self.app.refresh_from_db()
            row = annotate_application(self.app)
            self.assertEqual(row["days_since_activity"], 31)
            self.assertTrue(row["is_stale"])
            self.assertTrue(row["next_action_due"])
            ordinary = {**row, "id": 99, "next_action_due": False, "days_since_activity": 90}
            self.assertEqual([r["id"] for r in needs_attention([ordinary, row])], [self.app.pk, 99])

    def test_event_precision_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.document(evidence_event_at=timezone.now(), evidence_event_date=date.today())

    def test_shared_bytes_do_not_share_document_arrival_time(self):
        first = self.document("resume", original_upload_at=datetime(2020, 1, 1, tzinfo=UTC))
        self.derive()
        other = Application.objects.create(workspace=self.ws, section="applications", company="Same", role_label="Role")
        second = Document.objects.create(workspace=self.ws, application=other, file=first.file.name,
            filename=first.filename, doc_type="resume", ext=".txt", content_hash=first.content_hash, size=first.size,
            original_upload_at=datetime(2022, 1, 1, tzinfo=UTC))
        other = derive_application(actor=self.user, workspace=self.ws, application_id=other.pk)
        self.assertEqual(DocumentExtraction.objects.count(), 1)
        self.assertEqual(other.last_activity, second.original_upload_at)
        self.app.refresh_from_db()
        self.assertEqual(self.app.last_activity, first.original_upload_at)
        self.assertNotEqual(self.app.portable_id, other.portable_id)

    def test_type_override_response_tracks_changes_and_clear(self):
        document = self.document("resume")
        for value, expected in (("rejection_notice", "rejected"), ("interview_notice", "interviewing"), (None, "drafted")):
            response = self.post(f"documents/{document.pk}/override/", {"doc_type_override": value})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["effective_doc_type"], value or "resume")
            self.app.refresh_from_db()
            self.assertEqual(self.app.status, expected)

    def test_reconciliation_route_does_not_fabricate_historical_history(self):
        self.app.status = "applied"
        self.app.save()
        self.document("rejection_notice")
        response = self.post(f"applications/{self.app.pk}/derive/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "rejected")
        self.assertFalse(self.app.status_history.exists())
        before = self.snapshot()
        self.post(f"applications/{self.app.pk}/derive/")
        self.assertEqual(self.snapshot(), before)

    def test_derivation_rejects_foreign_cache_provenance_atomically(self):
        foreign = Workspace.objects.create(owner=User.objects.create_user(username="cache-owner"), name="Other")
        foreign_app = Application.objects.create(workspace=foreign, section="applications", company="Other")
        foreign_doc = Document.objects.create(workspace=foreign, application=foreign_app,
            filename="foreign.txt", file="foreign.txt", size=1, ext=".txt", content_hash="foreign")
        local = self.document("resume")
        DocumentExtraction.objects.create(workspace=self.ws, document=foreign_doc, content_hash=local.content_hash,
            extractor_version="4", extracted_at=timezone.now(), extracted_json={"extraction_ok": True})
        before = self.snapshot()
        self.assertEqual(self.post(f"applications/{self.app.pk}/derive/").status_code, 404)
        self.assertEqual(self.post(f"documents/{local.pk}/rename/", {"new_filename": "rejection.txt"}).status_code, 404)
        local.refresh_from_db()
        self.assertEqual(local.filename, "evidence1.txt")
        self.assertEqual(self.snapshot(), before)

    def test_derivation_route_requires_auth_csrf_and_live_parent(self):
        from rest_framework.test import APIClient
        url = f"/api/workspaces/{self.ws.pk}/applications/{self.app.pk}/derive/"
        self.assertEqual(APIClient().post(url, {}).status_code, 401)
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post(url, {}).status_code, 403)
        self.trash(self.app)
        self.assertEqual(self.post(f"applications/{self.app.pk}/derive/").status_code, 409)

    def test_admin_uses_derivation_and_protects_automatic_fields(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from types import SimpleNamespace
        document = self.document("resume")
        self.derive()
        authority = admin.site._registry[Document]
        document.doc_type = "rejection_notice"
        with transaction.atomic():
            authority.save_model(RequestFactory().post("/admin/"), document,
                                 SimpleNamespace(changed_data=["doc_type"]), True)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "rejected")
        application_admin = admin.site._registry[Application]
        self.assertIn("status", application_admin.readonly_fields)
        before = self.snapshot()
        form = SimpleNamespace(instance=self.app, changed_data=["company"], save_m2m=lambda: None)
        with transaction.atomic():
            application_admin.save_model(RequestFactory().post("/admin/"), self.app, form, True)
            application_admin.save_related(RequestFactory().post("/admin/"), form, [], True)
        self.assertEqual(self.snapshot(), before)
        # Section is an actual derivation input, unlike company/notes edits.
        self.app.section = "credentials"
        form.changed_data = ["section"]
        with transaction.atomic():
            application_admin.save_model(RequestFactory().post("/admin/"), self.app, form, True)
            application_admin.save_related(RequestFactory().post("/admin/"), form, [], True)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "n/a")

    def test_equivalent_evidence_in_reverse_order_has_same_business_result(self):
        evidence = [("resume", b"Date: July 2, 2025\n"),
                    ("application_confirmation", b"Date: July 1, 2025\n"),
                    ("interview_notice", b"Date: July 3, 2025\n"),
                    ("rejection_notice", b"Date: July 2, 2025\n")]
        for kind, text in evidence:
            self.document(kind, text, original_upload_at=datetime(2019, 1, 1, tzinfo=UTC))
        first = self.derive()
        self.app = Application.objects.create(workspace=self.ws, section="applications", company="Same", role_label="Role")
        for kind, text in reversed(evidence):
            self.document(kind, text, original_upload_at=datetime(2019, 1, 1, tzinfo=UTC))
        second = self.derive()
        # Compare supported business values, not different Document identities.
        for field in ("status", "first_activity", "first_activity_date", "last_activity", "last_activity_date", "automatic_date_applied"):
            self.assertEqual(getattr(first, field), getattr(second, field), field)
