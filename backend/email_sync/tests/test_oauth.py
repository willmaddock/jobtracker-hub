"""
Tests for email_sync/oauth.py (Phase 9 OAuth slice,
docs/DJANGO_MIGRATION_PLAN.md). Everything that talks to Google over
the network (google_auth_oauthlib.flow.Flow, googleapiclient's
discovery `build()`) is mocked -- these tests exercise this module's
own logic (token encryption/storage, refresh-on-expiry, account
get_or_create/reactivation, error classification), not Google's API or
OAuth libraries themselves.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from google.auth.exceptions import RefreshError

from accounts.models import Workspace

from .. import oauth
from ..models import EmailAccount, GmailCredential
from ..providers import ProviderAuthError, get_provider


def _fake_google_credentials(
    token="access-tok",
    refresh_token="refresh-tok",
    expiry=None,
    scopes=None,
    valid=True,
):
    creds = MagicMock()
    creds.token = token
    creds.refresh_token = refresh_token
    creds.expiry = expiry
    creds.scopes = scopes or list(oauth.settings.GMAIL_OAUTH_SCOPES)
    creds.valid = valid
    return creds


class EncryptionRoundTripTests(TestCase):
    def test_encrypt_then_decrypt_recovers_original(self):
        secret = "ya29.some-real-looking-access-token"
        ciphertext = oauth._encrypt(secret)
        self.assertNotEqual(ciphertext, secret)
        self.assertEqual(oauth._decrypt(ciphertext), secret)

    def test_decrypting_garbage_raises_provider_auth_error(self):
        with self.assertRaises(ProviderAuthError):
            oauth._decrypt("not-valid-fernet-ciphertext")


class StoreCredentialsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="gmail", email="alice@example.com"
        )

    def test_creates_credential_row_with_encrypted_tokens(self):
        creds = _fake_google_credentials(
            token="access-1", refresh_token="refresh-1", expiry=datetime(2026, 6, 1, 12, 0)
        )
        oauth._store_credentials(self.account, creds)

        row = GmailCredential.objects.get(account=self.account)
        self.assertNotEqual(row.access_token, "access-1")
        self.assertNotEqual(row.refresh_token, "refresh-1")
        self.assertEqual(oauth._decrypt(row.access_token), "access-1")
        self.assertEqual(oauth._decrypt(row.refresh_token), "refresh-1")
        self.assertEqual(row.token_expiry, datetime(2026, 6, 1, 12, 0, tzinfo=dt_timezone.utc))

    def test_updating_without_new_refresh_token_preserves_old_one(self):
        oauth._store_credentials(
            self.account, _fake_google_credentials(token="a1", refresh_token="r1")
        )
        # A routine access-token refresh commonly comes back with no
        # refresh_token at all (Google only resends it when it
        # changes) -- simulate that by passing refresh_token=None.
        oauth._store_credentials(
            self.account, _fake_google_credentials(token="a2", refresh_token=None)
        )

        row = GmailCredential.objects.get(account=self.account)
        self.assertEqual(oauth._decrypt(row.access_token), "a2")
        self.assertEqual(oauth._decrypt(row.refresh_token), "r1")


class BuildAuthorizationUrlTests(TestCase):
    @override_settings(GOOGLE_OAUTH_CLIENT_ID="", GOOGLE_OAUTH_CLIENT_SECRET="")
    def test_raises_oauth_config_error_when_unconfigured(self):
        with self.assertRaises(oauth.OAuthConfigError):
            oauth.build_authorization_url()

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="client-id", GOOGLE_OAUTH_CLIENT_SECRET="client-secret"
    )
    def test_returns_url_and_state_from_flow(self):
        fake_flow = MagicMock()
        fake_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?...", "state-xyz")
        with patch.object(oauth.Flow, "from_client_config", return_value=fake_flow):
            url, state = oauth.build_authorization_url()

        self.assertEqual(state, "state-xyz")
        self.assertTrue(url.startswith("https://accounts.google.com"))
        fake_flow.authorization_url.assert_called_once_with(
            access_type="offline", prompt="consent", include_granted_scopes="true"
        )


@override_settings(GOOGLE_OAUTH_CLIENT_ID="client-id", GOOGLE_OAUTH_CLIENT_SECRET="client-secret")
class CompleteGmailConnectionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")

    def test_creates_new_account_and_stores_credentials(self):
        fake_flow = MagicMock()
        fake_flow.credentials = _fake_google_credentials(
            token="access-1", refresh_token="refresh-1"
        )
        fake_profile_service = MagicMock()
        fake_profile_service.users.return_value.getProfile.return_value.execute.return_value = {
            "emailAddress": "alice@gmail.com"
        }

        with patch.object(oauth.Flow, "from_client_config", return_value=fake_flow), patch.object(
            oauth, "build_gmail_client", return_value=fake_profile_service
        ):
            account = oauth.complete_gmail_connection(self.workspace, code="auth-code", state="s1")

        self.assertEqual(account.email, "alice@gmail.com")
        self.assertEqual(account.provider, "gmail")
        self.assertEqual(account.status, "connected")
        self.assertTrue(GmailCredential.objects.filter(account=account).exists())

    def test_reconnecting_revives_existing_disconnected_account(self):
        existing = EmailAccount.objects.create(
            workspace=self.workspace,
            provider="gmail",
            email="alice@gmail.com",
            status="disconnected",
        )
        fake_flow = MagicMock()
        fake_flow.credentials = _fake_google_credentials()
        fake_profile_service = MagicMock()
        fake_profile_service.users.return_value.getProfile.return_value.execute.return_value = {
            "emailAddress": "alice@gmail.com"
        }

        with patch.object(oauth.Flow, "from_client_config", return_value=fake_flow), patch.object(
            oauth, "build_gmail_client", return_value=fake_profile_service
        ):
            account = oauth.complete_gmail_connection(self.workspace, code="auth-code", state="s1")

        self.assertEqual(account.id, existing.id)
        self.assertEqual(EmailAccount.objects.filter(email="alice@gmail.com").count(), 1)
        account.refresh_from_db()
        self.assertEqual(account.status, "connected")


class LoadGoogleCredentialsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="gmail", email="alice@example.com"
        )

    def test_no_stored_credential_raises_provider_auth_error(self):
        with self.assertRaises(ProviderAuthError):
            oauth._load_google_credentials(self.account)

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="client-id", GOOGLE_OAUTH_CLIENT_SECRET="client-secret"
    )
    def test_valid_unexpired_credential_is_not_refreshed(self):
        future = datetime.now(dt_timezone.utc) + timedelta(hours=1)
        oauth._store_credentials(
            self.account, _fake_google_credentials(token="a1", refresh_token="r1", expiry=future)
        )

        fake_credentials_instance = MagicMock(valid=True)
        with patch.object(oauth, "Credentials", return_value=fake_credentials_instance) as CredsCls:
            result = oauth._load_google_credentials(self.account)

        fake_credentials_instance.refresh.assert_not_called()
        self.assertIs(result, fake_credentials_instance)
        CredsCls.assert_called_once()

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="client-id", GOOGLE_OAUTH_CLIENT_SECRET="client-secret"
    )
    def test_expired_credential_is_refreshed_and_persisted(self):
        past = datetime.now(dt_timezone.utc) - timedelta(hours=1)
        oauth._store_credentials(
            self.account, _fake_google_credentials(token="a1", refresh_token="r1", expiry=past)
        )

        def _refresh(request):
            fake_credentials_instance.valid = True
            fake_credentials_instance.token = "a2-refreshed"
            fake_credentials_instance.expiry = datetime.now(dt_timezone.utc) + timedelta(hours=1)

        fake_credentials_instance = MagicMock(valid=False, refresh_token="r1", scopes=oauth.settings.GMAIL_OAUTH_SCOPES)
        fake_credentials_instance.refresh.side_effect = _refresh

        with patch.object(oauth, "Credentials", return_value=fake_credentials_instance), patch.object(
            oauth, "GoogleAuthRequest"
        ):
            oauth._load_google_credentials(self.account)

        fake_credentials_instance.refresh.assert_called_once()
        row = GmailCredential.objects.get(account=self.account)
        self.assertEqual(oauth._decrypt(row.access_token), "a2-refreshed")

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="client-id", GOOGLE_OAUTH_CLIENT_SECRET="client-secret"
    )
    def test_refresh_error_raises_provider_auth_error_and_marks_account_reconnect_needed(self):
        past = datetime.now(dt_timezone.utc) - timedelta(hours=1)
        oauth._store_credentials(
            self.account, _fake_google_credentials(token="a1", refresh_token="r1", expiry=past)
        )

        fake_credentials_instance = MagicMock(valid=False)
        fake_credentials_instance.refresh.side_effect = RefreshError("invalid_grant")

        with patch.object(oauth, "Credentials", return_value=fake_credentials_instance), patch.object(
            oauth, "GoogleAuthRequest"
        ):
            with self.assertRaises(ProviderAuthError):
                oauth._load_google_credentials(self.account)


class GmailServiceFactoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="gmail", email="alice@example.com"
        )

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="client-id", GOOGLE_OAUTH_CLIENT_SECRET="client-secret"
    )
    def test_builds_gmail_client_with_loaded_credentials(self):
        future = datetime.now(dt_timezone.utc) + timedelta(hours=1)
        oauth._store_credentials(
            self.account, _fake_google_credentials(token="a1", refresh_token="r1", expiry=future)
        )
        fake_credentials_instance = MagicMock(valid=True)
        fake_service = MagicMock()

        with patch.object(oauth, "Credentials", return_value=fake_credentials_instance), patch.object(
            oauth, "build_gmail_client", return_value=fake_service
        ) as build_mock:
            service = oauth.gmail_service_factory(self.account)

        self.assertIs(service, fake_service)
        build_mock.assert_called_once_with(
            "gmail", "v1", credentials=fake_credentials_instance, cache_discovery=False
        )


class ProviderRegistrationTests(TestCase):
    def test_get_provider_gmail_resolves_to_registered_gmail_provider(self):
        provider = get_provider("gmail")
        self.assertIsInstance(provider, oauth._RegisteredGmailProvider)
        self.assertIs(provider._service_factory, oauth.gmail_service_factory)


class RevokeGmailTokenTests(TestCase):
    def test_200_response_is_treated_as_success(self):
        fake_response = MagicMock(status_code=200)
        with patch.object(oauth.requests, "post", return_value=fake_response) as mock_post:
            oauth.revoke_gmail_token("some-token")
        mock_post.assert_called_once_with(
            oauth._REVOKE_URI, params={"token": "some-token"}, timeout=10
        )

    def test_400_response_is_treated_as_success(self):
        # Google's response for a token it no longer recognizes --
        # already revoked or expired from disuse. Not an error from
        # this app's perspective: the grant is gone either way.
        fake_response = MagicMock(status_code=400)
        with patch.object(oauth.requests, "post", return_value=fake_response):
            oauth.revoke_gmail_token("some-token")  # should not raise

    def test_5xx_response_raises_provider_error(self):
        fake_response = MagicMock(status_code=503)
        with patch.object(oauth.requests, "post", return_value=fake_response):
            with self.assertRaises(oauth.ProviderError):
                oauth.revoke_gmail_token("some-token")

    def test_network_failure_raises_provider_error(self):
        with patch.object(
            oauth.requests, "post", side_effect=oauth.requests.ConnectionError("boom")
        ):
            with self.assertRaises(oauth.ProviderError):
                oauth.revoke_gmail_token("some-token")


class DisconnectGmailAccountTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="gmail", email="alice@example.com", status="connected"
        )

    def test_revokes_token_deletes_credential_and_marks_disconnected(self):
        oauth._store_credentials(self.account, _fake_google_credentials(refresh_token="refresh-1"))
        self.assertTrue(GmailCredential.objects.filter(account=self.account).exists())

        with patch.object(oauth, "revoke_gmail_token") as mock_revoke:
            oauth.disconnect_gmail_account(self.account)

        mock_revoke.assert_called_once_with("refresh-1")
        self.assertFalse(GmailCredential.objects.filter(account=self.account).exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "disconnected")

    def test_falls_back_to_access_token_when_refresh_token_undecryptable(self):
        cred = GmailCredential.objects.create(
            account=self.account,
            access_token=oauth._encrypt("access-only"),
            refresh_token="not-valid-fernet-ciphertext",
        )
        with patch.object(oauth, "revoke_gmail_token") as mock_revoke:
            oauth.disconnect_gmail_account(self.account)
        mock_revoke.assert_called_once_with("access-only")
        self.assertFalse(GmailCredential.objects.filter(id=cred.id).exists())

    def test_no_stored_credential_still_marks_disconnected(self):
        # No GmailCredential row at all -- e.g. an account whose OAuth
        # exchange never completed. Disconnect should still succeed
        # rather than erroring on a row that was never there.
        oauth.disconnect_gmail_account(self.account)
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "disconnected")

    def test_revoke_failure_does_not_block_local_cleanup(self):
        oauth._store_credentials(self.account, _fake_google_credentials(refresh_token="refresh-1"))
        with patch.object(oauth, "revoke_gmail_token", side_effect=oauth.ProviderError("network down")):
            oauth.disconnect_gmail_account(self.account)  # should not raise

        self.assertFalse(GmailCredential.objects.filter(account=self.account).exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "disconnected")

    def test_undecryptable_credential_with_no_recoverable_token_still_deletes_row(self):
        cred = GmailCredential.objects.create(
            account=self.account,
            access_token="",
            refresh_token="not-valid-fernet-ciphertext",
        )
        with patch.object(oauth, "revoke_gmail_token") as mock_revoke:
            oauth.disconnect_gmail_account(self.account)
        mock_revoke.assert_not_called()
        self.assertFalse(GmailCredential.objects.filter(id=cred.id).exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "disconnected")
