"""
Domain-level errors — plain Python exceptions with no FastAPI dependency.

This is the piece the original api.py functions didn't have: item_key_for,
resolve_safe, and resolve_safe_dir all raised fastapi.HTTPException directly,
which meant none of them could be called (or tested) without FastAPI
installed and importable. That's a small thing for item_key_for, but it's
exactly the coupling that would block reusing this same logic from a future
Django view, a CLI script, or a plain pytest unit test with no HTTP
machinery at all.

api.py registers a FastAPI exception handler for each of these (see the
diff notes in EXTRACTION_NOTES.md) so existing routes keep returning the
exact same status codes and messages as before -- this is a structural
change only, not a behavior change.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain/infrastructure errors in this package."""


class ItemNotFoundError(DomainError):
    """No items row exists for the given numeric id (e.g. the index was
    rebuilt since the id was issued, or it was never valid)."""

    def __init__(self, app_id: int):
        self.app_id = app_id
        super().__init__(f"No application with id {app_id}. Try rebuilding the index.")


class PathEscapesRootError(DomainError):
    """A relpath resolved outside the current tracker root -- refused
    regardless of whether it was malicious or just a bad/stale path, since
    the caller can't tell the difference from here."""

    def __init__(self, relpath: str):
        self.relpath = relpath
        super().__init__("Path escapes JobTracker root.")


class FileNotFoundInRootError(DomainError):
    def __init__(self, relpath: str):
        self.relpath = relpath
        super().__init__(f"File not found: {relpath}")


class InvalidApplicationFolderError(DomainError):
    """relpath was empty, '.', or 'Applications' itself -- refusing to
    resolve it as a deletable application folder."""

    def __init__(self, relpath: str):
        self.relpath = relpath
        super().__init__("Refusing to delete: not a valid application folder.")


class RootDeletionRefusedError(DomainError):
    def __init__(self):
        super().__init__("Refusing to delete the JobTracker root.")


class ApplicationFolderNotFoundError(DomainError):
    def __init__(self, relpath: str):
        self.relpath = relpath
        super().__init__(f"Application folder not found: {relpath}")


class JobPostingNotFoundError(DomainError):
    def __init__(self, job_id: int):
        self.job_id = job_id
        super().__init__("No such job posting.")


class JobPostingAlreadyAppliedError(DomainError):
    """The posting already has an applied_item_key -- refuse a second
    apply rather than silently creating a duplicate application folder
    for the same posting."""

    def __init__(self, job_id: int):
        self.job_id = job_id
        super().__init__("Already applied to this posting.")


class InvalidApplyStatusError(DomainError):
    def __init__(self, status: str, valid_statuses):
        self.status = status
        self.valid_statuses = valid_statuses
        super().__init__(f"Unknown status '{status}'. Must be one of {valid_statuses}.")


class TrashFailedError(DomainError):
    """send2trash raised, or (macOS-specific) silently no-op'd without
    actually moving the file -- see infrastructure/paths.py's trash_path
    for why both cases are checked."""

    def __init__(self, path_name: str, reason: str):
        self.path_name = path_name
        self.reason = reason
        super().__init__(
            f"Couldn't move '{path_name}' to Trash ({reason}). "
            "On macOS this is almost always a missing Automation/Finder "
            "permission for whatever process is running this server — "
            "check System Settings > Privacy & Security > Automation "
            "(or Files and Folders) and allow it there, then try again."
        )
