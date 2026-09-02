"""
Workspace registry — lets JobTracker Hub manage more than one fully
isolated tracker ("profile") from a single running server.

Each workspace has its own:
    - root folder (an Applications/ tree, same shape as the original)
    - jobtracker.db  (disposable index, rebuilt from that root — lives
      in this app's own private storage, keyed by workspace id)
    - overrides.db   (durable notes/status/dates, never touched by
      rebuild — lives INSIDE the workspace's own root, under a hidden
      "<root>/.jobtracker/" folder, so it travels automatically with
      the folder itself: linking, importing, copying, or zipping a
      tracker folder always carries your notes along. See
      _portable_ov_db_path() and _migrate_ov_db_if_needed() below for
      why this is the one exception to "root is only ever read, never
      written" for linked workspaces, and how existing trackers move
      over automatically the first time they're loaded after this
      changed.)

The registry itself lives in a small JSON file next to this one
(_app/workspaces.json) and is the *only* new piece of persistent state
this feature adds outside a workspace's own root. It never rewrites or
moves anything that already existed before this feature was added —
see bootstrap() below.

Nothing here talks to jobtracker.db/overrides.db directly; api.py still
owns all of that. This module only answers "where do the active
workspace's files live right now" and "what workspaces exist."
"""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from classify import SECTION_RULES, should_ignore
from send2trash import send2trash

APP_DIR = Path(__file__).resolve().parent
# Same folder your original single-tracker setup always used — this is
# where _app/ was nested before this feature existed, so it becomes
# workspace "default" with zero migration and zero file moves.
ORIGINAL_ROOT = APP_DIR.parent

# --- Packaged-mode switch -------------------------------------------------
# Set by desktop/launcher.py (never by hand in normal dev use). When unset,
# every path below resolves exactly as it always did — dev mode is
# byte-for-byte unchanged from before this feature existed.
#
# In a packaged .app, APP_DIR lives inside the read-only bundle
# (JobTracker Hub.app/Contents/Resources/_app), so nothing can be written
# next to it: no workspaces.json, no jobtracker.db, no new tracker folders.
# JOBTRACKER_STATE_DIR points at the OS's real per-app writable directory
# (macOS: ~/Library/Application Support/JobTracker Hub) instead.
IS_PACKAGED = bool(os.environ.get("JOBTRACKER_PACKAGED"))
_STATE_DIR_OVERRIDE = os.environ.get("JOBTRACKER_STATE_DIR")
STATE_DIR = Path(_STATE_DIR_OVERRIDE) if _STATE_DIR_OVERRIDE else APP_DIR

REGISTRY_PATH = STATE_DIR / "workspaces.json"
# Extra per-workspace DB pairs live here, one folder per workspace id.
# In dev mode, the "default" workspace is the one exception — it keeps
# using _app/jobtracker.db / _app/overrides.db directly, exactly as before.
# Packaged mode has no such exception: there is no default workspace, so
# every workspace (including the first one you ever link) gets a DB pair
# under here.
WORKSPACES_DB_DIR = STATE_DIR / "workspaces"

DEFAULT_ID = "default"
DEFAULT_NAME = "Job Search"

# --- Portable overrides.db -------------------------------------------------
# Notes/status/dates now live inside the workspace's own root, under this
# hidden subfolder, instead of in this app's private storage. Hidden (dot-
# prefixed) so should_ignore() keeps it out of the index and out of a plain
# folder browse — but _resolve_import_dest() and export_workspace_to_zip()
# both special-case this exact folder so it still rides along on
# import/export, unlike every other dotfile. See module docstring.
OVERRIDES_DIRNAME = ".jobtracker"
OVERRIDES_DB_FILENAME = "overrides.db"

_lock = Lock()  # registry reads/writes are rare and cheap; simple is fine


