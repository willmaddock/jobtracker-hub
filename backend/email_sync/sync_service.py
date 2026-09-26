"""
Provider-agnostic sync orchestration -- the Phase 9 core that decides
*what to do* with a batch of fetched messages, independent of how they
were fetched (docs/DJANGO_MIGRATION_PLAN.md's Phase 9 section).

Deliberately kept separate from email_sync/providers.py: this module
imports no provider-specific code (no Gmail/Graph/IMAP client, no OAuth
token handling), only the EmailProvider *interface*. That means it's
fully coverable by tests today, against a fake in-memory provider,
well before any real OAuth credentials exist. Once a real provider
lands, sync_account() below is the function it plugs into -- nothing
here should need to change for that.

Idempotency (required by the migration plan -- "running sync four
times in a row should produce the same posting count each time, not
accumulate duplicates"):
  - AccountMatch has a (account, message_id) unique constraint; every
    match is created via get_or_create, never a blind insert.
  - Discovery has the same (account, message_id) shape. A message that
    already has a Discovery row -- in ANY status, including one the
    user already dismissed or accepted -- is never recreated or
    resurrected by a later sync. The user's own triage decision always
    wins over a re-sync seeing the same message again.
  - ThreadIdentifier is additive by design (see its own docstring);
    recording the same message_id against the same Application twice
    is a no-op via get_or_create.
  - EmailAccount.matched_email_count is recomputed from the actual
    AccountMatch count at the end of every sync, never incremented, so
    it can't drift from reality across repeated runs.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from applications.models import Application
from applications.creation import lock_workspace
from applications.retained_reviews import ensure_application_review

from .gmail_retention import mailbox_for_account, retain_gmail_message

from .matching import (
    extract_html_source_urls,
    extract_posting_urls,
    extract_primary_cta_url,
    extract_thread_message_ids,
    guess_company_from_email,
    is_job_posting_style_subject,
    is_usable_match_term,
    looks_like_untracked_application,
    term_matches_wholeword,
)
from .models import AccountMatch, Discovery, EmailAccount, JobPostingSender, ThreadIdentifier
from .providers import EmailProvider, FetchedMessage, ProviderAuthError, ProviderTemporaryError


@dataclass
class SyncResult:
    """Human-readable tally of one sync_account() run, for an API/CLI
    caller to report back to the user. Never consulted internally for
    idempotency decisions (those all live in the database constraints
    described in the module docstring) -- purely a summary."""

    account_id: int
    ok: bool = True
    error: str | None = None
    messages_seen: int = 0
    new_matches: int = 0
    new_discoveries: int = 0
    skipped_existing: int = 0


def _usable_terms(application: Application) -> list[str]:
    """company/role_label terms on `application` specific enough to
    match on (see matching.is_usable_match_term) -- an application
    with role_label "(root)" contributes only its company, one with
    both a generic company placeholder and a generic role contributes
    nothing and can only ever be reached via the thread-trust path."""
    return [
        term.strip()
        for term in (application.company, application.role_label)
        if is_usable_match_term(term)
    ]


def _all_search_terms(applications: list[Application]) -> list[str]:
    """De-duped (case-insensitively) usable terms across every
    candidate application, for handing to the provider as its coarse-
    search vocabulary."""
    seen: set[str] = set()
    terms: list[str] = []
    for app in applications:
        for term in _usable_terms(app):
            key = term.lower()
            if key not in seen:
                seen.add(key)
                terms.append(term)
    return terms


def _thread_trusted_application(
    message: FetchedMessage, thread_ids: set[str], applications: list[Application]
) -> Application | None:
    """The single-application trust path: if `message`'s own id or any
    id its In-Reply-To/References headers cite is already a known
    ThreadIdentifier for exactly one of `applications`, that
    application wins outright -- no term matching needed, and no
    ambiguity check either, even if the message's subject/body would
    otherwise look ambiguous (e.g. a bare "Re: quick question" that
    doesn't mention the company at all, or one that happens to mention
    a sibling company's name in a quoted reply chain). An established
    thread is a stronger signal than any subject/body heuristic. If the
    thread happens to touch more than one Application (shouldn't
    normally happen -- ThreadIdentifier rows are per-Application -- but
    two applications could theoretically share a quoted message id),
    this deliberately declines to guess and falls through to ordinary
    term matching instead.
    """
    candidate_ids = {value for value in (message.message_id, *thread_ids) if value}
    if not candidate_ids:
        return None
    app_ids = [app.id for app in applications]
    matched_app_ids = list(
        ThreadIdentifier.objects.filter(
            application_id__in=app_ids, message_id__in=candidate_ids
        )
        .values_list("application_id", flat=True)
        .distinct()
    )
    if len(matched_app_ids) != 1:
        return None
    by_id = {app.id: app for app in applications}
    return by_id.get(matched_app_ids[0])


def _term_matching_applications(
    message: FetchedMessage, applications: list[Application]
) -> list[Application]:
    """Every Application whose company or role_label term appears as a
    whole word (matching.term_matches_wholeword) in the message's
    subject or body. Usually zero or one; more than one happens when
    several tracked applications share a company (siblings, e.g. two
    different roles applied to at the same employer) and the message
    only mentions the company, not a specific role -- the caller routes
    that case to an ambiguous Discovery rather than guessing which
    sibling the message belongs to."""
    hits = []
    for app in applications:
        if any(term_matches_wholeword(term, message.subject, message.body) for term in _usable_terms(app)):
            hits.append(app)
    return hits


def _record_thread(application: Application, message: FetchedMessage, thread_ids: set[str]) -> None:
    for message_id in {message.message_id, *thread_ids}:
        ThreadIdentifier.objects.get_or_create(application=application, message_id=message_id)


def _create_confirmed_match(
    account: EmailAccount, application: Application, message: FetchedMessage
) -> tuple[AccountMatch, bool]:
    return AccountMatch.objects.get_or_create(
        account=account,
        message_id=message.message_id,
        defaults={
            "application": application,
            "subject": message.subject,
            "received_at": message.received_at,
        },
    )


def _guessed_posting_urls(message: FetchedMessage) -> list[str]:
    """Every posting-URL candidate recoverable for a message being
    filed as kind="posting", trying the plain-text body first and
    falling back to the raw MIME source's HTML links (see
    matching.extract_html_source_urls) only when the body yields
    nothing -- most providers supply a body, so the more expensive
    MIME parse is skipped whenever it isn't needed."""
    urls = extract_posting_urls(message.body)
    if urls:
        return urls
    return extract_html_source_urls(message.raw_source)


