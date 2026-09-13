"""Synchronous identity, review and replay contracts through both HTTP routes."""
from datetime import timedelta
from unittest.mock import patch
import uuid

from django.db import IntegrityError
from django.utils import timezone
from rest_framework.test import APITestCase
from accounts.models import User, Workspace
from applications.models import Application, Override, StatusHistory
from core.models import ApplicationRequestIntent
from email_sync.models import EmailAccount
from postings.models import JobPosting, PostingApplicationConversion


class CreationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="identity")
        self.workspace = Workspace.objects.create(owner=self.user, name="A")
        self.other = Workspace.objects.create(owner=self.user, name="B")
        self.client.force_authenticate(self.user)
        account = EmailAccount.objects.create(workspace=self.workspace, email="fixture@example.test")
        self.posting = JobPosting.objects.create(workspace=self.workspace, account=account,
            company="Acme", title="Engineer", dedupe_key="fixture")
        self.body = {"company": "Acme", "role_label": "Engineer", "status": "applied"}
        self.key = uuid.uuid4().hex

    def send(self, body=None, key=None, posting=False, workspace=None):
        ws = workspace or self.workspace
        suffix = f"job-postings/{self.posting.pk}/apply/" if posting else "applications/"
        return self.client.post(f"/api/workspaces/{ws.pk}/{suffix}", self.body if body is None else body,
                                format="json", HTTP_IDEMPOTENCY_KEY=key or self.key)

    def new_key(self):
        return uuid.uuid4().hex

    def test_non_ascii_challenge_is_validation_error_without_effects(self):
        self.send()
        for posting in (False, True):
            key = self.new_key()
            warning = self.send(key=key, posting=posting)
            self.assertEqual(warning.status_code, 409)
            response = self.send({**self.body, "challenge": "é"}, key, posting=posting)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["code"], "validation_error")
            self.assertFalse(ApplicationRequestIntent.objects.get(key=key).completed)
        self.assertEqual(Application.objects.count(), 1)
        self.assertEqual(PostingApplicationConversion.objects.count(), 0)

    def test_lost_response_replay_has_one_effect_and_initial_history(self):
        first = self.send()
        self.assertEqual(first.status_code, 201, first.data)
        replay = self.send()
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(first.data, replay.data)
        self.assertEqual(Application.objects.count(), 1)
        self.assertEqual(Override.objects.count(), 1)
        self.assertEqual(StatusHistory.objects.count(), 1)

    def test_changed_payload_and_route_conflict(self):
        self.send()
        self.assertEqual(self.send({**self.body, "status": "drafted"}).data["code"], "idempotency_key_reused")
        self.assertEqual(self.send(posting=True).data["code"], "idempotency_key_reused")

    def test_omission_is_bound_but_json_field_order_is_not(self):
        self.send({"company": "Acme"})
        self.assertEqual(self.send({"company": "Acme", "role_label": ""}).data["code"], "idempotency_key_reused")
        key = self.new_key()
        first = self.send({"role_label": "Other", "company": "Other"}, key)
        self.assertEqual(self.send({"company": "Other", "role_label": "Other"}, key).data, first.data)

    def test_explicit_repeat_then_replay_continuation(self):
        first = self.send()
        key = self.new_key()
        warning = self.send(key=key)
        self.assertEqual(warning.status_code, 409)
        self.assertEqual(warning.data["candidates"][0]["id"], first.data["id"])
        body = {**self.body, "challenge": warning.data["challenge"]}
        second = self.send(body, key)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertNotEqual(second.data["id"], first.data["id"])
        self.assertNotEqual(second.data["portable_id"], first.data["portable_id"])
        self.assertEqual(self.send(body, key).data, second.data)
        self.assertEqual(Application.objects.count(), 2)

    def test_challenge_cannot_authorize_different_key_workspace_or_actor(self):
        self.send()
        key = self.new_key()
        token = self.send(key=key).data["challenge"]
        body = {**self.body, "challenge": token}
        self.assertEqual(self.send(body, self.new_key()).data["code"], "invalid_challenge")
        self.assertEqual(self.send(body, key, workspace=self.other).data["code"], "invalid_challenge")
        self.client.force_authenticate(User.objects.create_user(username="foreign"))
        self.assertEqual(self.send(body, key).status_code, 404)
        self.assertEqual(Application.objects.count(), 1)

    def test_expired_stale_and_renewed_review(self):
        self.send()
        key = self.new_key()
        warning = self.send(key=key)
        token = warning.data["challenge"]
        ApplicationRequestIntent.objects.filter(key=key).update(challenge_expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.send({**self.body, "challenge": token}, key).data["code"], "challenge_expired")
        token = self.send(key=key).data["challenge"]
        Override.objects.update(archived=True)
        self.assertEqual(self.send({**self.body, "challenge": token}, key).data["code"], "stale_challenge")
        renewed = self.send(key=key)
        self.assertTrue(renewed.data["candidates"][0]["archived"])
        self.assertEqual(self.send({**self.body, "challenge": renewed.data["challenge"]}, key).status_code, 201)

    def test_candidate_creation_and_removal_invalidate_review(self):
        self.send()
        key = self.new_key()
        token = self.send(key=key).data["challenge"]
        Application.objects.create(workspace=self.workspace, company="ACME", role_label="Engineer", section="misc")
        self.assertEqual(self.send({**self.body, "challenge": token}, key).data["code"], "stale_challenge")
        token = self.send(key=key).data["challenge"]
        Application.objects.order_by("pk").first().delete()
        self.assertEqual(self.send({**self.body, "challenge": token}, key).data["code"], "stale_challenge")

    def test_removed_result_is_terminal_and_minimal(self):
        app = self.send().data
        Application.objects.get(pk=app["id"]).delete()
        response = self.send()
        self.assertEqual(response.data, {"state": "removed", "portable_id": app["portable_id"]})
        self.assertEqual(Application.objects.count(), 0)

    def test_posting_new_key_requires_confirmation_even_after_removal(self):
        first = self.send({}, posting=True)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(self.send({}, posting=True).status_code, 200)
        Application.objects.get(pk=first.data["application_id"]).delete()
        self.assertEqual(self.send({}, posting=True).data["state"], "removed")
        key = self.new_key()
        warning = self.send({}, key, posting=True)
        self.assertEqual(warning.status_code, 409)
        self.assertEqual(warning.data["candidates"], [])
        self.assertEqual(warning.data["prior_conversion_count"], 1)
        second = self.send({"challenge": warning.data["challenge"]}, key, posting=True)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(PostingApplicationConversion.objects.count(), 2)
        self.assertEqual(PostingApplicationConversion.objects.filter(application=None).count(), 1)

    def test_posting_change_invalidates_review(self):
        self.send()
        token = self.send({}, self.new_key(), posting=True) # direct/manual candidate also guards conversion
        intent = ApplicationRequestIntent.objects.get(kind="posting")
        self.posting.title = "Changed"
        self.posting.save()
        self.assertEqual(self.send({"challenge": token.data["challenge"]}, intent.key, posting=True).data["code"], "stale_challenge")

    def test_atomic_initial_records_and_no_integrity_error_duplicate_translation(self):
        with patch("applications.creation.StatusHistory.objects.create", side_effect=IntegrityError("fixture")):
            with self.assertRaises(IntegrityError):
                self.send()
        self.assertEqual(Application.objects.count(), 0)
        self.assertEqual(ApplicationRequestIntent.objects.count(), 0)
        self.assertEqual(Override.objects.count(), 0)

    def test_workspace_and_session_reauthorization(self):
        self.assertEqual(self.send().status_code, 201)
        self.assertEqual(self.send(workspace=self.other).status_code, 201)
        self.client.force_authenticate(None)
        self.assertEqual(self.send().status_code, 401)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.send().status_code, 200)

    def test_no_normal_identity_input_or_force_flag(self):
        for field in ("portable_id", "source_relpath", "id", "owner", "workspace", "force"):
            response = self.send({**self.body, field: "untrusted"}, self.new_key())
            self.assertEqual(response.status_code, 400, (field, response.data))
        response = self.client.post(f"/api/workspaces/{self.workspace.pk}/applications/", self.body, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Application.objects.count(), 0)

    def test_foreign_candidates_not_disclosed_and_normalization_advisory(self):
        Application.objects.create(workspace=self.other, company="Acme", role_label="Engineer", section="applications")
        self.assertEqual(self.send().status_code, 201)
        warning = self.send({**self.body, "company": " ACME ", "role_label": "engineer"}, self.new_key())
        self.assertEqual(warning.status_code, 409)
        self.assertEqual(len(warning.data["candidates"]), 1)


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient


