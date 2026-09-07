"""
Filesystem path safety and mutation -- pure infrastructure, no business
rules about *what* an application/document means, only *where it's allowed
to touch disk*.

Extracted from api.py verbatim (previous names: resolve_safe,
resolve_safe_dir, guess_media_type, _trash_path, _remove_empty_parents).
Same functional change throughout as domain/identity.py: these raise plain
domain errors instead of fastapi.HTTPException, so path-safety logic is
testable with a plain tmp_path fixture and no running API.

Imports below are absolute (`from domain.errors import ...`, not
`from ..domain.errors import ...`) to match this codebase's flat import
style -- _app/ itself is a sys.path entry, not a package (no
_app/__init__.py, see conftest.py), so `domain` and `infrastructure` are
each top-level packages from Python's point of view, not siblings under a
shared parent package that a `..`-relative import could reach.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from send2trash import send2trash

from domain.errors import (
    ApplicationFolderNotFoundError,
    FileNotFoundInRootError,
    InvalidApplicationFolderError,
    PathEscapesRootError,
    RootDeletionRefusedError,
    TrashFailedError,
)

# Moved from api.py's module-level EXTRA_MEDIA_TYPES constant -- import
# that dict here instead of redefining it, so there's exactly one copy.
from media_types import EXTRA_MEDIA_TYPES


def resolve_safe(root: Path, relpath: str) -> Path:
    """Resolve a relpath against `root` and refuse anything that escapes it
    (defense in depth -- relpaths only ever come from our own index, but
    this is reachable from the browser). `root` is passed in explicitly
    now instead of read from current_root() -- callers (the FastAPI route)
    own resolving *which* workspace root applies; this function only
    enforces the escape check against whatever root it's given."""
    root = root.resolve()
    full = (root / relpath).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        raise PathEscapesRootError(relpath)
    if not full.exists() or not full.is_file():
        raise FileNotFoundInRootError(relpath)
    return full


def resolve_safe_dir(root: Path, relpath: str) -> Path:
    """Same guarantee as resolve_safe, but for a whole application folder
    (source_relpath) instead of a single file -- used by application
    delete. Deliberately refuses the root itself and 'Applications/' itself
    (an empty/blank relpath), so a bad or missing source_relpath can never
    trash the whole JobTracker folder or the entire Applications section."""
    root = root.resolve()
    relpath = (relpath or "").strip()
    if not relpath or relpath in (".", "Applications"):
        raise InvalidApplicationFolderError(relpath)
    full = (root / relpath).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        raise PathEscapesRootError(relpath)
    if full == root:
        raise RootDeletionRefusedError()
    if not full.exists() or not full.is_dir():
        raise ApplicationFolderNotFoundError(relpath)
    return full


def guess_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in EXTRA_MEDIA_TYPES:
        return EXTRA_MEDIA_TYPES[ext]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def trash_path(full_path: Path) -> None:
    """Moves a file or folder to the OS Trash (send2trash -- recoverable,
    never a permanent unlink) and verifies it's actually gone. Shared by
    every delete path (single document, single application, bulk
    application delete, category delete) so they all get identical error
    handling instead of each duplicating this logic slightly differently."""
    try:
        send2trash(str(full_path))
    except Exception as e:
        raise TrashFailedError(full_path.name, str(e))

    # Belt-and-suspenders: on macOS, send2trash's AppleScript/Finder path
    # can swallow a missing-Automation-permission failure and return
    # successfully without actually moving anything. If we drop DB rows
    # and report success anyway, the file/folder quietly reappears on the
    # next rebuild and looks exactly like "delete doesn't work." Guard
    # against that by checking it's actually gone before touching the
    # database.
    if full_path.exists():
        raise TrashFailedError(full_path.name, "still on disk after the Trash call")


def remove_empty_parents(path: Path, stop_at: Path) -> None:
    """Walks up from `path`'s parent, removing now-empty directories,
    stopping at (and never removing) `stop_at` itself or anything outside
    it. Used after trashing a Role/ subfolder or a nested category item so
    an empty Company/ (or similar) shell doesn't linger on disk. Never
    trashes a directory that still has something in it."""
    stop_at = stop_at.resolve()
    parent = path.parent
    while parent != stop_at and stop_at in parent.parents and parent.exists() and not any(parent.iterdir()):
        empty_parent = parent
        parent = parent.parent
        try:
            empty_parent.rmdir()
        except OSError:
            # Not empty after all (race) or some other filesystem hiccup --
            # leave it rather than risk removing something unexpected.
            break
