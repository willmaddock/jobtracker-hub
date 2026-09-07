"""
Business rules around turning a job posting into a real tracked
application (apply_to_job_posting) -- what makes a posting eligible to
apply to, and what the response looks like once it's done.

Extracted from api.py's apply_to_job_posting route body. Deliberately a
*narrower* extraction than domain/applications.py's: apply_to_job_posting
is mostly orchestration of real side effects in a specific order --
create a folder on disk, save a PDF, rebuild the index, write three
overrides.db rows -- and forcing that sequence itself into a "pure"
function would mean either faking the filesystem/rebuild/DB in the
signature (indirection with no real testability gain, since the sequence
still needs real I/O to verify) or hiding the same I/O one level deeper.

What *is* genuinely separable -- and is exactly what's here -- is the
part with actual business rules and no I/O: whether a posting is even
eligible to be applied to (not already applied), whether the requested
status is valid, and what shape the success response takes. Each of
these was a small inline check/HTTPException scattered through the route
body; here they're plain functions over plain dicts, raising the same
domain errors as domain/errors.py's other modules, so they're callable
and testable with no FastAPI, no DB connection, and no filesystem at all.

The route itself still owns: connection management, create_application_
folder/_save_email_evidence_pdf/ensure_not_empty/build (the actual side
effects, in order), and the three overrides.db writes once the new item
exists -- none of that moved, since none of it is a business rule
separable from the I/O it performs.
"""

from __future__ import annotations

from domain.errors import (
    InvalidApplyStatusError,
    JobPostingAlreadyAppliedError,
    JobPostingNotFoundError,
)


def validate_apply_status(status: str, valid_statuses) -> None:
    """A blank/falsy status means "don't set manual_status at all" and is
    always fine -- only a *non-empty* status has to be one db.STATUS_ORDER
    recognizes. valid_statuses is passed in (db.STATUS_ORDER) rather than
    imported, so this has no dependency on db.py's schema module beyond
    what the caller already gives it."""
    if status and status not in valid_statuses:
        raise InvalidApplyStatusError(status, valid_statuses)


def ensure_postable(job, job_id: int) -> None:
    """A posting is eligible to apply to exactly when it exists and
    hasn't already been applied to -- applying twice would silently
    create a second application folder for the same posting, with no
    link back telling you the first one exists."""
    if job is None:
        raise JobPostingNotFoundError(job_id)
    if job["applied_item_key"]:
        raise JobPostingAlreadyAppliedError(job_id)


def build_apply_response(relpath: str, row) -> dict:
    """Shape of the success response, whether or not the rebuilt index
    actually picked up an items row for the new folder (row is None in
    the rare case build() didn't index it, e.g. a filesystem hiccup right
    after the folder was created) -- ok/relpath are always present so the
    caller knows the folder itself was created either way."""
    return {
        "ok": True,
        "relpath": relpath,
        "item_id": row["id"] if row is not None else None,
        "item_key": row["item_key"] if row is not None else None,
    }