class WorkspaceError(ValueError):
    """Raised for any invalid workspace operation (bad name, unknown id,
    attempt to delete the last/default workspace, etc), *and* for the
    packaged-mode "no tracker linked yet" state. api.py turns these into
    400s (or, for resolve_active with nothing linked yet, a clear message
    the first-run picker can show instead of a raw 500)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _portable_ov_db_path(root: Path) -> Path:
    """Where this workspace's overrides.db lives: inside its own root,
    under a hidden .jobtracker/ folder — never in this app's private
    storage. This is the single source of truth for the path; _load_raw()
    recomputes it from `root` for every entry on every load rather than
    trusting whatever's stored in workspaces.json, so a workspace's notes
    always follow wherever its root currently points."""
    return root / OVERRIDES_DIRNAME / OVERRIDES_DB_FILENAME


def _migrate_ov_db_if_needed(entry: dict) -> None:
    """One-time, best-effort move of a workspace's overrides.db from its
    old (pre-portability) location — this app's own private storage,
    wherever `entry["ov_db_path"]` used to point — into the workspace's
    own root. Safe to call on every _load_raw(): once the old file is
    gone, later calls are just an existence check and a no-op. Never
    raises — a failed migration should never break the app or the
    registry load that triggered it; worst case the old file just sits
    there untouched and gets picked up on a later run.

    Skips the move (rather than overwriting) if something's already at
    the new location — e.g. a linked folder that was previously exported
    from this same app and already has its own .jobtracker/overrides.db
    — so this never clobbers real data with an empty/older file."""
    old_path_str = entry.get("ov_db_path")
    if not old_path_str:
        return
    root = Path(entry["root"])
    old_path = Path(old_path_str)
    new_path = _portable_ov_db_path(root)
    if old_path == new_path or not old_path.exists() or new_path.exists():
        return
    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_path), str(new_path))
        # SQLite's WAL mode can leave -wal/-shm sidecars next to the db
        # with uncommitted-but-checkpointed data if the app wasn't closed
        # cleanly — bring those along too so nothing is silently dropped.
        for suffix in ("-wal", "-shm"):
            sidecar = Path(old_path_str + suffix)
            if sidecar.exists():
                shutil.move(str(sidecar), str(new_path) + suffix)
    except OSError:
        pass


def _default_entry() -> dict:
    root = ORIGINAL_ROOT
    return {
        "id": DEFAULT_ID,
        "name": DEFAULT_NAME,
        "root": str(root),
        "db_path": str(APP_DIR / "jobtracker.db"),
        "ov_db_path": str(_portable_ov_db_path(root)),
        "created": _now_iso(),
        "kind": "owned",
    }


def _empty_registry() -> dict:
    """Dev mode has always self-healed a "default" entry pointing at the
    bundle's own folder, since that folder is a real, writable tracker
    root in dev. Packaged mode must NOT do this: APP_DIR is inside the
    read-only .app bundle, so a "default" entry there would point at
    Resources/_app — not a tracker, and not writable. Packaged mode
    starts with no workspaces at all; the first-run picker's job is to
    get one created via link_workspace() or create_workspace()."""
    if IS_PACKAGED:
        return {"active": None, "workspaces": {}}
    return {"active": DEFAULT_ID, "workspaces": {DEFAULT_ID: _default_entry()}}


def _load_raw() -> dict:
    if not REGISTRY_PATH.exists():
        return _empty_registry()
    try:
        data = json.loads(REGISTRY_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        # Corrupt/unreadable registry — never let this take the whole app
        # down. Fall back to a fresh registry.
        return _empty_registry()
    data.setdefault("workspaces", {})
    if not IS_PACKAGED and DEFAULT_ID not in data["workspaces"]:
        # Dev-mode self-heal only. In packaged mode, an absent "default"
        # entry just means no tracker has been linked yet — never
        # fabricate one.
        data["workspaces"][DEFAULT_ID] = _default_entry()
    for entry in data["workspaces"].values():
        # Dev-mode upgrade path: entries saved before "kind" existed.
        # Every pre-existing entry was copy-based (create_workspace() or
        # an import), so "owned" is the correct backfill, including for
        # "default" itself.
        entry.setdefault("kind", "owned")
        # Upgrade path for entries saved before overrides.db became
        # portable: move the file into the workspace's own root the
        # first time it's seen, then always resolve ov_db_path fresh
        # from `root` rather than trusting whatever's stored — see
        # _portable_ov_db_path()/_migrate_ov_db_if_needed() above. This
        # intentionally doesn't persist the updated path back to
        # workspaces.json here (that would mean writing from inside a
        # read path, which every caller of _load_raw() relies on being
        # side-effect-free) — it's simply recomputed on every load,
        # which is equally correct and gets written out for free the
        # next time any mutating call below happens to save this entry.
        _migrate_ov_db_if_needed(entry)
        entry["ov_db_path"] = str(_portable_ov_db_path(Path(entry["root"])))
    data.setdefault("active", DEFAULT_ID if not IS_PACKAGED else None)
    if data["active"] is not None and data["active"] not in data["workspaces"]:
        data["active"] = DEFAULT_ID if (not IS_PACKAGED and DEFAULT_ID in data["workspaces"]) else None
    return data


def _save_raw(data: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(data, indent=2))


def bootstrap() -> None:
    """Idempotent — safe to call on every server start. Dev mode: creates
    workspaces.json (pointing "default" at the folders already in use)
    the first time only. Packaged mode: creates an empty registry (no
    workspaces yet) the first time only — link_workspace()/
    create_workspace() populate it from the first-run picker. Either
    way, a no-op on every later start."""
    with _lock:
        if not REGISTRY_PATH.exists():
            _save_raw(_empty_registry())


def list_workspaces() -> dict:
    """{'active': <id-or-None>, 'workspaces': [{id,name,root,created,kind,
    has_portable_overrides}, ...]} (db_path/ov_db_path deliberately
    omitted from the list view — those are internal, the frontend never
    needs them). active is None only in packaged mode before the first
    tracker is linked/created — the frontend/launcher treat that as
    "show the picker", not an error.

    has_portable_overrides powers the workspace status card (a "linked
    folder" vs. "JobTracker-owned copy" + "notes stored with tracker"
    checkmark) purely from data that already exists here -- no new
    storage, see kind and _portable_ov_db_path()."""
    data = _load_raw()
    entries = [
        {
            "id": w["id"],
            "name": w["name"],
            "root": w["root"],
            "created": w["created"],
            "kind": w.get("kind", "owned"),
            "has_portable_overrides": _portable_ov_db_path(Path(w["root"])).is_file(),
        }
        for w in data["workspaces"].values()
    ]
    entries.sort(key=lambda w: (w["id"] != DEFAULT_ID, w["created"]))
    return {"active": data["active"], "workspaces": entries}


def get_entry(workspace_id: str) -> dict:
    data = _load_raw()
    entry = data["workspaces"].get(workspace_id)
    if entry is None:
        raise WorkspaceError(f"No such tracker: {workspace_id}")
    return entry


def resolve_active() -> tuple[Path, Path, Path, dict]:
    """Returns (root, db_path, ov_db_path, entry) for whichever workspace
    is currently active. Called fresh on every request in api.py, so a
    switch takes effect immediately without a server restart.

    Raises WorkspaceError (never a bare KeyError) if there's no active
    workspace yet — only reachable in packaged mode before the first
    tracker is linked, since dev mode always self-heals a default. api.py
    turns this into a readable 400 instead of a 500."""
    data = _load_raw()
    if data["active"] is None or data["active"] not in data["workspaces"]:
        raise WorkspaceError("No tracker selected yet — choose or link a folder first.")
    entry = data["workspaces"][data["active"]]
    return Path(entry["root"]), Path(entry["db_path"]), Path(entry["ov_db_path"]), entry


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "tracker"


def _validate_name(name: str, existing_names: set[str], *, exclude_id: str | None = None) -> str:
    name = (name or "").strip()
    if not name:
        raise WorkspaceError("Tracker name can't be empty.")
    if len(name) > 80:
        raise WorkspaceError("Tracker name is too long (80 characters max).")
    if name.lower() in {n.lower() for n in existing_names}:
        raise WorkspaceError(f"A tracker named '{name}' already exists.")
    return name


_OWNED_ROOT_PREFIX = "JobTracker — "


def _strip_owned_prefix(name: str) -> str:
    """Strips a leading "JobTracker — " from a proposed tracker name.

    Every owned tracker's root folder is named "JobTracker — <name>"
    (see _new_sibling_root). That prefix can leak back in as a *name*
    two ways: importing a zip whose suggested/default name comes from
    the export's own filename (which is itself already
    "JobTracker — <name>.zip" in some flows), or -- the more common
    case -- picking an existing app-owned folder as an import source,
    where the packaged app's native folder picker defaults the name to
    the folder's own basename (desktop/launcher.py's import_folder).
    Left unstripped, _new_sibling_root would prepend the prefix a
    second time ("JobTracker — JobTracker — <name>"), and it would
    compound further on every subsequent export/reimport cycle.
    Only applied where a name is about to become (part of) a new owned
    root's folder name -- link_workspace/rename_workspace never add
    this prefix, so they leave whatever the user typed alone."""
    if name.startswith(_OWNED_ROOT_PREFIX):
        stripped = name[len(_OWNED_ROOT_PREFIX):].strip()
        return stripped or name
    return name


def _owned_siblings_dir() -> Path:
    """Where app-created ("owned") sibling tracker folders go — used by
    create_workspace() and both import paths. In dev mode this is just
    next to the original root, exactly as always. In packaged mode,
    ORIGINAL_ROOT.parent is meaningless (APP_DIR is nested inside the
    read-only .app bundle, so its parent is some bundle-internal
    Resources/ or Contents/ folder) — use ~/Documents/JobTracker Hub
    instead, a normal, visible, writable place."""
    if IS_PACKAGED:
        docs_dir = Path.home() / "Documents" / "JobTracker Hub"
        docs_dir.mkdir(parents=True, exist_ok=True)
        return docs_dir
    return ORIGINAL_ROOT.parent


def create_workspace(name: str) -> dict:
    """Creates a brand-new, fully isolated tracker: a sibling folder
    (dev mode: next to the original JobTracker root; packaged mode:
    under ~/Documents/JobTracker Hub — see _owned_siblings_dir()), with
    its own empty Applications/ folder and its own DB pair. Tagged
    kind:"owned" since this app made the folder and copies files into
    it — as opposed to kind:"linked" (see link_workspace()), an existing
    folder registered in place. Does NOT switch to it — call
    set_active() separately (api.py does both in one request)."""
    with _lock:
        data = _load_raw()
        existing_names = {w["name"] for w in data["workspaces"].values()}
        clean_name = _strip_owned_prefix(_validate_name(name, existing_names))

        base_slug = _slugify(clean_name)
        workspace_id = f"{base_slug}-{uuid.uuid4().hex[:6]}"

        root, stale_siblings_found = _new_sibling_root(clean_name)
        (root / "Applications").mkdir(parents=True, exist_ok=True)

        ws_dir = WORKSPACES_DB_DIR / workspace_id
        ws_dir.mkdir(parents=True, exist_ok=True)

        entry = {
            "id": workspace_id,
            "name": clean_name,
            "root": str(root),
            "db_path": str(ws_dir / "jobtracker.db"),
            "ov_db_path": str(_portable_ov_db_path(root)),
            "created": _now_iso(),
            "kind": "owned",
            "stale_siblings_found": stale_siblings_found,
        }
        data["workspaces"][workspace_id] = entry
        _save_raw(data)
        return entry


# Cap file scanning in inspect_folder() so pointing it at an enormous
# folder (a whole Documents tree, an old Time Machine mount, etc.) can't
# hang the picker -- callers only need a rough sense of "is there
# anything here", not an exact count.
_INSPECT_FILE_SCAN_CAP = 2000


def _matches_known_section(top_level_name: str) -> bool:
    """True if `top_level_name` matches one of classify.py's own
    SECTION_RULES (Applications, Certifications, References, ...) --
    the exact same rules build_index.py uses, so a folder this function
    calls tracker-shaped is one a real rebuild would actually recognize,
    not a separate guess that could disagree with it."""
    return any(pattern.search(top_level_name) for pattern, _ in SECTION_RULES)


def inspect_folder(folder: str | Path) -> dict:
    """Read-only preview of what linking/importing `folder` would mean,
    called by the API *before* any workspace is created -- so the picker
    (first-run.html, and the in-app "Link existing folder" flow) can show
    the user what's actually there instead of linking blind. This is the
    fix for the exact failure mode of manually shuttling files in
    Terminal because the app gave no feedback about what it found: now
    there's a preview step in between "pick a folder" and "commit to it".

    Never writes anything and never raises WorkspaceError -- a bad path
    is reported back via the "error" key instead, since this is meant to
    render inline in a preview panel, not abort a request.

    Returns a dict:
        exists              -- False if the path doesn't exist or isn't
                                a directory (see "error" for why)
        error               -- human-readable reason, or None
        is_empty            -- no non-ignored files found anywhere inside
        file_count          -- non-ignored files found, capped at
                                _INSPECT_FILE_SCAN_CAP
        capped              -- True if file_count hit the cap (there may
                                be more)
        looks_like_tracker  -- at least one top-level folder matches a
                                known section name (Applications,
                                Certifications, References, ...)
        has_portable_overrides -- a .jobtracker/overrides.db already
                                sits in this folder, i.e. it's already
                                been used as a JobTracker root (linked,
                                exported, or unlinked-and-relinked)
        already_linked      -- this exact folder (after resolving
                                symlinks/relative bits) is already
                                another workspace's root
        already_linked_name -- that workspace's name, if already_linked
        internal_conflict   -- human-readable reason this folder can't be
                                used as a link/import target because it's
                                JobTracker's own internal storage (its
                                ".jobtracker" folder itself, or anything
                                nested inside an existing tracker's root)
                                -- or None if there's no such conflict.
                                See _internal_tracker_conflict().
    """
    result = {
        "exists": False,
        "error": None,
        "is_empty": True,
        "file_count": 0,
        "capped": False,
        "looks_like_tracker": False,
        "has_portable_overrides": False,
        "already_linked": False,
        "already_linked_name": None,
        "internal_conflict": None,
    }

    try:
        root = Path(folder).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        result["error"] = f"That path isn't valid: {exc}"
        return result

    if not root.exists():
        result["error"] = "That folder doesn't exist."
        return result
    if not root.is_dir():
        result["error"] = "That's not a folder."
        return result

    result["exists"] = True

    # Compare against every registered workspace's own *resolved* root
    # (not the raw stored string), so a symlink or trailing-slash
    # difference doesn't produce a false negative.
    data = _load_raw()
    for w in data["workspaces"].values():
        try:
            other_root = Path(w["root"]).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if other_root == root:
            result["already_linked"] = True
            result["already_linked_name"] = w.get("name")
            break

    result["internal_conflict"] = _internal_tracker_conflict(root, data)
    result["has_portable_overrides"] = _portable_ov_db_path(root).is_file()

    try:
        top_entries = [e for e in os.listdir(root) if not should_ignore(e)]
    except OSError as exc:
        result["error"] = f"Couldn't read that folder: {exc}"
        return result

    result["looks_like_tracker"] = any(
        (root / e).is_dir() and _matches_known_section(e) for e in top_entries
    )

    file_count = 0
    capped = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not should_ignore(d)]
        for fname in filenames:
            if should_ignore(fname):
                continue
            file_count += 1
            if file_count >= _INSPECT_FILE_SCAN_CAP:
                capped = True
                break
        if capped:
            break

    result["file_count"] = file_count
    result["capped"] = capped
    result["is_empty"] = file_count == 0
    return result


def link_workspace(name: str, folder: str | Path) -> dict:
    """Registers an EXISTING folder as a tracker in place — nothing is
    copied. This is the packaged app's primary "add a tracker" path: the
    native folder picker (desktop/launcher.py) points straight at a
    user's existing job-search folder (which may be large — years of
    resumes/cover letters), and copy-based create/import would be both
    slow and a surprising duplicate of files the user already manages
    directly in Finder.

    Tagged kind:"linked" so the UI can, if it ever wants to, treat this
    differently from an app-owned folder (e.g. "unlink" instead of
    "delete" — an unlink should never trash the user's own folder the
    way delete_workspace() trashes an app-owned one). This function
    itself does not implement that distinction beyond the tag; callers
    should not assume a linked workspace's root is safe to trash.

    `folder` must already exist and be a directory. An Applications/
    subfolder is created inside it if missing (same shape every other
    tracker root has), but nothing already in the folder is touched,
    moved, or deleted.

    Refuses (WorkspaceError) if `folder` is JobTracker's own internal
    storage folder, or is nested inside an existing tracker's root at
    all -- see _internal_tracker_conflict(). Without this check, picking
    e.g. an existing tracker's own ".jobtracker" folder in the native
    picker used to succeed silently: it created a spurious empty
    Applications/ folder inside that real tracker's internal storage and
    registered a permanently-empty duplicate workspace pointed at it. No
    data was ever corrupted by that (see docs/archive/handoffs/HANDOFF_SESSION16_LEGACY.md §3i for the full
    trace), but it produced a confusing, avoidable mess -- this guard
    stops it before it can happen."""
    with _lock:
        data = _load_raw()
        existing_names = {w["name"] for w in data["workspaces"].values()}
        clean_name = _validate_name(name, existing_names)

        root = Path(folder).expanduser().resolve()
        if not root.is_dir():
            raise WorkspaceError(f"That folder doesn't exist: {root}")

        conflict = _internal_tracker_conflict(root, data)
        if conflict:
            raise WorkspaceError(conflict)

        base_slug = _slugify(clean_name)
        workspace_id = f"{base_slug}-{uuid.uuid4().hex[:6]}"

        (root / "Applications").mkdir(parents=True, exist_ok=True)

        ws_dir = WORKSPACES_DB_DIR / workspace_id
        ws_dir.mkdir(parents=True, exist_ok=True)

        entry = {
            "id": workspace_id,
            "name": clean_name,
            "root": str(root),
            "db_path": str(ws_dir / "jobtracker.db"),
            # Portable path, not ws_dir -- if this folder already has a
            # .jobtracker/overrides.db (e.g. it was previously exported,
            # or unlinked and is now being relinked), that existing file
            # is what gets used here: nothing is created or overwritten,
            # this is just where get_conn() will find it.
            "ov_db_path": str(_portable_ov_db_path(root)),
            "created": _now_iso(),
            "kind": "linked",
        }
        data["workspaces"][workspace_id] = entry
        _save_raw(data)
        return entry


def _internal_tracker_conflict(root: Path, data: dict) -> str | None:
    """Returns a human-readable reason `root` is NOT a valid link/import
    target because it's JobTracker's own internal storage, or None if
    `root` is fine.

    Two cases, both real (see §3i of docs/archive/handoffs/HANDOFF_SESSION16_LEGACY.md — traced from a native
    folder-picker click that selected a tracker's own hidden storage
    folder one level too deep):
      1. `root`'s own name is the internal storage dirname (".jobtracker")
         itself.
      2. `root` sits *inside* another registered workspace's root at all
         (not just the ".jobtracker" case above -- any folder nested
         inside an existing tracker is a confusing, almost certainly
         accidental target for a brand-new tracker).

    Compares against every registered workspace's *resolved* root, the
    same way inspect_folder's already_linked check does, so a symlink or
    trailing-slash difference doesn't produce a false negative. `data`
    is the already-loaded registry (`_load_raw()`'s return value) so
    callers that already have it don't pay for a second load."""
    if root.name == OVERRIDES_DIRNAME:
        return (
            "That looks like JobTracker's own internal data folder, not a "
            "tracker folder — pick the folder one level up instead."
        )
    for w in data["workspaces"].values():
        try:
            other_root = Path(w["root"]).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if other_root == root:
            continue  # that's an already_linked match, not a nesting conflict
        try:
            root.relative_to(other_root)
        except ValueError:
            continue
        return (
            f'That folder is inside the existing tracker "{w.get("name")}" '
            "— pick a folder outside of any existing tracker instead."
        )
    return None


def _shared_top_level_prefix(names: list[str]) -> str | None:
    """If every path in `names` starts with the same single top-level
    folder (e.g. zipping/selecting the tracker folder itself, so every
    entry is "my-tracker/Applications/...", "my-tracker/References/..."),
    returns that prefix (with trailing "/") so callers can strip it —
    letting an import of the tracker's *contents* and an import of the
    tracker *folder* both land in the same place. Returns None if there's
    no single shared folder (already-flat contents, or genuinely mixed
    top-level entries)."""
    if not names:
        return None
    first_top = names[0].split("/", 1)[0]
    prefix = first_top + "/"
    return prefix if all(n.startswith(prefix) for n in names) else None


def _new_sibling_root(clean_name: str) -> tuple[Path, int]:
    """Picks and creates a not-yet-existing sibling folder for a
    brand-new tracker — same naming/collision handling used by
    create_workspace() and both import paths below. Uses
    _owned_siblings_dir() so packaged mode lands in ~/Documents/JobTracker
    Hub instead of inside the read-only .app bundle.

    Returns (root, skipped) where `skipped` is how many already-existing
    folders of this same base name it had to step past to land on `root`.
    This app's own registry (workspaces.json) is the only thing that
    tracks which folders are "real" trackers -- a folder can be left
    behind on disk with nothing pointing at it anymore (the registry got
    reset during development, an app reinstall, manual edits, etc.),
    and this function has no way to tell that apart from a folder someone
    is actively using. Previously it just silently incremented past
    whatever it found, which is how a name can quietly accumulate
    " (2)", " (3)", " (4)"... over repeated create/import attempts with
    nothing ever surfaced to the person doing it. Returning the count
    lets callers report it instead of hiding it."""
    siblings_dir = _owned_siblings_dir()
    root = siblings_dir / f"JobTracker — {clean_name}"
    suffix = 2
    skipped = 0
    while root.exists():
        skipped += 1
        root = siblings_dir / f"JobTracker — {clean_name} ({suffix})"
        suffix += 1
    root.mkdir(parents=True, exist_ok=True)
    return root, skipped


def _resolve_import_dest(root: Path, resolved_root: Path, raw_relpath: str, strip_prefix: str | None) -> Path | None:
    """Destination Path for one imported entry, or None if it should be
    skipped: filtered by should_ignore() (matches a real rebuild's
    ignore rules — _app/, hidden files, venvs, stray db/zip files),
    empty after prefix-stripping, or would escape `root` (zip-slip /
    path-traversal guard, refused per-entry rather than aborting the
    whole import)."""
    relpath = raw_relpath.replace("\\", "/")  # normalize in case a browser sends Windows-style separators
    if strip_prefix:
        if not relpath.startswith(strip_prefix):
            return None
        relpath = relpath[len(strip_prefix):]
    if not relpath:
        return None
    parts = relpath.split("/")
    # Everything under .jobtracker/ (in practice, just overrides.db) is
    # exempt from should_ignore(): it's a dotfile *and* ends in .db, both
    # normally-ignored patterns, but this is the one dotfile that should
    # survive an import intact -- it's how a re-imported export brings
    # its notes/status/dates along instead of starting them over. See
    # _portable_ov_db_path().
    if parts[0] != OVERRIDES_DIRNAME and any(should_ignore(part) for part in parts):
        return None
    dest = (root / relpath).resolve()
    try:
        dest.relative_to(resolved_root)
    except ValueError:
        return None
    return dest


def _finish_import(clean_name: str, root: Path, extracted_any: bool, empty_message: str, stale_siblings_found: int) -> dict:
    """Shared tail end of both import paths: bail out (and clean up the
    partially-created root) if nothing importable was found, otherwise
    make sure Applications/ exists, register the new workspace's DB pair,
    and save the registry. Assumes it's called from inside the module
    lock and inside an already-loaded `data` — see both callers."""
    if not extracted_any:
        shutil.rmtree(root, ignore_errors=True)
        raise WorkspaceError(empty_message)
    (root / "Applications").mkdir(parents=True, exist_ok=True)

    base_slug = _slugify(clean_name)
    workspace_id = f"{base_slug}-{uuid.uuid4().hex[:6]}"
    ws_dir = WORKSPACES_DB_DIR / workspace_id
    ws_dir.mkdir(parents=True, exist_ok=True)

    return {
        "id": workspace_id,
        "name": clean_name,
        "root": str(root),
        "db_path": str(ws_dir / "jobtracker.db"),
        # Portable path. If the imported zip/folder itself contained a
        # .jobtracker/overrides.db (see _resolve_import_dest's exemption
        # for that path below), it's already sitting at this exact
        # location by the time this returns -- imported notes/status
        # survive the round trip, not just imported files.
        "ov_db_path": str(_portable_ov_db_path(root)),
        "created": _now_iso(),
        "kind": "owned",
        "stale_siblings_found": stale_siblings_found,
    }


def import_workspace_from_zip(name: str, zip_path: Path) -> dict:
    """Same end result as create_workspace() — a brand-new, fully isolated
    tracker: sibling folder next to the original root, own DB pair under
    _app/workspaces/<id>/ — except the new root is populated from the
    given zip file instead of starting empty. Does NOT switch to it;
    call set_active() separately, same as create_workspace().

    Handles the common case where the zip wraps everything in one
    top-level folder (e.g. zipping the "my-tracker" folder itself
    produces entries like "my-tracker/Applications/...") by detecting
    and stripping that single shared prefix — see _shared_top_level_prefix.

    Raises WorkspaceError for a bad/unreadable zip, an empty zip, or a
    zip where every entry got filtered out (nothing importable found —
    most likely because it wasn't actually a JobTracker export)."""
    with _lock:
        data = _load_raw()
        existing_names = {w["name"] for w in data["workspaces"].values()}
        clean_name = _strip_owned_prefix(_validate_name(name, existing_names))

        try:
            zf = zipfile.ZipFile(zip_path)
        except zipfile.BadZipFile:
            raise WorkspaceError("That file isn't a valid .zip archive.")

        root = None
        with zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if not names:
                raise WorkspaceError("That zip file is empty.")
            strip_prefix = _shared_top_level_prefix(names)

            root, stale_siblings_found = _new_sibling_root(clean_name)
            resolved_root = root.resolve()

            extracted_any = False
            for member in zf.infolist():
                if member.is_dir():
                    continue
                dest = _resolve_import_dest(root, resolved_root, member.filename, strip_prefix)
                if dest is None:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
                extracted_any = True

        entry = _finish_import(
            clean_name, root, extracted_any,
            "Nothing importable was found in that zip — it may not be a "
            "JobTracker export, or everything in it was filtered out "
            "(app files, hidden files, caches).",
            stale_siblings_found,
        )
        data["workspaces"][entry["id"]] = entry
        _save_raw(data)
        return entry


def import_workspace_from_files(name: str, files: list[tuple[str, object]]) -> dict:
    """Same as import_workspace_from_zip, but for a folder picked directly
    from the browser's native folder picker instead of a zip — `files` is
    a list of (relative_path, readable_binary_stream) pairs, one per file
    in the selected folder (relative_path comes from the browser's
    File.webkitRelativePath, e.g. "my-tracker/Applications/Acme
    Robotics/resume.tex"). Same top-level-prefix stripping, same
    should_ignore() filtering, same zip-slip-style guard against a path
    escaping the new root. The *source* folder on your computer is never
    modified or deleted by this — only ever read from — so anything in
    it (including its own _app/ if it has one) stays exactly as it was."""
    with _lock:
        data = _load_raw()
        existing_names = {w["name"] for w in data["workspaces"].values()}
        clean_name = _strip_owned_prefix(_validate_name(name, existing_names))

        names = [relpath for relpath, _ in files]
        if not names:
            raise WorkspaceError("That folder is empty.")
        strip_prefix = _shared_top_level_prefix([n.replace("\\", "/") for n in names])

        root, stale_siblings_found = _new_sibling_root(clean_name)
        resolved_root = root.resolve()

        extracted_any = False
        for relpath, stream in files:
            dest = _resolve_import_dest(root, resolved_root, relpath, strip_prefix)
            if dest is None:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as out:
                shutil.copyfileobj(stream, out)
            extracted_any = True

        entry = _finish_import(
            clean_name, root, extracted_any,
            "Nothing importable was found in that folder — it may not be a "
            "JobTracker tracker folder, or everything in it was filtered "
            "out (app files, hidden files, caches).",
            stale_siblings_found,
        )
        data["workspaces"][entry["id"]] = entry
        _save_raw(data)
        return entry


def import_workspace_from_local_folder(name: str, folder: str | Path) -> dict:
    """Same as import_workspace_from_files, but for a folder already
    sitting on this machine's disk (packaged desktop's native
    FOLDER_DIALOG hands back a real path, not browser File objects) --
    used by desktop/launcher.py's Api.import_folder via
    /api/workspaces/import-folder-local. Unlike link_workspace(), this
    COPIES the folder's contents into a brand-new sibling root rather
    than pointing a tracker at it in place, matching the other two
    import paths (zip / browser folder picker) rather than link's
    behavior -- "Import tracker" always means "copy in", "Link existing
    folder" (first-run only) always means "use in place".

    Same top-level-prefix stripping and should_ignore() filtering as the
    other import paths. The source folder is only ever read here, never
    modified or deleted."""
    with _lock:
        data = _load_raw()
        existing_names = {w["name"] for w in data["workspaces"].values()}
        clean_name = _strip_owned_prefix(_validate_name(name, existing_names))

        src = Path(folder)
        if not src.is_dir():
            raise WorkspaceError("That folder doesn't exist or isn't a folder.")
        resolved_src = src.resolve()

        rel_paths = [
            str(p.relative_to(src)).replace("\\", "/")
            for p in src.rglob("*")
            if p.is_file()
        ]
        if not rel_paths:
            raise WorkspaceError("That folder is empty.")
        # Picking a folder directly (rather than its parent) never
        # yields a shared top-level prefix the way a zip or a browser
        # webkitdirectory selection can -- rglob's paths are already
        # relative to the chosen folder itself, so there's no wrapping
        # layer to strip. strip_prefix stays None here; _resolve_import_dest
        # still applies the same should_ignore() filtering either way.

        root, stale_siblings_found = _new_sibling_root(clean_name)
        resolved_root = root.resolve()

        extracted_any = False
        for rel in rel_paths:
            dest = _resolve_import_dest(root, resolved_root, rel, None)
            if dest is None:
                continue
            src_file = resolved_src / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)
            extracted_any = True

        entry = _finish_import(
            clean_name, root, extracted_any,
            "Nothing importable was found in that folder — it may not be a "
            "JobTracker tracker folder, or everything in it was filtered "
            "out (app files, hidden files, caches).",
            stale_siblings_found,
        )
        data["workspaces"][entry["id"]] = entry
        _save_raw(data)
        return entry


