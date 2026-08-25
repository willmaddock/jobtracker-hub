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

REGISTRY_PATH = APP_DIR / "workspaces.json"
# Extra per-workspace DB pairs live here, one folder per workspace id.
# The "default" workspace is the one exception — it keeps using
# _app/jobtracker.db / _app/overrides.db directly, exactly as before.
WORKSPACES_DB_DIR = APP_DIR / "workspaces"

DEFAULT_ID = "default"
DEFAULT_NAME = "Job Search"

_lock = Lock()  # registry reads/writes are rare and cheap; simple is fine


class WorkspaceError(ValueError):
    """Raised for any invalid workspace operation (bad name, unknown id,
    attempt to delete the last/default workspace, etc). api.py turns
    these into 400 responses."""


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
    }


def _load_raw() -> dict:
    if not REGISTRY_PATH.exists():
        return {"active": DEFAULT_ID, "workspaces": {DEFAULT_ID: _default_entry()}}
    try:
        data = json.loads(REGISTRY_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        # Corrupt/unreadable registry — never let this take the whole app
        # down. Fall back to a fresh registry; the default workspace still
        # points at exactly the same files it always did.
        return {"active": DEFAULT_ID, "workspaces": {DEFAULT_ID: _default_entry()}}
    data.setdefault("workspaces", {})
    if DEFAULT_ID not in data["workspaces"]:
        data["workspaces"][DEFAULT_ID] = _default_entry()
    data.setdefault("active", DEFAULT_ID)
    if data["active"] not in data["workspaces"]:
        data["active"] = DEFAULT_ID
    return data


def _save_raw(data: dict) -> None:
    REGISTRY_PATH.write_text(json.dumps(data, indent=2))


def bootstrap() -> None:
    """Idempotent — safe to call on every server start. Creates
    workspaces.json (pointing "default" at the folders already in use)
    the first time only; a no-op on every later start."""
    with _lock:
        if not REGISTRY_PATH.exists():
            _save_raw({"active": DEFAULT_ID, "workspaces": {DEFAULT_ID: _default_entry()}})


def list_workspaces() -> dict:
    """{'active': <id>, 'workspaces': [{id,name,root,created}, ...]}
    (db_path/ov_db_path deliberately omitted from the list view — those
    are internal, the frontend never needs them)."""
    data = _load_raw()
    entries = [
        {"id": w["id"], "name": w["name"], "root": w["root"], "created": w["created"]}
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
    switch takes effect immediately without a server restart."""
    data = _load_raw()
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


def create_workspace(name: str) -> dict:
    """Creates a brand-new, fully isolated tracker: a sibling folder next
    to the original JobTracker root (so it's just as easy to find in
    Finder/Explorer as the original), with its own empty Applications/
    folder and its own DB pair under _app/workspaces/<id>/. Does NOT
    switch to it — call set_active() separately (api.py does both in one
    request)."""
    with _lock:
        data = _load_raw()
        existing_names = {w["name"] for w in data["workspaces"].values()}
        clean_name = _validate_name(name, existing_names)

        base_slug = _slugify(clean_name)
        workspace_id = f"{base_slug}-{uuid.uuid4().hex[:6]}"

        # Sibling of the ORIGINAL root's parent, not the currently-active
        # root — new trackers should always land next to your one real
        # JobTracker folder, regardless of which workspace you're viewing
        # when you create it.
        siblings_dir = ORIGINAL_ROOT.parent
        root = siblings_dir / f"JobTracker — {clean_name}"
        suffix = 2
        while root.exists():
            root = siblings_dir / f"JobTracker — {clean_name} ({suffix})"
            suffix += 1
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
    """Picks and creates a not-yet-existing sibling folder next to the
    original root for a brand-new tracker — same naming/collision
    handling used by create_workspace() and both import paths below."""
    siblings_dir = ORIGINAL_ROOT.parent
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
        clean_name = _validate_name(name, existing_names)

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
        clean_name = _validate_name(name, existing_names)

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
        for path in sorted(root.rglob("*")):
            if path.is_dir():
                continue
            relparts = path.relative_to(root).parts
            if any(should_ignore(part) for part in relparts):
                continue
            zf.write(path, arcname="/".join(relparts))

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
    (_app/workspaces/<id>/jobtracker.db, overrides.db), and sends its
    `root` folder to the OS Trash/Recycle Bin — recoverable there, same
    as document/category deletion elsewhere in this app, just no longer
    left behind untouched on disk.

    This is safe precisely because every non-default workspace's root is
    a folder *this app created* — a fresh sibling ("JobTracker — <name>")
    made by create_workspace() or one of the import paths, which only
    ever copies files into it, never moves the original source. So
    trashing it here never touches anything the app didn't create itself
    — the "never destructive to something it didn't create" rule this
    app follows everywhere else still holds; it's just that an
    app-created folder is fair game once you've asked to remove it.

    The default workspace's root is the one exception, and it's already
    excluded below: it's your original folder, not something the app
    made, so it's never a candidate for this at all. The default
    workspace (and the last remaining workspace of any kind) can't be
    removed — there always has to be one."""
    with _lock:
        data = _load_raw()
        if workspace_id not in data["workspaces"]:
            raise WorkspaceError(f"No such tracker: {workspace_id}")
        if workspace_id == DEFAULT_ID:
            raise WorkspaceError("The original tracker can't be removed — you can rename it instead.")
        if len(data["workspaces"]) <= 1:
            raise WorkspaceError("Can't remove the only remaining tracker.")
        root = Path(data["workspaces"][workspace_id]["root"])
        del data["workspaces"][workspace_id]
        if data["active"] == workspace_id:
            data["active"] = DEFAULT_ID
        _save_raw(data)

    # Outside the lock (registry write is already durable) — best-effort
    # from here down. A failure trashing the folder (already gone,
    # permissions, no trash helper on this OS) should never leave the
    # workspace stuck half-deleted in the registry, so this never raises.
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
