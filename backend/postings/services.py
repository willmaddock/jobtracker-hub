"""
postings services.

Phase 5 (docs/DJANGO_MIGRATION_PLAN.md) port of _app/domain/
job_postings.py. Unlike applications/services.py, this one isn't a
verbatim port -- the shape of "has this posting been applied to"
changed under it in Phase 3: the old schema's job_postings.
applied_item_key was a bare string (nullable, matched loosely against
items.item_key) specifically because item_key was the only identity
available at the time. postings/models.py's JobPosting.
applied_application is a real nullable FK to Application now, so the
eligibility check below reads applied_application_id instead of
applied_item_key, and build_apply_response returns the Application's
own id instead of the old response's item_id/item_key pair -- there's
only one id to report once Application.id is the real identity (see
applications/models.py).

What ported unchanged: the actual business rules -- a posting is
eligible to apply to exactly when it exists and hasn't already been
applied to; an apply's requested status has to be one the caller's
STATUS_ORDER-equivalent recognizes, or be blank/falsy (meaning "don't
set manual_status at all"). Still no I/O here on purpose, same as the
original: the route/view still owns creating the Application, saving
the source email as a Document, and the Override writes, in that
order -- see the original module's docstring for why that sequencing
isn't a "pure" function.
"""
from __future__ import annotations

from core.exceptions import (
    InvalidApplyStatusError,
    JobPostingAlreadyAppliedError,
    JobPostingNotFoundError,
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


def ensure_postable(job, job_id: int) -> None:
    """A posting is eligible to apply to exactly when it exists and
    hasn't already been applied to -- applying twice would silently
    create a second Application for the same posting, with no link
    back telling you the first one exists.
    """
    if job is None:
        raise JobPostingNotFoundError(job_id)
    if job.applied_application_id:
        raise JobPostingAlreadyAppliedError(job_id)


def build_apply_response(application) -> dict:
    """Shape of the success response. Simpler than the original's
    ok/relpath/item_id/item_key: Application.id is the one real
    identity now (see applications/models.py), so there's nothing
    else to report once the Application row exists -- no separate
    disposable-index id that might not have picked up the new folder
    yet, since there's no folder/index to walk in the first place.
    """
    return {
        "ok": True,
        "application_id": application.id,
    }
