"""Posting ingestion and status validation; allocation lives in applications.creation."""
from __future__ import annotations

from core.exceptions import (
    InvalidApplyStatusError,
)


def validate_apply_status(status: str, valid_statuses) -> None:
    """A blank/falsy status means "don't set manual_status at all" and
    is always fine -- only a *non-empty* status has to be one of
    Application.STATUS_CHOICES' values. valid_statuses is passed in
    rather than imported, so this has no direct dependency on
    applications.models beyond what the caller already gives it.
    """
    if status and status not in valid_statuses:
        raise InvalidApplyStatusError(status, valid_statuses)


def ingest_extracted_postings(
    account,
    message_id: str,
    sender: str | None,
    subject: str | None,
    body: str | None,
    received_at=None,
    posting_urls=None,
) -> list:
    """Phase 6 ingestion glue: turns extraction.extract_postings()'s raw
    dicts into real, deduped JobPosting rows for one email.

    posting_urls, if given, is a list of per-job URLs positionally
    aligned with extract_postings()'s return list (index i's URL goes
    with raw_jobs[i]) -- extraction.py deliberately doesn't attach URLs
    itself (see its module docstring's Layer 4 note: URL-to-job
    association isn't reliable enough to do positionally inside the
    body parsers). Not yet wired to a real caller -- Phase 9 is where
    an actual sync loop exists to call this with real per-job URLs from
    mail_app_store's/the OAuth provider's URL extraction. Until then
    this is exercised directly (management command, shell, tests).

    Deliberately idempotent via JobPosting.dedupe_key: calling this
    again for the same message_id (same account, same URLs) updates
    the same rows via update_or_create rather than creating duplicates
    -- required for Phase 9's "running sync four times in a row
    produces the same posting count each time" acceptance bar, even
    though that loop doesn't exist yet.
    """
    from .extraction import compute_dedupe_key, extract_postings
    from .models import JobPosting

    raw_jobs = extract_postings(sender, subject, body)
    postings = []
    for i, job in enumerate(raw_jobs):
        posting_url = posting_urls[i] if posting_urls and i < len(posting_urls) else None
        dedupe_key = compute_dedupe_key(
            str(account.id), message_id, posting_url, job.get("title"), job.get("company"),
        )
        posting, _created = JobPosting.objects.update_or_create(
            dedupe_key=dedupe_key,
            defaults={
                "workspace": account.workspace,
                "account": account,
                "message_id": message_id,
                "source": job.get("source"),
                "title": job.get("title"),
                "company": job.get("company"),
                "location": job.get("location"),
                "salary": job.get("salary"),
                "employment_type": job.get("employment_type"),
                "posting_url": posting_url,
                "received_at": received_at,
                "email_subject": subject,
                "sender": sender,
            },
        )
        postings.append(posting)
    return postings