def export_workspace_to_zip(workspace_id: str, dest_zip: Path) -> str:
    """Writes a zip of the given workspace's root folder to `dest_zip`
    (the caller picks where — api.py uses a temp file it streams back and
    then deletes). Returns a suggested download filename,
    "{tracker-name}-{yyyy-mm-dd}.zip".

    Mirrors the import paths in reverse and shares their exact filtering:
    should_ignore() skips the same things a rebuild would (_app/ itself —
    relevant for the default workspace, where _app/ actually lives inside
    root — plus hidden files, venvs, stray db/zip files). Read-only: this
    never modifies, moves, or deletes anything under the workspace's root,
    it only reads from it."""
    entry = get_entry(workspace_id)
    root = Path(entry["root"])
    if not root.exists():
        raise WorkspaceError(f"This tracker's folder no longer exists: {root}")

    overrides_dir = root / OVERRIDES_DIRNAME
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        # os.walk (not Path.rglob) so ignored directories can be pruned
        # *before* descending into them, and so followlinks=False can be
        # set explicitly. This matters for "linked" workspaces (a real,
        # pre-existing folder the user pointed us at, as opposed to an
        # app-owned one) — those can contain things an app-owned tracker
        # never would: huge unrelated subtrees a naive rglob would still
        # walk into even though should_ignore() would filter their
        # files, or, worse, a symlink cycle (common in synced folders)
        # that Path.rglob would follow forever, hanging the export with
        # no error and no way to tell it apart from "just slow."
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            here = Path(dirpath)
            inside_overrides = here == overrides_dir
            # .jobtracker/ is a dotfile -- should_ignore() would normally
            # prune it and everything in it (overrides.db also matches
            # the .db suffix rule on top of that). It's exempted here so
            # an export always carries your notes/status/dates along,
            # not just your files -- see _portable_ov_db_path().
            dirnames[:] = [
                d for d in dirnames
                if (here == root and d == OVERRIDES_DIRNAME) or not should_ignore(d)
            ]
            for filename in filenames:
                if not inside_overrides and should_ignore(filename):
                    continue
                file_path = here / filename
                relparts = file_path.relative_to(root).parts
                try:
                    zf.write(file_path, arcname="/".join(relparts))
                except OSError:
                    # Permission-denied, broken symlink, file removed
                    # mid-walk, etc. -- skip that one file rather than
                    # aborting the whole export over it.
                    continue

    date_str = datetime.now().strftime("%Y-%m-%d")
    return f"{_slugify(entry['name'])}-{date_str}.zip"


