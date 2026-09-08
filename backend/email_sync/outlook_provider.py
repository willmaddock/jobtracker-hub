"""
Microsoft Graph implementation of the EmailProvider interface (Phase 9,
docs/DJANGO_MIGRATION_PLAN.md). Message-fetching logic only -- see
providers.py's own docstring for what's deliberately NOT here yet:

  - No OAuth connect/callback flow and no credential storage. This
    provider is handed an already-authorized `requests.Session` (or
    anything duck-typing `.get(url, params=...)` /
    `.get(url, headers=...)` returning a `requests.Response`-shaped
    object) via `session_factory` at construction time; where that
    session's Authorization header comes from -- an OAuth token
    stored per EmailAccount, refreshed on expiry, etc. -- is
    outlook_oauth.py's job, same split as gmail_provider.py /
    oauth.py.
  - No hard dependency on the `msal` library or any Microsoft-specific
    SDK: Graph is a plain REST API, so this module only ever needs
    `requests`, which the project already depends on (see
    requirements.txt). Errors are classified by reading the HTTP
    status code straight off the response, the same shape any Graph
    caller gets regardless of which HTTP client made the request.

Design note on message_id: FetchedMessage.message_id here is the
message's own RFC 5322 "Message-ID" header, extracted from the raw
MIME payload Graph hands back via the `/messages/{id}/$value`
endpoint -- NOT Graph's own internal message id (the opaque base64-ish
string used in API paths like /me/messages/{id}). This matters for
exactly the reason gmail_provider.py's own docstring gives: thread
matching (email_sync.matching.extract_thread_message_ids,
sync_service's thread-trust path) operates entirely in RFC 5322
Message-ID terms, since a reply's In-Reply-To/References headers cite
other messages' Message-ID header values, never a provider's own
internal id. Graph's own id is only ever used internally here, to
fetch each message's full MIME content.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from email import message_from_bytes
from email.message import Message
from typing import Any, Callable, Iterable

from .matching import ATS_SENDER_DOMAINS
from .models import EmailAccount
from .providers import EmailProvider, FetchedMessage, ProviderAuthError, ProviderTemporaryError

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Graph's /me/messages list is paged via @odata.nextLink; this caps
# how many pages one fetch_messages() call will follow, same safety-
# valve purpose as gmail_provider._MAX_LIST_PAGES -- not a limit
# anyone should expect to hit given `since` already keeps each
# incremental sync's result set small.
_MAX_LIST_PAGES = 50

# How many messages to request per page. Graph's own default/max for
# $top on /messages is 999, but Outlook mailboxes commonly reject
# large $top values on $search queries with a 400; 100 is comfortably
# under that ceiling and keeps each page's $value re-fetch fan-out
# reasonable.
_PAGE_SIZE = 100

# Graph's `receivedDateTime ge ...` filter is only as fine-grained as
# the timestamp given it, but unlike Gmail's date-only `after:`
# operator it does accept full ISO-8601 datetimes -- still widened by
# a day here for the same reason gmail_provider._SINCE_OVERLAP is:
# guarantee overlap with the previous sync rather than risk a
# same-day message right at the cutoff being missed, since re-
# fetching an already-classified message is a harmless no-op
# (sync_service's already_seen check) and missing a real one is not
# recoverable until some later sync happens to widen its own window
# past it.
_SINCE_OVERLAP = timedelta(days=1)


def _looks_like_auth_error(status_code: int) -> bool:
    """True for Graph's shape of "this token is no longer valid"
    (expired/revoked grant, insufficient scope) -- 401 Unauthorized or
    403 Forbidden, the same pair gmail_provider._looks_like_auth_error
    treats as auth failures for Gmail's API."""
    return status_code in (401, 403)


def _looks_like_temporary_error(status_code: int) -> bool:
    """True for a Graph failure retryable on a later sync without the
    user reconnecting anything -- 429 (throttled, Graph's own rate-
    limit status) or any 5xx (a Graph-side failure)."""
    return status_code == 429 or 500 <= status_code < 600


def _raise_for_status(response) -> None:
    """Raise the appropriate ProviderError subclass if `response`'s
    status code looks like one of Graph's known failure shapes,
    otherwise leave it alone -- an unrecognized non-2xx is a bug to
    surface loudly (via response.raise_for_status()'s own
    HTTPError), not something to paper over as a generic
    ProviderError."""
    if response.status_code < 400:
        return
    if _looks_like_auth_error(response.status_code):
        raise ProviderAuthError(
            f"Microsoft Graph returned {response.status_code}: {response.text[:500]}"
        )
    if _looks_like_temporary_error(response.status_code):
        raise ProviderTemporaryError(
            f"Microsoft Graph returned {response.status_code}: {response.text[:500]}"
        )
    response.raise_for_status()


def _quote_term(term: str) -> str:
    """Wrap a term for Graph's $search syntax as an exact phrase.
    Graph's $search (like Gmail's phrase search) is a coarse,
    case-insensitive match over a handful of default properties
    (subject, body, sender, ...) for messages -- matching.
    term_matches_wholeword's same precision caveats apply downstream;
    this only needs to narrow down candidates, not get them exactly
    right."""
    return '"{}"'.format(term.replace('"', '\\"'))


