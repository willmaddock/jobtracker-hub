"""
Tests for the Gmail OAuth connect/callback endpoints
(email_sync/views.py, Phase 9 OAuth slice,
docs/DJANGO_MIGRATION_PLAN.md). Google-facing calls are mocked at the
same seams email_sync/tests/test_oauth.py already uses; these tests
are about the HTTP/session layer on top -- ownership checks, session
state round-tripping, and status codes -- not the OAuth exchange logic
itself.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace

from .. import oauth
from ..models import EmailAccount


@override_settings(GOOGLE_OAUTH_CLIENT_ID="client-id", GOOGLE_OAUTH_CLIENT_SECRET="client-secret")
class GmailConnectViewTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.other_user = User.objects.create_user(username="bob", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.other_workspace = Workspace.objects.create(owner=self.other_user, name="Bob's workspace")
        self.client.force_authenticate(self.user)
        self.url = reverse("gmail-oauth-connect")

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_requires_workspace_param(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_workspace_not_owned_by_user(self):
        response = self.client.get(self.url, {"workspace": self.other_workspace.id})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_returns_authorization_url_and_stashes_session_state(self):
        fake_flow = MagicMock()
        fake_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?x=1", "state-abc")
        fake_flow.code_verifier = "verifier-abc"
        with patch.object(oauth.Flow, "from_client_config", return_value=fake_flow):
            response = self.client.get(self.url, {"workspace": self.workspace.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["authorization_url"], "https://accounts.google.com/o/oauth2/auth?x=1")
        session = self.client.session
        self.assertEqual(session["gmail_oauth_state"], "state-abc")
        self.assertEqual(session["gmail_oauth_workspace_id"], self.workspace.id)
        self.assertEqual(session["gmail_oauth_code_verifier"], "verifier-abc")

    @override_settings(GOOGLE_OAUTH_CLIENT_ID="", GOOGLE_OAUTH_CLIENT_SECRET="")
    def test_returns_503_when_oauth_not_configured(self):
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)


class GmailOAuthCallbackViewTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.url = reverse("gmail-oauth-callback")

    def _seed_session_state(self, state="state-abc", code_verifier="verifier-abc"):
        session = self.client.session
        session["gmail_oauth_state"] = state
        session["gmail_oauth_workspace_id"] = self.workspace.id
        session["gmail_oauth_code_verifier"] = code_verifier
        session.save()

    def test_google_error_param_returns_400(self):
        response = self.client.get(self.url, {"error": "access_denied"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_code_or_state_returns_400(self):
        response = self.client.get(self.url, {"code": "abc"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_state_mismatch_is_rejected(self):
        self._seed_session_state(state="expected-state")
        response = self.client.get(self.url, {"code": "abc", "state": "wrong-state"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_prior_connect_call_is_rejected(self):
        # No session state seeded at all -- e.g. a stale/replayed
        # callback URL hit directly.
        response = self.client.get(self.url, {"code": "abc", "state": "whatever"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(GOOGLE_OAUTH_CLIENT_ID="client-id", GOOGLE_OAUTH_CLIENT_SECRET="client-secret")
    def test_successful_callback_connects_account_and_clears_session_state(self):
        self._seed_session_state(state="state-abc")

        fake_flow = MagicMock()
        fake_flow.credentials = MagicMock(
            token="access-1", refresh_token="refresh-1", expiry=None, scopes=oauth.settings.GMAIL_OAUTH_SCOPES
        )
        fake_profile_service = MagicMock()
        fake_profile_service.users.return_value.getProfile.return_value.execute.return_value = {
            "emailAddress": "alice@gmail.com"
        }

        with patch.object(oauth.Flow, "from_client_config", return_value=fake_flow), patch.object(
            oauth, "build_gmail_client", return_value=fake_profile_service
        ):
            response = self.client.get(self.url, {"code": "auth-code", "state": "state-abc"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "alice@gmail.com")
        self.assertTrue(
            EmailAccount.objects.filter(
                workspace=self.workspace, email="alice@gmail.com", provider="gmail", status="connected"
            ).exists()
        )
        # The stashed PKCE verifier should have been threaded through
        # to the flow used for the token exchange.
        self.assertEqual(fake_flow.code_verifier, "verifier-abc")
        session = self.client.session
        self.assertNotIn("gmail_oauth_state", session)
        self.assertNotIn("gmail_oauth_workspace_id", session)
        self.assertNotIn("gmail_oauth_code_verifier", session)

    @override_settings(GOOGLE_OAUTH_CLIENT_ID="", GOOGLE_OAUTH_CLIENT_SECRET="")
    def test_returns_503_when_oauth_not_configured(self):
        self._seed_session_state(state="state-abc")
        response = self.client.get(self.url, {"code": "auth-code", "state": "state-abc"})
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
