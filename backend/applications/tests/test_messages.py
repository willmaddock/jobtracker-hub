"""Synthetic relationship workflows; no provider calls or personal tracker data."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from unittest.mock import patch
import uuid

from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, OperationalError, connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import NotFound
from rest_framework.test import APIClient, APIRequestFactory

from accounts.models import User, Workspace
from applications.message_relationships import attach_message
from applications.models import Application, ApplicationMessage, StatusHistory
from core.lifecycle import set_trash
from documents.models import Document
from email_sync.models import (AccountMatch, Discovery, EmailAccount, MailboxLineage,
    RetainedMessage, RetainedObservation, RetentionKey, ThreadIdentifier)
from email_sync.retention import establish_mailbox, retain_observation
from email_sync.tests.test_retention import fixture
from email_sync.tests.test_gmail_adoption import AdoptionFixtures, fetched
from postings.models import JobPosting


class Fixtures:
    def setUp(self):
        self.user = User.objects.create_user(username="owner")
        self.other = User.objects.create_user(username="other")
        self.ws = Workspace.objects.create(owner=self.user, name="A")
        self.ws_b = Workspace.objects.create(owner=self.user, name="B")
        self.ws_c = Workspace.objects.create(owner=self.other, name="C")
        self.app = self.application(self.ws)
        self.mailbox = establish_mailbox(actor=self.user, workspace=self.ws, provider="gmail",
            evidence={"method": "fixture", "reference": "synthetic"})
        self.data = fixture(self.mailbox)
        self.data["content"]["headers"].append(["Message-ID", "<shared@example.test>"])
        self.data["content"]["conversation_id"] = "shared-thread"
        self.message = self.retain("first", self.data)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def application(self, ws):
        return Application.objects.create(workspace=ws, section="applications", company="Same", role_label="Engineer")

    def retain(self, key, data):
        result = retain_observation(actor=self.user, workspace=self.ws, key=key, observation=data)
        return RetainedMessage.objects.get(pk=result.message_id) if result.message_id else result

    def url(self, app=None, ws=None):
        return f"/api/workspaces/{(ws or self.ws).pk}/applications/{(app or self.app).pk}/messages/"

    def post(self, message=None, app=None):
        return self.client.post(self.url(app), {"retained_message_id": (message or self.message).pk}, format="json")

    def attach(self):
        return attach_message(actor=self.user, workspace=self.ws,
            application_id=self.app.pk, retained_message_id=self.message.pk)


class MessageTests(Fixtures, TestCase):
    def test_first_attachment_and_exact_and_observation_replay(self):
        first = self.post()
        self.assertEqual(first.status_code, 201)
        before = list(ApplicationMessage.objects.values())
        self.retain("another-observation", self.data)
        second = self.post()
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data, second.data)
        self.assertEqual(before, list(ApplicationMessage.objects.values()))
        self.assertEqual(first.data["origin"], "manual")
        self.assertEqual(first.data["retained_message"]["id"], self.message.pk)

    def test_many_to_many_repeated_attempts_and_weak_identifiers(self):
        app_b = self.application(self.ws)
        data = deepcopy(self.data)
        data["source"]["value"] = "different-native-id"
        other = self.retain("different-source", data)
        for app, message in [(self.app, self.message), (self.app, other), (app_b, self.message)]:
            self.assertEqual(self.post(message, app).status_code, 201)
        self.assertEqual(ApplicationMessage.objects.count(), 3)
        self.assertEqual(Application.objects.count(), 2)
        result = self.client.get(self.url())
        self.assertEqual({r["retained_message_id"] for r in result.data["results"]}, {self.message.pk, other.pk})

    def test_workspace_ownership_and_redundant_scope(self):
        for ws in (self.ws_b, self.ws_c):
            foreign = self.application(ws)
            self.assertEqual(self.post(app=foreign).status_code, 404)
            self.assertEqual(self.client.get(self.url(foreign)).status_code, 404)
            if ws == self.ws_c:
                self.assertEqual(self.client.get(self.url(foreign, ws)).status_code, 404)
        for field in ("workspace", "workspace_id", "owner", "owner_id"):
            response = self.client.post(self.url(), {"retained_message_id": self.message.pk, field: self.ws_b.pk}, format="json")
            self.assertEqual(response.status_code, 400)
        with self.assertRaises(NotFound):
            attach_message(actor=self.other, workspace=self.ws, application_id=self.app.pk, retained_message_id=self.message.pk)
        with self.assertRaises(NotFound):
            attach_message(actor=AnonymousUser(), workspace=self.ws, application_id=self.app.pk, retained_message_id=self.message.pk)
        self.assertEqual(ApplicationMessage.objects.count(), 0)

    def test_foreign_source_and_corrupt_redundant_scope_hidden(self):
        mailbox = establish_mailbox(actor=self.user, workspace=self.ws_b, provider="gmail",
            evidence={"method": "fixture", "reference": "other"})
        result = retain_observation(actor=self.user, workspace=self.ws_b, key="foreign", observation=fixture(mailbox))
        foreign = RetainedMessage.objects.get(pk=result.message_id)
        self.assertEqual(self.post(foreign).status_code, 404)
        # Privileged maintenance corruption must not leak via normal reads/writes.
        self.post()
        RetainedMessage.objects.filter(pk=self.message.pk).update(mailbox=mailbox)
        self.assertEqual(self.post().status_code, 404)
        self.assertEqual(self.client.get(self.url()).data["results"], [])

    def test_auth_csrf_strict_payload_and_no_mutation_routes(self):
        self.assertEqual(APIClient().post(self.url(), {}, format="json").status_code, 401)
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post(self.url(), {"retained_message_id": self.message.pk}, format="json").status_code, 403)
        for payload in ({}, [], {"observation_id": 1}, {"retained_message_id": True},
                        {"retained_message_id": "1"}, {"retained_message_id": 0},
                        {"retained_message_id": 2**63}, {"retained_message_id": self.message.pk, "origin": "manual"}):
            self.assertEqual(self.client.post(self.url(), payload, format="json").status_code, 400, payload)
        for method in ("put", "patch", "delete"):
            self.assertEqual(getattr(self.client, method)(self.url(), {}, format="json").status_code, 405)

    def test_corrupt_relationship_workspace_is_not_returned_on_replay(self):
        row, _ = self.attach()
        ApplicationMessage.objects.filter(pk=row.pk).update(workspace=self.ws_b)
        self.assertEqual(self.post().status_code, 404)
        self.assertEqual(self.client.get(self.url()).data["results"], [])

    def test_json_suffix_uses_same_writer_and_read_contract(self):
        url = self.url().rstrip("/") + ".json"
        self.assertEqual(self.client.post(url, {"retained_message_id": self.message.pk}, format="json").status_code, 201)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.post().status_code, 200)

    def test_unresolved_observation_cannot_be_promoted_and_conflict_rejected(self):
        data = deepcopy(self.data)
        data["source"] = None
        unresolved = self.retain("unresolved", data)
        self.assertIsNone(unresolved.message_id)
        self.assertEqual(self.client.post(self.url(), {"observation_id": unresolved.observation_id}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url(), {"retained_message_id": unresolved.observation_id}, format="json").status_code, 404)
        self.post()
        before = list(ApplicationMessage.objects.values())
        data = deepcopy(self.data)
        data["content"]["subject"] = "Conflict"
        self.retain("conflict", data)
        response = self.post()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "retained_source_ineligible")
        self.assertEqual(self.post(app=self.application(self.ws)).status_code, 409)
        self.assertEqual(before, list(ApplicationMessage.objects.values()))
        self.assertFalse(self.client.get(self.url()).data["results"][0]["retained_message"]["eligible"])

    def test_partial_source_independent_of_credentials_and_all_other_data_unchanged(self):
        account = EmailAccount.objects.create(workspace=self.ws, provider="gmail", email="synthetic@example.test")
        AccountMatch.objects.create(account=account, application=self.app, message_id="<old>")
        discovery = Discovery.objects.create(account=account, message_id="<old>", status="dismissed")
        Discovery.objects.create(account=account, message_id="<posting>", kind="posting", status="dismissed",
                                 posting_urls=["https://example.test/job"])
        discovery.candidate_applications.add(self.app)
        JobPosting.objects.create(workspace=self.ws, account=account, dedupe_key="old")
        ThreadIdentifier.objects.create(application=self.app, message_id="<old>")
        models = (Application, StatusHistory, Document, AccountMatch, Discovery, JobPosting,
                  ThreadIdentifier, MailboxLineage, RetainedMessage, RetentionKey, RetainedObservation,
                  Discovery.candidate_applications.through)
        before = [list(model.objects.values()) for model in models]
        with patch("email_sync.sync_service.sync_account", side_effect=AssertionError("provider call")), \
             patch("applications.derivation.derive_application", side_effect=AssertionError("derivation")):
            self.assertEqual(self.post().status_code, 201)
        self.assertEqual(before, [list(model.objects.values()) for model in models])
        account.delete()  # no credential/source relationship dependency
        self.assertEqual(self.post().status_code, 200)
        data = deepcopy(self.data)
        data["source"]["value"] = "partial"
        data["content"]["text"] = {"value": "Part", "completeness": "partial", "reason": "provider_limit"}
        partial = self.retain("partial", data)
        self.assertEqual(self.post(partial).status_code, 201)

    def test_trash_restore_preserves_relationship_and_source(self):
        self.post()
        before = list(ApplicationMessage.objects.values()), list(RetainedMessage.objects.values())
        for state, revision in [(True, 0), (False, 1)]:
            set_trash(actor=self.user, workspace=self.ws, kind="applications", pk=self.app.pk,
                      trashed=state, expected_revision=revision)
            if state:
                self.assertEqual(self.post().status_code, 409)
                data = deepcopy(self.data)
                data["source"]["value"] = "new"
                new = self.retain("new", data)
                self.assertEqual(self.post(new).status_code, 409)
                self.assertEqual(self.client.get(self.url()).status_code, 409)
            else:
                self.assertEqual(self.post().status_code, 200)
                self.assertEqual(len(self.client.get(self.url()).data["results"]), 1)
            self.assertEqual(before[0], list(ApplicationMessage.objects.values()))
            self.assertEqual(before[1], list(RetainedMessage.objects.filter(pk=self.message.pk).values()))

    def test_model_identity_protection_constraints_and_admin(self):
        row, _ = self.attach()
        other_app = self.application(self.ws)
        for field, value in [("application_id", other_app.pk), ("workspace_id", self.ws_b.pk),
                             ("retained_message_id", 999), ("portable_id", uuid.uuid4()),
                             ("origin", "inferred"), ("created_at", None), ("pk", row.pk + 100)]:
            instance = ApplicationMessage.objects.get(pk=row.pk)
            setattr(instance, field, value)
            with self.assertRaises(ModelValidationError):
                instance.save()
        with self.assertRaises(ModelValidationError):
            row.delete()
        with self.assertRaises(ModelValidationError):
            ApplicationMessage.objects.create(workspace=self.ws_b, application=self.app, retained_message=self.message)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ApplicationMessage.objects.bulk_create([ApplicationMessage(workspace=self.ws, application=self.app, retained_message=self.message)])
        with self.assertRaises(IntegrityError), transaction.atomic():
            ApplicationMessage.objects.bulk_create([ApplicationMessage(workspace=self.ws, application=other_app, retained_message=self.message, origin="inferred")])
        for obj in (self.app, self.message, self.ws):
            with self.assertRaises(ProtectedError), transaction.atomic():
                type(obj).objects.filter(pk=obj.pk).delete()
        model_admin = admin.site._registry[ApplicationMessage]
        request = APIRequestFactory().get("/")
        request.user = self.user
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request, row))
        self.assertFalse(model_admin.has_delete_permission(request, row))
        self.assertFalse(model_admin.get_actions(request))
        self.assertEqual(set(model_admin.get_readonly_fields(request)), {f.name for f in row._meta.fields})

    def test_rollback_after_actual_insert(self):
        save = ApplicationMessage.save
        def fail(instance, *args, **kwargs):
            save(instance, *args, **kwargs)
            raise RuntimeError("synthetic after-insert failure")
        before = list(RetainedMessage.objects.values()), list(Application.objects.values())
        with patch.object(ApplicationMessage, "save", fail), self.assertRaises(RuntimeError):
            self.attach()
        self.assertEqual(ApplicationMessage.objects.count(), 0)
        self.assertEqual(before, (list(RetainedMessage.objects.values()), list(Application.objects.values())))
        self.assertTrue(self.attach()[1])

    def test_pagination_safe_summary_and_invalid_cursor(self):
        for n in range(51):
            data = deepcopy(self.data)
            data["source"]["value"] = str(n)
            self.post(self.retain(str(n), data))
        first = self.client.get(self.url()).data
        self.assertEqual(len(first["results"]), 50)
        second = self.client.get(self.url(), {"after": first["next_after"]}).data
        self.assertEqual(len(second["results"]), 1)
        self.assertIsNone(second["next_after"])
        self.assertNotIn("content", first["results"][0]["retained_message"])
        self.assertEqual(self.client.get(self.url(), {"after": "-1"}).status_code, 400)


class MessageConcurrencyTests(Fixtures, TransactionTestCase):
    def test_concurrent_pair_converges_after_any_sqlite_lock_refusal(self):
        barrier = Barrier(2)
        def run(_):
            connections.close_all()
            client = APIClient()
            client.force_authenticate(User.objects.get(pk=self.user.pk))
            barrier.wait(timeout=10)
            try:
                return client.post(self.url(), {"retained_message_id": self.message.pk}, format="json").status_code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(run, range(2)))
        self.assertTrue(all(code in (200, 201, 503) for code in outcomes), outcomes)
        self.assertLessEqual(outcomes.count(201), 1)
        first, _ = self.attach()
        second, created = self.attach()
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.created_at, second.created_at)
        self.assertEqual(ApplicationMessage.objects.count(), 1)

    def test_explicit_sqlite_refusal_then_same_operation_replay(self):
        with patch("applications.message_relationships.lock_workspace", side_effect=OperationalError("database is locked")):
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "lifecycle_busy")
        self.assertEqual(ApplicationMessage.objects.count(), 0)
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post().status_code, 200)


class LegacyProjectionIsolationTests(AdoptionFixtures, TestCase):
    def test_gmail_projection_never_allocates_canonical_relationships(self):
        message = fetched()
        self.sync(message)
        self.assertEqual(AccountMatch.objects.count(), 1)
        self.assertEqual(RetainedMessage.objects.count(), 1)
        self.assertEqual(ApplicationMessage.objects.count(), 0)
        row, created = attach_message(actor=self.user, workspace=self.ws,
            application_id=self.app.pk, retained_message_id=RetainedMessage.objects.get().pk)
        self.assertTrue(created)
        before = list(ApplicationMessage.objects.values())
        self.sync(message)
        self.assertEqual(before, list(ApplicationMessage.objects.values()))
        self.assertEqual(AccountMatch.objects.count(), 1)
        self.assertEqual(ApplicationMessage.objects.get().pk, row.pk)
