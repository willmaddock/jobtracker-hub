"""
Tests for email_sync/gmail_provider.py -- the Gmail API implementation
of EmailProvider (Phase 9 slice, docs/DJANGO_MIGRATION_PLAN.md).

Exercises GmailProvider.fetch_messages() end-to-end against a hand-
built fake that duck-types the same `.users().messages().list(...)
.execute()` / `.get(...).execute()` surface a real
googleapiclient.discovery Resource exposes -- no google-api-python-
client dependency needed to run these.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Workspace

from ..gmail_provider import GmailProvider, _build_query, _quote_term
from ..matching import ATS_SENDER_DOMAINS
from ..models import EmailAccount
from ..providers import ProviderAuthError, ProviderTemporaryError


def _raw_message(
    message_id: str,
    subject: str = "Re: Application",
    sender: str = "recruiter@acme.example",
    body: str = "Thanks for applying.",
    extra_headers: str = "",
) -> str:
    """Base64url-encode a minimal RFC 5322 message the way Gmail's
    `raw` field represents one, deliberately without padding (Gmail's
    own payloads aren't reliably padded either) to exercise
    _decode_raw's manual padding restoration."""
    source = (
        f"Message-ID: {message_id}\r\n"
        f"Subject: {subject}\r\n"
        f"From: {sender}\r\n"
        f"To: me@example.com\r\n"
        f"{extra_headers}"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        f"{body}\r\n"
    )
    encoded = base64.urlsafe_b64encode(source.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


class _FakeExecutable:
    def __init__(self, result=None, exc: Exception | None = None):
        self._result = result
        self._exc = exc

    def execute(self):
        if self._exc is not None:
            raise self._exc
        return self._result


class _FakeHttpError(Exception):
    """Duck-types googleapiclient.errors.HttpError's `.resp.status`
    shape without importing the real library. `message`, when given,
    overrides the default `f"HTTP {status}"` string -- used to
    simulate a real Gmail 403's parsed-body reason (e.g.
    "rateLimitExceeded") showing up in str(exc), the same place it'd
    appear on a genuine googleapiclient.errors.HttpError."""

    class _Resp:
        def __init__(self, status: int):
            self.status = status

    def __init__(self, status: int, message: str | None = None):
        self.resp = self._Resp(status)
        super().__init__(message or f"HTTP {status}")


class _FakeMessages:
    def __init__(self, service: "_FakeGmailService"):
        self._service = service

    def list(self, userId, q, pageToken=None):  # noqa: N803 -- mirrors Gmail API kwarg names
        self._service.list_calls.append({"userId": userId, "q": q, "pageToken": pageToken})
        if self._service.list_exc is not None:
            return _FakeExecutable(exc=self._service.list_exc)
        pages = self._service.list_pages
        idx = 0 if pageToken is None else self._service.page_tokens.index(pageToken) + 1
        return _FakeExecutable(result=pages[idx])

    def get(self, userId, id, format):  # noqa: A002,N803 -- mirrors Gmail API kwarg names
        self._service.get_calls.append(id)
        if self._service.get_exc is not None:
            return _FakeExecutable(exc=self._service.get_exc)
        return _FakeExecutable(result=self._service.messages_by_id[id])


class _FakeUsers:
    def __init__(self, service: "_FakeGmailService"):
        self._service = service

    def messages(self):
        return _FakeMessages(self._service)


class _FakeGmailService:
    """Fake googleapiclient.discovery Resource for Gmail. `list_pages`
    is the sequence of list() responses returned in order across
    successive pageToken-driven calls; `page_tokens` are the
    nextPageToken values those pages hand out (parallel-indexed so the
    fake can figure out which page a given token means to fetch next).
    """

    def __init__(
        self,
        list_pages: list[dict] | None = None,
        page_tokens: list[str] | None = None,
        messages_by_id: dict[str, dict] | None = None,
        list_exc: Exception | None = None,
        get_exc: Exception | None = None,
    ):
        self.list_pages = list_pages if list_pages is not None else [{"messages": []}]
        self.page_tokens = page_tokens or []
        self.messages_by_id = messages_by_id or {}
        self.list_exc = list_exc
        self.get_exc = get_exc
        self.list_calls: list[dict] = []
        self.get_calls: list[str] = []

    def users(self):
        return _FakeUsers(self)


class QueryBuildingTests(TestCase):
    def test_quote_term_escapes_embedded_quotes(self):
        self.assertEqual(_quote_term('senior "swe" role'), '"senior \\"swe\\" role"')

    def test_build_query_ors_terms_and_ats_domains(self):
        query = _build_query(["Acme Corp", "Widget Co"], since=None)
        self.assertIn('"Acme Corp"', query)
        self.assertIn('"Widget Co"', query)
        for domain in ATS_SENDER_DOMAINS:
            self.assertIn(f"from:{domain}", query)

    def test_build_query_applies_since_with_one_day_overlap(self):
        since = datetime(2026, 3, 15, 12, 0, tzinfo=dt_timezone.utc)
        query = _build_query(["Acme"], since=since)
        self.assertIn("after:2026/03/14", query)

    def test_build_query_with_no_terms_still_includes_since(self):
        since = datetime(2026, 1, 10, tzinfo=dt_timezone.utc)
        query = _build_query([], since=since)
        self.assertTrue(query.startswith("(") is False or "after:2026/01/09" in query)
        self.assertIn("after:2026/01/09", query)


class GmailProviderFetchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pw123456")
        self.workspace = Workspace.objects.create(owner=self.user, name="Alice's workspace")
        self.account = EmailAccount.objects.create(
            workspace=self.workspace, provider="gmail", email="alice@example.com"
        )

    def _provider_for(self, service: _FakeGmailService) -> GmailProvider:
        return GmailProvider(service_factory=lambda account: service)

    def test_fetches_and_parses_a_single_message(self):
        raw = _raw_message("<abc123@mail.gmail.com>", subject="Interview scheduled")
        service = _FakeGmailService(
            list_pages=[{"messages": [{"id": "gmail-internal-1"}]}],
            messages_by_id={
                "gmail-internal-1": {
                    "raw": raw,
                    "internalDate": "1700000000000",
                }
            },
        )
        provider = self._provider_for(service)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))

        self.assertEqual(len(results), 1)
        msg = results[0]
        # message_id must be the RFC 5322 Message-ID header, never
        # Gmail's own internal id -- see the module docstring.
        self.assertEqual(msg.message_id, "<abc123@mail.gmail.com>")
        self.assertEqual(msg.subject, "Interview scheduled")
        self.assertEqual(msg.sender, "recruiter@acme.example")
        self.assertEqual(msg.body.strip(), "Thanks for applying.")
        self.assertIsNotNone(msg.raw_headers)
        self.assertIsNotNone(msg.raw_source)
        self.assertEqual(
            msg.received_at, datetime.fromtimestamp(1700000000, tz=dt_timezone.utc)
        )

    def test_drops_message_with_no_message_id_header(self):
        # Build a raw message with no Message-ID header at all.
        source = (
            "Subject: no id here\r\n"
            "From: someone@example.com\r\n"
            "Content-Type: text/plain\r\n\r\n"
            "body\r\n"
        )
        raw = base64.urlsafe_b64encode(source.encode()).decode("ascii").rstrip("=")
        service = _FakeGmailService(
            list_pages=[{"messages": [{"id": "g1"}]}],
            messages_by_id={"g1": {"raw": raw, "internalDate": "1700000000000"}},
        )
        provider = self._provider_for(service)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertEqual(results, [])

    def test_paginates_across_multiple_list_pages(self):
        raw1 = _raw_message("<m1@mail.gmail.com>")
        raw2 = _raw_message("<m2@mail.gmail.com>")
        service = _FakeGmailService(
            list_pages=[
                {"messages": [{"id": "g1"}], "nextPageToken": "PAGE2"},
                {"messages": [{"id": "g2"}]},
            ],
            page_tokens=["PAGE2"],
            messages_by_id={
                "g1": {"raw": raw1, "internalDate": "1700000000000"},
                "g2": {"raw": raw2, "internalDate": "1700000001000"},
            },
        )
        provider = self._provider_for(service)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))

        self.assertEqual({m.message_id for m in results}, {"<m1@mail.gmail.com>", "<m2@mail.gmail.com>"})
        self.assertEqual(len(service.list_calls), 2)

    def test_since_narrows_the_search_query(self):
        service = _FakeGmailService(list_pages=[{"messages": []}])
        provider = self._provider_for(service)
        since = datetime(2026, 5, 1, tzinfo=dt_timezone.utc)
        list(provider.fetch_messages(self.account, terms=["Acme"], since=since))

        self.assertEqual(len(service.list_calls), 1)
        self.assertIn("after:2026/04/30", service.list_calls[0]["q"])

    def test_401_on_list_raises_provider_auth_error(self):
        service = _FakeGmailService(list_exc=_FakeHttpError(401))
        provider = self._provider_for(service)
        with self.assertRaises(ProviderAuthError):
            list(provider.fetch_messages(self.account, terms=["Acme"]))

    def test_403_on_list_raises_provider_auth_error(self):
        service = _FakeGmailService(list_exc=_FakeHttpError(403))
        provider = self._provider_for(service)
        with self.assertRaises(ProviderAuthError):
            list(provider.fetch_messages(self.account, terms=["Acme"]))

    def test_403_rate_limit_on_list_raises_provider_temporary_error(self):
        # Regression test: Gmail returns HTTP 403 for both an actual
        # expired/revoked grant AND quota/rate-limit exhaustion
        # (domain "usageLimits", reason "rateLimitExceeded") -- only
        # the parsed reason in the body tells them apart. Treating
        # every 403 as an auth failure would wrongly mark a perfectly
        # valid account "blocked" for what's really a transient,
        # retry-later condition.
        service = _FakeGmailService(
            list_exc=_FakeHttpError(
                403,
                message=(
                    "<HttpError 403 ... returned \"Quota exceeded for quota metric "
                    "'Total Query Cost' ...\". Details: \"[{'message': '...', "
                    "'domain': 'usageLimits', 'reason': 'rateLimitExceeded'}]\">"
                ),
            )
        )
        provider = self._provider_for(service)
        with self.assertRaises(ProviderTemporaryError):
            list(provider.fetch_messages(self.account, terms=["Acme"]))

    def test_429_on_list_raises_provider_temporary_error(self):
        service = _FakeGmailService(list_exc=_FakeHttpError(429))
        provider = self._provider_for(service)
        with self.assertRaises(ProviderTemporaryError):
            list(provider.fetch_messages(self.account, terms=["Acme"]))

    def test_5xx_on_get_raises_provider_temporary_error(self):
        service = _FakeGmailService(
            list_pages=[{"messages": [{"id": "g1"}]}],
            get_exc=_FakeHttpError(503),
        )
        provider = self._provider_for(service)
        with self.assertRaises(ProviderTemporaryError):
            list(provider.fetch_messages(self.account, terms=["Acme"]))

    def test_unrecognized_error_propagates_unchanged(self):
        service = _FakeGmailService(list_exc=ValueError("something else broke"))
        provider = self._provider_for(service)
        with self.assertRaises(ValueError):
            list(provider.fetch_messages(self.account, terms=["Acme"]))

    def test_html_only_message_has_no_plain_text_body(self):
        source = (
            "Message-ID: <html1@mail.gmail.com>\r\n"
            "Subject: html only\r\n"
            "From: someone@example.com\r\n"
            "Content-Type: text/html; charset=utf-8\r\n\r\n"
            "<p>hello</p>\r\n"
        )
        raw = base64.urlsafe_b64encode(source.encode()).decode("ascii").rstrip("=")
        service = _FakeGmailService(
            list_pages=[{"messages": [{"id": "g1"}]}],
            messages_by_id={"g1": {"raw": raw, "internalDate": "1700000000000"}},
        )
        provider = self._provider_for(service)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].body)
        # Falls back to raw_source so HTML link extraction can still work.
        self.assertIn("<p>hello</p>", results[0].raw_source)

    def test_missing_internal_date_yields_none_received_at(self):
        raw = _raw_message("<nodate@mail.gmail.com>")
        service = _FakeGmailService(
            list_pages=[{"messages": [{"id": "g1"}]}],
            messages_by_id={"g1": {"raw": raw}},
        )
        provider = self._provider_for(service)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertIsNone(results[0].received_at)

    def test_empty_message_list_returns_no_results(self):
        service = _FakeGmailService(list_pages=[{"messages": []}])
        provider = self._provider_for(service)
        results = list(provider.fetch_messages(self.account, terms=["Acme"]))
        self.assertEqual(results, [])
