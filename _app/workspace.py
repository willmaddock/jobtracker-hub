"""
Workspace registry — lets JobTracker Hub manage more than one fully
isolated tracker ("profile") from a single running server.

Each workspace has its own:
    - root folder (an Applications/ tree, same shape as the original)
    - jobtracker.db  (disposable index, rebuilt from that root)
    - overrides.db   (durable notes/status/dates, never touched by rebuild)

The registry itself lives in a small JSON file next to this one
(_app/workspaces.json) and is the *only* new piece of persistent state
this feature adds. It never rewrites or moves anything that already
existed before this feature was added — see bootstrap() below.

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

from classify import should_ignore
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

_lock = Lock()  # registry reads/writes are rare and cheap; simple is fine


class WorkspaceError(ValueError):
    """Raised for any invalid workspace operation (bad name, unknown id,
    attempt to delete the last/default workspace, etc), *and* for the
    packaged-mode "no tracker linked yet" state. api.py turns these into
    400s (or, for resolve_active with nothing linked yet, a clear message
    the first-run picker can show instead of a raw 500)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_entry() -> dict:
    return {
        "id": DEFAULT_ID,
        "name": DEFAULT_NAME,
        "root": str(ORIGINAL_ROOT),
        "db_path": str(APP_DIR / "jobtracker.db"),
        "ov_db_path": str(APP_DIR / "overrides.db"),
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
    """{'active': <id-or-None>, 'workspaces': [{id,name,root,created,kind}, ...]}
    (db_path/ov_db_path deliberately omitted from the list view — those
    are internal, the frontend never needs them). active is None only in
    packaged mode before the first tracker is linked/created — the
    frontend/launcher treat that as "show the picker", not an error."""
    data = _load_raw()
    entries = [
        {"id": w["id"], "name": w["name"], "root": w["root"], "created": w["created"], "kind": w.get("kind", "owned")}
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

        root = _new_sibling_root(clean_name)
        (root / "Applications").mkdir(parents=True, exist_ok=True)

        ws_dir = WORKSPACES_DB_DIR / workspace_id
        ws_dir.mkdir(parents=True, exist_ok=True)

        entry = {
            "id": workspace_id,
            "name": clean_name,
            "root": str(root),
            "db_path": str(ws_dir / "jobtracker.db"),
            "ov_db_path": str(ws_dir / "overrides.db"),
            "created": _now_iso(),
            "kind": "owned",
        }
        data["workspaces"][workspace_id] = entry
        _save_raw(data)
        return entry


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
    moved, or deleted."""
    with _lock:
        data = _load_raw()
        existing_names = {w["name"] for w in data["workspaces"].values()}
        clean_name = _validate_name(name, existing_names)

        root = Path(folder).expanduser().resolve()
        if not root.is_dir():
            raise WorkspaceError(f"That folder doesn't exist: {root}")

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
            "ov_db_path": str(ws_dir / "overrides.db"),
            "created": _now_iso(),
            "kind": "linked",
        }
        data["workspaces"][workspace_id] = entry
        _save_raw(data)
        return entry


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


def _new_sibling_root(clean_name: str) -> Path:
    """Picks and creates a not-yet-existing sibling folder for a
    brand-new tracker — same naming/collision handling used by
    create_workspace() and both import paths below. Uses
    _owned_siblings_dir() so packaged mode lands in ~/Documents/JobTracker
    Hub instead of inside the read-only .app bundle."""
    siblings_dir = _owned_siblings_dir()
    root = siblings_dir / f"JobTracker — {clean_name}"
    suffix = 2
    while root.exists():
        root = siblings_dir / f"JobTracker — {clean_name} ({suffix})"
        suffix += 1
    root.mkdir(parents=True, exist_ok=True)
    return root


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
    if any(should_ignore(part) for part in relpath.split("/")):
        return None
    dest = (root / relpath).resolve()
    try:
        dest.relative_to(resolved_root)
    except ValueError:
        return None
    return dest


def _finish_import(clean_name: str, root: Path, extracted_any: bool, empty_message: str) -> dict:
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
        "ov_db_path": str(ws_dir / "overrides.db"),
        "created": _now_iso(),
        "kind": "owned",
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

            root = _new_sibling_root(clean_name)
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

        root = _new_sibling_root(clean_name)
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

        root = _new_sibling_root(clean_name)
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
            dirnames[:] = [d for d in dirnames if not should_ignore(d)]
            for filename in filenames:
                if should_ignore(filename):
                    continue
                file_path = Path(dirpath) / filename
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
    """Removes the workspace from the registry, deletes its own DB pair
    (_app/workspaces/<id>/jobtracker.db, overrides.db), and — for an
    app-owned workspace only — sends its `root` folder to the OS
    Trash/Recycle Bin, recoverable there, same as document/category
    deletion elsewhere in this app.

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

    # Best-effort cleanup of this workspace's own DB folder. Only ever
    # removes _app/workspaces/<id>/, never anything under the
    # workspace's root (already handled above).
    ws_dir = (WORKSPACES_DB_DIR / workspace_id).resolve()
    try:
        ws_dir.relative_to(WORKSPACES_DB_DIR.resolve())
    except ValueError:
        return  # paranoia: never rmtree outside the workspaces dir
    if ws_dir.exists():
        import shutil
        shutil.rmtree(ws_dir, ignore_errors=True)
