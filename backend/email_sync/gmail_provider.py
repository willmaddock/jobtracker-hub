"""
Gmail API implementation of the EmailProvider interface (Phase 9,
docs/DJANGO_MIGRATION_PLAN.md). Message-fetching logic only -- see
email_sync/providers.py's own docstring for what's deliberately NOT
here yet:

  - No OAuth connect/callback flow and no credential storage. This
    provider is handed an already-authorized Gmail API client (a
    googleapiclient.discovery Resource, or anything duck-typing the
    same `.users().messages()...` surface) via `service_factory` at
    construction time; where that client comes from -- an OAuth token
    stored per EmailAccount, refreshed on expiry, etc. -- is a
    follow-up slice's job, same as EmailAccount's own docstring's
    "no credentials of any kind are ever stored here" already flags.
  - No hard dependency on google-api-python-client being installed:
    errors are classified by duck-typing an `.resp.status` attribute
    (what a real googleapiclient.errors.HttpError instance actually
    exposes), not by importing the google client library's exception
    classes. That keeps this module -- and its tests -- fully
    importable and runnable with zero new third-party dependencies;
    google-api-python-client only becomes a real requirements.txt
    addition once something builds a real `service_factory` via
    googleapiclient.discovery.build(...), which is itself follow-up-
    slice work.

Design note on message_id: FetchedMessage.message_id here is the
message's own RFC 5322 "Message-ID" header (e.g.
"<CAB+abc@mail.gmail.com>"), NOT Gmail's own internal message id (the
opaque hex string used in API paths like /messages/{id}). This matters
because email_sync.sync_service's thread-trust path (and
matching.extract_thread_message_ids) both operate in RFC 5322
Message-ID terms -- a message's In-Reply-To/References headers cite
*other messages' Message-ID header values*, never Gmail's own id.
Using Gmail's id as message_id would silently break every thread-based
match: a reply's References header would never line up with anything
ThreadIdentifier has on file. Gmail's own id is only ever used
internally here, to fetch each message's full content.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone as dt_timezone
from email import message_from_bytes
from email.message import Message
from typing import Any, Callable, Iterable

from .matching import ATS_SENDER_DOMAINS
from .models import EmailAccount
from .providers import EmailProvider, FetchedMessage, ProviderAuthError, ProviderTemporaryError

# Gmail list() pages are capped at this many fetches per sync as a
# safety valve against an unbounded loop (a malformed query, or an API
# bug that never stops returning nextPageToken) -- not a limit anyone
# should expect to hit in normal use, since `since` already keeps each
# incremental sync's result set small.
_MAX_LIST_PAGES = 50

# Gmail's after: search operator is date-granularity only. Widening
# the cutoff by one day guarantees overlap with the previous sync
# rather than risking a same-day message just before the cutoff being
# missed outright -- re-fetching an already-classified message is a
# harmless no-op (sync_service's already_seen check); missing a real
# one is not recoverable until some later sync happens to widen its
# own window past it.
_SINCE_OVERLAP = timedelta(days=1)


def _looks_like_auth_error(exc: Exception) -> bool:
    """True if `exc` duck-types a googleapiclient HttpError carrying an
    HTTP 401 or 403 -- Gmail's shape for "this token is no longer
    valid" (expired/revoked grant, insufficient scope). Duck-typed
    rather than `isinstance(exc, googleapiclient.errors.HttpError)` so
    this module never needs to import the google client library
    itself -- see the module docstring."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    return status in (401, 403)


