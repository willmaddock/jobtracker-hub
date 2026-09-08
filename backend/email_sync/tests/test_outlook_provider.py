"""
Tests for email_sync/outlook_provider.py -- the Microsoft Graph
implementation of EmailProvider (Phase 9 second-provider slice,
docs/DJANGO_MIGRATION_PLAN.md).

Exercises OutlookProvider.fetch_messages() end-to-end against a
hand-built fake that duck-types the `.get(url, params=None,
headers=None)` -> requests.Response-shaped surface a real
`requests.Session` exposes -- no live network access needed to run
these, same spirit as test_gmail_provider.py's fake Gmail service.
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Workspace

from ..matching import ATS_SENDER_DOMAINS
from ..models import EmailAccount
from ..outlook_provider import OutlookProvider, _build_search, _quote_term
from ..providers import ProviderAuthError, ProviderTemporaryError


def _raw_message(
    message_id: str,
    subject: str = "Re: Application",
    sender: str = "recruiter@acme.example",
    body: str = "Thanks for applying.",
    date: str | None = "Mon, 01 Jun 2026 12:00:00 +0000",
    extra_headers: str = "",
) -> bytes:
    """Build a minimal RFC 5322 message the way Graph's
    `/messages/{id}/$value` hands one back -- raw bytes, no base64
    wrapping (unlike Gmail's `raw` JSON field)."""
    date_line = f"Date: {date}\r\n" if date else ""
    source = (
        f"Message-ID: {message_id}\r\n"
        f"Subject: {subject}\r\n"
        f"From: {sender}\r\n"
        f"To: me@example.com\r\n"
        f"{date_line}"
        f"{extra_headers}"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        f"{body}\r\n"
    )
    return source.encode("utf-8")


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, content=b"", text=""):
        self.status_code = status_code
        self._json_body = json_body
        self.content = content
        self.text = text or (str(json_body) if json_body is not None else "")

    def json(self):
        return self._json_body


class _FakeGraphSession:
    """Fake session for OutlookProvider. `list_pages` is the sequence
    of /me/messages page bodies returned in order; `messages_by_id`
    maps a Graph message id to the raw MIME bytes its $value fetch
    should return. `list_status`/`get_status` let tests simulate a
    non-2xx response from either endpoint."""

    def __init__(
        self,
        list_pages: list[dict] | None = None,
        messages_by_id: dict[str, bytes] | None = None,
        list_status: int = 200,
        get_status: int = 200,
    ):
        self.list_pages = list_pages if list_pages is not None else [{"value": []}]
        self.messages_by_id = messages_by_id or {}
        self.list_status = list_status
        self.get_status = get_status
        self.get_calls: list[tuple[str, dict | None]] = []
        self._page_index = 0

    def get(self, url, params=None, headers=None):
        self.get_calls.append((url, params))
        if url.endswith("/$value"):
            graph_id = url.rsplit("/messages/", 1)[1].split("/")[0]
            if self.get_status != 200:
                return _FakeResponse(status_code=self.get_status, text="get failed")
            return _FakeResponse(status_code=200, content=self.messages_by_id[graph_id])

        # Otherwise this is a /me/messages list page (either the
        # initial call with params, or a follow-up to a full
        # @odata.nextLink URL with params=None).
        if self.list_status != 200:
            return _FakeResponse(status_code=self.list_status, text="list failed")
        page = self.list_pages[self._page_index]
        self._page_index += 1
        return _FakeResponse(status_code=200, json_body=page)


class QueryBuildingTests(TestCase):
    def test_quote_term_escapes_embedded_quotes(self):
        self.assertEqual(_quote_term('senior "swe" role'), '"senior \\"swe\\" role"')

    def test_build_search_ors_terms_and_ats_domains(self):
        search = _build_search(["Acme Corp", "Widget Co"])
        self.assertIn('"Acme Corp"', search)
        self.assertIn('"Widget Co"', search)
        for domain in ATS_SENDER_DOMAINS:
            self.assertIn(f'"from:{domain}"', search)

    def test_build_search_with_no_terms_and_no_domains_returns_none(self):
        # ATS_SENDER_DOMAINS is always non-empty in practice, so this
        # exercises the guard directly rather than relying on that.
        from .. import outlook_provider

        original = outlook_provider.ATS_SENDER_DOMAINS
        try:
            outlook_provider.ATS_SENDER_DOMAINS = []
            self.assertIsNone(_build_search([]))
        finally:
            outlook_provider.ATS_SENDER_DOMAINS = original


class OutlookProviderFetchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="outlook", email="alice@outlook.example"
        )

    def _provider_for(self, session: _FakeGraphSession) -> OutlookProvider:
        return OutlookProvider(session_factory=lambda account: session)

    def test_fetches_and_parses_a_single_message(self):
        raw = _raw_message("<abc123@outlook.example>", subject="Interview scheduled")
        session = _FakeGraphSession(
            list_pages=[{"value": [{"id": "graph-internal-1"}]}],
            messages_by_id={"graph-internal-1": raw},
        )
        provider = self._provider_for(session)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))

        self.assertEqual(len(results), 1)
        msg = results[0]
        self.assertEqual(msg.message_id, "<abc123@outlook.example>")
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
        session = _FakeGraphSession(
            list_pages=[{"value": [{"id": "g1"}]}],
            messages_by_id={"g1": source},
        )
        provider = self._provider_for(session)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertEqual(results, [])

    def test_paginates_via_odata_next_link(self):
        raw1 = _raw_message("<m1@outlook.example>")
        raw2 = _raw_message("<m2@outlook.example>")
        next_link = "https://graph.microsoft.com/v1.0/me/messages?$skip=100"
        session = _FakeGraphSession(
            list_pages=[
                {"value": [{"id": "g1"}], "@odata.nextLink": next_link},
                {"value": [{"id": "g2"}]},
            ],
            messages_by_id={"g1": raw1, "g2": raw2},
        )
        provider = self._provider_for(session)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))

        self.assertEqual(
            {m.message_id for m in results},
            {"<m1@outlook.example>", "<m2@outlook.example>"},
        )
        list_calls = [c for c in session.get_calls if "$value" not in c[0]]
        self.assertEqual(len(list_calls), 2)
        self.assertEqual(list_calls[1][0], next_link)

    def test_since_narrows_the_filter(self):
        session = _FakeGraphSession(list_pages=[{"value": []}])
        provider = self._provider_for(session)
        since = datetime(2026, 5, 1, tzinfo=dt_timezone.utc)
        list(provider.fetch_messages(self.account, terms=["Acme"], since=since))

        list_calls = [c for c in session.get_calls if "$value" not in c[0]]
        self.assertEqual(len(list_calls), 1)
        self.assertIn("receivedDateTime ge 2026-04-30", list_calls[0][1]["$filter"])

    def test_401_on_list_raises_provider_auth_error(self):
        session = _FakeGraphSession(list_status=401)
        provider = self._provider_for(session)
        with self.assertRaises(ProviderAuthError):
            list(provider.fetch_messages(self.account, terms=["Acme"]))

    def test_403_on_list_raises_provider_auth_error(self):
        session = _FakeGraphSession(list_status=403)
        provider = self._provider_for(session)
        with self.assertRaises(ProviderAuthError):
            list(provider.fetch_messages(self.account, terms=["Acme"]))

    def test_429_on_list_raises_provider_temporary_error(self):
        session = _FakeGraphSession(list_status=429)
        provider = self._provider_for(session)
        with self.assertRaises(ProviderTemporaryError):
            list(provider.fetch_messages(self.account, terms=["Acme"]))

    def test_5xx_on_value_fetch_raises_provider_temporary_error(self):
        session = _FakeGraphSession(
            list_pages=[{"value": [{"id": "g1"}]}],
            get_status=503,
        )
        provider = self._provider_for(session)
        with self.assertRaises(ProviderTemporaryError):
            list(provider.fetch_messages(self.account, terms=["Acme"]))

    def test_html_only_message_has_no_plain_text_body(self):
        source = (
            "Message-ID: <html1@outlook.example>\r\n"
            "Subject: html only\r\n"
            "From: someone@example.com\r\n"
            "Content-Type: text/html; charset=utf-8\r\n\r\n"
            "<p>hello</p>\r\n"
        ).encode("utf-8")
        session = _FakeGraphSession(
            list_pages=[{"value": [{"id": "g1"}]}],
            messages_by_id={"g1": source},
        )
        provider = self._provider_for(session)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].body)
        self.assertIn("<p>hello</p>", results[0].raw_source)

    def test_missing_date_header_yields_none_received_at(self):
        raw = _raw_message("<nodate@outlook.example>", date=None)
        session = _FakeGraphSession(
            list_pages=[{"value": [{"id": "g1"}]}],
            messages_by_id={"g1": raw},
        )
        provider = self._provider_for(session)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertIsNone(results[0].received_at)

    def test_empty_message_list_returns_no_results(self):
        session = _FakeGraphSession(list_pages=[{"value": []}])
        provider = self._provider_for(session)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertEqual(results, [])
