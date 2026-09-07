"""
core exceptions.

Phase 5 (docs/DJANGO_MIGRATION_PLAN.md) port of _app/domain/errors.py.
The plan's instruction here was to "swap HTTPException-style errors
for DRF APIException subclasses (or a custom exception_handler) using
the same status codes and messages domain/errors.py already defines,
so behavior doesn't silently shift." Going with APIException
subclasses directly rather than a custom exception_handler: DRF's
default view dispatch already turns an uncaught APIException into the
right Response using its status_code/detail, so a plain `raise
JobPostingAlreadyAppliedError(job_id)` from service-layer code (see
postings/services.py) is enough on its own -- no
settings.REST_FRAMEWORK["EXCEPTION_HANDLER"] override needed. These
are still plain exceptions otherwise, so they're just as raiseable
from a management command or a test as from a DRF view.

What did NOT come along from domain/errors.py, and why:

- PathEscapesRootError, FileNotFoundInRootError,
  InvalidApplicationFolderError, RootDeletionRefusedError,
  ApplicationFolderNotFoundError, TrashFailedError -- all of these
  existed to guard a literal filesystem path (a relpath under the
  JobTracker root) and to report send2trash failures. Phase 4
  replaced that whole surface with Document rows in S3-backed
  storage: there's no root to escape and no OS Trash to fail to move
  something into. The equivalent check is now a plain ownership
  lookup -- see documents/services.get_owned_document -- which fails
  with an ordinary 404 rather than a bespoke error class. This is
  exactly the "different and simpler permission check, not a
  like-for-like port" the migration plan flagged ahead of time in
  its Phase 0 endpoint inventory notes.

- ItemNotFoundError -- not ported either. It existed because the old
  schema's public id was an AUTOINCREMENT column reset on every
  index rebuild, so item_key (not id) was the real identity.
  Application.id has been the real identity since Phase 3 (see
  applications/models.py). A plain get_object_or_404(Application,
  pk=...) already produces the "no such application" 404 for free.

What DID come along: the job-posting-apply errors, unchanged in
status code and message -- that rule (is this posting still eligible
to apply to) has nothing to do with the filesystem.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException


class DomainError(APIException):
    """Base class for domain-rule violations raised from service-layer
    code (applications/services.py, postings/services.py, ...) rather
    than from a serializer's field validation.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Domain error."
    default_code = "domain_error"


class JobPostingNotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "No such job posting."
    default_code = "job_posting_not_found"

    def __init__(self, job_id: int):
        self.job_id = job_id
        super().__init__(self.default_detail)


class JobPostingAlreadyAppliedError(DomainError):
    """The posting already has an applied_application -- refuse a
    second apply rather than silently creating a duplicate
    Application for the same posting (see
    postings/models.py JobPosting.applied_application).
    """
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Already applied to this posting."
    default_code = "job_posting_already_applied"

    def __init__(self, job_id: int):
        self.job_id = job_id
        super().__init__(self.default_detail)


class InvalidApplyStatusError(DomainError):
    default_code = "invalid_apply_status"

    def __init__(self, status_value: str, valid_statuses):
        self.status_value = status_value
        self.valid_statuses = valid_statuses
        super().__init__(f"Unknown status '{status_value}'. Must be one of {valid_statuses}.")
