"""
Tests for EmailAccountSyncAllView (email_sync/views.py's bulk "sync
all my accounts" endpoint, Phase 10).

This view only dispatches -- it never runs sync_account() itself --
so `email_sync.tasks.sync_account_task.delay` is patched throughout
rather than a provider, the same way test_email_account_sync_view.py
patches `email_sync.views.get_provider` rather than exercising a real
provider. What's under test here is the ownership scoping (only the
authenticated user's own connected accounts get dispatched) and the
response shape, not sync_account_task's own behavior -- that's
test_tasks.py's job.
"""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Workspace

from ..models import EmailAccount


class EmailAccountSyncAllViewTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.other_user = User.objects.create_user(username="bob", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.other_workspace = Workspace.objects.create(owner=self.other_user, name="Bob's workspace")
        self.client.force_authenticate(self.user)
        self.url = reverse("email-account-sync-all")

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_no_accounts_dispatches_nothing(self):
        with patch("email_sync.views.sync_account_task.delay") as mock_delay:
            response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["dispatched"], 0)
        self.assertEqual(response.data["account_ids"], [])
        mock_delay.assert_not_called()

    def test_dispatches_only_the_users_own_connected_accounts(self):
        mine_connected = EmailAccount.objects.create(
            workspace=self.workspace, provider="gmail", email="a@example.com", status="connected"
        )
        EmailAccount.objects.create(
            workspace=self.workspace, provider="outlook", email="b@example.com", status="disconnected"
        )
        EmailAccount.objects.create(
            workspace=self.other_workspace,
            provider="gmail",
            email="c@example.com",
            status="connected",
        )

        with patch("email_sync.views.sync_account_task.delay") as mock_delay:
            response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["dispatched"], 1)
        self.assertEqual(response.data["account_ids"], [mine_connected.id])
        mock_delay.assert_called_once_with(mine_connected.id)

    def test_dispatches_all_of_the_users_connected_accounts_across_multiple(self):
        first = EmailAccount.objects.create(
            workspace=self.workspace, provider="gmail", email="a@example.com", status="connected"
        )
        second = EmailAccount.objects.create(
            workspace=self.workspace, provider="outlook", email="b@example.com", status="connected"
        )

        with patch("email_sync.views.sync_account_task.delay") as mock_delay:
            response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["dispatched"], 2)
        self.assertCountEqual(response.data["account_ids"], [first.id, second.id])
        self.assertEqual(mock_delay.call_count, 2)
