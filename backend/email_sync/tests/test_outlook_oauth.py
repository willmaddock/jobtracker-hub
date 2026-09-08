"""
Tests for email_sync/outlook_oauth.py (Phase 9 second-provider slice,
docs/DJANGO_MIGRATION_PLAN.md). Everything that talks to Microsoft
over the network (`requests.post`/`requests.get` against the token
endpoint and Graph's /me) is mocked -- these tests exercise this
module's own logic (token encryption/storage, refresh-on-expiry,
account get_or_create/reactivation, error classification), not
Microsoft's API or OAuth endpoints themselves.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from accounts.models import Workspace

from .. import outlook_oauth
from ..models import EmailAccount, OutlookCredential
from ..providers import ProviderAuthError, get_provider


def _fake_response(status_code=200, json_body=None, text=""):
    resp = MagicMock(status_code=status_code)
    resp.json.return_value = json_body or {}
    resp.text = text
    return resp


class EncryptionRoundTripTests(TestCase):
    def test_encrypt_then_decrypt_recovers_original(self):
        secret = "EwB4A8l6BAAU...a-real-looking-access-token"
        ciphertext = outlook_oauth._encrypt(secret)
        self.assertNotEqual(ciphertext, secret)
        self.assertEqual(outlook_oauth._decrypt(ciphertext), secret)

    def test_decrypting_garbage_raises_provider_auth_error(self):
        with self.assertRaises(ProviderAuthError):
            outlook_oauth._decrypt("not-valid-fernet-ciphertext")


class StoreCredentialsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="outlook", email="alice@outlook.example"
        )

    def test_creates_credential_row_with_encrypted_tokens(self):
        outlook_oauth._store_credentials(
            self.account,
            {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 3600,
                "scope": "Mail.Read offline_access",
            },
        )

        row = OutlookCredential.objects.get(account=self.account)
        self.assertNotEqual(row.access_token, "access-1")
        self.assertNotEqual(row.refresh_token, "refresh-1")
        self.assertEqual(outlook_oauth._decrypt(row.access_token), "access-1")
        self.assertEqual(outlook_oauth._decrypt(row.refresh_token), "refresh-1")
        self.assertIsNotNone(row.token_expiry)

    def test_updating_without_new_refresh_token_preserves_old_one(self):
        outlook_oauth._store_credentials(
            self.account, {"access_token": "a1", "refresh_token": "r1", "expires_in": 3600}
        )
        # A routine access-token refresh commonly comes back with no
        # refresh_token at all -- simulate that by omitting the key.
        outlook_oauth._store_credentials(
            self.account, {"access_token": "a2", "expires_in": 3600}
        )

        row = OutlookCredential.objects.get(account=self.account)
        self.assertEqual(outlook_oauth._decrypt(row.access_token), "a2")
        self.assertEqual(outlook_oauth._decrypt(row.refresh_token), "r1")


class BuildAuthorizationUrlTests(TestCase):
    @override_settings(MICROSOFT_OAUTH_CLIENT_ID="", MICROSOFT_OAUTH_CLIENT_SECRET="")
    def test_raises_oauth_config_error_when_unconfigured(self):
        with self.assertRaises(outlook_oauth.OAuthConfigError):
            outlook_oauth.build_authorization_url()

    @override_settings(
        MICROSOFT_OAUTH_CLIENT_ID="client-id", MICROSOFT_OAUTH_CLIENT_SECRET="client-secret"
    )
    def test_returns_url_and_state(self):
        url, state = outlook_oauth.build_authorization_url()
        self.assertTrue(url.startswith(outlook_oauth._AUTH_URI))
        self.assertIn("client_id=client-id", url)
        self.assertIn(f"state={state}", url)
        self.assertTrue(state)


@override_settings(
    MICROSOFT_OAUTH_CLIENT_ID="client-id", MICROSOFT_OAUTH_CLIENT_SECRET="client-secret"
)
class CompleteOutlookConnectionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")

    def test_creates_new_account_and_stores_credentials(self):
        token_response = _fake_response(
            200, {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600}
        )
        profile_response = _fake_response(200, {"mail": "alice@outlook.com"})

        with patch.object(outlook_oauth.requests, "post", return_value=token_response), patch.object(
            outlook_oauth.requests, "get", return_value=profile_response
        ):
            account = outlook_oauth.complete_outlook_connection(
                self.workspace, code="auth-code", state="s1"
            )

        self.assertEqual(account.email, "alice@outlook.com")
        self.assertEqual(account.provider, "outlook")
        self.assertEqual(account.status, "connected")
        self.assertTrue(OutlookCredential.objects.filter(account=account).exists())

    def test_falls_back_to_user_principal_name_when_mail_is_null(self):
        token_response = _fake_response(
            200, {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600}
        )
        profile_response = _fake_response(
            200, {"mail": None, "userPrincipalName": "alice@tenant.onmicrosoft.com"}
        )

        with patch.object(outlook_oauth.requests, "post", return_value=token_response), patch.object(
            outlook_oauth.requests, "get", return_value=profile_response
        ):
            account = outlook_oauth.complete_outlook_connection(
                self.workspace, code="auth-code", state="s1"
            )

        self.assertEqual(account.email, "alice@tenant.onmicrosoft.com")

    def test_reconnecting_revives_existing_disconnected_account(self):
        existing = EmailAccount.objects.create(
            workspace=self.workspace,
            provider="outlook",
            email="alice@outlook.com",
            status="disconnected",
        )
        token_response = _fake_response(
            200, {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600}
        )
        profile_response = _fake_response(200, {"mail": "alice@outlook.com"})

        with patch.object(outlook_oauth.requests, "post", return_value=token_response), patch.object(
            outlook_oauth.requests, "get", return_value=profile_response
        ):
            account = outlook_oauth.complete_outlook_connection(
                self.workspace, code="auth-code", state="s1"
            )

        self.assertEqual(account.id, existing.id)
        self.assertEqual(EmailAccount.objects.filter(email="alice@outlook.com").count(), 1)
        account.refresh_from_db()
        self.assertEqual(account.status, "connected")

    def test_token_exchange_failure_raises_oauth_config_error(self):
        token_response = _fake_response(400, {"error": "invalid_grant"}, text="invalid_grant")
        with patch.object(outlook_oauth.requests, "post", return_value=token_response):
            with self.assertRaises(outlook_oauth.OAuthConfigError):
                outlook_oauth.complete_outlook_connection(self.workspace, code="bad-code", state="s1")


class LoadAccessTokenTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="outlook", email="alice@outlook.example"
        )

    def test_no_stored_credential_raises_provider_auth_error(self):
        with self.assertRaises(ProviderAuthError):
            outlook_oauth._load_access_token(self.account)

    def test_valid_unexpired_token_is_returned_without_refresh(self):
        future = datetime.now(dt_timezone.utc) + timedelta(hours=1)
        OutlookCredential.objects.create(
            account=self.account,
            access_token=outlook_oauth._encrypt("still-good"),
            refresh_token=outlook_oauth._encrypt("r1"),
            token_expiry=future,
        )
        with patch.object(outlook_oauth.requests, "post") as mock_post:
            token = outlook_oauth._load_access_token(self.account)
        self.assertEqual(token, "still-good")
        mock_post.assert_not_called()

    @override_settings(
        MICROSOFT_OAUTH_CLIENT_ID="client-id", MICROSOFT_OAUTH_CLIENT_SECRET="client-secret"
    )
    def test_expired_credential_is_refreshed_and_persisted(self):
        past = datetime.now(dt_timezone.utc) - timedelta(hours=1)
        OutlookCredential.objects.create(
            account=self.account,
            access_token=outlook_oauth._encrypt("a1"),
            refresh_token=outlook_oauth._encrypt("r1"),
            token_expiry=past,
        )
        refresh_response = _fake_response(
            200, {"access_token": "a2-refreshed", "refresh_token": "r1", "expires_in": 3600}
        )
        with patch.object(outlook_oauth.requests, "post", return_value=refresh_response) as mock_post:
            token = outlook_oauth._load_access_token(self.account)

        self.assertEqual(token, "a2-refreshed")
        mock_post.assert_called_once()
        row = OutlookCredential.objects.get(account=self.account)
        self.assertEqual(outlook_oauth._decrypt(row.access_token), "a2-refreshed")

    @override_settings(
        MICROSOFT_OAUTH_CLIENT_ID="client-id", MICROSOFT_OAUTH_CLIENT_SECRET="client-secret"
    )
    def test_refresh_failure_raises_provider_auth_error(self):
        past = datetime.now(dt_timezone.utc) - timedelta(hours=1)
        OutlookCredential.objects.create(
            account=self.account,
            access_token=outlook_oauth._encrypt("a1"),
            refresh_token=outlook_oauth._encrypt("r1"),
            token_expiry=past,
        )
        refresh_response = _fake_response(400, {"error": "invalid_grant"}, text="invalid_grant")
        with patch.object(outlook_oauth.requests, "post", return_value=refresh_response):
            with self.assertRaises(ProviderAuthError):
                outlook_oauth._load_access_token(self.account)


class OutlookSessionFactoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="outlook", email="alice@outlook.example"
        )

    def test_session_carries_bearer_token_on_get(self):
        future = datetime.now(dt_timezone.utc) + timedelta(hours=1)
        OutlookCredential.objects.create(
            account=self.account,
            access_token=outlook_oauth._encrypt("tok-123"),
            refresh_token=outlook_oauth._encrypt("r1"),
            token_expiry=future,
        )
        fake_response = _fake_response(200, {"value": []})
        with patch.object(outlook_oauth.requests, "get", return_value=fake_response) as mock_get:
            session = outlook_oauth.outlook_session_factory(self.account)
            session.get("https://graph.microsoft.com/v1.0/me/messages")

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok-123")


class ProviderRegistrationTests(TestCase):
    def test_get_provider_outlook_resolves_to_registered_outlook_provider(self):
        provider = get_provider("outlook")
        self.assertIsInstance(provider, outlook_oauth._RegisteredOutlookProvider)
        self.assertIs(provider._session_factory, outlook_oauth.outlook_session_factory)


class DisconnectOutlookAccountTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace,
            provider="outlook",
            email="alice@outlook.example",
            status="connected",
        )

    def test_deletes_credential_and_marks_disconnected(self):
        OutlookCredential.objects.create(
            account=self.account,
            access_token=outlook_oauth._encrypt("a1"),
            refresh_token=outlook_oauth._encrypt("r1"),
        )
        outlook_oauth.disconnect_outlook_account(self.account)

        self.assertFalse(OutlookCredential.objects.filter(account=self.account).exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "disconnected")

    def test_no_stored_credential_still_marks_disconnected(self):
        outlook_oauth.disconnect_outlook_account(self.account)
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "disconnected")