def _build_search(terms: list[str]) -> str | None:
    """Coarse Graph $search value: an OR of every usable tracked-item
    term plus every known ATS/job-board sender domain (matching.
    ATS_SENDER_DOMAINS), or None if there are no terms and no domains
    to search for at all (Graph rejects an empty $search value).
    Deliberately broad, same "over-fetch, precision-filter in Python
    afterward" split as gmail_provider._build_query -- email_sync.
    sync_service does the actual precision filtering.

    Known gap, same one gmail_provider._build_query's own docstring
    flags: per-workspace JobPostingSender whitelist entries aren't
    folded in here either, for the same reason (the EmailProvider
    interface only passes `terms`, not the workspace's whitelist).
    """
    clauses = [_quote_term(term) for term in terms]
    clauses.extend(f'"from:{domain}"' for domain in ATS_SENDER_DOMAINS)
    if not clauses:
        return None
    return " OR ".join(clauses)


def _build_params(terms: list[str], since: datetime | None) -> dict[str, str]:
    """Query params for one GET /me/messages page. Graph doesn't allow
    combining $search with $orderby (and $filter's `ge`/`le` operators
    on receivedDateTime work fine alongside $search), so `since` is
    expressed as a $filter clause rather than folded into $search the
    way Gmail's `after:` operator is folded into its own query
    string."""
    params: dict[str, str] = {"$top": str(_PAGE_SIZE)}

    search = _build_search(terms)
    if search is not None:
        params["$search"] = search

    if since is not None:
        cutoff = (since - _SINCE_OVERLAP).strftime("%Y-%m-%dT%H:%M:%SZ")
        params["$filter"] = f"receivedDateTime ge {cutoff}"

    return params


def _plain_text_body(msg: Message) -> str | None:
    """First text/plain part's decoded text, or None if the message
    has no plain-text part at all (an HTML-only email) -- callers fall
    back to raw_source-based HTML link extraction in that case, same
    as gmail_provider._plain_text_body and email_sync.sync_service.
    _guessed_posting_urls already do for any provider."""
    parts = list(msg.walk()) if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_type() != "text/plain":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            return payload.decode("utf-8", errors="replace")
    return None


def _to_fetched_message(raw_bytes: bytes) -> FetchedMessage | None:
    """Build a FetchedMessage from one Graph `/messages/{id}/$value`
    response -- the message's full RFC 5322 MIME source, unlike
    Gmail's list-then-get-raw shape this is the entire payload of a
    single request. Returns None (never raises) for a message with no
    Message-ID header, same rare-in-practice, can't-thread-match-
    without-it reasoning as gmail_provider._to_fetched_message's own
    docstring."""
    msg = message_from_bytes(raw_bytes)

    message_id = msg.get("Message-ID")
    if not message_id:
        return None

    # Date header (RFC 5322's own received-at) is used here rather
    # than a Graph-supplied field, since $value returns the raw
    # message with no accompanying JSON metadata to read
    # internalDate-equivalent timestamp from the way gmail_provider
    # does -- the MIME source's own Date header is the only received-
    # at this endpoint hands back at all.
    received_at = None
    date_header = msg.get("Date")
    if date_header:
        try:
            from email.utils import parsedate_to_datetime

            received_at = parsedate_to_datetime(date_header)
            if received_at is not None and received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=dt_timezone.utc)
        except (TypeError, ValueError):
            received_at = None

    raw_source = raw_bytes.decode("utf-8", errors="replace")
    return FetchedMessage(
        message_id=message_id.strip(),
        subject=msg.get("Subject"),
        sender=msg.get("From"),
        received_at=received_at,
        body=_plain_text_body(msg),
        raw_headers=raw_source,
        raw_source=raw_source,
    )


class OutlookProvider(EmailProvider):
    """EmailProvider backed by Microsoft Graph's `/me/messages`
    endpoint.

    Constructed with a `session_factory` callable rather than a single
    pre-built session, for the same reason GmailProvider takes a
    `service_factory`: a real caller needs a *fresh* authorized
    session per account (each EmailAccount has its own OAuth grant),
    and token refresh is entirely `session_factory`'s problem, not
    this class's. `session_factory(account)` must return an object
    exposing a `.get(url, params=None, headers=None)` method returning
    a `requests.Response`-shaped object (`.status_code`, `.json()`,
    `.content`, `.text`) with the Graph bearer token already attached
    -- in tests, a hand-built fake with that same shape; in
    production, a real `requests.Session` with its `Authorization`
    header set.
    """

    def __init__(self, session_factory: Callable[[EmailAccount], Any]):
        self._session_factory = session_factory

    def fetch_messages(
        self,
        account: EmailAccount,
        terms: list[str],
        since: datetime | None = None,
    ) -> Iterable[FetchedMessage]:
        session = self._session_factory(account)
        params = _build_params(terms, since)

        message_ids: list[str] = []
        url = f"{_GRAPH_BASE}/me/messages"
        next_params: dict[str, str] | None = params
        for _ in range(_MAX_LIST_PAGES):
            response = session.get(url, params=next_params)
            _raise_for_status(response)
            payload = response.json()

            message_ids.extend(item["id"] for item in payload.get("value", []))

            next_link = payload.get("@odata.nextLink")
            if not next_link:
                break
            # @odata.nextLink is already a complete, fully-query-
            # stringed URL -- pass it through as-is on the next
            # iteration rather than re-appending params to it.
            url = next_link
            next_params = None

        results: list[FetchedMessage] = []
        for graph_id in message_ids:
            response = session.get(
                f"{_GRAPH_BASE}/me/messages/{graph_id}/$value",
                headers={"Accept": "text/plain"},
            )
            _raise_for_status(response)

            fetched = _to_fetched_message(response.content)
            if fetched is not None:
                results.append(fetched)

        return results
