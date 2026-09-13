"""
Tests for the IMAP connect endpoint (email_sync/views.py, Phase 9
third-provider slice, docs/DJANGO_MIGRATION_PLAN.md). Real IMAP calls
are mocked at the same seam email_sync/tests/test_imap_auth.py already
uses (imaplib.IMAP4_SSL); these tests are about the HTTP layer on top
-- ownership checks, required fields, and status codes -- not the
verify-then-store logic itself, which test_imap_auth.py already
covers directly.
"""
from __future__ import annotations

import imaplib
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace

from ..models import EmailAccount, IMAPCredential


def _fake_imap_client(select_typ="OK"):
    client = MagicMock()
    client.login.return_value = ("OK", [b"LOGIN completed"])
    client.select.return_value = (select_typ, [b"1"])
    return client


class ImapConnectViewTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.other_user = User.objects.create_user(username="bob", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.other_workspace = Workspace.objects.create(owner=self.other_user, name="Bob's workspace")
        self.client.force_authenticate(self.user)
        self.url = reverse("imap-connect")
        self.valid_body = {
            "workspace": None,  # set per-test
            "email": "alice@example.com",
            "password": "app-password-1",
            "host": "imap.example.com",
            "port": 993,
        }

    def _body(self, **overrides):
        body = dict(self.valid_body, workspace=self.workspace.id)
        body.update(overrides)
        return body

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        response = self.client.post(self.url, self._body())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_requires_workspace_email_password_host(self):
        for missing_field in ("workspace", "email", "password", "host"):
            body = self._body()
            body.pop(missing_field)
            response = self.client.post(self.url, body)
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                msg=f"expected 400 when {missing_field!r} is missing",
            )

    def test_rejects_workspace_not_owned_by_user(self):
        response = self.client.post(self.url, self._body(workspace=self.other_workspace.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_integer_port_returns_400(self):
        response = self.client.post(self.url, self._body(port="not-a-number"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_successful_connect_returns_200_and_creates_account(self):
        client = _fake_imap_client()
        with patch.object(imaplib, "IMAP4_SSL", return_value=client):
            response = self.client.post(self.url, self._body())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "alice@example.com")
        self.assertEqual(response.data["status"], "connected")
        account = EmailAccount.objects.get(email="alice@example.com")
        self.assertEqual(account.provider, "imap")
        self.assertTrue(IMAPCredential.objects.filter(account=account).exists())

    def test_wrong_password_returns_400(self):
        client = MagicMock()
        client.login.side_effect = imaplib.IMAP4.error("LOGIN failed")
        with patch.object(imaplib, "IMAP4_SSL", return_value=client):
            response = self.client.post(self.url, self._body(password="wrong"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(EmailAccount.objects.filter(email="alice@example.com").exists())

    def test_unreachable_host_returns_503(self):
        import socket

        with patch.object(imaplib, "IMAP4_SSL", side_effect=socket.gaierror("no such host")):
            response = self.client.post(self.url, self._body(host="nonexistent.invalid"))

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_retired_basic_auth_domain_returns_400_without_connecting(self):
        with patch.object(imaplib, "IMAP4_SSL") as mock_ssl:
            response = self.client.post(
                self.url,
                self._body(email="alice@outlook.com", host="outlook.office365.com"),
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_ssl.assert_not_called()

    def test_defaults_port_when_omitted(self):
        body = self._body()
        body.pop("port")
        client = _fake_imap_client()
        with patch.object(imaplib, "IMAP4_SSL", return_value=client) as mock_ssl:
            response = self.client.post(self.url, body)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(mock_ssl.call_args[0][1], 993)

    def test_custom_username_is_used_for_login(self):
        client = _fake_imap_client()
        with patch.object(imaplib, "IMAP4_SSL", return_value=client):
            response = self.client.post(self.url, self._body(username="alice.mailbox"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        client.login.assert_called_once_with("alice.mailbox", "app-password-1")