def set_active(workspace_id: str) -> dict:
    with _lock:
        data = _load_raw()
        if workspace_id not in data["workspaces"]:
            raise WorkspaceError(f"No such tracker: {workspace_id}")
        data["active"] = workspace_id
        _save_raw(data)
        return data["workspaces"][workspace_id]


def rename_workspace(workspace_id: str, new_name: str) -> dict:
    with _lock:
        data = _load_raw()
        if workspace_id not in data["workspaces"]:
            raise WorkspaceError(f"No such tracker: {workspace_id}")
        existing_names = {
            w["name"] for wid, w in data["workspaces"].items() if wid != workspace_id
        }
        clean_name = _validate_name(new_name, existing_names)
        data["workspaces"][workspace_id]["name"] = clean_name
        _save_raw(data)
        return data["workspaces"][workspace_id]


def delete_workspace(workspace_id: str) -> None:
    """Removes the workspace from the registry, deletes its own cached
    index (_app/workspaces/<id>/jobtracker.db — overrides.db lives
    inside the workspace's own root now, not here, see module
    docstring), and — for an app-owned workspace only — sends its
    `root` folder (notes/status/dates included) to the OS Trash/Recycle
    Bin, recoverable there, same as document/category deletion
    elsewhere in this app.

    Trashing the root is safe for an "owned" workspace precisely
    because that folder is one *this app created* — a fresh sibling
    ("JobTracker — <name>") made by create_workspace() or one of the
    import paths, which only ever copies files into it, never moves
    the original source. So trashing it here never touches anything
    the app didn't create itself.

    A "linked" workspace's root is different: it's an existing folder
    the user pointed the app at in place (see link_workspace()) —
    trashing it would destroy files the app never created and doesn't
    own. Deleting a linked workspace must only remove it from the
    registry (and clean up this app's own DB pair for it); the
    user's folder itself is never touched.

    The default workspace's root is the one exception, and it's already
    excluded below: it's your original folder, not something the app
    made, so it's never a candidate for this at all. The default
    workspace can't be removed — there always has to be one of those in
    dev mode (see the self-heal in _load_raw). Packaged mode has no
    default at all, so there it's fine to delete down to zero
    workspaces — that's the same legitimate "no tracker yet" state a
    fresh install starts in (see /api/status's workspace: None), and
    the user can always link or create another."""
    with _lock:
        data = _load_raw()
        if workspace_id not in data["workspaces"]:
            raise WorkspaceError(f"No such tracker: {workspace_id}")
        if workspace_id == DEFAULT_ID:
            raise WorkspaceError("The original tracker can't be removed — you can rename it instead.")
        entry = data["workspaces"][workspace_id]
        root = Path(entry["root"])
        is_owned = entry.get("kind") == "owned"
        del data["workspaces"][workspace_id]
        if data["active"] == workspace_id:
            # DEFAULT_ID doesn't exist as a workspace in packaged mode, so
            # falling back to it unconditionally would leave "active"
            # pointing at nothing. Fall back to any remaining workspace
            # instead, or None if that was the last one (packaged mode
            # only -- dev mode always still has DEFAULT_ID left, since it
            # can never be the one just deleted, guarded above).
            data["active"] = next(iter(data["workspaces"]), None)
        _save_raw(data)

    # Outside the lock (registry write is already durable) — best-effort
    # from here down. A failure trashing the folder (already gone,
    # permissions, no trash helper on this OS) should never leave the
    # workspace stuck half-deleted in the registry, so this never raises.
    # Only ever trash an app-owned root -- a linked folder is the
    # user's own and must survive deletion untouched.
    if is_owned:
        try:
            if root.exists():
                send2trash(str(root))
        except Exception:
            pass

    # Best-effort cleanup of this workspace's own cached-index folder.
    # Only ever removes _app/workspaces/<id>/ (just jobtracker.db these
    # days), never anything under the workspace's root -- overrides.db
    # lives there now and is handled above (trashed with an owned root,
    # left untouched for a linked one).
    ws_dir = (WORKSPACES_DB_DIR / workspace_id).resolve()
    try:
        ws_dir.relative_to(WORKSPACES_DB_DIR.resolve())
    except ValueError:
        return  # paranoia: never rmtree outside the workspaces dir
    if ws_dir.exists():
        import shutil
        shutil.rmtree(ws_dir, ignore_errors=True)
