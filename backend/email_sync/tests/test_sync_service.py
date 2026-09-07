"""
Tests for email_sync/sync_service.py -- the provider-agnostic sync
orchestration layer (Phase 9 scoping slice, docs/DJANGO_MIGRATION_PLAN.md).

Exercises sync_account() end-to-end against FakeProvider, an in-memory
EmailProvider double defined here rather than in providers.py itself:
sync_service.py is meant to be fully testable with zero OAuth
credentials or real provider code, and a fake belongs next to the
tests that need it, not shipped as part of the production provider
interface.
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from typing import Iterable

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Workspace
from applications.models import Application

from ..models import AccountMatch, Discovery, EmailAccount, JobPostingSender, ThreadIdentifier
from ..providers import EmailProvider, FetchedMessage, ProviderAuthError
from ..sync_service import sync_account


def _dt(*args) -> datetime:
    return datetime(*args, tzinfo=dt_timezone.utc)


class FakeProvider(EmailProvider):
    """In-memory EmailProvider double. `messages` is the fixed list of
    FetchedMessage this provider hands back on every call -- tests set
    it up directly rather than simulating any real search/filter
    behavior, since sync_service.py (not the provider) owns all
    classification logic; a provider's only job is "hand back
    messages." `raise_auth_error`, when set, makes fetch_messages()
    raise ProviderAuthError instead, for exercising sync_account()'s
    error path."""

    def __init__(self, messages: Iterable[FetchedMessage] = (), raise_auth_error: bool = False):
        self.messages = list(messages)
        self.raise_auth_error = raise_auth_error
        self.calls: list[tuple[list[str], datetime | None]] = []

    def fetch_messages(self, account, terms, since=None):
        self.calls.append((list(terms), since))
        if self.raise_auth_error:
            raise ProviderAuthError("credentials revoked")
        return list(self.messages)


class SyncServiceTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="gmail", email="alice@example.com"
        )

    def _application(self, company, role_label="Backend Engineer", **kwargs):
        return Application.objects.create(
            workspace=self.workspace,
            section="applications",
            company=company,
            role_label=role_label,
            source_relpath="",
            **kwargs,
        )


class ConfirmedMatchTests(SyncServiceTestCase):
    def test_single_term_match_creates_confirmed_account_match(self):
        app = self._application("Acme Robotics")
        message = FetchedMessage(
            message_id="<msg-1@acme.example>",
            subject="Your application to Acme Robotics",
            sender="no-reply@greenhouse.io",
            received_at=_dt(2025, 7, 1),
            body="Thanks for applying to Acme Robotics.",
        )
        provider = FakeProvider([message])

        result = sync_account(self.account, provider, now=_dt(2025, 7, 2))

        self.assertTrue(result.ok)
        self.assertEqual(result.new_matches, 1)
        self.assertEqual(result.new_discoveries, 0)
        match = AccountMatch.objects.get(account=self.account, message_id="<msg-1@acme.example>")
        self.assertEqual(match.application, app)
        self.account.refresh_from_db()
        self.assertEqual(self.account.matched_email_count, 1)
        self.assertEqual(self.account.last_synced_at, _dt(2025, 7, 2))
        self.assertEqual(self.account.status, "connected")

    def test_subject_term_match_uses_whole_word_boundary(self):
        # "Tech" as a role label must not match "Technical" in the
        # subject -- see matching.term_matches_wholeword's docstring
        # for the real-world case this guards against.
        self._application("Metro Water Recovery", role_label="Tech")
        message = FetchedMessage(
            message_id="<msg-2@example.com>",
            subject="Technical Project Manager at Ladders",
            sender="jobalerts-noreply@linkedin.com",
            body="New jobs matching your preferences",
        )
        provider = FakeProvider([message])

        result = sync_account(self.account, provider)

        self.assertEqual(result.new_matches, 0)
        self.assertFalse(AccountMatch.objects.filter(account=self.account).exists())

    def test_records_thread_identifiers_for_own_and_referenced_ids(self):
        self._application("Acme Robotics")
        message = FetchedMessage(
            message_id="<msg-3@acme.example>",
            subject="Acme Robotics interview",
            body="We would like to schedule an interview at Acme Robotics.",
            raw_headers="In-Reply-To: <orig-3@acme.example>\r\n",
        )
        provider = FakeProvider([message])

        sync_account(self.account, provider)

        app = Application.objects.get(company="Acme Robotics")
        ids = set(ThreadIdentifier.objects.filter(application=app).values_list("message_id", flat=True))
        self.assertEqual(ids, {"<msg-3@acme.example>", "<orig-3@acme.example>"})


class ThreadTrustPathTests(SyncServiceTestCase):
    def test_established_thread_wins_even_without_term_match(self):
        app = self._application("Acme Robotics")
        ThreadIdentifier.objects.create(application=app, message_id="<orig@acme.example>")
        # No mention of "Acme Robotics" anywhere -- a bare reply.
        message = FetchedMessage(
            message_id="<reply@acme.example>",
            subject="Re: quick question",
            body="Sounds good, talk soon.",
            raw_headers="In-Reply-To: <orig@acme.example>\r\n",
        )
        provider = FakeProvider([message])

        result = sync_account(self.account, provider)

        self.assertEqual(result.new_matches, 1)
        match = AccountMatch.objects.get(message_id="<reply@acme.example>")
        self.assertEqual(match.application, app)

    def test_thread_trust_overrides_ambiguous_sibling_terms(self):
        # Two siblings share a company; the thread is only established
        # for one of them. A message that would otherwise be ambiguous
        # by company-only term matching should still resolve to the
        # thread-owning sibling, not fall into an ambiguous Discovery.
        backend = self._application("Acme Robotics", role_label="Backend Engineer")
        self._application("Acme Robotics", role_label="Frontend Engineer")
        ThreadIdentifier.objects.create(application=backend, message_id="<orig@acme.example>")
        message = FetchedMessage(
            message_id="<reply@acme.example>",
            subject="Re: Acme Robotics",
            body="Following up on Acme Robotics.",
            raw_headers="References: <orig@acme.example>\r\n",
        )
        provider = FakeProvider([message])

        result = sync_account(self.account, provider)

        self.assertEqual(result.new_matches, 1)
        self.assertEqual(result.new_discoveries, 0)
        match = AccountMatch.objects.get(message_id="<reply@acme.example>")
        self.assertEqual(match.application, backend)


class SiblingCompanyAmbiguityTests(SyncServiceTestCase):
    def test_company_only_match_across_siblings_creates_ambiguous_discovery(self):
        backend = self._application("Acme Robotics", role_label="Backend Engineer")
        frontend = self._application("Acme Robotics", role_label="Frontend Engineer")
        message = FetchedMessage(
            message_id="<msg-4@acme.example>",
            subject="Update from Acme Robotics",
            sender="hr@acme.example",
            body="We have an update regarding your application to Acme Robotics.",
        )
        provider = FakeProvider([message])

        result = sync_account(self.account, provider)

        self.assertEqual(result.new_matches, 0)
        self.assertEqual(result.new_discoveries, 1)
        discovery = Discovery.objects.get(message_id="<msg-4@acme.example>")
        self.assertEqual(discovery.match_kind, "ambiguous")
        self.assertEqual(discovery.kind, "application")
        self.assertCountEqual(list(discovery.candidate_applications.all()), [backend, frontend])

    def test_unrelated_third_application_not_swept_into_ambiguous_group(self):
        backend = self._application("Acme Robotics", role_label="Backend Engineer")
        frontend = self._application("Acme Robotics", role_label="Frontend Engineer")
        self._application("Riverbend Public Library", role_label="Librarian")
        message = FetchedMessage(
            message_id="<msg-5@acme.example>",
            subject="Update from Acme Robotics",
            body="Update regarding Acme Robotics.",
        )
        provider = FakeProvider([message])

        sync_account(self.account, provider)

        discovery = Discovery.objects.get(message_id="<msg-5@acme.example>")
        self.assertCountEqual(list(discovery.candidate_applications.all()), [backend, frontend])


class UnmatchedDiscoveryTests(SyncServiceTestCase):
    def test_untracked_ats_style_message_creates_pending_application_discovery(self):
        message = FetchedMessage(
            message_id="<msg-6@newco.example>",
            subject="Thank you for applying to NewCo",
            sender="no-reply@lever.co",
            body="Thanks for applying to NewCo!",
        )
        provider = FakeProvider([message])

        result = sync_account(self.account, provider)

        self.assertEqual(result.new_discoveries, 1)
        discovery = Discovery.objects.get(message_id="<msg-6@newco.example>")
        self.assertEqual(discovery.match_kind, "unmatched")
        self.assertEqual(discovery.kind, "application")
        self.assertEqual(discovery.guessed_company, "NewCo")

    def test_digest_style_subject_excluded_entirely(self):
        message = FetchedMessage(
            message_id="<msg-7@linkedin.com>",
            subject="New jobs in Denver Metropolitan Area match your preferences",
            sender="jobalerts-noreply@linkedin.com",
            body="Check out these jobs.",
        )
        provider = FakeProvider([message])

        result = sync_account(self.account, provider)

        self.assertEqual(result.new_discoveries, 0)
        self.assertFalse(Discovery.objects.exists())

    def test_ordinary_unrelated_mail_is_ignored(self):
        message = FetchedMessage(
            message_id="<msg-8@newsletter.example>",
            subject="Your weekly newsletter digest",
            sender="news@newsletter.example",
            body="Here's what's new this week.",
        )
        provider = FakeProvider([message])

        result = sync_account(self.account, provider)

        self.assertEqual(result.new_discoveries, 0)
        self.assertEqual(result.messages_seen, 1)


class WhitelistedSenderTests(SyncServiceTestCase):
    def test_whitelisted_sender_forces_posting_kind_regardless_of_subject(self):
        JobPostingSender.objects.create(
            workspace=self.workspace, sender="Weekly Digest <digest@boardsite.example>"
        )
        message = FetchedMessage(
            message_id="<msg-9@boardsite.example>",
            subject="Roles you might like this week",
            sender="Weekly Digest <digest@boardsite.example>",
            body="Check out https://boardsite.example/jobs/12345 for a great fit.",
        )
        provider = FakeProvider([message])

        result = sync_account(self.account, provider)

        self.assertEqual(result.new_discoveries, 1)
        discovery = Discovery.objects.get(message_id="<msg-9@boardsite.example>")
        self.assertEqual(discovery.kind, "posting")

    def test_job_posting_style_subject_without_whitelist_also_routes_to_posting(self):
        message = FetchedMessage(
            message_id="<msg-10@indeedemail.com>",
            subject="KPMG just posted a 92% match Front End Engineer job",
            sender="alerts@indeedemail.com",
            body="View the listing at https://www.indeed.com/viewjob?jk=abc123",
        )
        provider = FakeProvider([message])

        sync_account(self.account, provider)

        discovery = Discovery.objects.get(message_id="<msg-10@indeedemail.com>")
        self.assertEqual(discovery.kind, "posting")
        self.assertEqual(discovery.posting_url, "https://www.indeed.com/viewjob?jk=abc123")


class AuthErrorHandlingTests(SyncServiceTestCase):
    def test_auth_error_marks_account_blocked_and_reports_failure(self):
        provider = FakeProvider(raise_auth_error=True)

        result = sync_account(self.account, provider)

        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "blocked")

    def test_auth_error_creates_no_partial_matches(self):
        self._application("Acme Robotics")
        provider = FakeProvider(raise_auth_error=True)

        sync_account(self.account, provider)

        self.assertFalse(AccountMatch.objects.exists())
        self.assertFalse(Discovery.objects.exists())


class IdempotencyTests(SyncServiceTestCase):
    def test_repeated_sync_does_not_duplicate_matches_or_discoveries(self):
        self._application("Acme Robotics")
        messages = [
            FetchedMessage(
                message_id="<match@acme.example>",
                subject="Your application to Acme Robotics",
                body="Thanks for applying to Acme Robotics.",
            ),
            FetchedMessage(
                message_id="<discovery@newco.example>",
                subject="Thank you for applying to NewCo",
                sender="no-reply@lever.co",
                body="Thanks for applying to NewCo!",
            ),
        ]
        provider = FakeProvider(messages)

        first = sync_account(self.account, provider, now=_dt(2025, 7, 1))
        second = sync_account(self.account, provider, now=_dt(2025, 7, 2))

        self.assertEqual(first.new_matches, 1)
        self.assertEqual(first.new_discoveries, 1)
        self.assertEqual(second.new_matches, 0)
        self.assertEqual(second.new_discoveries, 0)
        self.assertEqual(second.skipped_existing, 2)
        self.assertEqual(AccountMatch.objects.filter(account=self.account).count(), 1)
        self.assertEqual(Discovery.objects.filter(account=self.account).count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.matched_email_count, 1)
        self.assertEqual(self.account.last_synced_at, _dt(2025, 7, 2))

    def test_dismissed_discovery_is_never_recreated_or_resurrected(self):
        message = FetchedMessage(
            message_id="<discovery@newco.example>",
            subject="Thank you for applying to NewCo",
            sender="no-reply@lever.co",
            body="Thanks for applying to NewCo!",
        )
        provider = FakeProvider([message])

        sync_account(self.account, provider, now=_dt(2025, 7, 1))
        discovery = Discovery.objects.get(message_id="<discovery@newco.example>")
        discovery.status = "dismissed"
        discovery.save(update_fields=["status"])

        sync_account(self.account, provider, now=_dt(2025, 7, 2))

        discovery.refresh_from_db()
        self.assertEqual(discovery.status, "dismissed")
        self.assertEqual(Discovery.objects.filter(account=self.account).count(), 1)

    def test_thread_identifiers_are_not_duplicated_across_syncs(self):
        self._application("Acme Robotics")
        message = FetchedMessage(
            message_id="<msg@acme.example>",
            subject="Acme Robotics interview",
            body="Interview at Acme Robotics.",
            raw_headers="In-Reply-To: <orig@acme.example>\r\n",
        )
        provider = FakeProvider([message])

        sync_account(self.account, provider, now=_dt(2025, 7, 1))
        sync_account(self.account, provider, now=_dt(2025, 7, 2))

        app = Application.objects.get(company="Acme Robotics")
        self.assertEqual(ThreadIdentifier.objects.filter(application=app).count(), 2)


class ProviderCallShapeTests(SyncServiceTestCase):
    def test_provider_receives_deduped_search_terms_and_since(self):
        self._application("Acme Robotics", role_label="Backend Engineer")
        self._application("Acme Robotics", role_label="Frontend Engineer")
        self.account.last_synced_at = _dt(2025, 6, 1)
        self.account.save(update_fields=["last_synced_at"])
        provider = FakeProvider([])

        sync_account(self.account, provider)

        self.assertEqual(len(provider.calls), 1)
        terms, since = provider.calls[0]
        self.assertEqual(terms.count("Acme Robotics"), 1)
        self.assertEqual(since, _dt(2025, 6, 1))

    def test_explicit_since_overrides_account_last_synced_at(self):
        self.account.last_synced_at = _dt(2025, 6, 1)
        self.account.save(update_fields=["last_synced_at"])
        provider = FakeProvider([])

        sync_account(self.account, provider, since=_dt(2025, 1, 1))

        _, since = provider.calls[0]
        self.assertEqual(since, _dt(2025, 1, 1))
