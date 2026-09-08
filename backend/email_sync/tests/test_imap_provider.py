"""
Tests for email_sync/imap_provider.py -- the generic IMAP
implementation of EmailProvider (Phase 9 third-provider slice,
docs/DJANGO_MIGRATION_PLAN.md).

Exercises ImapProvider.fetch_messages() end-to-end against a
hand-built fake that duck-types the `.search(charset, *criteria)` /
`.fetch(message_set, message_parts)` -> `(typ, data)`-shaped surface a
real `imaplib.IMAP4_SSL` client exposes -- no live network access
needed to run these, same spirit as test_outlook_provider.py's fake
Graph session.
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Workspace

from ..matching import ATS_SENDER_DOMAINS
from ..models import EmailAccount
from ..imap_provider import (
    ImapProvider,
    ImapProviderError,
    _build_search_criteria,
    _or_chain,
    _quote_criterion,
)
from ..providers import ProviderTemporaryError


def _raw_message(
    message_id: str,
    subject: str = "Re: Application",
    sender: str = "recruiter@acme.example",
    body: str = "Thanks for applying.",
    date: str | None = "Mon, 01 Jun 2026 12:00:00 +0000",
) -> bytes:
    """Build a minimal RFC 5322 message the way an IMAP `FETCH (RFC822)`
    response hands one back -- raw bytes, no envelope wrapping."""
    date_line = f"Date: {date}\r\n" if date else ""
    source = (
        f"Message-ID: {message_id}\r\n"
        f"Subject: {subject}\r\n"
        f"From: {sender}\r\n"
        f"To: me@example.com\r\n"
        f"{date_line}"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        f"{body}\r\n"
    )
    return source.encode("utf-8")


class _FakeImapClient:
    """Fake IMAP4-shaped client for ImapProvider. `search_result` is
    the raw `(typ, data)` tuple `.search()` should return;
    `messages_by_num` maps a (bytes) message number to the raw RFC822
    bytes its fetch should return. `search_typ`/`fetch_typ` let tests
    simulate a non-"OK" response from either command."""

    def __init__(
        self,
        message_numbers: list[bytes] | None = None,
        messages_by_num: dict[bytes, bytes] | None = None,
        search_typ: str = "OK",
        fetch_typ: str = "OK",
    ):
        self.message_numbers = message_numbers if message_numbers is not None else []
        self.messages_by_num = messages_by_num or {}
        self.search_typ = search_typ
        self.fetch_typ = fetch_typ
        self.search_calls: list[tuple] = []
        self.fetch_calls: list[bytes] = []

    def search(self, charset, *criteria):
        self.search_calls.append((charset, criteria))
        if self.search_typ != "OK":
            return (self.search_typ, [b"search failed"])
        blob = b" ".join(self.message_numbers)
        return ("OK", [blob])

    def fetch(self, message_set, message_parts):
        self.fetch_calls.append(message_set)
        if self.fetch_typ != "OK":
            return (self.fetch_typ, [b"fetch failed"])
        raw = self.messages_by_num.get(message_set)
        if raw is None:
            return ("OK", [None])
        return ("OK", [(b"%s (RFC822 {%d}" % (message_set, len(raw)), raw), b")"])


class SearchCriteriaBuildingTests(TestCase):
    def test_quote_criterion_escapes_quotes_and_backslashes(self):
        self.assertEqual(_quote_criterion('senior "swe" role'), '"senior \\"swe\\" role"')
        self.assertEqual(_quote_criterion("back\\slash"), '"back\\\\slash"')

    def test_or_chain_single_clause_is_unwrapped(self):
        self.assertEqual(_or_chain(["SUBJECT a"]), "SUBJECT a")

    def test_or_chain_empty_is_none(self):
        self.assertIsNone(_or_chain([]))

    def test_or_chain_nests_binary_or(self):
        result = _or_chain(["a", "b", "c"])
        self.assertEqual(result, "OR a (OR b (c))")

    def test_build_search_criteria_ors_terms_and_domains(self):
        criteria = _build_search_criteria(["Acme Corp"], since=None)
        self.assertIn('SUBJECT "Acme Corp"', criteria)
        self.assertIn('BODY "Acme Corp"', criteria)
        for domain in ATS_SENDER_DOMAINS:
            self.assertIn(f'FROM "{domain}"', criteria)

    def test_build_search_criteria_with_since_appends_since_key(self):
        since = datetime(2026, 5, 1, tzinfo=dt_timezone.utc)
        criteria = _build_search_criteria(["Acme"], since=since)
        # _SINCE_OVERLAP widens by one day, so 2026-05-01 -> 2026-04-30.
        self.assertIn("SINCE 30-Apr-2026", criteria)

    def test_build_search_criteria_no_terms_no_domains_no_since_is_all(self):
        from .. import imap_provider

        original = imap_provider.ATS_SENDER_DOMAINS
        try:
            imap_provider.ATS_SENDER_DOMAINS = []
            self.assertEqual(_build_search_criteria([], since=None), "ALL")
        finally:
            imap_provider.ATS_SENDER_DOMAINS = original

    def test_build_search_criteria_since_only_no_terms_no_domains(self):
        from .. import imap_provider

        original = imap_provider.ATS_SENDER_DOMAINS
        try:
            imap_provider.ATS_SENDER_DOMAINS = []
            since = datetime(2026, 5, 1, tzinfo=dt_timezone.utc)
            criteria = _build_search_criteria([], since=since)
            self.assertEqual(criteria, "SINCE 30-Apr-2026")
        finally:
            imap_provider.ATS_SENDER_DOMAINS = original


class ImapProviderFetchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="imap", email="alice@example.com"
        )

    def _provider_for(self, client: _FakeImapClient) -> ImapProvider:
        return ImapProvider(client_factory=lambda account: client)

    def test_fetches_and_parses_a_single_message(self):
        raw = _raw_message(b"<abc123@example.com>".decode(), subject="Interview scheduled")
        client = _FakeImapClient(
            message_numbers=[b"1"],
            messages_by_num={b"1": raw},
        )
        provider = self._provider_for(client)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))

        self.assertEqual(len(results), 1)
        msg = results[0]
        self.assertEqual(msg.message_id, "<abc123@example.com>")
        self.assertEqual(msg.subject, "Interview scheduled")
        self.assertEqual(msg.sender, "recruiter@acme.example")
        self.assertEqual(msg.body.strip(), "Thanks for applying.")
        self.assertIsNotNone(msg.raw_headers)
        self.assertIsNotNone(msg.raw_source)
        self.assertEqual(
            msg.received_at, datetime(2026, 6, 1, 12, 0, tzinfo=dt_timezone.utc)
        )

    def test_drops_message_with_no_message_id_header(self):
        source = (
            "Subject: no id here\r\n"
            "From: someone@example.com\r\n"
            "Content-Type: text/plain\r\n\r\n"
            "body\r\n"
        ).encode("utf-8")
        client = _FakeImapClient(message_numbers=[b"1"], messages_by_num={b"1": source})
        provider = self._provider_for(client)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertEqual(results, [])

    def test_multiple_messages_all_fetched(self):
        raw1 = _raw_message("<m1@example.com>")
        raw2 = _raw_message("<m2@example.com>")
        client = _FakeImapClient(
            message_numbers=[b"1", b"2"],
            messages_by_num={b"1": raw1, b"2": raw2},
        )
        provider = self._provider_for(client)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertEqual(
            {m.message_id for m in results}, {"<m1@example.com>", "<m2@example.com>"}
        )
        self.assertEqual(len(client.fetch_calls), 2)

    def test_vanished_message_between_search_and_fetch_is_skipped(self):
        client = _FakeImapClient(message_numbers=[b"1"], messages_by_num={})
        provider = self._provider_for(client)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertEqual(results, [])

    def test_search_failure_raises_provider_temporary_error(self):
        client = _FakeImapClient(search_typ="NO")
        provider = self._provider_for(client)
        with self.assertRaises(ProviderTemporaryError):
            list(provider.fetch_messages(self.account, terms=["Acme"]))

    def test_fetch_failure_raises_provider_temporary_error(self):
        client = _FakeImapClient(message_numbers=[b"1"], fetch_typ="NO")
        provider = self._provider_for(client)
        with self.assertRaises(ProviderTemporaryError):
            list(provider.fetch_messages(self.account, terms=["Acme"]))

    def test_html_only_message_has_no_plain_text_body(self):
        source = (
            "Message-ID: <html1@example.com>\r\n"
            "Subject: html only\r\n"
            "From: someone@example.com\r\n"
            "Content-Type: text/html; charset=utf-8\r\n\r\n"
            "<p>hello</p>\r\n"
        ).encode("utf-8")
        client = _FakeImapClient(message_numbers=[b"1"], messages_by_num={b"1": source})
        provider = self._provider_for(client)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].body)
        self.assertIn("<p>hello</p>", results[0].raw_source)

    def test_missing_date_header_yields_none_received_at(self):
        raw = _raw_message("<nodate@example.com>", date=None)
        client = _FakeImapClient(message_numbers=[b"1"], messages_by_num={b"1": raw})
        provider = self._provider_for(client)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertIsNone(results[0].received_at)

    def test_empty_search_result_returns_no_results(self):
        client = _FakeImapClient(message_numbers=[])
        provider = self._provider_for(client)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertEqual(results, [])

    def test_caps_at_max_messages(self):
        from .. import imap_provider

        original_cap = imap_provider._MAX_MESSAGES
        try:
            imap_provider._MAX_MESSAGES = 2
            numbers = [b"1", b"2", b"3"]
            msgs = {n: _raw_message(f"<{n.decode()}@example.com>") for n in numbers}
            client = _FakeImapClient(message_numbers=numbers, messages_by_num=msgs)
            provider = self._provider_for(client)
            results = list(provider.fetch_messages(self.account, terms=["Acme"]))
            self.assertEqual(len(results), 2)
        finally:
            imap_provider._MAX_MESSAGES = original_cap
