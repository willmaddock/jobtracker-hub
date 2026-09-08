"""
Tests for email_sync/imap_auth.py (Phase 9 third-provider slice,
docs/DJANGO_MIGRATION_PLAN.md). Everything that talks to a real IMAP
server (`imaplib.IMAP4_SSL`) is mocked -- these tests exercise this
module's own logic (credential encryption/storage, verify-then-store
ordering, account get_or_create/reactivation, blocked-domain
rejection, error classification), not any real mail server.
"""
from __future__ import annotations

import imaplib
import socket
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Workspace

from .. import imap_auth
from ..models import EmailAccount, IMAPCredential
from ..providers import ProviderAuthError, ProviderError, get_provider


def _fake_imap_client(select_typ="OK"):
    client = MagicMock()
    client.login.return_value = ("OK", [b"LOGIN completed"])
    client.select.return_value = (select_typ, [b"1"])
    return client


class EncryptionRoundTripTests(TestCase):
    def test_encrypt_then_decrypt_recovers_original(self):
        secret = "a-real-looking-app-password"
        ciphertext = imap_auth._encrypt(secret)
        self.assertNotEqual(ciphertext, secret)
        self.assertEqual(imap_auth._decrypt(ciphertext), secret)

    def test_decrypting_garbage_raises_provider_auth_error(self):
        with self.assertRaises(ProviderAuthError):
            imap_auth._decrypt("not-valid-fernet-ciphertext")


class BlockedDomainTests(TestCase):
    def test_rejects_outlook_domain(self):
        with self.assertRaises(ProviderError):
            imap_auth._reject_if_basic_auth_retired("alice@outlook.com")

    def test_rejects_hotmail_domain_case_insensitively(self):
        with self.assertRaises(ProviderError):
            imap_auth._reject_if_basic_auth_retired("alice@HotMail.COM")

    def test_allows_other_domains(self):
        imap_auth._reject_if_basic_auth_retired("alice@example.com")  # no raise


class ConnectImapAccountTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")

    def test_creates_account_and_stores_encrypted_credential(self):
        client = _fake_imap_client()
        with patch.object(imaplib, "IMAP4_SSL", return_value=client):
            account = imap_auth.connect_imap_account(
                self.workspace,
                email="alice@example.com",
                password="app-password-1",
                host="imap.example.com",
                port=993,
            )

        self.assertEqual(account.email, "alice@example.com")
        self.assertEqual(account.provider, "imap")
        self.assertEqual(account.status, "connected")
        client.login.assert_called_once_with("alice@example.com", "app-password-1")
        client.select.assert_called_once_with("INBOX")
        client.logout.assert_called_once()

        row = IMAPCredential.objects.get(account=account)
        self.assertEqual(row.host, "imap.example.com")
        self.assertEqual(row.port, 993)
        self.assertEqual(row.username, "alice@example.com")
        self.assertNotEqual(row.password, "app-password-1")
        self.assertEqual(imap_auth._decrypt(row.password), "app-password-1")

    def test_separate_username_overrides_email(self):
        client = _fake_imap_client()
        with patch.object(imaplib, "IMAP4_SSL", return_value=client):
            account = imap_auth.connect_imap_account(
                self.workspace,
                email="alice@example.com",
                password="pw1",
                host="imap.example.com",
                username="alice.mailbox",
            )
        client.login.assert_called_once_with("alice.mailbox", "pw1")
        row = IMAPCredential.objects.get(account=account)
        self.assertEqual(row.username, "alice.mailbox")

    def test_defaults_to_standard_port(self):
        client = _fake_imap_client()
        with patch.object(imaplib, "IMAP4_SSL", return_value=client) as mock_ssl:
            imap_auth.connect_imap_account(
                self.workspace, email="alice@example.com", password="pw1", host="imap.example.com"
            )
        _args, kwargs = mock_ssl.call_args
        # host/port are positional in imap_auth._open_connection.
        self.assertEqual(mock_ssl.call_args[0][0], "imap.example.com")
        self.assertEqual(mock_ssl.call_args[0][1], 993)

    def test_rejects_retired_basic_auth_domain_before_connecting(self):
        with patch.object(imaplib, "IMAP4_SSL") as mock_ssl:
            with self.assertRaises(ProviderError):
                imap_auth.connect_imap_account(
                    self.workspace,
                    email="alice@outlook.com",
                    password="pw1",
                    host="outlook.office365.com",
                )
        mock_ssl.assert_not_called()

    def test_unreachable_host_raises_connection_error(self):
        with patch.object(imaplib, "IMAP4_SSL", side_effect=socket.gaierror("no such host")):
            with self.assertRaises(imap_auth.ImapConnectionError):
                imap_auth.connect_imap_account(
                    self.workspace,
                    email="alice@example.com",
                    password="pw1",
                    host="nonexistent.invalid",
                )
        self.assertFalse(EmailAccount.objects.filter(email="alice@example.com").exists())

    def test_rejected_login_raises_provider_auth_error_and_stores_nothing(self):
        client = MagicMock()
        client.login.side_effect = imaplib.IMAP4.error("LOGIN failed")
        with patch.object(imaplib, "IMAP4_SSL", return_value=client):
            with self.assertRaises(ProviderAuthError):
                imap_auth.connect_imap_account(
                    self.workspace,
                    email="alice@example.com",
                    password="wrong-password",
                    host="imap.example.com",
                )
        self.assertFalse(EmailAccount.objects.filter(email="alice@example.com").exists())
        client.logout.assert_called_once()

    def test_select_inbox_failure_raises_provider_auth_error(self):
        client = _fake_imap_client(select_typ="NO")
        with patch.object(imaplib, "IMAP4_SSL", return_value=client):
            with self.assertRaises(ProviderAuthError):
                imap_auth.connect_imap_account(
                    self.workspace,
                    email="alice@example.com",
                    password="pw1",
                    host="imap.example.com",
                )
        self.assertFalse(EmailAccount.objects.filter(email="alice@example.com").exists())

    def test_reconnecting_revives_existing_disconnected_account(self):
        existing = EmailAccount.objects.create(
            workspace=self.workspace,
            provider="imap",
            email="alice@example.com",
            status="disconnected",
        )
        client = _fake_imap_client()
        with patch.object(imaplib, "IMAP4_SSL", return_value=client):
            account = imap_auth.connect_imap_account(
                self.workspace,
                email="alice@example.com",
                password="pw1",
                host="imap.example.com",
            )
        self.assertEqual(account.id, existing.id)
        self.assertEqual(EmailAccount.objects.filter(email="alice@example.com").count(), 1)
        account.refresh_from_db()
        self.assertEqual(account.status, "connected")

    def test_reconnecting_overwrites_previous_credential_row(self):
        client = _fake_imap_client()
        with patch.object(imaplib, "IMAP4_SSL", return_value=client):
            account = imap_auth.connect_imap_account(
                self.workspace, email="alice@example.com", password="pw1", host="imap.example.com"
            )
            imap_auth.connect_imap_account(
                self.workspace, email="alice@example.com", password="pw2", host="imap.example.com"
            )
        self.assertEqual(IMAPCredential.objects.filter(account=account).count(), 1)
        row = IMAPCredential.objects.get(account=account)
        self.assertEqual(imap_auth._decrypt(row.password), "pw2")


class ImapClientFactoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="imap", email="alice@example.com"
        )

    def test_no_stored_credential_raises_provider_auth_error(self):
        with self.assertRaises(ProviderAuthError):
            imap_auth.imap_client_factory(self.account)

    def test_opens_connection_with_stored_credential(self):
        IMAPCredential.objects.create(
            account=self.account,
            host="imap.example.com",
            port=993,
            username="alice@example.com",
            password=imap_auth._encrypt("stored-pw"),
        )
        client = _fake_imap_client()
        with patch.object(imaplib, "IMAP4_SSL", return_value=client) as mock_ssl:
            result = imap_auth.imap_client_factory(self.account)

        mock_ssl.assert_called_once()
        self.assertEqual(mock_ssl.call_args[0][0], "imap.example.com")
        self.assertEqual(mock_ssl.call_args[0][1], 993)
        client.login.assert_called_once_with("alice@example.com", "stored-pw")
        client.select.assert_called_once_with("INBOX")
        self.assertIs(result, client)

    def test_select_failure_logs_out_and_raises(self):
        IMAPCredential.objects.create(
            account=self.account,
            host="imap.example.com",
            port=993,
            username="alice@example.com",
            password=imap_auth._encrypt("stored-pw"),
        )
        client = _fake_imap_client(select_typ="NO")
        with patch.object(imaplib, "IMAP4_SSL", return_value=client):
            with self.assertRaises(ProviderAuthError):
                imap_auth.imap_client_factory(self.account)
        client.logout.assert_called_once()


class DisconnectImapAccountTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="imap", email="alice@example.com"
        )

    def test_deletes_credential_and_marks_disconnected(self):
        IMAPCredential.objects.create(
            account=self.account,
            host="imap.example.com",
            port=993,
            username="alice@example.com",
            password=imap_auth._encrypt("pw"),
        )
        imap_auth.disconnect_imap_account(self.account)
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "disconnected")
        self.assertFalse(IMAPCredential.objects.filter(account=self.account).exists())

    def test_idempotent_when_already_disconnected(self):
        self.account.status = "disconnected"
        self.account.save(update_fields=["status"])
        imap_auth.disconnect_imap_account(self.account)  # should not raise
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "disconnected")


class ProviderRegistrationTests(TestCase):
    def test_imap_is_registered(self):
        provider = get_provider("imap")
        self.assertIsInstance(provider, imap_auth._RegisteredImapProvider)
