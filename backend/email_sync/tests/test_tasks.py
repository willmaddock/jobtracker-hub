"""
Tests for email_sync/tasks.py's two Celery tasks (Phase 10 background
task runner).

Both tasks are called directly as plain functions here (e.g.
`sync_account_task(account.id)`, not `.delay(...)`) -- a
`@shared_task`-decorated callable still runs its body synchronously,
in-process, when invoked this way; only `.delay()`/`.apply_async()`
need a real broker. That means these tests exercise the exact same
code a worker would run, without needing Redis/a running worker in
this sandbox (same "no network access" constraint every earlier
checkpoint on this track has flagged -- see
docs/DJANGO_BACKEND_HANDOFF.md).

sync_account() itself is already exhaustively covered by
test_sync_service.py against FakeProvider; these tests are about the
task-level wrapping on top: id-vs-instance lookup, the disconnected/
missing-account/no-provider guard clauses, and sync_all_accounts_task's
fan-out (`.delay` is patched there specifically, since asserting *what
was dispatched* is the point of that test, not actually running each
dispatched task).
"""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Workspace

from ..models import EmailAccount
from ..providers import ProviderError
from .test_sync_service import FakeProvider
from ..tasks import sync_account_task, sync_all_accounts_task


class SyncAccountTaskTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="gmail", email="alice@example.com"
        )

    def test_missing_account_returns_not_ok_without_raising(self):
        result = sync_account_task(999999)
        self.assertFalse(result["ok"])
        self.assertEqual(result["account_id"], 999999)
        self.assertIn("not found", result["error"])

    def test_disconnected_account_is_skipped(self):
        self.account.status = "disconnected"
        self.account.save(update_fields=["status"])
        result = sync_account_task(self.account.id)
        self.assertFalse(result["ok"])
        self.assertIn("disconnected", result["error"])

    def test_no_registered_provider_returns_not_ok_without_raising(self):
        self.account.provider = "mail_app"
        self.account.save(update_fields=["provider"])
        with patch(
            "email_sync.tasks.get_provider",
            side_effect=ProviderError("no email provider registered for 'mail_app' yet"),
        ):
            result = sync_account_task(self.account.id)
        self.assertFalse(result["ok"])
        self.assertIn("mail_app", result["error"])

    def test_successful_sync_returns_result_dict_and_runs_sync_account(self):
        provider = FakeProvider([])
        with patch("email_sync.tasks.get_provider", return_value=provider):
            result = sync_account_task(self.account.id)

        self.assertTrue(result["ok"])
        self.assertEqual(result["account_id"], self.account.id)
        self.assertEqual(result["messages_seen"], 0)
        self.assertEqual(len(provider.calls), 1)
        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.last_synced_at)
        self.assertEqual(self.account.status, "connected")

    def test_provider_auth_error_is_reported_but_task_does_not_raise(self):
        provider = FakeProvider([], raise_auth_error=True)
        with patch("email_sync.tasks.get_provider", return_value=provider):
            result = sync_account_task(self.account.id)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "blocked")
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "blocked")


class SyncAllAccountsTaskTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")

    def test_dispatches_one_task_per_connected_account_only(self):
        connected = EmailAccount.objects.create(
            workspace=self.workspace, provider="gmail", email="a@example.com", status="connected"
        )
        EmailAccount.objects.create(
            workspace=self.workspace, provider="outlook", email="b@example.com", status="disconnected"
        )
        EmailAccount.objects.create(
            workspace=self.workspace, provider="imap", email="c@example.com", status="blocked"
        )

        with patch("email_sync.tasks.sync_account_task.delay") as mock_delay:
            result = sync_all_accounts_task()

        mock_delay.assert_called_once_with(connected.id)
        self.assertEqual(result["dispatched"], 1)

    def test_no_connected_accounts_dispatches_nothing(self):
        with patch("email_sync.tasks.sync_account_task.delay") as mock_delay:
            result = sync_all_accounts_task()

        mock_delay.assert_not_called()
        self.assertEqual(result["dispatched"], 0)
