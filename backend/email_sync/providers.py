"""
Provider interface for Phase 9 email sync (docs/DJANGO_MIGRATION_PLAN.md).

This module defines the *shape* every mailbox provider (Gmail API,
Microsoft Graph, generic IMAP, ...) must satisfy so that
email_sync/sync_service.py can orchestrate a sync without knowing or
caring which provider an EmailAccount actually uses. No concrete
provider lives here yet -- that is real OAuth-client work (token
storage/refresh, API pagination, rate-limit handling) that's out of
scope until its own slice. What's here is deliberately just the
contract plus the plain-data type providers hand back, both of which
are needed *now* so sync_service.py has something concrete to import,
call, and test against a fake implementation, well before any real
provider exists.

Splitting this out from sync_service.py (rather than defining
FetchedMessage/EmailProvider inline there) keeps the future Gmail/
Graph/IMAP provider modules -- and their OAuth-specific dependencies --
out of the orchestration module entirely: sync_service.py will only
ever need to import names from this file, never a provider's own
client library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .models import EmailAccount


class ProviderError(Exception):
    """Base class for a provider failing to fetch messages. Callers
    (sync_service.sync_account) should treat any subclass as "this
    sync attempt didn't complete," distinct from "the fetched messages
    just happened to be empty," which is not an error at all."""


class ProviderAuthError(ProviderError):
    """The stored credentials for this EmailAccount are no longer
    valid -- an OAuth token was revoked, a refresh token expired, an
    app password was changed, etc. This is NOT retryable by simply
    running sync again; the account needs to be reconnected. See
    sync_service.sync_account(), which catches this specifically to
    mark the account "blocked" rather than silently leaving it
    "connected" with a sync that quietly did nothing."""


class ProviderTemporaryError(ProviderError):
    """A transient failure -- rate limiting, a network timeout, a 5xx
    from the provider's API. Retryable on a later sync without any
    user action; sync_service.sync_account() does not change the
    account's status for this, unlike ProviderAuthError."""


@dataclass(frozen=True)
class FetchedMessage:
    """One email, as handed to sync_service by a provider, in exactly
    the shape email_sync.matching's classification functions expect.
    Every field beyond message_id is optional and defaults to None --
    a provider that can't cheaply supply something (e.g. raw MIME
    source, which is expensive to fetch in bulk from some APIs) should
    just omit it rather than fetching it speculatively; the matching
    functions that use it (extract_html_source_urls, in particular)
    are already written to treat "no raw_source" as "no HTML links
    recoverable this way," not as an error.

    message_id must be the same stable identifier the provider would
    return for this message on every future sync (Gmail's message id,
    a Message-ID header, etc.) -- it is the dedupe key AccountMatch and
    Discovery both enforce uniqueness on, so sync's idempotency
    guarantee depends on it never changing between runs for the same
    message.
    """

    message_id: str
    subject: str | None = None
    sender: str | None = None
    received_at: datetime | None = None
    # Plain-text body, used for term matching and extract_posting_urls.
    body: str | None = None
    # Raw RFC 5322 header block, used for extract_thread_message_ids.
    raw_headers: str | None = None
    # Raw MIME source, used for extract_html_source_urls when the
    # plain-text body doesn't carry the underlying <a href> links.
    raw_source: str | None = None


class EmailProvider(abc.ABC):
    """What sync_service.sync_account() needs from any mailbox
    provider. A single method rather than the old AppleScript version's
    split between search_messages (coarse term search) and
    search_unmatched_messages (separate "does this look like
    application mail" search): a real API-backed provider building its
    own query can -- and should -- combine both into one request
    (fetch everything that's either a term hit or plausibly
    application-related), same "coarse search, precision-filter in
    Python afterward" split matching.py's own docstrings describe.
    Returning too broad a set costs sync_service a bit of extra
    classification work; returning too narrow a set silently drops
    real matches, so providers should err toward over-fetching.
    """

    @abc.abstractmethod
    def fetch_messages(
        self,
        account: EmailAccount,
        terms: list[str],
        since: datetime | None = None,
    ) -> Iterable[FetchedMessage]:
        """Every message worth classifying for this account: matches
        one of `terms` (a whole-word-unsafe, coarse substring search --
        sync_service re-checks precision itself, see
        matching.term_matches_wholeword) OR plausibly reads as
        application-related mail on its own (an ATS sender domain, an
        ATS subject phrase, a whitelisted job-posting sender -- see
        matching.looks_like_untracked_application). `since`, when
        given, limits the search to messages received on/after that
        time (typically account.last_synced_at) so a repeat sync
        doesn't re-fetch the account's entire history every time;
        omit or ignore it for a full backfill.

        Raises ProviderAuthError if the account's credentials are no
        longer valid, ProviderTemporaryError for a retryable failure.
        """


_REGISTRY: dict[str, type[EmailProvider]] = {}


def register_provider(name: str):
    """Class decorator: `@register_provider("gmail")` on a future
    GmailProvider makes get_provider("gmail") resolve to it. Kept as a
    plain module-level registry (not Django settings/apps machinery)
    since providers are plugged in by name via EmailAccount.provider,
    not configured per-project."""

    def _decorate(cls: type[EmailProvider]) -> type[EmailProvider]:
        _REGISTRY[name] = cls
        return cls

    return _decorate


def get_provider(provider_name: str) -> EmailProvider:
    """Look up and instantiate the EmailProvider registered for
    `provider_name` (an EmailAccount.provider value). Raises
    ProviderError if none is registered -- true today for every
    provider name, since no real Gmail/Outlook/IMAP client exists yet;
    callers that already have a provider instance (every current test,
    via a fake) should pass it directly to sync_service.sync_account()
    rather than going through this lookup."""
    try:
        cls = _REGISTRY[provider_name]
    except KeyError as exc:
        raise ProviderError(
            f"no email provider registered for {provider_name!r} yet -- "
            "OAuth providers (Gmail/Outlook) are a later Phase 9 slice"
        ) from exc
    return cls()