def _create_discovery(
    account: EmailAccount,
    message: FetchedMessage,
    *,
    match_kind: str,
    kind: str,
    candidate_applications: list[Application] | None = None,
) -> tuple[Discovery, bool]:
    posting_urls: list[str] = []
    posting_url: str | None = None
    if kind == "posting":
        posting_urls = _guessed_posting_urls(message)
        posting_url = posting_urls[0] if posting_urls else extract_primary_cta_url(message.body)

    discovery, created = Discovery.objects.get_or_create(
        account=account,
        message_id=message.message_id,
        defaults={
            "subject": message.subject,
            "sender": message.sender,
            "received_at": message.received_at,
            "guessed_company": guess_company_from_email(message.subject, message.sender),
            "match_kind": match_kind,
            "kind": kind,
            "posting_url": posting_url,
            "posting_urls": posting_urls,
        },
    )
    if created and candidate_applications:
        discovery.candidate_applications.set(candidate_applications)
    return discovery, created


def _classify_message(message, applications, always_posting_senders):
    """Existing relevance order, with no retention or projection effects."""
    thread_ids = extract_thread_message_ids(message.raw_headers or "")
    trusted = _thread_trusted_application(message, thread_ids, applications)
    if trusted is not None:
        return ("match", [trusted], thread_ids)
    general, posting = looks_like_untracked_application(
        message.subject, message.sender, always_posting_senders
    )
    if posting or is_job_posting_style_subject(message.subject):
        return ("posting", [], thread_ids)
    hits = _term_matching_applications(message, applications)
    if len(hits) == 1:
        return ("match", hits, thread_ids)
    if len(hits) > 1:
        return ("ambiguous", hits, thread_ids)
    if general:
        return ("application", [], thread_ids)
    return None