class ConcurrentCreationTests(TransactionTestCase):
    def test_simultaneous_same_key_has_one_effect_and_uncertain_response_reconciles(self):
        user = User.objects.create_user(username="concurrent")
        workspace = Workspace.objects.create(owner=user, name="Concurrent")
        key = uuid.uuid4().hex
        barrier = Barrier(2)
        url = f"/api/workspaces/{workspace.pk}/applications/"
        def send():
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(user)
                barrier.wait(timeout=10)
                return client.post(url, {"company": "Same"}, format="json", HTTP_IDEMPOTENCY_KEY=key).status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: send(), range(2)))
        self.assertLessEqual(outcomes.count(201), 1)
        if connection.vendor != "sqlite":
            self.assertEqual(outcomes.count(201), 1)
        self.assertTrue(set(outcomes) <= ({200, 201, 503} if connection.vendor == "sqlite" else {200, 201}), outcomes)
        initial_effects = outcomes.count(201)
        self.assertEqual(Application.objects.count(), initial_effects)
        self.assertEqual(ApplicationRequestIntent.objects.count(), initial_effects)
        client = APIClient()
        client.force_authenticate(user)
        replay = client.post(url, {"company": "Same"}, format="json", HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(replay.status_code, 200 if initial_effects else 201)
        self.assertEqual(Application.objects.count(), 1)

    def test_simultaneous_manual_and_posting_requests_share_authority(self):
        user = User.objects.create_user(username="cross-path")
        workspace = Workspace.objects.create(owner=user, name="Concurrent")
        account = EmailAccount.objects.create(workspace=workspace, email="fixture@example.test")
        posting = JobPosting.objects.create(workspace=workspace, account=account, company="Same", title="", dedupe_key="concurrent")
        barrier = Barrier(2)
        urls = [f"/api/workspaces/{workspace.pk}/applications/", f"/api/workspaces/{workspace.pk}/job-postings/{posting.pk}/apply/"]
        keys = [uuid.uuid4().hex, uuid.uuid4().hex]
        def send(i):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(user)
                barrier.wait(timeout=10)
                return client.post(urls[i], {"company": "Same"}, format="json", HTTP_IDEMPOTENCY_KEY=keys[i]).status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(send, range(2)))
        self.assertLessEqual(outcomes.count(201), 1, outcomes)
        if connection.vendor != "sqlite":
            self.assertEqual(outcomes.count(201), 1, outcomes)
        self.assertEqual(Application.objects.count(), outcomes.count(201))
        self.assertTrue(set(outcomes) <= ({201, 409, 503} if connection.vendor == "sqlite" else {201, 409}), outcomes)
        client = APIClient()
        client.force_authenticate(user)
        for i, outcome in enumerate(outcomes):
            existed = Application.objects.exists()
            replay = client.post(urls[i], {"company": "Same"}, format="json", HTTP_IDEMPOTENCY_KEY=keys[i])
            self.assertEqual(replay.status_code, 200 if outcome == 201 else (409 if existed else 201))
        self.assertEqual(Application.objects.count(), 1)
