"""
Tests for EmailAccountSyncView (email_sync/views.py's manual "sync
now" endpoint, Phase 9, docs/DJANGO_MIGRATION_PLAN.md).

sync_account() itself is already exhaustively covered by
test_sync_service.py against FakeProvider -- these tests are about the
HTTP/ownership layer this view adds on top: does it find the right
account, refuse the wrong owner, resolve a provider correctly, and
shape sync_account()'s result as JSON. providers.get_provider() is
patched at the view's own import (email_sync.views.get_provider) so a
test can hand back a FakeProvider without touching real Gmail OAuth
machinery at all.
"""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace

from ..models import EmailAccount
from ..providers import ProviderError
from .test_sync_service import FakeProvider


class EmailAccountSyncViewTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.other_user = User.objects.create_user(username="bob", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.other_workspace = Workspace.objects.create(owner=self.other_user, name="Bob's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="gmail", email="alice@example.com"
        )
        self.client.force_authenticate(self.user)
        self.url = reverse("email-account-sync", args=[self.account.id])

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_404_for_nonexistent_account(self):
        url = reverse("email-account-sync", args=[999999])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_404_for_account_owned_by_another_user(self):
        other_account = EmailAccount.objects.create(
            workspace=self.other_workspace, provider="gmail", email="bob@example.com"
        )
        url = reverse("email-account-sync", args=[other_account.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_rejects_disconnected_account(self):
        self.account.status = "disconnected"
        self.account.save(update_fields=["status"])
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_when_no_provider_registered(self):
        self.account.provider = "mail_app"
        self.account.save(update_fields=["provider"])
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_successful_sync_returns_result_and_runs_sync_account(self):
        provider = FakeProvider([])
        with patch("email_sync.views.get_provider", return_value=provider):
            response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["account_id"], self.account.id)
        self.assertTrue(response.data["ok"])
        self.assertEqual(response.data["messages_seen"], 0)
        self.assertEqual(len(provider.calls), 1)
        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.last_synced_at)
        self.assertEqual(self.account.status, "connected")

    def test_provider_auth_error_is_reported_but_still_200(self):
        provider = FakeProvider([], raise_auth_error=True)
        with patch("email_sync.views.get_provider", return_value=provider):
            response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["ok"])
        self.assertEqual(response.data["status"], "blocked")
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "blocked")

    def test_get_provider_is_called_with_account_provider_name(self):
        provider = FakeProvider([])
        with patch("email_sync.views.get_provider", return_value=provider) as mock_get_provider:
            self.client.post(self.url)
        mock_get_provider.assert_called_once_with("gmail")

    def test_provider_error_message_surfaces_in_response(self):
        with patch(
            "email_sync.views.get_provider",
            side_effect=ProviderError("no email provider registered for 'mail_app' yet"),
        ):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("mail_app", response.data["detail"])
