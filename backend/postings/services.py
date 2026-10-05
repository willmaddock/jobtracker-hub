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
    the same rows under Workspace serialization rather than creating duplicates
    -- required for Phase 9's "running sync four times in a row
    produces the same posting count each time" acceptance bar, even
    though that loop doesn't exist yet.
    """
    from .extraction import compute_dedupe_key, extract_postings
    from django.core.exceptions import ValidationError
    from django.db import router, transaction
    from email_sync.models import EmailAccount
    from .models import JobPosting, JobPostingAllocation, DESCRIPTOR_FIELDS, _lock_descriptor_workspace

    raw_jobs = extract_postings(sender, subject, body)
    postings = []
    for i, job in enumerate(raw_jobs):
        posting_url = posting_urls[i] if posting_urls and i < len(posting_urls) else None
        dedupe_key = compute_dedupe_key(
            str(account.id), message_id, posting_url, job.get("title"), job.get("company"),
        )
        using = router.db_for_write(JobPosting, instance=account)
        with transaction.atomic(using=using):
            persisted = EmailAccount.objects.using(using).filter(pk=account.pk).first()
            if persisted is None:
                raise ValidationError("Posting account no longer exists.")
            _lock_descriptor_workspace(persisted.workspace_id, using)
            if not EmailAccount.objects.using(using).filter(
                    pk=account.pk, workspace_id=persisted.workspace_id).exists():
                raise ValidationError("Posting account workspace changed.")
            posting = JobPosting.objects.using(using).select_for_update(of=("self",)).filter(
                dedupe_key=dedupe_key).first()
            if posting is not None and (posting.workspace_id != persisted.workspace_id
                                       or posting.account_id != persisted.pk):
                raise ValidationError("Posting dedupe identity has inconsistent ownership.")
            values = dict(message_id=message_id, posting_url=posting_url, received_at=received_at,
                          email_subject=subject, sender=sender)
            if posting is None or (not posting.descriptor_projections.using(using).exists()
                    and not JobPostingAllocation.objects.using(using).filter(posting=posting).exists()):
                values.update({name: job.get(name) for name in DESCRIPTOR_FIELDS})
            if posting is None:
                posting = JobPosting.objects.using(using).create(workspace_id=persisted.workspace_id,
                    account=persisted, dedupe_key=dedupe_key, **values)
            else:
                for name, value in values.items():
                    setattr(posting, name, value)
                posting.save(using=using, update_fields=set(values))
            postings.append(posting)
    return postings