def _project_message(account, message, classification, result):
    """The single transitional RFC-ID projection path; never source authority."""
    kind, applications, thread_ids = classification
    if kind == "match":
        application = applications[0]
        _, created = _create_confirmed_match(account, application, message)
        if created:
            _record_thread(application, message, thread_ids)
            result.new_matches += 1
    else:
        _, created = _create_discovery(
            account, message,
            match_kind="ambiguous" if kind == "ambiguous" else "unmatched",
            kind="posting" if kind == "posting" else "application",
            candidate_applications=applications,
        )
        if created:
            result.new_discoveries += 1


def sync_account(
    account: EmailAccount,
    provider: EmailProvider,
    *,
    since: datetime | None = None,
    now: datetime | None = None,
) -> SyncResult:
    """Gmail fetches outside transactions and persists each relevant message atomically.

    Other providers keep their existing whole-pass transaction. Failed Gmail units
    roll back retention and projection together; earlier committed units are replay
    safe and the sync cursor advances only after the complete pass succeeds.
    """
    with nullcontext() if account.provider == "gmail" else transaction.atomic():
        return _sync_account(account, provider, since=since, now=now)


def _sync_account(account, provider, *, since, now):
    result = SyncResult(account_id=account.id)
    now = now or timezone.now()
    effective_since = since if since is not None else account.last_synced_at
    gmail = account.provider == "gmail"
    mailbox_id = mailbox_for_account(account) if gmail else None
    always_posting_senders = set(
        JobPostingSender.objects.filter(workspace_id=account.workspace_id).values_list("sender", flat=True)
    )
    applications = list(Application.objects.filter(workspace_id=account.workspace_id))
    terms = _all_search_terms(applications)
    try:
        messages = list(provider.fetch_messages(account, terms, since=effective_since))
    except ProviderAuthError as exc:
        account.status = "blocked"
        account.save(update_fields=["status", "updated_at"])
        result.ok = False
        result.error = str(exc)
        return result
    except ProviderTemporaryError as exc:
        result.ok = False
        result.error = str(exc)
        return result

    already_seen = set(
        AccountMatch.objects.filter(account=account).values_list("message_id", flat=True)
    ) | set(Discovery.objects.filter(account=account).values_list("message_id", flat=True))
    for message in messages:
        result.messages_seen += 1
        # RFC duplicate suppression must never hide native Gmail sources.
        if not gmail and message.message_id in already_seen:
            result.skipped_existing += 1
            continue
        classification = _classify_message(message, applications, always_posting_senders)
        if classification is None:
            if message.message_id in already_seen:
                result.skipped_existing += 1
            continue
        with transaction.atomic() if gmail else nullcontext():
            if gmail:
                lock_workspace(account.workspace.owner, account.workspace)
                kind = classification[0]
                reason = {"match": "application_evidence", "posting": "posting_source"}.get(kind, "discovery_review")
                retained = retain_gmail_message(account, message, reason, mailbox_id)
                # Conflicts preserve evidence but cannot cause new automatic effects.
                if retained.state == "conflict":
                    continue
                if retained.message_id is not None and kind in {"match", "ambiguous", "application"}:
                    ensure_application_review(actor=account.workspace.owner, workspace=account.workspace,
                        retained_message_id=retained.message_id, observation_id=retained.observation_id,
                        classification=kind, candidate_ids=[app.pk for app in classification[1]])
                if not message.rfc_message_id:
                    continue
                # Recheck inside the gate for competing syncs. Legacy rows remain
                # account/RFC scoped; they are not canonical source deduplication.
                seen = (AccountMatch.objects.filter(account=account, message_id=message.message_id).exists()
                        or Discovery.objects.filter(account=account, message_id=message.message_id).exists())
            else:
                seen = message.message_id in already_seen
            if seen:
                result.skipped_existing += 1
                continue
            _project_message(account, message, classification, result)

    with transaction.atomic() if gmail else nullcontext():
        if gmail:
            lock_workspace(account.workspace.owner, account.workspace)
            # Do not resurrect a concurrently disconnected account's status.
            current = EmailAccount.objects.get(pk=account.pk, workspace_id=account.workspace_id)
            account.status = current.status
        account.last_synced_at = now
        account.matched_email_count = AccountMatch.objects.filter(account=account).count()
        if account.status != "blocked" and (not gmail or account.status != "disconnected"):
            account.status = "connected"
        account.save(update_fields=["last_synced_at", "matched_email_count", "status", "updated_at"])
    return result
