"""
Generic IMAP implementation of the EmailProvider interface (Phase 9
third-provider slice, docs/DJANGO_MIGRATION_PLAN.md). Message-fetching
logic only -- see providers.py's own docstring for what's deliberately
NOT here yet, same split as gmail_provider.py/outlook_provider.py:

  - No credential storage, no connection setup, no app-password
    verification flow. This provider is handed an already-connected,
    already-authenticated, already-`SELECT`ed IMAP4 client (or
    anything duck-typing the small subset of `imaplib.IMAP4`/
    `IMAP4_SSL` used below: `.search(charset, criteria)`,
    `.fetch(msg_num, parts)`, `.select(mailbox)`) via `client_factory`
    at construction time -- where that connection's host/port/TLS
    setup and login credentials come from is imap_auth.py's job.
  - No OAuth/token machinery at all: unlike Gmail/Outlook, generic
    IMAP here means username + app-specific password (RFC 3501 LOGIN),
    so there's no token to refresh -- imap_auth.py's client_factory
    either logs in successfully every call or raises ProviderAuthError
    outright.

Design note on message_id: same as gmail_provider.py/
outlook_provider.py, FetchedMessage.message_id is the message's own
RFC 5322 "Message-ID" header, never IMAP's own per-mailbox UID --
UIDs are only stable within one mailbox on one server and are reused
across accounts, so they can't serve as sync's cross-run dedupe key or
participate in matching.extract_thread_message_ids' In-Reply-To/
References comparisons the way a real Message-ID does.

Design note on search: IMAP's SEARCH command has no native "OR of many
terms" syntax beyond a binary `OR <a> <b>` -- unlike Gmail's/Graph's
single string query, an N-term coarse search has to be built as a
right-nested chain of binary ORs (`OR a (OR b (OR c (d)))`), which
_build_search_criteria below does. This is IMAP4rev1's actual
documented shape (RFC 3501 §6.4.4), not a workaround.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from email import message_from_bytes
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable

from .matching import ATS_SENDER_DOMAINS
from .models import EmailAccount
from .providers import EmailProvider, FetchedMessage, ProviderError, ProviderTemporaryError

# Safety cap on how many messages a single fetch_messages() call will
# actually FETCH the full RFC822 body for, mirroring outlook_provider.
# _MAX_LIST_PAGES's "don't let one runaway account's mailbox turn a
# single sync into an unbounded fetch loop" purpose. A wide IMAP
# SEARCH with generic ATS domain terms against a large, long-lived
# mailbox with a distant/absent `since` cutoff (a first-ever backfill)
# is exactly the case this guards -- 500 comfortably covers even a
# very active job search's inbox for one sync pass, and any excess is
# picked up on the next incremental sync since already-classified
# messages are a harmless no-op downstream.
_MAX_MESSAGES = 500

# Same overlap purpose and duration as outlook_provider._SINCE_OVERLAP
# / gmail_provider._SINCE_OVERLAP: IMAP's SINCE search key is date-only
# (no time-of-day component per RFC 3501 §6.4.4), so a message
# received earlier the same day as the previous sync's cutoff could
# otherwise be missed entirely rather than just harmlessly re-fetched.
_SINCE_OVERLAP = timedelta(days=1)

# IMAP's SEARCH command takes a list of space-separated criteria that
# are implicitly AND'ed together, but has no keyword for "search the
# whole message" the way Gmail's bare query terms do -- SUBJECT and
# BODY are the two RFC 3501 keys covering, respectively, the subject
# header and the full mail body, which together approximate the
# "matches one of terms" half of EmailProvider.fetch_messages' own
# over-fetch contract without requiring a HEADER FROM search per term
# too (senders are covered separately in _build_search_criteria via
# the known ATS domains).
_SEARCH_KEYS = ("SUBJECT", "BODY")


class ImapProviderError(ProviderError):
    """An IMAP command (SEARCH/FETCH/SELECT) itself failed or returned
    a malformed response -- distinct from ProviderAuthError (bad
    credentials, raised by imap_auth.py before this provider is ever
    constructed) and ProviderTemporaryError (a transient network/
    server issue, raised below for the cases that look retryable)."""


def _quote_criterion(value: str) -> str:
    """IMAP SEARCH string literals containing spaces or special
    characters must be quoted per RFC 3501 §9's ASTRING syntax; a
    literal double-quote inside the term is backslash-escaped the same
    way, so a term like `"onsite" role` can't prematurely terminate
    the quoted string it's embedded in."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _or_chain(clauses: list[str]) -> str | None:
    """Right-nest a flat list of already-built SEARCH clauses into
    IMAP's binary `OR <a> <b>` form -- `OR a (OR b (OR c (d)))` for four
    clauses, one bare clause unwrapped for a single-item list, and
    None for an empty list (the caller must omit an OR key entirely
    rather than search for nothing, same as outlook_provider.
    _build_search returning None for no terms/domains at all)."""
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return f"OR {clauses[0]} ({_or_chain(clauses[1:])})"


