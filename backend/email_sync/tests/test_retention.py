"""Fixture-driven foundation acceptance, with no provider adoption."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, OperationalError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.test import APIClient, APIRequestFactory

from accounts.models import User, Workspace
from applications.models import Application, StatusHistory
from documents.models import Document
from email_sync.models import (
    MailboxLineage, RetainedMessage, RetainedObservation, RetentionKey,
    EmailAccount, IMAPCredential, Discovery, AccountMatch,
)
from email_sync.retention import establish_mailbox, retain_observation
from email_sync.imap_auth import disconnect_imap_account


def fixture(mailbox=None):
    unknown = {"precision": "unknown", "value": None, "source": "unknown"}
    return {"reason": "discovery_review", "observed_at": "2026-09-19T13:00:00+00:00",
            "mailbox_id": mailbox.pk if mailbox else None,
            "source": {"provider": "gmail", "kind": "gmail_message_id", "value": "source-1", "folder": "", "stability": "v1"},
            "content": {"subject": "Interview", "addresses": {"from": [{"name": "Recruiter", "address": "recruiter@example.test"}]},
                        "headers": [["Date", "Fri, 18 Sep 2026 10:00:00 +0000"], ["References", "<one>"], ["References", "<two>"]],
                        "text": {"value": "First\nSecond", "completeness": "complete"},
                        "html": {"value": '<script>alert(1)</script><img src="https://tracking.invalid/">', "completeness": "complete"},
                        "header_sent": {"precision": "instant", "value": "2026-09-18T10:00:00Z", "source": "header_date"},
                        "provider_received": unknown, "provenance": {"method": "fixture-decoder", "version": "1"}}}


class Fixtures:
    def setUp(self):
        self.user = User.objects.create_user(username="owner")
        self.other = User.objects.create_user(username="other")
        self.ws = Workspace.objects.create(owner=self.user, name="A")
        self.ws_b = Workspace.objects.create(owner=self.user, name="B")
        self.ws_c = Workspace.objects.create(owner=self.other, name="C")
        self.mailbox = self.lineage(self.ws)
        self.data = fixture(self.mailbox)

    def lineage(self, workspace, provider="gmail"):
        return establish_mailbox(actor=workspace.owner, workspace=workspace, provider=provider,
                                 evidence={"method": "isolated-fixture", "reference": "verified-principal"})

    def retain(self, key="observation-1", data=None, workspace=None):
        return retain_observation(actor=self.user, workspace=workspace or self.ws, key=key, observation=data or self.data)


class RetentionTests(Fixtures, TestCase):
    def test_strong_identity_without_rfc_id_and_exact_retry(self):
        first = self.retain()
        before = list(RetainedMessage.objects.values()), list(RetainedObservation.objects.values())
        second = self.retain()
        self.assertEqual(first.message_id, second.message_id)
        self.assertTrue(second.replay)
        self.assertTrue(second.eligible)
        self.assertEqual(before, (list(RetainedMessage.objects.values()), list(RetainedObservation.objects.values())))
        third = self.retain("new-observation")
        self.assertEqual(first.message_id, third.message_id)
        self.assertEqual(RetainedObservation.objects.count(), 2)

    def test_weak_identifiers_do_not_merge(self):
        self.data["content"]["headers"].append(["Message-ID", "<same>"])
        self.retain()
        self.data["source"]["value"] = "different"
        self.retain("second")
        self.assertEqual(RetainedMessage.objects.count(), 2)
        self.assertEqual(len(set(RetainedMessage.objects.values_list("content_digest", flat=True))), 1)

    def test_lineage_workspace_and_provider_namespaces(self):
        first = self.retain()
        second_mailbox = self.lineage(self.ws)
        self.data["mailbox_id"] = second_mailbox.pk
        second = self.retain("second")
        self.assertNotEqual(first.message_id, second.message_id)
        third_mailbox = self.lineage(self.ws_b)
        self.data["mailbox_id"] = third_mailbox.pk
        third = self.retain(workspace=self.ws_b)
        self.assertNotIn(third.message_id, [first.message_id, second.message_id])
        graph = self.lineage(self.ws, "outlook")
        self.data["mailbox_id"] = graph.pk
        self.data["source"].update(provider="outlook", kind="graph_immutable_id")
        self.retain("graph")
        self.assertEqual(RetainedMessage.objects.count(), 4)

    def test_imap_folder_and_uidvalidity_isolation(self):
        mailbox = self.lineage(self.ws, "imap")
        self.data["mailbox_id"] = mailbox.pk
        self.data["source"] = {"provider": "imap", "kind": "imap_uid", "value": "7", "folder": "INBOX", "stability": "uidvalidity:10"}
        self.retain()
        self.data["source"]["folder"] = "Archive"
        self.retain("folder")
        self.data["source"]["stability"] = "uidvalidity:11"
        self.retain("version")
        self.assertEqual(RetainedMessage.objects.count(), 3)

    def test_relevant_unresolved_and_retry_are_retained_without_identity_invention(self):
        for index, changes in enumerate([{"mailbox_id": None}, {"source": None}, {"mailbox_id": None, "source": None}]):
            data = deepcopy(self.data)
            data.update(changes)
            result = self.retain(str(index), data)
            self.assertEqual(result.state, "unresolved")
            self.assertFalse(result.eligible)
            self.assertTrue(self.retain(str(index), data).replay)
        self.assertEqual(RetainedMessage.objects.count(), 0)
        self.assertEqual(RetainedObservation.objects.count(), 3)

    def test_incomplete_source_namespace_preserves_known_facts_as_unresolved(self):
        del self.data["source"]["stability"]
        result = self.retain()
        self.assertEqual(result.state, "unresolved")
        self.assertFalse(result.eligible)
        self.assertFalse(RetainedMessage.objects.exists())
        row = RetainedObservation.objects.get(pk=result.observation_id)
        self.assertEqual(row.payload["source"]["value"], "source-1")
        self.assertIsNone(row.payload["source"]["stability"])

    def test_relevance_required_and_arbitrary_metadata_rejected(self):
        for reason in [None, "", "examined", [], {}]:
            data = deepcopy(self.data)
            data["reason"] = reason
            with self.assertRaises(ValidationError):
                self.retain(data=data)
        self.data["content"]["provenance"]["access_token"] = "secret"
        with self.assertRaises(ValidationError) as error:
            self.retain()
        self.assertNotIn("secret", str(error.exception))
        self.assertFalse(RetentionKey.objects.exists())

    def test_material_content_conflict_preserves_both_and_blocks_original_replay(self):
        first = self.retain()
        canonical = RetainedMessage.objects.get(pk=first.message_id)
        before = canonical.content, canonical.retained_at, canonical.portable_id
        self.data["content"]["text"]["value"] = "Changed content"
        conflict = self.retain("second")
        self.assertEqual(conflict.state, "conflict")
        self.assertFalse(conflict.eligible)
        self.assertEqual(conflict.message_id, first.message_id)
        canonical.refresh_from_db()
        self.assertEqual(before, (canonical.content, canonical.retained_at, canonical.portable_id))
        self.assertTrue(canonical.has_conflict)
        self.assertEqual(self.retain(data=fixture(self.mailbox)).state, "conflict")
        self.assertEqual(RetainedObservation.objects.count(), 2)

    def test_changed_key_conflict_never_allocates_second_source(self):
        first = self.retain()
        self.data["source"]["value"] = "new-source"
        changed = self.retain()
        self.assertEqual(changed.state, "conflict")
        self.assertEqual(changed.message_id, first.message_id)
        self.assertEqual(RetainedMessage.objects.count(), 1)
        self.assertTrue(self.retain().replay)
        self.assertEqual(RetainedObservation.objects.count(), 2)
        row = RetainedObservation.objects.get(pk=changed.observation_id)
        self.assertEqual(row.payload["source"]["value"], "new-source")
        self.assertEqual(row.conflict_reason, "observation_key_reused")

    def test_unresolved_key_reuse_does_not_promote_identity(self):
        original = deepcopy(self.data)
        original["source"] = None
        self.retain(data=original)
        result = self.retain()
        self.assertEqual(result.state, "conflict")
        self.assertIsNone(result.message_id)
        self.assertFalse(RetainedMessage.objects.exists())

    def test_version_one_normalization_equivalence_and_order_sensitivity(self):
        first = self.retain()
        self.data["content"]["text"]["value"] = "First\r\nSecond"
        self.data["content"]["headers"][0][0] = "DATE"
        self.data["observed_at"] = "2026-09-19T15:00:00+02:00"
        self.assertTrue(self.retain().replay)
        self.data["content"]["headers"].reverse()
        self.assertEqual(self.retain("reordered").state, "conflict")
        self.assertEqual(RetainedMessage.objects.count(), 1)

    def test_material_provenance_and_html_differences_are_not_normalized_away(self):
        self.retain()
        self.data["content"]["html"]["value"] += "\r\n"
        self.assertEqual(self.retain("html").state, "conflict")
        self.data = fixture(self.mailbox)
        self.data["content"]["provenance"]["version"] = "2"
        self.assertEqual(self.retain("provenance").state, "conflict")

    @override_settings(RETAINED_EMAIL_TEXT_BYTES=7, RETAINED_EMAIL_HTML_BYTES=12)
    def test_bounded_utf8_content_and_tail_conflicts(self):
        self.data["content"]["text"]["value"] = "éééé first"
        result = self.retain()
        content = RetainedMessage.objects.get(pk=result.message_id).content
        self.assertEqual(content["text"]["value"], "ééé")
        self.assertEqual(content["text"]["completeness"], "partial")
        self.assertEqual(content["text"]["truncation"]["retained_bytes"], 6)
        self.assertEqual(content["html"]["completeness"], "partial")
        self.data["content"]["text"]["value"] = "éééé second"
        self.assertEqual(self.retain("tail").state, "conflict")
        self.assertEqual(RetainedObservation.objects.count(), 2)

    def test_oversized_observation_or_metadata_rejected_atomically(self):
        for field, value in [("subject", "x" * 4097), ("headers", [["Date", "x" * 8193]])]:
            data = deepcopy(self.data)
            data["content"][field] = value
            with self.assertRaises(ValidationError):
                self.retain(data=data)
        self.data["content"]["text"]["value"] = "x" * (2 * 1024 * 1024)
        with self.assertRaises(ValidationError):
            self.retain()
        self.assertFalse(RetentionKey.objects.exists())

    def test_unavailable_is_not_complete_and_no_source_time_is_fabricated(self):
        self.data["content"]["text"] = {"value": None, "completeness": "unavailable", "reason": "not_supplied"}
        self.data["content"]["header_sent"] = {"precision": "date", "value": "2020-01-02", "source": "header_date"}
        row = RetainedMessage.objects.get(pk=self.retain().message_id)
        self.assertEqual(row.content["text"]["completeness"], "unavailable")
        self.assertEqual(row.content["header_sent"]["value"], "2020-01-02")
        self.assertIsNone(row.content["provider_received"]["value"])
        self.data["content"]["header_sent"] = {"precision": "uncertain", "value": "2020-01-02T12:00:00", "source": "legacy_naive"}
        self.data["source"]["value"] = "other"
        row = RetainedMessage.objects.get(pk=self.retain("uncertain").message_id)
        self.assertEqual(row.content["header_sent"]["value"], "2020-01-02T12:00:00")

    def test_genuine_receipt_source_and_original_offset_preserved(self):
        self.data["content"]["provider_received"] = {"precision": "instant", "value": "2026-09-18T12:00:00+02:00", "source": "gmail_internal_date"}
        result = self.retain()
        content = RetainedMessage.objects.get(pk=result.message_id).content
        self.assertEqual(content["provider_received"]["value"], "2026-09-18T10:00:00+00:00")
        self.assertEqual(content["provider_received"]["source_utc_offset_seconds"], 7200)
        self.assertNotEqual(content["provider_received"]["value"], self.data["observed_at"])
        self.data["content"]["provider_received"]["source"] = "imap_internaldate"
        with self.assertRaises(ValidationError):
            self.retain("wrong-provider")

    def test_naive_instants_and_header_date_as_receipt_rejected(self):
        self.data["content"]["provider_received"] = {"precision": "instant", "value": "2020-01-01T12:00:00Z", "source": "header_date"}
        with self.assertRaises(ValidationError):
            self.retain()
        self.data = fixture(self.mailbox)
        self.data["observed_at"] = "2020-01-01T12:00:00"
        with self.assertRaises(ValidationError):
            self.retain()

    def test_invalid_namespaces_never_fall_back_to_weak_identity(self):
        for changes in [{"kind": "message-id"}, {"folder": "unexpected"}, {"stability": ""}, {"provider": "outlook"}]:
            data = deepcopy(self.data)
            data["source"].update(changes)
            with self.assertRaises(ValidationError):
                self.retain(data=data)
        self.assertFalse(RetainedObservation.objects.exists())

    def test_authorization_and_mailbox_references(self):
        for workspace in [self.ws_b, self.ws_c]:
            with self.assertRaises(NotFound):
                self.retain(workspace=workspace)
        for workspace in [self.ws_b, self.ws_c]:
            self.data["mailbox_id"] = self.lineage(workspace).pk
            with self.assertRaises(NotFound):
                self.retain()
        self.assertFalse(RetentionKey.objects.exists())

    def test_ownership_revalidated_inside_transaction(self):
        with patch("email_sync.retention.lock_workspace", side_effect=NotFound):
            with self.assertRaises(NotFound):
                self.retain()
        self.assertFalse(RetentionKey.objects.exists())

    def test_failure_rolls_back_entire_operation(self):
        with patch("email_sync.retention.RetainedObservation.objects.create", side_effect=RuntimeError("fixture failure")):
            with self.assertRaises(RuntimeError):
                self.retain()
        self.assertFalse(RetentionKey.objects.exists())
        self.assertFalse(RetainedMessage.objects.exists())
        self.retain()
        self.data["content"]["subject"] = "conflict"
        with patch("email_sync.retention.RetainedObservation.objects.create", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.retain()
        self.assertFalse(RetentionKey.objects.get().has_conflict)
        self.assertFalse(RetainedMessage.objects.get().has_conflict)

    def test_disconnect_and_account_deletion_preserve_independent_evidence(self):
        result = self.retain()
        account = EmailAccount.objects.create(workspace=self.ws, provider="imap", email="same@example.test")
        IMAPCredential.objects.create(account=account, host="fixture", username="user", password="not-a-real-secret")
        before = list(MailboxLineage.objects.values()), list(RetainedMessage.objects.values()), list(RetainedObservation.objects.values())
        disconnect_imap_account(account)
        self.assertFalse(IMAPCredential.objects.exists())
        account.delete()
        self.assertEqual(before, (list(MailboxLineage.objects.values()), list(RetainedMessage.objects.values()), list(RetainedObservation.objects.values())))
        EmailAccount.objects.create(workspace=self.ws, provider="imap", email="same@example.test")
        self.assertEqual(MailboxLineage.objects.count(), 1)

    def test_no_application_or_workflow_effects(self):
        app = Application.objects.create(workspace=self.ws, company="Fixture", section="applications", status="applied")
        doc = Document.objects.create(workspace=self.ws, application=app, filename="old.txt", file="fixture/old.txt", size=5, ext=".txt")
        models = [Application, Document, StatusHistory, AccountMatch, Discovery]
        before = [list(model.objects.values()) for model in models]
        self.retain()
        self.data["content"]["subject"] = "Conflict"
        self.retain("conflict")
        self.assertEqual(before, [list(model.objects.values()) for model in models])

    def test_model_and_admin_guards_and_workspace_protection(self):
        result = self.retain()
        request = APIRequestFactory().get("/")
        request.user = self.user
        for model in [MailboxLineage, RetainedMessage, RetentionKey, RetainedObservation]:
            row = model.objects.first()
            with self.assertRaises(ModelValidationError):
                row.save()
            with self.assertRaises(ModelValidationError):
                row.delete()
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request, row))
            self.assertFalse(model_admin.has_delete_permission(request, row))
            self.assertFalse(model_admin.get_actions(request))
        with self.assertRaises(ProtectedError):
            self.ws.delete()
        with self.assertRaises(ProtectedError):
            self.user.delete()

    def test_database_uniqueness(self):
        self.retain()
        for model in [RetainedMessage, RetentionKey, RetainedObservation]:
            values = model.objects.values().get()
            del values["id"]
            with self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.create(**values)


class InspectionTests(Fixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.result = self.retain()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def url(self, suffix, workspace=None):
        return f"/api/workspaces/{(workspace or self.ws).pk}/{suffix}"

    def test_authenticated_plain_json_inspection_is_read_only(self):
        suffixes = ["retained-messages/", f"retained-messages/{self.result.message_id}/", "retained-observations/",
                    f"retained-observations/{self.result.observation_id}/", f"mailbox-lineages/{self.mailbox.pk}/"]
        with patch("email_sync.providers.get_provider", side_effect=AssertionError("must not fetch")):
            for suffix in suffixes:
                for method in ["get", "head"]:
                    with CaptureQueriesContext(connection) as queries:
                        response = getattr(self.client, method)(self.url(suffix))
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(all(q["sql"].lstrip().upper().startswith("SELECT") for q in queries))
                    self.assertNotIn(b"<script>", response.content)
                    self.assertNotIn(b"tracking.invalid", response.content)
                    self.assertNotIn(b"access_token", response.content)
        response = self.client.get(self.url(f"retained-messages/{self.result.message_id}/"))
        self.assertEqual(response.data["content"]["text"]["value"], "First\nSecond")
        self.assertTrue(response.data["content"]["html"]["available"])
        self.assertNotIn("value", response.data["content"]["html"])

    def test_no_public_mutation_or_raw_html_renderer(self):
        url = self.url(f"retained-messages/{self.result.message_id}/")
        for method in ["post", "put", "patch", "delete"]:
            self.assertEqual(getattr(self.client, method)(url, {}, format="json").status_code, 405)
        self.assertEqual(self.client.get(url, HTTP_ACCEPT="text/html").status_code, 406)

    def test_cross_user_and_same_owner_workspace_isolation(self):
        for suffix in [f"retained-messages/{self.result.message_id}/", f"retained-observations/{self.result.observation_id}/", f"mailbox-lineages/{self.mailbox.pk}/"]:
            for workspace in [self.ws_b, self.ws_c]:
                response = self.client.get(self.url(suffix, workspace))
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.data["code"], "not_found")
        self.assertEqual(self.client.get(self.url("retained-messages/", self.ws_b)).data["results"], [])
        self.assertEqual(self.client.get(self.url(f"retained-observations/?message_id={self.result.message_id}", self.ws_b)).status_code, 404)
        self.client.force_authenticate(None)
        response = self.client.get(self.url("retained-messages/"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_unresolved_and_conflicted_original_are_inspectable(self):
        self.data["content"]["subject"] = "Changed"
        self.retain("conflict")
        response = self.client.get(self.url(f"retained-observations/{self.result.observation_id}/"))
        self.assertEqual(response.data["state"], "conflict")
        self.assertFalse(response.data["eligible"])
        self.data["mailbox_id"] = None
        unresolved = self.retain("unresolved")
        response = self.client.get(self.url(f"retained-observations/{unresolved.observation_id}/"))
        self.assertEqual(response.data["state"], "unresolved")
        self.assertIsNone(response.data["message_id"])

    def test_bounded_collection_and_bad_cursor_scope(self):
        for n in range(52):
            self.retain(str(n))
        response = self.client.get(self.url("retained-observations/"))
        self.assertEqual(len(response.data["results"]), 50)
        next_page = self.client.get(self.url(f'retained-observations/?after={response.data["next_after"]}'))
        self.assertEqual(len(next_page.data["results"]), 3)
        for query in ["after=-1", "after=9999999999999999999", "after=abc", f"workspace={self.ws.pk}"]:
            self.assertEqual(self.client.get(self.url("retained-observations/?" + query)).status_code, 400)


class RetentionConcurrencyTests(Fixtures, TransactionTestCase):
    def test_competing_equivalent_and_conflicting_operations(self):
        for conflict in [False, True]:
            barrier = Barrier(2)
            data = deepcopy(self.data)
            data["source"]["value"] = str(conflict)
            def compete(n):
                close_old_connections()
                candidate = deepcopy(data)
                if conflict and n:
                    candidate["content"]["subject"] = "Conflicting subject"
                barrier.wait(timeout=10)
                try:
                    return retain_observation(actor=self.user, workspace=self.ws, key=f"{conflict}-{n}", observation=candidate)
                except OperationalError:
                    return None
                finally:
                    close_old_connections()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(compete, range(2)))
            # SQLite may reject either or both. Explicit same-input reconciliation,
            # not hidden automatic retries, must converge without lost evidence.
            for n in range(2):
                candidate = deepcopy(data)
                if conflict and n:
                    candidate["content"]["subject"] = "Conflicting subject"
                self.retain(f"{conflict}-{n}", candidate)
            rows = RetainedMessage.objects.filter(locator_value=str(conflict))
            self.assertEqual(rows.count(), 1)
            self.assertEqual(rows.get().has_conflict, conflict)
            self.assertEqual(rows.get().observations.count(), 2)

    def test_competing_same_observation_key(self):
        barrier = Barrier(2)
        def compete(n):
            close_old_connections()
            candidate = deepcopy(self.data)
            candidate["source"]["value"] = str(n)
            barrier.wait(timeout=10)
            try:
                return self.retain(data=candidate)
            except OperationalError:
                return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(compete, range(2)))
        for n in range(2):
            candidate = deepcopy(self.data)
            candidate["source"]["value"] = str(n)
            self.retain(data=candidate)
        self.assertEqual(RetainedMessage.objects.count(), 1)
        self.assertEqual(RetainedObservation.objects.count(), 2)
        self.assertTrue(RetentionKey.objects.get().has_conflict)
