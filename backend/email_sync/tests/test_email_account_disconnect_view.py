"""
Tests for EmailAccountDisconnectView (email_sync/views.py's disconnect
endpoint, Phase 9, docs/DJANGO_MIGRATION_PLAN.md).

oauth.disconnect_gmail_account()'s own revoke/cleanup logic is already
covered by test_oauth.py's DisconnectGmailAccountTests -- these tests
are about the HTTP/ownership layer on top: does it find the right
account, refuse the wrong owner, route to the Gmail-specific cleanup
only for gmail accounts, and behave idempotently on a second call.
oauth.disconnect_gmail_account is patched at the view's own import
(email_sync.views.oauth) so these tests never touch Google's revoke
endpoint.
"""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace

from ..models import EmailAccount, GmailCredential
from .. import oauth


class EmailAccountDisconnectViewTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.other_user = User.objects.create_user(username="bob", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.other_workspace = Workspace.objects.create(owner=self.other_user, name="Bob's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="gmail", email="alice@example.com", status="connected"
        )
        self.client.force_authenticate(self.user)
        self.url = reverse("email-account-disconnect", args=[self.account.id])

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_404_for_nonexistent_account(self):
        url = reverse("email-account-disconnect", args=[999999])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_404_for_account_owned_by_another_user(self):
        other_account = EmailAccount.objects.create(
            workspace=self.other_workspace, provider="gmail", email="bob@example.com"
        )
        url = reverse("email-account-disconnect", args=[other_account.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_gmail_account_routes_to_oauth_disconnect(self):
        with patch.object(oauth, "disconnect_gmail_account") as mock_disconnect:
            def _side_effect(account):
                account.status = "disconnected"
                account.save(update_fields=["status"])
            mock_disconnect.side_effect = _side_effect

            response = self.client.post(self.url)

        mock_disconnect.assert_called_once()
        self.assertEqual(mock_disconnect.call_args[0][0].id, self.account.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "disconnected")

    def test_non_gmail_account_just_flips_status(self):
        self.account.provider = "mail_app"
        self.account.save(update_fields=["provider"])

        with patch.object(oauth, "disconnect_gmail_account") as mock_disconnect:
            response = self.client.post(self.url)

        mock_disconnect.assert_not_called()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "disconnected")
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "disconnected")

    def test_idempotent_on_already_disconnected_account(self):
        self.account.status = "disconnected"
        self.account.save(update_fields=["status"])

        with patch.object(oauth, "disconnect_gmail_account") as mock_disconnect:
            response = self.client.post(self.url)

        mock_disconnect.assert_not_called()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "disconnected")

    def test_end_to_end_deletes_real_credential_row(self):
        oauth._store_credentials(
            self.account,
            type("Creds", (), {"token": "a1", "refresh_token": "r1", "expiry": None, "scopes": []})(),
        )
        self.assertTrue(GmailCredential.objects.filter(account=self.account).exists())

        with patch.object(oauth, "revoke_gmail_token"):
            response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(GmailCredential.objects.filter(account=self.account).exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "disconnected")