def _build_search_criteria(terms: list[str], since: datetime | None) -> str:
    """The full SEARCH criteria string for one fetch_messages() call:
    an OR of `SUBJECT "<term>"` / `BODY "<term>"` for every tracked
    term plus `FROM "<domain>"` for every known ATS/job-board sender
    domain (matching.ATS_SENDER_DOMAINS) -- same "over-fetch, precision
    -filter in Python afterward" split as outlook_provider.
    _build_search/gmail_provider._build_query -- ANDed with a SINCE
    date bound when `since` is given. Falls back to a bare `SINCE`-
    only (or, absent that too, `ALL`) search if there are no terms and
    no domains, rather than returning None the way outlook_provider.
    _build_search can -- unlike Graph's $search, IMAP's SEARCH command
    requires *some* criteria to be present, so "search for nothing in
    particular" is expressed as ALL, not an omitted parameter.

    Known gap, same one flagged in outlook_provider._build_search's
    own docstring: per-workspace JobPostingSender whitelist entries
    aren't folded in here either, since EmailProvider.fetch_messages
    only ever receives `terms`, not the workspace's whitelist.
    """
    clauses: list[str] = []
    for term in terms:
        quoted = _quote_criterion(term)
        for key in _SEARCH_KEYS:
            clauses.append(f"{key} {quoted}")
    for domain in ATS_SENDER_DOMAINS:
        clauses.append(f"FROM {_quote_criterion(domain)}")

    or_chain = _or_chain(clauses)

    since_clause = None
    if since is not None:
        cutoff = since - _SINCE_OVERLAP
        # IMAP's SINCE date format is dd-Mon-yyyy (RFC 3501 §9), always
        # in the server's own locale-independent month abbreviations.
        since_clause = f"SINCE {cutoff.strftime('%d-%b-%Y')}"

    if or_chain is not None and since_clause is not None:
        return f"({or_chain}) {since_clause}"
    if or_chain is not None:
        return or_chain
    if since_clause is not None:
        return since_clause
    return "ALL"


def _plain_text_body(msg: Message) -> str | None:
    """First text/plain part's decoded text, or None for an HTML-only
    message -- identical in shape and reasoning to outlook_provider.
    _plain_text_body/gmail_provider._plain_text_body: callers fall
    back to raw_source-based HTML link extraction in that case."""
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
    """Build a FetchedMessage from one message's full RFC822 source,
    the same shape a `FETCH <num> (RFC822)` response body hands back.
    Returns None (never raises) for a message with no Message-ID
    header, same rare-in-practice reasoning as outlook_provider.
    _to_fetched_message's own docstring."""
    msg = message_from_bytes(raw_bytes)

    message_id = msg.get("Message-ID")
    if not message_id:
        return None

    received_at = None
    date_header = msg.get("Date")
    if date_header:
        try:
            received_at = parsedate_to_datetime(date_header)
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


def _parse_search_response(raw) -> list[bytes]:
    """imaplib's `.search()` returns `(typ, data)` where `data` is a
    one-element list containing a single space-separated bytestring of
    message numbers (e.g. `[b"1 2 3"]`), or `[b""]` for zero results
    -- never one element per number the way `.fetch()`'s response
    list-of-tuples might suggest. Raises ImapProviderError on an
    unexpected shape rather than silently treating a malformed
    response as "no messages," since that would make a broken
    connection indistinguishable from an empty, healthy mailbox."""
    if not raw or raw[0] is None:
        raise ImapProviderError(f"IMAP SEARCH returned an unexpected response: {raw!r}")
    blob = raw[0]
    if not blob:
        return []
    return blob.split()


def _parse_fetch_response(raw) -> bytes | None:
    """imaplib's `.fetch()` returns `(typ, data)` where `data` is a
    list of response parts; for a single-message `RFC822` fetch this
    is `[(b'<num> (RFC822 {size}', b'<raw message bytes>'), b')']` --
    the raw source lives in `data[0][1]`. Returns None (rather than
    raising) for a message that vanished between SEARCH and FETCH
    (deleted/moved mid-sync) -- IMAP servers commonly return an empty
    fetch result rather than an error for that case, and a vanished
    message is not a sync failure worth surfacing."""
    if not raw:
        return None
    first = raw[0]
    if not first or not isinstance(first, tuple) or len(first) < 2:
        return None
    return first[1]


class ImapProvider(EmailProvider):
    """EmailProvider backed by a generic IMAP4 mailbox (RFC 3501).

    Constructed with a `client_factory` callable rather than a single
    pre-built client, for the same reason OutlookProvider/GmailProvider
    take a `session_factory`/`service_factory`: a real caller needs a
    *fresh*, already-authenticated, already-`SELECT`ed connection per
    account (each EmailAccount has its own IMAP credentials and, in
    principle, its own host), and everything about how that connection
    is opened -- host/port, TLS, LOGIN, mailbox selection -- is
    `client_factory`'s problem, not this class's. `client_factory(
    account)` must return an object exposing `.search(charset,
    *criteria)` and `.fetch(message_set, message_parts)` in
    `imaplib.IMAP4`'s own `(typ, data)`-returning shape -- in tests, a
    hand-built fake with that same shape; in production, a real
    `imaplib.IMAP4_SSL` instance already logged in with `.select(
    "INBOX")` already called.
    """

    def __init__(self, client_factory: Callable[[EmailAccount], Any]):
        self._client_factory = client_factory

    def fetch_messages(
        self,
        account: EmailAccount,
        terms: list[str],
        since: datetime | None = None,
    ) -> Iterable[FetchedMessage]:
        client = self._client_factory(account)
        criteria = _build_search_criteria(terms, since)

        typ, raw = client.search(None, criteria)
        if typ != "OK":
            raise ProviderTemporaryError(f"IMAP SEARCH failed ({typ}): {raw!r}")
        message_numbers = _parse_search_response(raw)[:_MAX_MESSAGES]

        results: list[FetchedMessage] = []
        for num in message_numbers:
            typ, raw_fetch = client.fetch(num, "(RFC822)")
            if typ != "OK":
                raise ProviderTemporaryError(
                    f"IMAP FETCH failed for message {num!r} ({typ}): {raw_fetch!r}"
                )
            raw_bytes = _parse_fetch_response(raw_fetch)
            if raw_bytes is None:
                continue
            fetched = _to_fetched_message(raw_bytes)
            if fetched is not None:
                results.append(fetched)

        return results