def _looks_like_temporary_error(exc: Exception) -> bool:
    """True if `exc` duck-types an HttpError carrying a 429 (rate
    limited) or 5xx (Gmail-side failure) -- both retryable on a later
    sync without the user reconnecting anything."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    return status == 429 or (isinstance(status, int) and 500 <= status < 600)


def _raise_classified(exc: Exception) -> None:
    """Re-raise `exc` as the appropriate ProviderError subclass if it
    looks like one of Gmail's known failure shapes, otherwise let the
    original exception propagate unchanged -- an unrecognized failure
    is a bug to surface loudly, not something to paper over as a
    generic ProviderError."""
    if _looks_like_auth_error(exc):
        raise ProviderAuthError(str(exc)) from exc
    if _looks_like_temporary_error(exc):
        raise ProviderTemporaryError(str(exc)) from exc
    raise exc


def _quote_term(term: str) -> str:
    """Wrap a term for Gmail's search syntax as an exact phrase. Gmail
    phrase search is itself just a coarse, case-insensitive
    substring-ish match over subject+body -- the same precision
    caveats matching.term_matches_wholeword exists to clean up
    downstream apply here unchanged; this only needs to narrow down
    candidates, not get them exactly right."""
    return '"{}"'.format(term.replace('"', '\\"'))


def _build_query(terms: list[str], since: datetime | None) -> str:
    """Coarse Gmail search query: an OR of every usable tracked-item
    term plus every known ATS/job-board sender domain
    (matching.ATS_SENDER_DOMAINS), optionally bounded by `since`.
    Deliberately broad -- see providers.EmailProvider.fetch_messages's
    own docstring on erring toward over-fetching; email_sync.
    sync_service does all the actual precision filtering in Python
    afterward.

    Known gap: per-workspace JobPostingSender whitelist entries aren't
    folded into this query -- the EmailProvider interface only passes
    `terms`, not the workspace's whitelist. A whitelisted digest sender
    is still only surfaced here if one of its messages happens to also
    mention a tracked term or come from a known ATS domain. Threading
    the whitelist through is a reasonable follow-up; not done here to
    avoid changing an interface email_sync.sync_service's tests
    already rely on.
    """
    clauses = [_quote_term(term) for term in terms]
    clauses.extend(f"from:{domain}" for domain in ATS_SENDER_DOMAINS)
    query = "(" + " OR ".join(clauses) + ")" if clauses else ""

    if since is not None:
        cutoff = (since - _SINCE_OVERLAP).strftime("%Y/%m/%d")
        after_clause = f"after:{cutoff}"
        query = f"{query} {after_clause}" if query else after_clause

    return query


def _decode_raw(raw_field: str) -> bytes:
    """Gmail's `raw` message field is the whole RFC 5322 message,
    base64url-encoded -- note the url-safe alphabet, and that Gmail's
    payloads are not reliably padded, so padding is restored
    explicitly rather than trusting urlsafe_b64decode's own leniency
    (which varies by input length)."""
    padded = raw_field + "=" * (-len(raw_field) % 4)
    return base64.urlsafe_b64decode(padded)


def _plain_text_body(msg: Message) -> str | None:
    """First text/plain part's decoded text, or None if the message
    has no plain-text part at all (an HTML-only email) -- callers fall
    back to raw_source-based HTML link extraction in that case, same
    as email_sync.sync_service._guessed_posting_urls already does for
    any provider."""
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


def _received_at(gmail_message: dict) -> datetime | None:
    """Gmail's own `internalDate` (epoch milliseconds, always present,
    server-assigned) rather than the message's own `Date` header -- the
    header is client-supplied and occasionally missing, malformed, or
    simply wrong (a misconfigured sender's clock); internalDate is
    Gmail's own receipt timestamp and always parses cleanly."""
    raw = gmail_message.get("internalDate")
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw) / 1000, tz=dt_timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def _to_fetched_message(gmail_message: dict) -> FetchedMessage | None:
    """Build a FetchedMessage from one Gmail API `messages.get(...,
    format="raw")` response. Returns None (never raises) for a message
    with no RFC 5322 Message-ID header -- vanishingly rare in
    practice, but such a message can never participate in thread-based
    matching (see the module docstring's message_id design note) and
    dropping it here is simpler and safer than fabricating an id that
    would collide with nothing real."""
    raw_field = gmail_message.get("raw")
    if not raw_field:
        return None
    raw_bytes = _decode_raw(raw_field)
    msg = message_from_bytes(raw_bytes)

    message_id = msg.get("Message-ID")
    if not message_id:
        return None

    # HeaderParser (used by matching.extract_thread_message_ids) only
    # ever reads up to the first blank line, so handing it the full
    # raw source instead of a headers-only slice is safe and avoids
    # re-parsing the message a second time just to split headers out.
    raw_source = raw_bytes.decode("utf-8", errors="replace")
    return FetchedMessage(
        message_id=message_id.strip(),
        subject=msg.get("Subject"),
        sender=msg.get("From"),
        received_at=_received_at(gmail_message),
        body=_plain_text_body(msg),
        raw_headers=raw_source,
        raw_source=raw_source,
    )


class GmailProvider(EmailProvider):
    """EmailProvider backed by the Gmail API.

    Constructed with a `service_factory` callable rather than a single
    pre-built client because a real caller needs a *fresh* authorized
    client per account -- each EmailAccount has its own OAuth grant --
    and because token refresh (a call this class never makes itself)
    is entirely `service_factory`'s problem, not this class's.
    `service_factory(account)` must return an object exposing the same
    `.users().messages().list(...).execute()` /
    `.users().messages().get(...).execute()` surface as a real
    `googleapiclient.discovery.build("gmail", "v1", credentials=...)`
    resource -- in tests, a hand-built fake with that same shape; in
    production, the real thing.
    """

    def __init__(self, service_factory: Callable[[EmailAccount], Any]):
        self._service_factory = service_factory

    def fetch_messages(
        self,
        account: EmailAccount,
        terms: list[str],
        since: datetime | None = None,
    ) -> Iterable[FetchedMessage]:
        service = self._service_factory(account)
        query = _build_query(terms, since)

        message_ids: list[str] = []
        page_token = None
        for _ in range(_MAX_LIST_PAGES):
            try:
                response = (
                    service.users()
                    .messages()
                    .list(userId="me", q=query, pageToken=page_token)
                    .execute()
                )
            except Exception as exc:
                _raise_classified(exc)
                raise  # pragma: no cover -- _raise_classified always raises

            message_ids.extend(m["id"] for m in response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        results: list[FetchedMessage] = []
        for gmail_id in message_ids:
            try:
                gmail_message = (
                    service.users()
                    .messages()
                    .get(userId="me", id=gmail_id, format="raw")
                    .execute()
                )
            except Exception as exc:
                _raise_classified(exc)
                raise  # pragma: no cover -- _raise_classified always raises

            fetched = _to_fetched_message(gmail_message)
            if fetched is not None:
                results.append(fetched)

        return results
