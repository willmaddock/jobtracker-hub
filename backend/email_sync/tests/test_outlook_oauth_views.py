"""
Tests for the Outlook OAuth connect/callback endpoints
(email_sync/views.py, Phase 9 second-provider slice,
docs/DJANGO_MIGRATION_PLAN.md). Microsoft-facing calls are mocked at
the same seams email_sync/tests/test_outlook_oauth.py already uses;
these tests are about the HTTP/session layer on top -- ownership
checks, session state round-tripping, and status codes -- not the
OAuth exchange logic itself. Mirrors test_gmail_oauth_views.py
field-for-field.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace

from .. import outlook_oauth
from ..models import EmailAccount


def _fake_response(status_code=200, json_body=None, text=""):
    resp = MagicMock(status_code=status_code)
    resp.json.return_value = json_body or {}
    resp.text = text
    return resp


@override_settings(
    MICROSOFT_OAUTH_CLIENT_ID="client-id", MICROSOFT_OAUTH_CLIENT_SECRET="client-secret"
)
class OutlookConnectViewTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.other_user = User.objects.create_user(username="bob", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.other_workspace = Workspace.objects.create(owner=self.other_user, name="Bob's workspace")
        self.client.force_authenticate(self.user)
        self.url = reverse("outlook-oauth-connect")

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
        response = self.client.get(self.url, {"workspace": self.workspace.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["authorization_url"].startswith(outlook_oauth._AUTH_URI))
        session = self.client.session
        self.assertEqual(session["outlook_oauth_workspace_id"], self.workspace.id)
        self.assertIn("outlook_oauth_state", session)
        self.assertIn(session["outlook_oauth_state"], response.data["authorization_url"])

    @override_settings(MICROSOFT_OAUTH_CLIENT_ID="", MICROSOFT_OAUTH_CLIENT_SECRET="")
    def test_returns_503_when_oauth_not_configured(self):
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)


class OutlookOAuthCallbackViewTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.url = reverse("outlook-oauth-callback")

    def _seed_session_state(self, state="state-abc"):
        session = self.client.session
        session["outlook_oauth_state"] = state
        session["outlook_oauth_workspace_id"] = self.workspace.id
        session.save()

    def test_microsoft_error_param_returns_400(self):
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
        response = self.client.get(self.url, {"code": "abc", "state": "whatever"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(
        MICROSOFT_OAUTH_CLIENT_ID="client-id", MICROSOFT_OAUTH_CLIENT_SECRET="client-secret"
    )
    def test_successful_callback_connects_account_and_clears_session_state(self):
        self._seed_session_state(state="state-abc")

        token_response = _fake_response(
            200, {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600}
        )
        profile_response = _fake_response(200, {"mail": "alice@outlook.com"})

        with patch.object(outlook_oauth.requests, "post", return_value=token_response), patch.object(
            outlook_oauth.requests, "get", return_value=profile_response
        ):
            response = self.client.get(self.url, {"code": "auth-code", "state": "state-abc"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "alice@outlook.com")
        self.assertTrue(
            EmailAccount.objects.filter(
                workspace=self.workspace,
                email="alice@outlook.com",
                provider="outlook",
                status="connected",
            ).exists()
        )
        session = self.client.session
        self.assertNotIn("outlook_oauth_state", session)
        self.assertNotIn("outlook_oauth_workspace_id", session)

    @override_settings(MICROSOFT_OAUTH_CLIENT_ID="", MICROSOFT_OAUTH_CLIENT_SECRET="")
    def test_returns_503_when_oauth_not_configured(self):
        self._seed_session_state(state="state-abc")
        response = self.client.get(self.url, {"code": "auth-code", "state": "state-abc"})
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
