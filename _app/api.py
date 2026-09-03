"""
JobTracker Hub — API server.

FastAPI backend for the JobTracker Hub web application. It doesn't
reimplement any indexing/status/staleness rules — it wraps db.py,
overrides_store.py, build_index.py, and classify.py, exposing them as
JSON for the web frontend in frontend/, and then serves that frontend
itself so the whole app lives at one origin.

Run with (from inside _app/):
    pip install -r requirements.txt
    uvicorn api:app --reload --port 8000

Then open http://localhost:8000 — that's it. The frontend is served by
this same process (see the StaticFiles mount at the bottom of this file),
so there's no separate dev server, no file:// page, and no CORS to worry
about.

Zero-config: `_app/` is meant to live nested one level inside your
JobTracker folder (see db.DEFAULT_ROOT), so there's no root path to type in
or store — /api/rebuild always (re)indexes the folder _app/ sits inside.

Two local SQLite files:
    - jobtracker.db  — disposable, rebuilt from your JobTracker folder
    - overrides.db   — your notes/status/dates/merges, never touched by rebuild

The server binds to 127.0.0.1 by default (see __main__ block) — this is a
single-user local tool, not something meant to be exposed on your network.
"""

from __future__ import annotations

import mimetypes
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import html as html_lib

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from send2trash import send2trash

import db
import dossier
import overrides_store as ov
import mail_app_store as mailapp
import labels
import workspace as ws
import email_pdf
import posting_extract
from build_index import build, create_application_folder, create_category_folder, ensure_not_empty, iso_mtime, sha256_of
from classify import classify_section
from classify import classify_doc_type, is_source_file, normalize_for_search
from db import APP_DIR

ws.bootstrap()
FRONTEND_DIR = APP_DIR / "frontend"


# --- active workspace (multi-tracker support) -------------------------------
# Every route below reads DEFAULT_ROOT/DB_PATH/OV_DB_PATH through these
# functions instead of using module-level constants, so a workspace switch
# (POST /api/workspaces/switch) takes effect on the very next request —
# no server restart. The "default" workspace resolves to exactly the same
# two files (_app/jobtracker.db, _app/overrides.db) and the same root
# (the folder _app/ is nested inside) this app always used, so nothing
# about the original single-tracker setup changes unless you actually
# create a second tracker.
def _active():
    return ws.resolve_active()


def current_root() -> Path:
    return _active()[0]


def current_db_path() -> Path:
    return _active()[1]


def current_ov_db_path() -> Path:
    return _active()[2]

# Explicit MIME types for formats browsers/servers sometimes guess wrong
# (or don't know at all, like .tex) — used by /api/file so inline
# previews (PDF iframe, .md/.tex text view) always get a sane Content-Type
# instead of falling back to application/octet-stream.
EXTRA_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".tex": "text/x-tex",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
}

# Extensions that /api/file renders as plain text in the iframe viewer.
# These get wrapped in our own minimal HTML (see _wrap_text_for_viewer)
# instead of served raw as text/plain/text/x-tex/etc. Raw text/* responses
# get handed to the browser's *native* plain-text viewer when loaded in an
# <iframe>, and that viewer's dark-mode handling is inconsistent for
# same-origin nested iframes vs. top-level navigation: the text color
# flips to white to match the OS/browser dark preference, but the
# background does not reliably flip with it, leaving white text on a
# transparent (effectively white, from the surrounding page) background.
# Wrapping the content ourselves means the colors are explicit CSS we
# control, so the page renders correctly regardless of how it's embedded.
TEXT_VIEWER_EXTENSIONS = {".txt", ".tex", ".md", ".markdown"}


def _wrap_text_for_viewer(raw_text: str) -> str:
    """Wrap raw text content in a small self-contained HTML page with
    explicit light/dark colors, for use by /api/file's inline iframe
    viewer. See TEXT_VIEWER_EXTENSIONS for why this exists instead of
    just serving text/plain directly."""
    escaped = html_lib.escape(raw_text)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  html, body {{
    margin: 0;
    padding: 0;
    background: #ffffff;
    color: #1a1a1a;
  }}
  pre {{
    margin: 0;
    padding: 16px;
    font-family: ui-monospace, Menlo, Consolas, monospace;
    font-size: 13px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-wrap: break-word;
  }}
  @media (prefers-color-scheme: dark) {{
    html, body {{ background: #1e1e1e; color: #e8e8e8; }}
  }}
</style>
</head>
<body>
<pre>{escaped}</pre>
</body>
</html>"""

app = FastAPI(title="JobTracker Hub API")

# Kept for flexibility (e.g. running the frontend from a separate dev
# server) even though the normal path — serving everything from this same
# process at http://localhost:8000 — never needs it. Note: frontend/index.html
# is designed to be served by this API (relative /api/... fetches), not
# opened directly as a file:// page — that origin isn't listed here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:8000", "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- helpers -----------------------------------------------------------------
def get_conns():
    if not current_db_path().exists():
        raise HTTPException(status_code=409, detail="Index not built yet. POST /api/rebuild first.")
    jt_conn = db.get_jt_conn(current_db_path())
    ov_conn = ov.get_conn(current_ov_db_path())
    return jt_conn, ov_conn


def resolve_safe(relpath: str) -> Path:
    """Resolve a relpath against DEFAULT_ROOT and refuse anything that
    escapes it (defense in depth — relpaths only ever come from our own
    index, but this endpoint is reachable from the browser)."""
    root = current_root().resolve()
    full = (root / relpath).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path escapes JobTracker root.")
    if not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {relpath}")
    return full


def resolve_safe_dir(relpath: str) -> Path:
    """Same guarantee as resolve_safe, but for a whole application folder
    (source_relpath) instead of a single file — used by application
    delete. Deliberately refuses the root itself and 'Applications/' itself
    (an empty/blank relpath), so a bad or missing source_relpath can never
    trash the whole JobTracker folder or the entire Applications section."""
    root = current_root().resolve()
    relpath = (relpath or "").strip()
    if not relpath or relpath in (".", "Applications"):
        raise HTTPException(status_code=400, detail="Refusing to delete: not a valid application folder.")
    full = (root / relpath).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path escapes JobTracker root.")
    if full == root:
        raise HTTPException(status_code=403, detail="Refusing to delete the JobTracker root.")
    if not full.exists() or not full.is_dir():
        raise HTTPException(status_code=404, detail=f"Application folder not found: {relpath}")
    return full


def guess_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in EXTRA_MEDIA_TYPES:
        return EXTRA_MEDIA_TYPES[ext]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def item_key_for(jt_conn, app_id: int) -> str:
    """Resolve a numeric `items.id` (what the frontend/URLs use) to the
    stable `item_key` that overrides.db is actually keyed by. Ids come
    from an AUTOINCREMENT column that gets reset on every /api/rebuild, so
    they're convenient/clean for routes and URLs but are NOT what
    overrides should be stored against — item_key (section|company|role|
    relpath) is the thing that survives a rebuild."""
    row = jt_conn.execute("SELECT item_key FROM items WHERE id = ?", (app_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No application with id {app_id}. Try rebuilding the index.")
    return row["item_key"]


# --- models --------------------------------------------------------------
class OverrideRequest(BaseModel):
    manual_status: Optional[str] = None
    reset_status: bool = False
    notes: Optional[str] = None
    date_applied: Optional[str] = None
    date_applied_source: Optional[str] = None  # "confirmation"/"posting" when accepting a
                                                # detected-date suggestion; omit for a manual
                                                # retype so save_override clears stale provenance
    next_action: Optional[str] = None
    next_action_date: Optional[str] = None
    archived: Optional[bool] = None
    snoozed_until: Optional[str] = None
    activity_override: Optional[str] = None  # "Reset activity clock" — ISO date


class BulkOverrideRequest(BaseModel):
    item_ids: list[int]
    manual_status: Optional[str] = None
    reset_status: bool = False
    archived: Optional[bool] = None
    snoozed_until: Optional[str] = None
    next_action: Optional[str] = None
    next_action_date: Optional[str] = None
    activity_override: Optional[str] = None


class OpenFileRequest(BaseModel):
    relpath: str


class OpenUrlRequest(BaseModel):
    url: str


class MergeRequest(BaseModel):
    names: list[str]
    canonical: str


class UnmergeRequest(BaseModel):
    alias: str


class DocumentOverrideRequest(BaseModel):
    relpath: str
    doc_type_override: Optional[str] = None  # None/empty clears the correction


class DeleteDocumentRequest(BaseModel):
    relpath: str


class HubCustomLinkRequest(BaseModel):
    link_name: str
    title: Optional[str] = None
    url: Optional[str] = None


class HubCustomCardRequest(BaseModel):
    category_id: str
    id: str
    title: str
    url: Optional[str] = None
    note: Optional[str] = None


class HubDeleteCustomCardRequest(BaseModel):
    category_id: str
    id: str


class RenameDocumentRequest(BaseModel):
    relpath: str
    new_filename: str


class BulkDeleteApplicationsRequest(BaseModel):
    item_ids: list[int]


# --- status / config -------------------------------------------------------
@app.get("/api/status")
def status():
    # Only reachable in packaged mode before the first tracker is
    # linked/created (dev mode always has "default"). Return a clear
    # "no workspace yet" shape instead of letting resolve_active()'s
    # WorkspaceError turn into an unhandled 500 — the frontend/first-run
    # picker checks /api/workspaces for this state anyway, but any client
    # hitting /api/status directly during that window should still get a
    # sane, documented response rather than a crash.
    import os

    packaged = os.environ.get("JOBTRACKER_PACKAGED") == "1"
    try:
        root, db_path, _ov_path, entry = _active()
    except ws.WorkspaceError:
        return {"workspace": None, "index_built": False, "doc_count": 0, "packaged": packaged}
    return {
        "root": str(root),
        "index_built": db_path.exists(),
        "doc_count": (
            db.get_jt_conn(db_path).execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            if db_path.exists() else 0
        ),
        "status_order": db.STATUS_ORDER,
        "status_colors": db.STATUS_COLORS,
        "status_icons": db.STATUS_ICONS,
        "section_labels": labels.SECTION_LABELS,
        "doc_type_labels": labels.DOC_TYPE_LABELS,
        # kind + has_portable_overrides back the workspace status card
        # (linked-in-place folder vs. JobTracker-owned copy, plus whether
        # notes/status travel with the folder) — both already sit in the
        # registry/filesystem, nothing new is stored for this.
        "workspace": {
            "id": entry["id"],
            "name": entry["name"],
            "kind": entry.get("kind", "owned"),
            "has_portable_overrides": _ov_path.is_file(),
        },
        # Lets the frontend tell "running inside the packaged desktop
        # shell (pywebview)" apart from "plain browser" -- used to swap
        # the folder-import flow, since pywebview substitutes its own
        # file dialog for <input type="file"> and never does the
        # browser-only webkitdirectory walk. See
        # /api/workspaces/import-folder-local and desktop/launcher.py's
        # Api.confirm_import_folder.
        "packaged": packaged,
    }


# --- diagnostics --------------------------------------------------------
# Everything a user (or whoever's helping them) needs to troubleshoot a
# stuck/misbehaving app, surfaced in Settings > Diagnostics. Deliberately
# separate from /api/status: this can be called and stay useful even if
# resolve_active() is failing, since half the point is diagnosing exactly
# that kind of thing.
@app.get("/api/diagnostics")
def diagnostics():
    import os
    import platform as platform_mod
    import sys as sys_mod

    state_dir = os.environ.get("JOBTRACKER_STATE_DIR")
    log_path = Path(state_dir) / "backend.log" if state_dir else None

    try:
        root, db_path, ov_path, entry = _active()
        workspace = {
            "name": entry["name"],
            "root": str(root),
            "index_built": db_path.exists(),
            "index_db": str(db_path),
            "overrides_db": str(ov_path),
        }
    except ws.WorkspaceError:
        workspace = None

    return {
        "port": os.environ.get("JOBTRACKER_PORT"),
        "packaged": os.environ.get("JOBTRACKER_PACKAGED") == "1",
        "state_dir": state_dir,
        "log_path": str(log_path) if log_path else None,
        "log_exists": log_path.exists() if log_path else False,
        "platform": platform_mod.platform(),
        "python_version": platform_mod.python_version(),
        "executable_frozen": getattr(sys_mod, "frozen", False),
        "workspace": workspace,
    }


@app.post("/api/diagnostics/reveal-log")
def reveal_log():
    """Same cross-platform 'shell out to the OS's default opener' approach
    as /api/open, but for the backend log file specifically -- reveals it
    in Finder/Explorer/file manager rather than opening it in an editor,
    since a user forwarding a bug report usually wants to attach/drag the
    file, not read it."""
    import os
    state_dir = os.environ.get("JOBTRACKER_STATE_DIR")
    if not state_dir:
        raise HTTPException(status_code=404, detail="No state directory configured (not running packaged).")
    log_path = Path(state_dir) / "backend.log"
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="No log file yet -- nothing has been written this session.")

    import platform
    import subprocess

    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", "-R", str(log_path)], check=False)
        elif system == "Windows":
            subprocess.run(["explorer", "/select,", str(log_path)], check=False)
        else:
            subprocess.run(["xdg-open", str(log_path.parent)], check=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not reveal log file: {e}")
    return {"ok": True}


# --- health ------------------------------------------------------------------
# Deliberately independent of workspace/db state — used by
# desktop/launcher.py to poll while waiting for the bundled backend
# subprocess to come up. Must return 200 even before any tracker has been
# linked (packaged mode's pre-first-run state), so the launcher can tell
# "process is alive" apart from "a tracker exists" (see /api/workspaces
# for the latter).
@app.get("/api/health")
def health():
    return {"ok": True}


# --- workspaces (multiple isolated trackers) --------------------------------
class CreateWorkspaceRequest(BaseModel):
    name: str


class SwitchWorkspaceRequest(BaseModel):
    id: str


class RenameWorkspaceRequest(BaseModel):
    name: str


class LinkWorkspaceRequest(BaseModel):
    name: str
    path: str


class InspectFolderRequest(BaseModel):
    path: str


@app.get("/api/workspaces")
def list_workspaces():
    return ws.list_workspaces()


@app.post("/api/workspaces/inspect")
def inspect_folder(req: InspectFolderRequest):
    """Read-only preview of what linking/importing a folder would mean —
    called by the picker (in-app "Link existing folder" and the desktop
    first-run flow) BEFORE the user commits, so they see what's actually
    in the folder instead of linking blind. See workspace.inspect_folder
    for the full shape of the response. Never 400s on a bad path — a
    missing/unreadable folder comes back as {"exists": false, "error":
    "..."} so the caller can render it inline instead of catching an
    exception."""
    return ws.inspect_folder(req.path)


@app.post("/api/workspaces")
def create_and_switch_workspace(req: CreateWorkspaceRequest):
    """Creates a brand-new, empty tracker (its own Applications/ folder,
    its own jobtracker.db/overrides.db) and switches to it immediately —
    same "create then use" pattern as /api/applications/new. Your other
    trackers, including the original, are completely untouched."""
    try:
        entry = ws.create_workspace(req.name)
        ws.set_active(entry["id"])
    except ws.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    build(current_root(), current_db_path())
    return {"ok": True, "workspace": {"id": entry["id"], "name": entry["name"], "stale_siblings_found": entry.get("stale_siblings_found", 0)}}


@app.post("/api/workspaces/link")
def link_workspace(req: LinkWorkspaceRequest):
    """Registers an EXISTING folder as a tracker in place (nothing
    copied) and switches to it immediately. This is what
    desktop/launcher.py's native folder-picker flow calls — see
    workspace.link_workspace for why linking, not copying, is the right
    behavior for a packaged app pointed at a user's own existing
    job-search folder. Also reachable from a browser dev workflow if a
    "Link existing folder" action is ever added to the web UI; nothing
    about this endpoint is packaged-mode-only."""
    try:
        entry = ws.link_workspace(req.name, req.path)
        ws.set_active(entry["id"])
    except ws.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    build(current_root(), current_db_path())
    return {"ok": True, "workspace": {"id": entry["id"], "name": entry["name"]}}


@app.post("/api/workspaces/import")
async def import_workspace(name: str = Form(...), file: UploadFile = File(...)):
    """Imports a .zip export of another JobTracker tracker as a brand-new
    workspace, then switches to it — same "create then use" pattern as
    the plain New Tracker endpoint above, except the new root is
    populated from the zip instead of starting empty. Accepts either a
    zip of the tracker folder's *contents* (Applications/, Certifications/,
    etc. at the top level) or a zip of the tracker *folder itself* — see
    workspace.import_workspace_from_zip for how that's detected. A 400
    means either the name was invalid, the upload wasn't a valid zip, or
    nothing importable was found inside it."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Please upload a .zip file.")

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        try:
            entry = ws.import_workspace_from_zip(name, tmp_path)
            ws.set_active(entry["id"])
        except ws.WorkspaceError as e:
            raise HTTPException(status_code=400, detail=str(e))
    finally:
        tmp_path.unlink(missing_ok=True)

    build(current_root(), current_db_path())
    return {"ok": True, "workspace": {"id": entry["id"], "name": entry["name"], "stale_siblings_found": entry.get("stale_siblings_found", 0)}}


@app.post("/api/workspaces/import-folder")
async def import_workspace_folder(name: str = Form(...), files: list[UploadFile] = File(...)):
    """Same end result as /api/workspaces/import above, but for a folder
    picked directly via the browser's native folder picker instead of a
    zip — the frontend sends every file in the folder in one multipart
    request, each with its browser-supplied relative path
    (File.webkitRelativePath) set as its filename so the server can
    rebuild the same folder structure. See
    workspace.import_workspace_from_files for the shared prefix-stripping
    and should_ignore() filtering (identical behavior to the zip path —
    an _app/ folder inside the picked folder, for instance, is skipped
    the same way). The folder on your computer is only ever read from
    here, never modified."""
    entries = [(f.filename or "", f.file) for f in files if f.filename]
    if not entries:
        raise HTTPException(status_code=400, detail="No files were received from that folder.")

    try:
        entry = ws.import_workspace_from_files(name, entries)
        ws.set_active(entry["id"])
    except ws.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))

    build(current_root(), current_db_path())
    return {"ok": True, "workspace": {"id": entry["id"], "name": entry["name"], "stale_siblings_found": entry.get("stale_siblings_found", 0)}}


class ImportLocalFolderRequest(BaseModel):
    name: str
    path: str


@app.post("/api/workspaces/import-folder-local")
def import_workspace_folder_local(req: ImportLocalFolderRequest):
    """Packaged-desktop counterpart to /api/workspaces/import-folder above.
    The browser version has to upload every file because a webpage can't
    read the filesystem directly -- but the packaged app's backend and
    its pywebview frontend are the same machine, so desktop/launcher.py's
    Api.confirm_import_folder can hand over a plain local folder path from its
    native FOLDER_DIALOG instead of re-uploading the whole folder over
    HTTP. Trusts the given path the same way /api/workspaces/link
    already does (both are only ever called by the local desktop shell,
    never reachable from the packaged app's web UI in a browser). See
    workspace.import_workspace_from_local_folder for the shared
    prefix-stripping/should_ignore() filtering (identical behavior to
    both other import paths). The source folder is only ever read from,
    never modified."""
    try:
        entry = ws.import_workspace_from_local_folder(req.name, req.path)
        ws.set_active(entry["id"])
    except ws.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))

    build(current_root(), current_db_path())
    return {"ok": True, "workspace": {"id": entry["id"], "name": entry["name"], "stale_siblings_found": entry.get("stale_siblings_found", 0)}}


@app.get("/api/workspaces/{workspace_id}/export")
def export_workspace(workspace_id: str, background_tasks: BackgroundTasks):
    """Streams a zip of the given tracker's data folder back as a
    download — the export counterpart to /api/workspaces/import(-folder).
    Read-only: never touches, moves, or deletes anything in the
    workspace's root. Works on any workspace in the list, not just the
    active one, same as rename/delete. The zip is written to a temp file
    and removed right after the response finishes sending (via
    BackgroundTasks) so nothing lingers on disk."""
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        filename = ws.export_workspace_to_zip(workspace_id, tmp_path)
    except ws.WorkspaceError as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(e))

    background_tasks.add_task(tmp_path.unlink, missing_ok=True)
    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=filename,
        background=background_tasks,
    )


@app.post("/api/workspaces/switch")
def switch_workspace(req: SwitchWorkspaceRequest):
    try:
        entry = ws.set_active(req.id)
    except ws.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "workspace": {"id": entry["id"], "name": entry["name"]}}


@app.post("/api/workspaces/{workspace_id}/rename")
def rename_workspace(workspace_id: str, req: RenameWorkspaceRequest):
    try:
        entry = ws.rename_workspace(workspace_id, req.name)
    except ws.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "workspace": {"id": entry["id"], "name": entry["name"]}}


@app.delete("/api/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str):
    """Removes the tracker from the switcher, deletes its own cache DB
    pair (_app/workspaces/<id>/jobtracker.db, overrides.db), and sends
    its root folder to the OS Trash — see workspace.py's delete_workspace
    docstring for why that's safe (the root is always a folder this app
    created, never something pointed at externally)."""
    try:
        ws.delete_workspace(workspace_id)
    except ws.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.post("/api/rebuild")
def rebuild():
    """(Re)indexes the active tracker's root folder. No path is ever
    accepted from the client.

    Only reachable with zero trackers in packaged mode (dev mode always
    has "default" — see /api/status). Onboarding's "no tracker yet"
    empty state is meant to keep this endpoint from ever being hit in
    that situation, but if it somehow is (e.g. a stale page reloaded
    after the last tracker was deleted elsewhere), resolve_active()'s
    WorkspaceError should surface as a clear 400, not an unhandled 500."""
    try:
        root, db_path = current_root(), current_db_path()
    except ws.WorkspaceError:
        raise HTTPException(
            status_code=400,
            detail="No tracker is set up yet. Create, import, or link one first.",
        )
    build(root, db_path)
    return {"ok": True}


# --- connected accounts -------------------------------------------------------
# Every connected account is a Mail.app account the user already set up
# in System Settings -> Internet Accounts. See mail_app_store.py for the
# AppleScript handshake -- no OAuth, no IMAP credentials, no keychain.

class MailAppConnectBody(BaseModel):
    name: str   # Mail.app's own account name, e.g. "hotmail" -- what mail_app_store.search_messages() queries by
    email: str  # display address, e.g. "stumping123@outlook.com"


@app.get("/api/accounts")
def list_accounts():
    _, ov_conn = get_conns()
    rows = ov.list_accounts(ov_conn)
    ov_conn.close()
    return rows


@app.get("/api/accounts/mail-app/available")
def list_available_mail_app_accounts():
    """Accounts Mail.app has configured that JobTracker Hub hasn't
    already connected -- what the '+ Connect an account' picker offers.
    A MailAppError here (osascript missing, Automation permission
    denied) surfaces as a 400 with mail_app_store's own message, which
    is already written for the end user."""
    try:
        all_accounts = mailapp.list_mail_app_accounts()
    except mailapp.MailAppError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _, ov_conn = get_conns()
    connected_names = {r["account_name"] for r in ov.list_accounts(ov_conn) if r.get("account_name")}
    ov_conn.close()
    return [a for a in all_accounts if a["name"] not in connected_names]


@app.post("/api/accounts/mail-app/connect")
def connect_mail_app_account(body: MailAppConnectBody):
    """No handshake needed -- Mail.app already owns this account's
    login. 'Connecting' just means recording it in overrides.db so the
    rest of the app knows to sync against it."""
    account_id = mailapp.new_account_id()
    _, ov_conn = get_conns()
    ov.upsert_account(ov_conn, account_id, "mail_app", body.email, account_name=body.name)
    ov_conn.close()
    return {"ok": True, "account_id": account_id}


@app.delete("/api/accounts/{account_id}")
def disconnect_account(account_id: str):
    """No tokens to forget -- just drop the row (and its matches)."""
    _, ov_conn = get_conns()
    ov.delete_account(ov_conn, account_id)
    ov_conn.close()
    return {"ok": True}


def _extract_and_store_job_postings(
    ov_conn, account_id: str, account_name: str, message_id: str,
    subject: str | None, sender: str | None, received_at: str | None,
) -> int:
    """Fetches the body of one job-alert-classified message and persists
    every individual job it contains as its own job_postings row
    (CLAUDE_HANDOFF.md sections 2/7.5: extraction happens here, during
    sync, not lazily on preview). Returns how many NEW jobs this call
    added (re-running over an already-extracted message is always safe
    -- see overrides_store.add_job_posting's dedupe_key uniqueness).

    Never raises: a Mail.app fetch failure for one message shouldn't
    take down the rest of a sync, so any mailapp.MailAppError here is
    swallowed and treated as "0 postings extracted this time" -- the
    discovered_matches row for the raw email is unaffected either way,
    so nothing is lost; the next sync will simply try extraction again.
    """
    try:
        body = mailapp.get_message_preview(account_name, message_id)
    except mailapp.MailAppError:
        return 0
    if not body:
        return 0

    jobs = posting_extract.extract_postings(sender, subject, body)
    if not jobs:
        return 0

    # Every job-board URL in the body, for positional best-effort
    # association only (CLAUDE_HANDOFF.md section 10's Layer 4 note: URL
    # evidence is a deliberately separate layer from Layer 3's line-based
    # body-structure parsing above -- splicing URLs back into that parser
    # would risk corrupting job extraction itself, since a raw URL on its
    # own line looks just like a new job title to it. Position-in-body
    # matching isn't architecturally available here for that reason.
    #
    # So positional association is trusted ONLY when the URL count
    # exactly matches the job count -- the common well-formed-digest case
    # this was designed for. Any mismatch (e.g. an extra "view digest"/
    # header link ahead of the real per-job links, or a job with no link
    # at all) means there's no reliable way to tell which URL maps to
    # which job, so none are guessed rather than risking every job after
    # the mismatch getting silently attached to the wrong listing -- "no
    # fake link" per mail_app_store.guess_posting_url()'s own philosophy,
    # extended here to "no fake pairing" too. See audit finding #3 /
    # tests/test_audit_findings.py.
    urls = mailapp.extract_posting_urls(body)
    urls_for_jobs = urls if len(urls) == len(jobs) else []

    added = 0
    for i, job in enumerate(jobs):
        posting_url = urls_for_jobs[i] if i < len(urls_for_jobs) else None
        dedupe_key = posting_extract.compute_dedupe_key(
            account_id, message_id, posting_url, job.get("title"), job.get("company"),
        )
        if ov.add_job_posting(
            ov_conn, account_id, message_id, dedupe_key, job.get("source"),
            job.get("title"), job.get("company"), job.get("location"),
            job.get("salary"), job.get("employment_type"), posting_url,
            received_at, subject, sender,
        ):
            added += 1
    return added


@app.post("/api/accounts/{account_id}/sync")
def sync_account(account_id: str):
    """For every open (non-archived) application item, searches this
    account's inbox for messages mentioning the item's company or role
    (via mail_app_store.search_messages()) and records any new hits as
    account_matches. A company/role term that's too short or generic to
    safely drive a `contains` search on its own (e.g. a role label of
    "IT") is dropped by mail_app_store.is_usable_match_term() before it
    ever reaches Mail.app -- see that function's docstring; an item left
    with no usable terms at all is skipped for this sync rather than
    matched on nothing. The role term (when there's also a usable
    company term) is passed to search_messages() as role_terms, so a
    role-only whole-word hit -- e.g. "Resume" or "Tech" matching some
    unrelated company's mail -- isn't trusted without the company term
    also appearing; see search_messages()'s docstring for the two live
    cases that motivated this. Each item's already-confirmed thread ids
    (fetched once up front via ov.get_all_thread_ids_by_item()) are
    also passed to search_messages() as `thread_ids`, so a reply whose
    In-Reply-To/References headers cite one of them attaches
    deterministically even when its subject/sender share no company or
    role text at all (e.g. "Re: your submission") -- see
    search_messages()'s docstring for the full explanation. An item
    with no usable text terms AND no known thread ids yet is skipped,
    same as before. Returns how many were new this sync -- de-dupe
    against prior syncs happens in ov.add_account_match() by
    message_id, so re-running this is always safe.

    Company-only hits are first checked against
    mailapp.is_job_posting_style_subject() regardless of how many open
    items that company has -- a job-alert digest is never application
    correspondence, whether the company has one open item or several.
    Only once a company-only hit is *not* job-posting-shaped does the
    open-item count matter: against a multi-item company it's routed to
    the discoveries queue instead of auto-attached (see the
    `ambiguous_siblings` check below) -- this closes a real
    misattribution bug: a hit that only whole-word-matched an item's
    company term (no role term also matched -- either because the role
    label was too generic to search on at all, e.g. "IT", or it simply
    wasn't in this message) used to be trusted for whichever item
    happened to be processed, with nothing to say it was the *right*
    item once that company has more than one open application.
    Confirmed against a real tracker: a company-wide "Notice from Adams
    County" rejection email, mentioning "Adams County Government"
    broadly with no department/role text in its subject or sender,
    text-matches ANY open Adams-County-named item regardless of which
    specific role it's actually about. `ambiguous_matches` in the
    response counts how many landed in the review queue this way."""
    jt_conn, ov_conn = get_conns()
    account = ov.get_account(ov_conn, account_id)
    if account is None:
        ov_conn.close()
        raise HTTPException(status_code=404, detail="No such connected account.")

    account_name = account.get("account_name") or account["email"]
    apps = [a for a in db.load_applications(jt_conn, ov_conn) if not a["archived"]]
    thread_ids_by_item = ov.get_all_thread_ids_by_item(ov_conn)

    # Group currently-open items by their normalized effective company,
    # so a company-only hit can be checked against every sibling item
    # sharing that company -- not just the one item being processed when
    # the hit happened to come back. Items with no usable company at all
    # are simply never ambiguous by this check.
    company_groups: dict[str, list[str]] = {}
    for a in apps:
        c = (a.get("effective_company") or "").strip().lower()
        if c:
            company_groups.setdefault(c, []).append(a["item_key"])

    new_count = 0
    ambiguous_count = 0
    try:
        for a in apps:
            company = a.get("effective_company")
            role = a.get("role_label")
            company_terms = [company] if company and company.strip() and mailapp.is_usable_match_term(company) else []
            role_terms = [role] if role and role.strip() and mailapp.is_usable_match_term(role) else []
            terms = company_terms + role_terms
            known_thread_ids = thread_ids_by_item.get(a["item_key"])
            if not terms and not known_thread_ids:
                continue
            # role_terms is only passed through when we also have a
            # company term to confirm against -- see search_messages()'s
            # docstring. With no company term at all (rare: the company
            # name itself was too short/generic), fall back to trusting
            # the role term alone, same as before this hardening.
            hits = mailapp.search_messages(
                account_name, terms,
                role_terms=role_terms if company_terms else None,
                thread_ids=known_thread_ids,
            )
            norm_company = (company or "").strip().lower()
            siblings = company_groups.get(norm_company, [])
            ambiguous_siblings = siblings if len(siblings) > 1 else None

            for h in hits:
                if h.get("company_only"):
                    # A job-alert-shaped subject (e.g. "KPMG just posted a
                    # 78% match...") never belongs in the application
                    # thread, even though its company name just matched an
                    # open item here -- file it as a posting instead, with
                    # no candidate to attach to. Checked unconditionally
                    # for every company-only hit (not just when the company
                    # has multiple open items): a single-open-item company
                    # is just as capable of receiving a job-alert digest as
                    # a multi-item one, and this same subject text isn't
                    # application correspondence either way. See
                    # mail_app_store.is_job_posting_style_subject().
                    if mailapp.is_job_posting_style_subject(h["subject"]):
                        ov.add_discovered_match(
                            ov_conn, account_id, h["message_id"], h["subject"], h.get("sender"),
                            h["received_at"], company, kind="posting",
                        )
                        _extract_and_store_job_postings(
                            ov_conn, account_id, account_name, h["message_id"],
                            h["subject"], h.get("sender"), h["received_at"],
                        )
                        continue
                    if ambiguous_siblings:
                        if ov.add_discovered_match(
                            ov_conn, account_id, h["message_id"], h["subject"], h.get("sender"),
                            h["received_at"], company,
                            match_kind="ambiguous", candidate_item_keys=ambiguous_siblings,
                        ):
                            ambiguous_count += 1
                        continue
                    # Company-only hit, not job-posting-shaped, and the
                    # company has only this one open item -- no sibling to
                    # be ambiguous against, so it's trusted for this item
                    # the same way it always was before this hardening.
                if ov.add_account_match(ov_conn, account_id, a["item_key"], h["message_id"], h["subject"], h["received_at"]):
                    new_count += 1
                    ov.add_thread_identifiers(ov_conn, a["item_key"], h.get("thread_message_ids") or [])
    except mailapp.MailAppPermissionError as e:
        ov.mark_account_status(ov_conn, account_id, "blocked")
        ov_conn.close()
        raise HTTPException(status_code=400, detail=str(e))
    except mailapp.MailAppError as e:
        # Anything other than a denied permission (a timeout, a mailbox
        # lookup failure, osascript itself missing) is surfaced as a
        # failed attempt, not a persistent 'blocked' state -- retrying
        # might just work, and mislabeling it as a permission problem
        # sends the user to the wrong System Settings pane for nothing.
        ov_conn.close()
        raise HTTPException(status_code=400, detail=str(e))

    ov.mark_account_status(ov_conn, account_id, "connected")
    ov.record_sync(ov_conn, account_id, new_count)
    ov_conn.close()
    return {"ok": True, "new_matches": new_count, "ambiguous_matches": ambiguous_count}


# --- discovery review queue ("Possible new applications") --------------------
# Separate from sync_account() above on purpose: that endpoint only ever
# attaches evidence to applications you've already logged. This is the
# opposite direction -- "scan the inbox for application mail that isn't
# tied to anything you've tracked yet" -- and it never silently creates a
# tracker item on its own. A scan only ever produces rows in the
# discovered_matches review queue; a real item only appears once the user
# explicitly accepts one via /api/discoveries/{id}/accept below.

@app.post("/api/accounts/{account_id}/discover")
def discover_new_applications(account_id: str):
    """Scans this account's inbox (mail_app_store.search_unmatched_messages)
    for messages that look application-related but don't match any
    currently-open item, and files each as a pending row in the
    discovered_matches review queue (de-duped by message_id -- see
    ov.add_discovered_match). Returns the up-to-date pending queue, same
    shape as GET /api/discoveries, so the frontend can just re-render
    from this response instead of making a second round-trip."""
    jt_conn, ov_conn = get_conns()
    account = ov.get_account(ov_conn, account_id)
    if account is None:
        ov_conn.close()
        raise HTTPException(status_code=404, detail="No such connected account.")

    account_name = account.get("account_name") or account["email"]
    apps = [a for a in db.load_applications(jt_conn, ov_conn) if not a["archived"]]
    known_terms = []
    for a in apps:
        for t in (a.get("effective_company"), a.get("role_label")):
            if t and t.strip() and mailapp.is_usable_match_term(t):
                known_terms.append(t.strip())

    always_posting_senders = ov.list_job_posting_senders(ov_conn)
    try:
        candidates = mailapp.search_unmatched_messages(
            account_name, known_terms, always_posting_senders=always_posting_senders,
        )
    except mailapp.MailAppPermissionError as e:
        ov.mark_account_status(ov_conn, account_id, "blocked")
        jt_conn.close()
        ov_conn.close()
        raise HTTPException(status_code=400, detail=str(e))
    except mailapp.MailAppError as e:
        jt_conn.close()
        ov_conn.close()
        raise HTTPException(status_code=400, detail=str(e))

    for c in candidates:
        # A whitelisted sender (see overrides_store.list_job_posting_senders)
        # is posting-classified unconditionally -- independent of subject
        # shape -- alongside the existing subject-pattern heuristic (see
        # discoveries-sender-classification-and-digests-spec.md Part 5.5a).
        kind = "posting" if (c.get("force_posting") or mailapp.is_job_posting_style_subject(c["subject"])) else "application"
        ov.add_discovered_match(
            ov_conn, account_id, c["message_id"], c["subject"], c["sender"],
            c["received_at"], c["guessed_company"], kind=kind,
        )
        if kind == "posting":
            _extract_and_store_job_postings(
                ov_conn, account_id, account_name, c["message_id"],
                c["subject"], c["sender"], c["received_at"],
            )

    pending = _discoveries_with_account_email(ov_conn, jt_conn)
    jt_conn.close()
    ov_conn.close()
    return pending


def _discoveries_with_account_email(ov_conn, jt_conn=None) -> list[dict]:
    """Decorates each pending discovery with the connected account's
    email for display, and -- for 'ambiguous' rows only -- a human-
    readable label per candidate item_key (e.g. "Adams County — IT"),
    so the frontend's picker doesn't have to know anything about
    item_key's internal format. Labeling needs `jt_conn`/db.load_
    applications() (an item_key alone isn't a label); callers that
    don't have a jt_conn handy (e.g. after an item-mutating route
    already closed it) can omit it and candidates fall back to their
    bare item_keys -- still usable by /attach, just less pretty."""
    accounts_by_id = {a["id"]: a for a in ov.list_accounts(ov_conn)}
    labels_by_key = {}
    if jt_conn is not None:
        for a in db.load_applications(jt_conn, ov_conn):
            role = a.get("role_label")
            label = a.get("effective_company") or a.get("company") or a["item_key"]
            if role and role != "(root)":
                label = f"{label} — {role}"
            labels_by_key[a["item_key"]] = label

    out = []
    for d in ov.list_pending_discoveries(ov_conn):
        acct = accounts_by_id.get(d["account_id"])
        d = dict(d)
        d["account_email"] = acct["email"] if acct else None
        if d.get("match_kind") == "ambiguous":
            d["candidates"] = [
                {"item_key": k, "label": labels_by_key.get(k, k)}
                for k in (d.get("candidate_item_keys") or [])
            ]
        else:
            d["candidates"] = []
        out.append(d)
    return out


@app.get("/api/discoveries")
def list_discoveries():
    """The current pending review queue, across all connected accounts --
    what the Settings panel's 'Possible new applications' section shows.
    Does not trigger a scan itself; call POST /api/accounts/{id}/discover
    for that."""
    jt_conn, ov_conn = get_conns()
    pending = _discoveries_with_account_email(ov_conn, jt_conn)
    jt_conn.close()
    ov_conn.close()
    return pending


@app.post("/api/discoveries/{discovery_id}/dismiss")
def dismiss_discovery(discovery_id: int):
    """Marks a candidate as not a real application, so it never resurfaces
    on a later scan of the same account (see ov.add_discovered_match's
    de-dupe, which checks for a row at ANY status, not just 'pending')."""
    _, ov_conn = get_conns()
    d = ov.get_discovery(ov_conn, discovery_id)
    if d is None:
        ov_conn.close()
        raise HTTPException(status_code=404, detail="No such discovery.")
    ov.set_discovery_status(ov_conn, discovery_id, "dismissed")
    ov_conn.close()
    return {"ok": True}


@app.get("/api/discoveries/{discovery_id}/preview")
def preview_discovery(discovery_id: int):
    """Lazily fetches the source email's body for the review modal, so
    the user can judge a candidate without alt-tabbing into Mail.app --
    see mail_app_store.get_message_preview()'s docstring for why this is
    on-demand (called only when a review modal opens) rather than stored
    at scan time. Returns {"body": str | None, "posting_url": str | None,
    "posting_urls": list[str]} -- body=None means the message could no
    longer be found (e.g. moved/deleted since the scan), which isn't an
    error the user needs to see, just an empty preview pane. For
    kind='posting' discoveries, this is also where the board's job-
    posting link(s) are found and persisted (see
    mail_app_store.extract_posting_urls() and
    discoveries-sender-classification-and-digests-spec.md Part 5.5b) --
    lazily, on the same trip that already fetches the body, rather than
    at scan time. posting_urls holds every listing link found (a digest
    can bundle several); posting_url is kept for backward compat and is
    always posting_urls[0] once populated."""
    _, ov_conn = get_conns()
    discovery = ov.get_discovery(ov_conn, discovery_id)
    if discovery is None:
        ov_conn.close()
        raise HTTPException(status_code=404, detail="No such discovery.")

    account = ov.get_account(ov_conn, discovery["account_id"])
    if account is None:
        ov_conn.close()
        return {
            "body": None,
            "posting_url": discovery.get("posting_url"),
            "posting_urls": discovery.get("posting_urls") or [],
        }

    account_name = account.get("account_name") or account["email"]
    try:
        body = mailapp.get_message_preview(account_name, discovery["message_id"])
    except mailapp.MailAppError:
        # A permission/timeout/inbox-loading hiccup here shouldn't block
        # reviewing the discovery -- the modal just falls back to
        # subject/sender/date, same as before this endpoint existed.
        body = None

    posting_url = discovery.get("posting_url")
    posting_urls = discovery.get("posting_urls") or []
    if not posting_urls and discovery.get("kind") == "posting" and body:
        guessed = mailapp.extract_posting_urls(body)
        if guessed:
            ov.set_discovery_posting_urls(ov_conn, discovery_id, guessed)
            posting_urls = guessed
            posting_url = guessed[0]
    ov_conn.close()
    return {"body": body, "posting_url": posting_url, "posting_urls": posting_urls}


@app.post("/api/discoveries/{discovery_id}/mark-posting")
def mark_discovery_as_posting(discovery_id: int):
    """Relabels a pending discovery as kind='posting' without touching
    its status -- the board's "drop/click onto Job Postings" action for
    a Needs-Triage card the classifier didn't already catch (see
    discoveries-kanban-spec.md Part 2). Durable ahead of any future
    reclassification of the underlying subject pattern: once marked,
    this discovery stays a posting on later scans/rebuilds regardless of
    what mail_app_store.is_job_posting_style_subject() would say about
    it now. 404 if the discovery doesn't exist; 409 if it's already been
    accepted/dismissed, same as attach/accept below.

    Also runs job-posting extraction immediately (same
    _extract_and_store_job_postings() helper sync_account()/
    discover_new_applications() use), so a discovery the classifier
    missed and a human had to manually relabel still ends up with its
    individual jobs on the /api/job-postings board, not just a
    reclassified discovery row. A failed extraction here (e.g. the
    account got disconnected since this discovery was found) is
    swallowed the same way it is at the other two call sites -- the
    relabel itself still succeeds either way."""
    jt_conn, ov_conn = get_conns()
    jt_conn.close()
    discovery = ov.get_discovery(ov_conn, discovery_id)
    if discovery is None:
        ov_conn.close()
        raise HTTPException(status_code=404, detail="No such discovery.")
    if discovery["status"] != "pending":
        ov_conn.close()
        raise HTTPException(status_code=409, detail="This discovery has already been decided.")
    ov.set_discovery_kind(ov_conn, discovery_id, "posting")
    account = ov.get_account(ov_conn, discovery["account_id"])
    if account is not None:
        account_name = account.get("account_name") or account["email"]
        _extract_and_store_job_postings(
            ov_conn, discovery["account_id"], account_name, discovery["message_id"],
            discovery.get("subject"), discovery.get("sender"), discovery.get("received_at"),
        )
    updated = ov.get_discovery(ov_conn, discovery_id)
    ov_conn.close()
    return updated


@app.post("/api/discoveries/dismiss-sender")
def dismiss_discoveries_by_sender(sender: str = Form(...)):
    """Bulk-dismisses every pending discovery from one exact sender (e.g.
    a recurring 'LinkedIn Job Alerts' digest) in a single action, instead
    of clicking Dismiss on each row -- see
    ov.dismiss_pending_discoveries_by_sender()'s docstring."""
    jt_conn, ov_conn = get_conns()
    count = ov.dismiss_pending_discoveries_by_sender(ov_conn, sender)
    pending = _discoveries_with_account_email(ov_conn, jt_conn)
    jt_conn.close()
    ov_conn.close()
    return {"ok": True, "dismissed_count": count, "discoveries": pending}


@app.post("/api/discoveries/sender-classification")
def add_job_posting_sender_classification(sender: str = Form(...)):
    """"Always treat this sender as postings" -- teaches the app that
    every future message from this exact sender should be classified
    kind='posting' unconditionally, without a code change (see
    overrides_store.add_job_posting_sender and
    discoveries-sender-classification-and-digests-spec.md Part 5.5a).
    Does not touch any already-filed discoveries from this sender --
    only affects future scans. Mirrors dismiss-sender's shape: returns
    the up-to-date pending queue so the frontend can re-render from this
    response instead of a second round-trip."""
    jt_conn, ov_conn = get_conns()
    ov.add_job_posting_sender(ov_conn, sender)
    pending = _discoveries_with_account_email(ov_conn, jt_conn)
    jt_conn.close()
    ov_conn.close()
    return {"ok": True, "discoveries": pending}


@app.post("/api/discoveries/{discovery_id}/attach")
def attach_discovery(discovery_id: int, item_key: str = Form(...)):
    """Confirms an 'ambiguous' discovery (see sync_account()'s docstring
    and the discovered_matches schema comment) really belongs to an
    EXISTING item -- unlike /accept, this never creates a new folder.
    Records the original email as an account_match on the chosen item
    (exactly as an ordinary sync would have, had the item been
    unambiguous) and its Message-ID as a thread identifier, then marks
    the discovery 'accepted' so it stops resurfacing. `item_key` isn't
    restricted to the discovery's own candidate_item_keys -- those are
    a helpful default list for the picker, not a hard constraint, since
    the user reviewing the email may correctly recognize it belongs to
    a *different* open item than the ones this sync run happened to
    consider -- but it must be a real, currently-open item, checked
    against db.load_applications() below rather than trusted blindly."""
    jt_conn, ov_conn = get_conns()
    discovery = ov.get_discovery(ov_conn, discovery_id)
    if discovery is None:
        jt_conn.close()
        ov_conn.close()
        raise HTTPException(status_code=404, detail="No such discovery.")
    if discovery["status"] != "pending":
        jt_conn.close()
        ov_conn.close()
        raise HTTPException(status_code=409, detail=f"This discovery was already {discovery['status']}.")

    valid_keys = {a["item_key"] for a in db.load_applications(jt_conn, ov_conn) if not a["archived"]}
    if item_key not in valid_keys:
        jt_conn.close()
        ov_conn.close()
        raise HTTPException(status_code=400, detail="No such open application item.")

    ov.add_account_match(
        ov_conn, discovery["account_id"], item_key, discovery["message_id"],
        discovery["subject"], discovery["received_at"],
    )
    if discovery["message_id"]:
        ov.add_thread_identifiers(ov_conn, item_key, [discovery["message_id"]])
    ov.set_discovery_status(ov_conn, discovery_id, "accepted")

    pending = _discoveries_with_account_email(ov_conn, jt_conn)
    jt_conn.close()
    ov_conn.close()
    return {"ok": True, "discoveries": pending}


def _save_email_evidence_pdf(dest_folder: Path, account, message_id: str, subject: str | None, sender: str | None, received_at: str | None) -> bool:
    """Fetches the source email's body (best-effort -- see
    preview_discovery's docstring on why a fetch failure here isn't
    fatal) and saves it as a real PDF document inside `dest_folder`, so
    an accepted/matched application has actual evidence to show in
    Attached Documents instead of only the notes.txt placeholder.
    Returns True if a PDF was written. Never raises -- a Mail.app
    hiccup here shouldn't block the folder/item from being created."""
    body = None
    if account is not None:
        account_name = account.get("account_name") or account["email"]
        try:
            body = mailapp.get_message_preview(account_name, message_id)
        except mailapp.MailAppError:
            body = None

    try:
        pdf_bytes = email_pdf.render_email_pdf(subject, sender, received_at, body)
        filename = email_pdf.safe_email_filename(subject) + ".pdf"
        dest = unique_dest_path(dest_folder, filename)
        dest.write_bytes(pdf_bytes)
        return True
    except OSError:
        # Disk-full / permission hiccup -- same "don't block the accept
        # over this" reasoning as the body fetch above.
        return False


@app.post("/api/discoveries/{discovery_id}/accept")
async def accept_discovery(
    discovery_id: int,
    company: str = Form(...),
    role_label: str = Form(""),
    status: str = Form(""),
):
    """Confirms a discovered message really is a new application: creates
    a stub Applications/<company>/ folder (same create_application_folder
    + rebuild path as POST /api/applications/new, so this produces a
    completely ordinary tracker item -- nothing about it is a special
    'discovered' item type going forward) and links the original email to
    the new item as an account_match, exactly as if a normal sync had
    found it. `company`/`role_label` default to the discovery's own
    subject/sender-derived guess in the frontend's pre-filled form, but
    are freely editable there first -- this endpoint takes whatever the
    user actually submitted, not the stored guess.

    Also saves the source email itself as a PDF into the new folder (see
    _save_email_evidence_pdf) *before* ensure_not_empty's placeholder
    check runs, so a freshly-accepted application gets real evidence
    instead of the generic notes.txt -- ensure_not_empty only drops its
    placeholder when a folder is still empty, so the PDF (when it saves
    successfully) preempts it entirely."""
    if status and status not in db.STATUS_ORDER:
        raise HTTPException(status_code=400, detail=f"Unknown status '{status}'. Must be one of {db.STATUS_ORDER}.")

    _, ov_conn = get_conns()
    discovery = ov.get_discovery(ov_conn, discovery_id)
    if discovery is None:
        ov_conn.close()
        raise HTTPException(status_code=404, detail="No such discovery.")
    if discovery["status"] != "pending":
        ov_conn.close()
        raise HTTPException(status_code=409, detail=f"This discovery was already {discovery['status']}.")

    try:
        dest_folder = create_application_folder(current_root(), company, role_label)
    except ValueError as e:
        ov_conn.close()
        raise HTTPException(status_code=400, detail=str(e))
    except FileExistsError as e:
        ov_conn.close()
        raise HTTPException(status_code=409, detail=str(e))

    account = ov.get_account(ov_conn, discovery["account_id"])
    _save_email_evidence_pdf(
        dest_folder, account, discovery["message_id"],
        discovery["subject"], discovery["sender"], discovery["received_at"],
    )

    ensure_not_empty(dest_folder)
    build(current_root(), current_db_path())

    root = current_root().resolve()
    relpath = str(dest_folder.relative_to(root))
    jt_conn = db.get_jt_conn(current_db_path())
    row = jt_conn.execute("SELECT id, item_key FROM items WHERE source_relpath = ?", (relpath,)).fetchone()
    jt_conn.close()

    if row is not None:
        if status:
            ov.upsert_override(ov_conn, row["item_key"], manual_status=status)
        ov.add_account_match(
            ov_conn, discovery["account_id"], row["item_key"],
            discovery["message_id"], discovery["subject"], discovery["received_at"],
        )

    ov.set_discovery_status(ov_conn, discovery_id, "accepted")
    ov_conn.close()
    return {"ok": True, "relpath": relpath, "item_id": row["id"] if row is not None else None}


@app.post("/api/discoveries/backfill-email-pdfs")
def backfill_email_pdfs():
    """Sweeps every already-linked email (account_matches -- i.e. every
    application that was synced or accepted before email_pdf.py
    existed, or where the save failed at the time e.g. a Mail.app
    hiccup) and saves a PDF for any whose folder doesn't already have
    one. Idempotent and safe to re-run: a folder that already has an
    "Email - ...pdf" (any of them -- see email_pdf.EMAIL_PDF_PREFIX) is
    left alone rather than getting a duplicate. Returns counts so the
    Settings panel can show the user something happened (or didn't)."""
    jt_conn, ov_conn = get_conns()
    root = current_root().resolve()

    matches = ov.list_all_account_matches(ov_conn)
    accounts_by_id = {a["id"]: a for a in ov.list_accounts(ov_conn)}

    checked = 0
    saved = 0
    skipped_existing = 0
    failed = 0
    for m in matches:
        row = jt_conn.execute(
            "SELECT source_relpath FROM items WHERE item_key = ?", (m["item_key"],)
        ).fetchone()
        if row is None:
            continue  # item no longer exists (deleted/merged since the match was made)
        checked += 1

        dest_folder = root / row["source_relpath"]
        if not dest_folder.is_dir():
            continue
        already_has_pdf = any(
            f.name.startswith(email_pdf.EMAIL_PDF_PREFIX) and f.suffix.lower() == ".pdf"
            for f in dest_folder.iterdir() if f.is_file()
        )
        if already_has_pdf:
            skipped_existing += 1
            continue

        account = accounts_by_id.get(m["account_id"])
        # account_matches (unlike discovered_matches) never stored the
        # original sender address -- only the mailbox it arrived in is
        # known at this point, so that's what the PDF's "From:" shows.
        sender_label = account["email"] if account else None
        ok = _save_email_evidence_pdf(
            dest_folder, account, m["message_id"], m["subject"], sender_label, m["received_at"],
        )
        if ok:
            saved += 1
        else:
            failed += 1

    jt_conn.close()
    ov_conn.close()

    if saved:
        build(current_root(), current_db_path())

    return {"ok": True, "checked": checked, "saved": saved, "skipped_existing": skipped_existing, "failed": failed}


# --- job postings (CLAUDE_HANDOFF.md sections 2/8/14) ------------------------
# First-class job records, one row per individual job -- NOT a filtered
# view of discovered_matches (see CLAUDE_HANDOFF.md section 15: "Do not
# use discoveries.filter(d => d.kind === 'posting') as the canonical Job
# Postings count"). Rows are populated during sync/discover by
# _extract_and_store_job_postings() above, not lazily here.

@app.get("/api/job-postings")
def list_job_postings():
    """Every non-dismissed job posting, newest first -- what the Job
    Postings board renders. The count of this list (not of any
    discovered_matches query) is the canonical "Job Postings · N" the
    UI should show (CLAUDE_HANDOFF.md section 4)."""
    jt_conn, ov_conn = get_conns()
    postings = ov.list_job_postings(ov_conn, status="new")
    jt_conn.close()
    ov_conn.close()
    return postings


@app.post("/api/job-postings/{job_id}/dismiss")
def dismiss_job_posting(job_id: int):
    """Hides one job posting from the board without deleting its row --
    same UX shape as /api/discoveries/{id}/dismiss. Re-extracting the
    same job on a later sync will not resurrect it (dedupe_key already
    exists), matching discovered_matches' own dismiss semantics."""
    jt_conn, ov_conn = get_conns()
    job = ov.get_job_posting(ov_conn, job_id)
    if job is None:
        jt_conn.close()
        ov_conn.close()
        raise HTTPException(status_code=404, detail="No such job posting.")
    ov.set_job_posting_status(ov_conn, job_id, "dismissed")
    jt_conn.close()
    ov_conn.close()
    return {"ok": True}


# --- applications / pipeline -------------------------------------------------
@app.get("/api/applications")
def list_applications():
    jt_conn, ov_conn = get_conns()
    apps = db.load_applications(jt_conn, ov_conn)
    jt_conn.close()
    ov_conn.close()
    return apps


@app.get("/api/applications/{item_id}/documents")
def application_documents(item_id: int):
    jt_conn, ov_conn = get_conns()
    docs = db.load_documents(jt_conn, item_id, ov_conn)
    jt_conn.close()
    ov_conn.close()
    return docs


@app.get("/api/applications/{item_id}/dossier")
def application_dossier(item_id: int):
    """Checkpoint 3: assembles the Application Dossier for one item --
    contacts merged across all its documents, plus the four role sections
    (role_summary/duties/required_qualifications/preferred_qualifications)
    from whichever document is classified as the job posting. Checkpoint 5
    adds detected_date_applied/detected_date_source_relpath, a best-effort
    date-applied suggestion pulled from an application_confirmation or
    job_posting document.

    Checkpoint 6 refines what happens with that suggestion, split by
    evidence tier (dossier.assemble_dossier's detected_date_evidence_tier):
      - date_applied already has a value (typed, or auto-filled earlier):
        NEVER touched here, regardless of tier. A value already on record
        only ever changes via an explicit accept through save_override.
      - date_applied is unset AND the evidence is "confirmation" (a direct
        record of submission, from an application_confirmation document):
        auto-filled here, once, silently -- see date_applied_auto_filled
        in the response, which the frontend uses to know it needs to
        refresh the applications list.
      - date_applied is unset AND the evidence is only "posting" (weaker --
        names when the position was *listed*, not applied to): left unset
        and still surfaced as a suggestion for the user to accept or
        dismiss, same as before.
    See dossier.assemble_dossier() for the extraction/tiebreak rules.

    Item 7 adds two more things to the response, both read-only here (this
    endpoint writes nothing new to overrides.db beyond the existing
    date_applied auto-fill above):
      - `timeline_events` is passed straight through from
        dossier.assemble_dossier() -- doc-derived, nothing to compute here.
      - `current_status` / `current_status_date` / `current_status_date_known`
        cover the Timeline's last line. `current_status` is the same
        manual-status-or-auto-status value db.load_applications() calls
        `effective_status`; the date comes from overrides_store.py's
        status_history log via get_latest_status_change(), which only has
        entries for changes made after Item 7 shipped -- so
        current_status_date_known is False (and current_status_date is
        None) for any status that predates it, rather than guessing."""
    jt_conn, ov_conn = get_conns()
    item_key = item_key_for(jt_conn, item_id)  # raises 404 if the item doesn't exist
    docs = db.load_documents(jt_conn, item_id, ov_conn)
    result = dossier.assemble_dossier(ov_conn, current_root(), docs)

    result["date_applied_auto_filled"] = False
    existing = ov.get_override(ov_conn, item_key)
    if (
        not existing.get("date_applied")
        and result.get("detected_date_evidence_tier") == "confirmation"
        and result.get("detected_date_applied")
    ):
        ov.upsert_override(
            ov_conn,
            item_key,
            date_applied=result["detected_date_applied"],
            date_applied_source="confirmation",
        )
        result["date_applied_auto_filled"] = True

    item_row = jt_conn.execute("SELECT status FROM items WHERE id = ?", (item_id,)).fetchone()
    auto_status = item_row["status"] if item_row else "unknown"
    current_status = existing.get("manual_status") or auto_status
    status_change = ov.get_latest_status_change(ov_conn, item_key, current_status)
    result["current_status"] = current_status
    result["current_status_date"] = status_change["changed_at"][:10] if status_change else None
    result["current_status_date_known"] = bool(status_change)

    # Item 8: connected-account matches for this item's timeline. Empty
    # list/dict for everyone until an account is actually connected and
    # synced -- cheap no-op reads, not worth gating behind a feature flag.
    matches = ov.get_matches_for_item(ov_conn, item_key)
    accounts_by_id = {a["id"]: a for a in ov.list_accounts(ov_conn)}
    for m in matches:
        acct = accounts_by_id.get(m["account_id"])
        m["account_email"] = acct["email"] if acct else None
        m["account_provider"] = acct["provider"] if acct else None
    result["account_matches"] = matches

    jt_conn.close()
    ov_conn.close()
    return result


def resync_fts(jt_conn) -> None:
    """Fully rebuild documents_fts from the documents/items tables (the real
    source of truth), instead of patching individual rows.

    documents_fts is a *contentless* FTS5 table (content='' in the schema),
    and SQLite unconditionally refuses plain DELETE/UPDATE statements against
    contentless tables — every row, every time, regardless of whether it
    exists. The old code tried `DELETE FROM documents_fts WHERE rowid = ?`
    on delete, and `INSERT OR REPLACE ...` on rename (which SQLite executes
    as delete-then-insert when the rowid already exists) — both raised
    `sqlite3.OperationalError: cannot DELETE from contentless fts5 table`,
    which surfaced to the UI as a generic "Internal Server Error" *after*
    the real file had already been deleted/renamed on disk, leaving a
    ghost row in jobtracker.db every time.

    Contentless tables only support clearing via the special 'delete-all'
    command, so we wipe and fully re-populate instead of trying to touch
    individual rows — safe, always-correct, and cheap enough for a local
    single-user index."""
    jt_conn.execute("INSERT INTO documents_fts(documents_fts) VALUES ('delete-all')")
    for doc_id, filename, company, role_label in jt_conn.execute(
        "SELECT d.id, d.filename, i.company, i.role_label FROM documents d JOIN items i ON i.id = d.item_id"
    ).fetchall():
        jt_conn.execute(
            "INSERT INTO documents_fts (rowid, filename, company, role_label) VALUES (?, ?, ?, ?)",
            (doc_id, normalize_for_search(filename), normalize_for_search(company), normalize_for_search(role_label)),
        )


def unique_dest_path(folder: Path, filename: str) -> Path:
    """Never clobbers an existing file — 'resume.pdf' becomes
    'resume (1).pdf', 'resume (2).pdf', ... same convention Finder/Explorer
    use on a name collision."""
    dest = folder / filename
    if not dest.exists():
        return dest
    stem, suffix = Path(filename).stem, Path(filename).suffix
    i = 1
    while True:
        candidate = folder / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


@app.post("/api/applications/{item_id}/documents")
async def upload_documents(item_id: int, files: list[UploadFile] = File(...)):
    """Drag-and-drop / file-picker upload for one application. Writes
    straight into that application's real folder on disk — items.source_relpath,
    the same folder build_index.py already grouped its other files into —
    never a staging area, so a later /api/rebuild sees it as just another
    file that was always there. Classifies and inserts the new row directly
    into jobtracker.db (same classify_doc_type/sha256_of/iso_mtime helpers
    build_index.py uses) so it shows up immediately without a full rescan."""
    jt_conn, ov_conn = get_conns()
    row = jt_conn.execute("SELECT source_relpath FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        jt_conn.close()
        ov_conn.close()
        raise HTTPException(status_code=404, detail=f"No application with id {item_id}. Try rebuilding the index.")

    root = current_root().resolve()
    dest_folder = (root / row["source_relpath"]).resolve()
    try:
        dest_folder.relative_to(root)
    except ValueError:
        jt_conn.close()
        ov_conn.close()
        raise HTTPException(status_code=403, detail="Refusing to write outside the JobTracker root.")
    dest_folder.mkdir(parents=True, exist_ok=True)

    for f in files:
        dest = unique_dest_path(dest_folder, f.filename)
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        relpath = dest.relative_to(root)
        jt_conn.execute(
            "INSERT INTO documents (item_id, doc_type, filename, relpath, ext, mtime, content_hash, is_source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item_id, classify_doc_type(dest.name), dest.name, str(relpath),
                dest.suffix.lower(), iso_mtime(dest), sha256_of(dest), int(is_source_file(dest.name)),
            ),
        )
    # Full FTS resync rather than a per-row INSERT — see resync_fts() for
    # why (contentless FTS5 table), and it also fixes the old inline INSERT
    # here having used un-normalized filenames with blank company/role_label,
    # inconsistent with how build_index.py populates the same index.
    resync_fts(jt_conn)
    jt_conn.commit()

    docs = db.load_documents(jt_conn, item_id, ov_conn)
    jt_conn.close()
    ov_conn.close()
    return {"ok": True, "documents": docs}


@app.post("/api/applications/new")
async def create_application(
    company: str = Form(...),
    role_label: str = Form(""),
    status: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    """Creates a brand-new Applications/<Company>/[<Role>/] folder on disk
    (via create_application_folder(), the same helper the frontend's
    "+ New Application" form uses), optionally drops uploaded files
    straight into it, then does a full /api/rebuild so the new
    application is picked up by the exact same build_index.py logic as
    every other one — there's no separate "draft" item type to keep in
    sync with the real index.
    A 400 means the name was invalid; a 409 means that company/role
    folder already exists and has files in it.

    `status` (optional) is one of db.STATUS_ORDER — e.g. "applied" for an
    application you're logging after the fact instead of drafting fresh.
    Written the same way the detail pane's status dropdown does: as a
    manual_status override in overrides.db, keyed by the new item's
    item_key, once the rebuild below has actually created that item_key.
    Blank/omitted just leaves it unset, same as before (falls back to
    auto-classification, effectively "drafted" until a real doc appears)."""
    if status and status not in db.STATUS_ORDER:
        raise HTTPException(status_code=400, detail=f"Unknown status '{status}'. Must be one of {db.STATUS_ORDER}.")

    try:
        dest_folder = create_application_folder(current_root(), company, role_label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))

    for f in files:
        if not f.filename:
            continue
        dest = unique_dest_path(dest_folder, f.filename)
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
    ensure_not_empty(dest_folder)

    build(current_root(), current_db_path())

    root = current_root().resolve()
    relpath = str(dest_folder.relative_to(root))
    jt_conn = db.get_jt_conn(current_db_path())
    row = jt_conn.execute("SELECT id, item_key FROM items WHERE source_relpath = ?", (relpath,)).fetchone()
    jt_conn.close()

    if status and row is not None:
        ov_conn = ov.get_conn(current_ov_db_path())
        ov.upsert_override(ov_conn, row["item_key"], manual_status=status)
        ov_conn.close()

    return {"ok": True, "relpath": relpath, "item_id": row["id"] if row is not None else None}


@app.post("/api/categories/new")
async def create_category(name: str = Form(...)):
    """Creates a brand-new top-level folder — e.g. "Case Management" or
    a fully custom name like "Solar Panel Docs" — on disk (via
    create_category_folder(), the category sibling of
    create_application_folder() above), drops a placeholder note in it
    so it's never invisible before you add real files, then does a full
    /api/rebuild so it shows up as a real Browse tab immediately. A 400
    means the name was invalid or reserved (see create_category_folder);
    a 409 means that folder already exists and has files in it.

    Returns the section id the new folder classified into (see
    classify.classify_section) so the frontend can jump straight to that
    Browse tab — a known name like "Credentials" lands on the section id
    you'd expect, and anything else becomes its own new slugified
    section rather than a generic catch-all."""
    try:
        dest_folder = create_category_folder(current_root(), name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))

    ensure_not_empty(dest_folder)
    build(current_root(), current_db_path())

    return {"ok": True, "relpath": dest_folder.name, "section": classify_section(dest_folder.name)}


# --- categories (archive/delete a whole Browse tab) --------------------------
# Categories (Browse tabs — Credentials, Network, a custom one, etc.) aren't
# rows anywhere in jobtracker.db; they're derived on the fly from top-level
# folder names via classify_section(). "Applications" is deliberately
# reserved here and can never be archived/deleted as a whole category —
# that's a far more destructive, differently-scoped operation than what
# archiving a category means everywhere else, and individual applications
# already have their own archive/delete (see save_override / delete_application).
#
# Archive/delete operate per *physical folder*, not per section, because
# more than one folder can share a single Browse tab — e.g. "Credentials"
# is backed by both Certifications/ and "Degree and Transcrips/". Folder
# names are already unique on disk (the one exception, the compliance-only
# nested-in-Applications case, is handled by using a two-part
# "Applications/<subfolder>" key instead), so a folder name alone is a
# stable, sufficient identity for these endpoints — no need to also key on
# section.
RESERVED_CATEGORY_SECTIONS = {"applications"}


class CategoryOverrideRequest(BaseModel):
    archived: bool


def _folder_key(source_relpath: str | None) -> str | None:
    """Maps an item's source_relpath to the physical folder that backs its
    category row. For almost everything this is just the top-level folder
    name (e.g. "Certifications"). The one exception is the compliance-only
    case of case-management docs nested inside an enabled nested-application
    marker folder (see classify.NESTED_APPLICATION_MARKERS and
    build_index.group_applications) — that folder ALSO contains real
    job-application subfolders classified under "applications", so its
    key has to include the immediate subfolder (e.g. "Applications/Workforce
    Center Compliance") to stay distinct from the reserved applications
    category and to let deletion trash only the compliance items' own
    files, never the shared parent."""
    relpath = (source_relpath or "").strip()
    if not relpath:
        return None
    parts = Path(relpath).parts
    if not parts:
        return None
    if parts[0] == "Applications":
        if len(parts) >= 2:
            return str(Path(*parts[:2]))
        return None
    return parts[0]


def _section_folder_rows(jt_conn) -> list[dict]:
    """Every (section, folder) pair backing a non-reserved category, each
    with the item ids it covers — one row per physical folder, even when
    several folders share a Browse tab. Powers list_categories()."""
    rows = jt_conn.execute("SELECT id, section, source_relpath FROM items").fetchall()
    grouped: dict[tuple[str, str], list[int]] = {}
    for r in rows:
        section = r["section"]
        if section in RESERVED_CATEGORY_SECTIONS:
            continue
        folder = _folder_key(r["source_relpath"])
        if not folder:
            continue
        grouped.setdefault((section, folder), []).append(r["id"])
    return [
        {"section": s, "folder": f, "item_ids": ids}
        for (s, f), ids in sorted(grouped.items())
    ]


def _items_for_folder(jt_conn, folder: str) -> tuple[str | None, list[int]]:
    """The section and item ids currently backed by one physical folder —
    the folder-scoped counterpart of _section_folder_rows, used by the
    single-folder archive/delete endpoints."""
    rows = jt_conn.execute("SELECT id, section, source_relpath FROM items").fetchall()
    item_ids: list[int] = []
    section: str | None = None
    for r in rows:
        if r["section"] in RESERVED_CATEGORY_SECTIONS:
            continue
        if _folder_key(r["source_relpath"]) == folder:
            item_ids.append(r["id"])
            section = r["section"]
    return section, item_ids


@app.get("/api/categories")
def list_categories():
    """Every physical folder backing a non-reserved Browse tab, each as its
    own row (so "Certifications" and "Degree and Transcrips" list and
    archive/delete separately even though both show under "Credentials"),
    with item/doc counts, which tab it lives under, and its archived
    state — powers Manage's "Categories" section, the archive/delete
    mirror of Manage's "Archived applications" section."""
    jt_conn, ov_conn = get_conns()
    rows = _section_folder_rows(jt_conn)
    folder_overrides = ov.get_all_folder_overrides(ov_conn)

    out = []
    for r in rows:
        item_ids = r["item_ids"]
        placeholders = ",".join("?" * len(item_ids))
        doc_count = jt_conn.execute(
            f"SELECT COUNT(*) FROM documents WHERE item_id IN ({placeholders})", item_ids
        ).fetchone()[0] if item_ids else 0
        out.append({
            "section": r["section"],
            "folder": r["folder"],
            "item_count": len(item_ids),
            "doc_count": doc_count,
            "archived": bool(folder_overrides.get(r["folder"], {}).get("archived")),
        })
    jt_conn.close()
    ov_conn.close()
    return out


@app.post("/api/categories/{folder:path}/override")
def save_category_override(folder: str, req: CategoryOverrideRequest):
    """Archive/unarchive one physical folder behind a category — purely a
    flag in overrides.db (folder_overrides.archived), nothing on disk
    moves. Same pattern as an application's archived override (save_override
    above), just folder-scoped instead of item-scoped."""
    jt_conn, ov_conn = get_conns()
    try:
        section, item_ids = _items_for_folder(jt_conn, folder)
        if not item_ids:
            raise HTTPException(status_code=404, detail=f"No category folder '{folder}' found. Try rebuilding the index.")
        ov.set_folder_archived(ov_conn, folder, section, req.archived)
    finally:
        jt_conn.close()
        ov_conn.close()
    return {"ok": True, "folder": folder, "archived": req.archived}


@app.post("/api/categories/{folder:path}/delete")
def delete_category(folder: str):
    """Permanently deletes one physical folder behind a category: trashes
    that top-level folder whole (recoverable via OS Trash — see
    _trash_path), or, for the compliance-only nested-in-Applications case
    (folder starting with "Applications/" — see _folder_key), trashes only
    the individual files that belong to it rather than their shared parent
    folder. Requires the folder to already be archived first — same
    server-side safety re-check bulk_delete_applications uses for a
    multi-item destructive operation.

    Also clears every item_overrides/document_overrides row tied to this
    folder before it's gone — same reasoning as _delete_application's
    cleanup for a single application: a leftover override row pointing at
    an item_key/relpath that will never exist again is just a ghost in
    overrides.db, which a rebuild never touches and so would never clean
    up on its own."""
    jt_conn, ov_conn = get_conns()
    try:
        override = ov.get_folder_override(ov_conn, folder)
        if not override.get("archived"):
            raise HTTPException(status_code=400, detail="Archive this category before deleting it.")

        section, item_ids = _items_for_folder(jt_conn, folder)
        if not item_ids:
            raise HTTPException(status_code=404, detail=f"No category folder '{folder}' found. Try rebuilding the index.")

        # Captured up front, before anything is trashed or deleted — every
        # item_key and document relpath under this folder, so every
        # matching overrides.db row (item-level and document-level) can be
        # cleared once the underlying files/rows are actually gone.
        placeholders = ",".join("?" * len(item_ids))
        item_keys = [
            r["item_key"] for r in jt_conn.execute(
                f"SELECT item_key FROM items WHERE id IN ({placeholders})", item_ids
            ).fetchall()
        ]
        doc_relpaths = [
            r["relpath"] for r in jt_conn.execute(
                f"SELECT relpath FROM documents WHERE item_id IN ({placeholders})", item_ids
            ).fetchall()
        ]

        root = current_root().resolve()
        trashed_folders: list[str] = []
        trashed_files: list[str] = []

        if folder.split("/")[0] == "Applications":
            # Nested-in-Applications case: never trash the shared parent
            # folder — only the individual files belonging to these items.
            apps_root = (root / "Applications").resolve()
            for item_id in item_ids:
                doc_rows = jt_conn.execute(
                    "SELECT relpath FROM documents WHERE item_id = ?", (item_id,)
                ).fetchall()
                # Resolved up front, before any trashing — resolve_safe
                # requires the file to still exist, so this has to happen
                # before the loop below removes it.
                doc_full_paths = [(d["relpath"], resolve_safe(d["relpath"])) for d in doc_rows]
                for relpath, full_path in doc_full_paths:
                    _trash_path(full_path)
                    trashed_files.append(relpath)
                if doc_full_paths:
                    _remove_empty_parents(doc_full_paths[0][1], apps_root)
        else:
            full_path = (root / folder).resolve()
            try:
                full_path.relative_to(root)
            except ValueError:
                full_path = None
            if full_path is not None and full_path != root and full_path.exists():
                _trash_path(full_path)
                trashed_folders.append(folder)

        jt_conn.execute(f"DELETE FROM documents WHERE item_id IN ({placeholders})", item_ids)
        jt_conn.execute(f"DELETE FROM items WHERE id IN ({placeholders})", item_ids)
        resync_fts(jt_conn)
        jt_conn.commit()

        # Now that everything's actually gone from disk and jobtracker.db,
        # clear every matching overrides.db row — item-level (notes/status/
        # archived/etc.) and document-level (doc-type corrections) — for
        # the whole folder.
        for item_key in item_keys:
            ov.delete_override(ov_conn, item_key)
            ov.delete_status_history(ov_conn, item_key)
        for relpath in doc_relpaths:
            ov.set_document_override(ov_conn, relpath, None)
        ov.delete_folder_override(ov_conn, folder)
    finally:
        jt_conn.close()
        ov_conn.close()
    return {"ok": True, "folder": folder, "trashed_folders": trashed_folders, "trashed_files": trashed_files}


@app.post("/api/documents/delete")
def delete_document(req: DeleteDocumentRequest):
    """Moves the file to the OS Trash (recoverable — same as a Finder/
    Explorer delete, never a permanent unlink) and drops it from
    jobtracker.db so it disappears from the app immediately instead of
    waiting for the next /api/rebuild. Also clears any doc-type override
    for it, since an override for a file that no longer exists is just
    clutter in overrides.db."""
    full_path = resolve_safe(req.relpath)
    jt_conn, ov_conn = get_conns()
    row = jt_conn.execute("SELECT id FROM documents WHERE relpath = ?", (req.relpath,)).fetchone()

    try:
        send2trash(str(full_path))
    except Exception as e:
        jt_conn.close()
        ov_conn.close()
        # send2trash on macOS goes through Finder/AppleEvents under the hood,
        # which silently fails (or raises exactly this kind of OSError) if
        # the process running this server hasn't been granted Automation
        # permission for Finder — the single most common cause of this.
        # See System Settings -> Privacy & Security -> Automation (or Files
        # and Folders), and allow your terminal/Python there.
        raise HTTPException(
            status_code=500,
            detail=(
                f"Couldn't move '{full_path.name}' to Trash ({e}). "
                "On macOS this is almost always a missing Automation/Finder "
                "permission for whatever process is running this server — "
                "check System Settings > Privacy & Security > Automation "
                "(or Files and Folders) and allow it there, then try again."
            ),
        )

    # Belt-and-suspenders: on macOS, send2trash's AppleScript/Finder path
    # can swallow a missing-Automation-permission failure and return
    # successfully without actually moving anything (this is distinct from
    # the exception case above — no exception is raised at all). If we drop
    # the DB row and report success here anyway, the file quietly reappears
    # on the next rebuild and looks exactly like "delete doesn't work."
    # Guard against that by checking the file is actually gone before we
    # touch the database.
    if full_path.exists():
        jt_conn.close()
        ov_conn.close()
        raise HTTPException(
            status_code=500,
            detail=(
                f"'{full_path.name}' is still on disk after the Trash call — "
                "it silently didn't move. On macOS this is almost always a "
                "missing Automation/Finder permission for whatever process "
                "is running this server — check System Settings > Privacy & "
                "Security > Automation (or Files and Folders) and allow it "
                "there, then try again."
            ),
        )

    if row is not None:
        jt_conn.execute("DELETE FROM documents WHERE id = ?", (row["id"],))
        resync_fts(jt_conn)
        jt_conn.commit()
    ov.set_document_override(ov_conn, req.relpath, None)
    jt_conn.close()
    ov_conn.close()
    return {"ok": True}


@app.post("/api/documents/rename")
def rename_document(req: RenameDocumentRequest):
    """Renames the file in place (same folder — this is a rename, not a
    move) and keeps jobtracker.db in sync immediately, same reasoning as
    delete above. doc_type is recomputed from the new filename via the
    same classify_doc_type rules the indexer uses, since a rename is
    usually exactly how you'd fix a file classify.py couldn't read (e.g.
    disambiguating 'AWS Job 2894707/2894707.pdf'). Any existing manual
    doc-type override still carries over to the new relpath, in case you
    want a correction on top of the new name too."""
    new_name = req.new_filename.strip()
    if not new_name or "/" in new_name or "\\" in new_name:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    full_path = resolve_safe(req.relpath)
    dest = unique_dest_path(full_path.parent, new_name) if new_name != full_path.name else full_path
    if dest == full_path:
        return {"ok": True, "relpath": req.relpath, "unchanged": True}

    full_path.rename(dest)
    root = current_root().resolve()
    new_relpath = str(dest.relative_to(root))

    jt_conn, ov_conn = get_conns()
    row = jt_conn.execute("SELECT id, item_id FROM documents WHERE relpath = ?", (req.relpath,)).fetchone()
    if row is not None:
        jt_conn.execute(
            "UPDATE documents SET filename = ?, relpath = ?, ext = ?, mtime = ?, doc_type = ?, is_source = ? WHERE id = ?",
            (
                dest.name, new_relpath, dest.suffix.lower(), iso_mtime(dest),
                classify_doc_type(dest.name), int(is_source_file(dest.name)), row["id"],
            ),
        )
        resync_fts(jt_conn)
        jt_conn.commit()

    overrides = ov.get_document_overrides(ov_conn)
    if req.relpath in overrides:
        ov.set_document_override(ov_conn, req.relpath, None)
        ov.set_document_override(ov_conn, new_relpath, overrides[req.relpath])

    item_id = row["item_id"] if row is not None else None
    docs = db.load_documents(jt_conn, item_id, ov_conn) if item_id is not None else []
    jt_conn.close()
    ov_conn.close()
    return {"ok": True, "relpath": new_relpath, "documents": docs}


@app.post("/api/documents/override")
def save_document_override(req: DocumentOverrideRequest):
    """Manual doc-type correction for a file classify.py's filename rules
    can't disambiguate on their own (e.g. Applications/AWS Job .../<id>.pdf).
    Never touches the file on disk; stored in overrides.db like every other
    manual correction, so it survives a rebuild. Returns the item's refreshed
    document list (same pattern as rename/upload) so the frontend can patch
    its per-item cache in place instead of wiping and losing it."""
    resolve_safe(req.relpath)  # 404s if the relpath doesn't actually exist under the root
    jt_conn, ov_conn = get_conns()
    ov.set_document_override(ov_conn, req.relpath, req.doc_type_override)
    row = jt_conn.execute("SELECT item_id FROM documents WHERE relpath = ?", (req.relpath,)).fetchone()
    item_id = row["item_id"] if row is not None else None
    docs = db.load_documents(jt_conn, item_id, ov_conn) if item_id is not None else []
    jt_conn.close()
    ov_conn.close()
    return {"ok": True, "item_id": item_id, "documents": docs}


@app.post("/api/applications/{app_id}/override")
def save_override(app_id: int, req: OverrideRequest):
    """Uses the numeric `items.id` in the URL (e.g. POST
    /api/applications/482/override) instead of a raw, double-URL-encoded
    item_key path string — item_keys contain '|' and '/' characters that
    previously round-tripped through encodeURIComponent() and then FastAPI's
    own path decoding and came out mismatched (`applications%7CAWS...`),
    404ing every save. Internally we still resolve to the stable item_key
    before writing, so your notes/status survive an index rebuild even
    though the id itself doesn't (see item_key_for)."""
    jt_conn, ov_conn = get_conns()
    item_key = item_key_for(jt_conn, app_id)

    # Use model_fields_set (not `is not None`) so an explicitly-sent null
    # (e.g. "Mark followed up" clearing next_action/next_action_date) is
    # actually applied instead of being indistinguishable from "field not
    # sent at all" and silently dropped by upsert_override's merge.
    fields: dict = {}
    if req.reset_status:
        fields["manual_status"] = None
    elif "manual_status" in req.model_fields_set:
        fields["manual_status"] = req.manual_status
    if "notes" in req.model_fields_set:
        fields["notes"] = req.notes
    if "date_applied" in req.model_fields_set:
        fields["date_applied"] = req.date_applied
        # A date_applied write that doesn't also carry a source is a manual
        # retype (or a clear) -- any provenance label from an earlier
        # detected-date accept is now stale, so drop it here rather than
        # leaving a "Detected from ..." caption pointing at a date the user
        # just overwrote by hand. When the caller DOES send a source (accepting
        # a suggestion), the branch below applies it instead of this default.
        fields["date_applied_source"] = None
    if "date_applied_source" in req.model_fields_set:
        fields["date_applied_source"] = req.date_applied_source
    if "next_action" in req.model_fields_set:
        fields["next_action"] = req.next_action
    if "next_action_date" in req.model_fields_set:
        fields["next_action_date"] = req.next_action_date
    if "archived" in req.model_fields_set:
        fields["archived"] = int(req.archived) if req.archived is not None else 0
    if "snoozed_until" in req.model_fields_set:
        fields["snoozed_until"] = req.snoozed_until
    if "activity_override" in req.model_fields_set:
        fields["activity_override"] = req.activity_override
    ov.upsert_override(ov_conn, item_key, **fields)

    # Item 7: log a status_history row whenever manual_status actually
    # changes (set OR cleared via reset_status) -- the resulting EFFECTIVE
    # status is what gets logged, not the raw manual_status field, so a
    # reset-to-auto is still a findable transition (see overrides_store.py).
    if "manual_status" in fields:
        item_row = jt_conn.execute("SELECT status FROM items WHERE id = ?", (app_id,)).fetchone()
        auto_status = item_row["status"] if item_row else "unknown"
        effective_status = fields["manual_status"] or auto_status
        ov.append_status_history(ov_conn, item_key, effective_status)

    jt_conn.close()
    ov_conn.close()
    return {"ok": True, "id": app_id}


@app.post("/api/applications/bulk-override")
def bulk_override(req: BulkOverrideRequest):
    """Apply the same override fields to many items at once — powers the
    multi-select bulk actions (Bulk Move to Applied / Bulk Mark Rejected /
    Bulk Archive) in Needs Attention. Takes numeric ids, same as the
    single-item override route above."""
    jt_conn, ov_conn = get_conns()
    # Same model_fields_set fix as save_override above — see its comment.
    fields: dict = {}
    if req.reset_status:
        fields["manual_status"] = None
    elif "manual_status" in req.model_fields_set:
        fields["manual_status"] = req.manual_status
    if "archived" in req.model_fields_set:
        fields["archived"] = int(req.archived) if req.archived is not None else 0
    if "snoozed_until" in req.model_fields_set:
        fields["snoozed_until"] = req.snoozed_until
    if "next_action" in req.model_fields_set:
        fields["next_action"] = req.next_action
    if "next_action_date" in req.model_fields_set:
        fields["next_action_date"] = req.next_action_date
    if "activity_override" in req.model_fields_set:
        fields["activity_override"] = req.activity_override

    updated = 0
    for app_id in req.item_ids:
        row = jt_conn.execute("SELECT item_key, status FROM items WHERE id = ?", (app_id,)).fetchone()
        if row is None:
            continue
        ov.upsert_override(ov_conn, row["item_key"], **fields)
        # Item 7: same status_history logging as save_override, per item --
        # see its comment above.
        if "manual_status" in fields:
            effective_status = fields["manual_status"] or row["status"]
            ov.append_status_history(ov_conn, row["item_key"], effective_status)
        updated += 1
    jt_conn.close()
    ov_conn.close()
    return {"ok": True, "count": updated}


def _trash_path(full_path: Path) -> None:
    """Moves a file or folder to the OS Trash (send2trash — recoverable,
    never a permanent unlink) and verifies it's actually gone. Shared by
    every delete path in this file (single document, single application,
    bulk application delete, and category delete) so they all get
    identical error messages and the same belt-and-suspenders check
    below, instead of each duplicating this logic slightly differently."""
    try:
        send2trash(str(full_path))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Couldn't move '{full_path.name}' to Trash ({e}). "
                "On macOS this is almost always a missing Automation/Finder "
                "permission for whatever process is running this server — "
                "check System Settings > Privacy & Security > Automation "
                "(or Files and Folders) and allow it there, then try again."
            ),
        )

    # Belt-and-suspenders: on macOS, send2trash's AppleScript/Finder path
    # can swallow a missing-Automation-permission failure and return
    # successfully without actually moving anything (distinct from the
    # exception case above — no exception is raised at all). If we drop
    # DB rows and report success anyway, the file/folder quietly
    # reappears on the next rebuild and looks exactly like "delete
    # doesn't work." Guard against that by checking it's actually gone
    # before touching the database.
    if full_path.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                f"'{full_path.name}' is still on disk after the Trash call — "
                "it silently didn't move. On macOS this is almost always a "
                "missing Automation/Finder permission for whatever process "
                "is running this server — check System Settings > Privacy & "
                "Security > Automation (or Files and Folders) and allow it "
                "there, then try again."
            ),
        )


def _remove_empty_parents(path: Path, stop_at: Path) -> None:
    """Walks up from `path`'s parent, removing now-empty directories,
    stopping at (and never removing) `stop_at` itself or anything outside
    it. Used after trashing a Role/ subfolder or a nested category item
    so an empty Company/ (or similar) shell doesn't linger on disk and
    read as "it only deleted the contents, not the whole folder." Never
    trashes a directory that still has something in it."""
    stop_at = stop_at.resolve()
    parent = path.parent
    while parent != stop_at and stop_at in parent.parents and parent.exists() and not any(parent.iterdir()):
        empty_parent = parent
        parent = parent.parent
        try:
            empty_parent.rmdir()
        except OSError:
            # Not empty after all (race) or some other filesystem hiccup —
            # leave it rather than risk removing something unexpected.
            break


def _delete_application(jt_conn, ov_conn, app_id: int) -> None:
    """Shared by both delete endpoints below: trashes the application's
    whole folder on disk (send2trash — recoverable, same guarantee as a
    single document delete) and cleans every trace of it out of both
    databases — its documents rows, its items row, and its overrides.db
    row (a leftover override for an item_key that no longer exists
    anywhere is just a ghost, same reasoning as delete_document's
    document-override cleanup)."""
    row = jt_conn.execute("SELECT item_key, source_relpath FROM items WHERE id = ?", (app_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No application with id {app_id}. Try rebuilding the index.")

    # Captured up front, before anything is deleted from documents — used
    # at the end to also clear each file's document_overrides row (see
    # comment down there for why this is needed).
    doc_relpaths = [
        r["relpath"] for r in jt_conn.execute(
            "SELECT relpath FROM documents WHERE item_id = ?", (app_id,)
        ).fetchall()
    ]

    full_path = resolve_safe_dir(row["source_relpath"])
    _trash_path(full_path)

    # If this application lived in a Role/ subfolder (Applications/<Company>/<Role>/),
    # the trash call above only removed that Role folder — the parent
    # Company/ folder it sat in is left behind on disk, now empty. From the
    # user's point of view that reads as "it only deleted the contents, not
    # the whole folder" (they think of Company/ as the folder, since that's
    # what New Application named for them).
    apps_root = (current_root() / "Applications").resolve()
    _remove_empty_parents(full_path, apps_root)

    jt_conn.execute("DELETE FROM documents WHERE item_id = ?", (app_id,))
    jt_conn.execute("DELETE FROM items WHERE id = ?", (app_id,))
    resync_fts(jt_conn)
    jt_conn.commit()
    ov.delete_override(ov_conn, row["item_key"])
    ov.delete_status_history(ov_conn, row["item_key"])
    # Also clear any per-document doc-type overrides for files that lived
    # under this application — the DELETE above only removed jobtracker.db's
    # `documents` rows; overrides.db's `document_overrides` table (keyed by
    # relpath, not item_key) was never touched by that, and a leftover row
    # there would be a permanent ghost pointing at a relpath nothing will
    # ever exist at again. Bug found via manual DB inspection: single-
    # document delete already did this correctly (see delete_document's
    # ov.set_document_override(..., None) call) — whole-application delete
    # just never mirrored it.
    for override_relpath in doc_relpaths:
        ov.set_document_override(ov_conn, override_relpath, None)


@app.post("/api/applications/{app_id}/delete")
def delete_application(app_id: int):
    """Permanently removes one application: trashes its whole folder on
    disk (recoverable via OS Trash, same guarantee as a single document
    delete) and drops every trace of it from both databases. Works whether
    the application is archived or not — Manage's Archived list is the
    normal place to reach for this, but there's no server-side requirement
    that an item be archived first for a single delete."""
    jt_conn, ov_conn = get_conns()
    try:
        _delete_application(jt_conn, ov_conn, app_id)
    finally:
        jt_conn.close()
        ov_conn.close()
    return {"ok": True, "id": app_id}


@app.post("/api/applications/bulk-delete")
def bulk_delete_applications(req: BulkDeleteApplicationsRequest):
    """Powers Manage's Archived-section multi-select delete (checkbox per
    row / select-all / delete-selected / delete-all-archived). Unlike
    single delete above, this re-verifies server-side that every id is
    actually archived before touching it — the frontend only ever offers
    this button from the Archived list, but that's a UI-level guarantee,
    not a security one, for a destructive, multi-item operation. Never
    aborts the whole batch on one bad id: each is attempted independently,
    and the response reports exactly which ids succeeded and which failed
    (and why)."""
    jt_conn, ov_conn = get_conns()
    deleted: list[int] = []
    failed: list[dict] = []
    try:
        for app_id in req.item_ids:
            item_row = jt_conn.execute("SELECT item_key FROM items WHERE id = ?", (app_id,)).fetchone()
            if item_row is None:
                failed.append({"id": app_id, "error": "Application not found."})
                continue
            override = ov.get_override(ov_conn, item_row["item_key"])
            if not override.get("archived"):
                failed.append({"id": app_id, "error": "Not archived — archive it before deleting."})
                continue
            try:
                _delete_application(jt_conn, ov_conn, app_id)
                deleted.append(app_id)
            except HTTPException as e:
                failed.append({"id": app_id, "error": e.detail})
    finally:
        jt_conn.close()
        ov_conn.close()
    return {"ok": len(failed) == 0, "deleted": deleted, "failed": failed}


@app.get("/api/attention")
def attention():
    jt_conn, ov_conn = get_conns()
    apps = db.load_applications(jt_conn, ov_conn)
    jt_conn.close()
    ov_conn.close()
    return db.needs_attention(apps)


@app.get("/api/insights")
def insights():
    jt_conn, ov_conn = get_conns()
    apps = db.load_applications(jt_conn, ov_conn)
    jt_conn.close()
    ov_conn.close()
    return db.compute_metrics(apps)


# --- search / browse -------------------------------------------------------
@app.get("/api/search")
def search(q: str = "", show_personal: bool = False):
    import re
    import sqlite3

    jt_conn, ov_conn = get_conns()
    if not q:
        jt_conn.close()
        ov_conn.close()
        return []

    tokens = [t for t in re.split(r"\s+", q.strip()) if t]
    fts_expr = " ".join(f'"{t}"*' for t in tokens)
    try:
        rows = jt_conn.execute(
            """
            SELECT d.*, i.company, i.role_label, i.section, i.status, i.source_relpath
            FROM documents d
            JOIN items i ON i.id = d.item_id
            WHERE d.id IN (SELECT rowid FROM documents_fts WHERE documents_fts MATCH ?)
            """,
            (fts_expr,),
        ).fetchall()
    except sqlite3.OperationalError:
        like = f"%{q}%"
        rows = jt_conn.execute(
            """
            SELECT d.*, i.company, i.role_label, i.section, i.status, i.source_relpath
            FROM documents d
            JOIN items i ON i.id = d.item_id
            WHERE d.filename LIKE ? OR i.company LIKE ?
            """,
            (like, like),
        ).fetchall()

    results = [dict(r) for r in rows]
    results = db.apply_document_overrides(ov_conn, results)
    results = db.annotate_duplicates(jt_conn, results)
    folder_overrides = ov.get_all_folder_overrides(ov_conn)
    jt_conn.close()
    ov_conn.close()

    if not show_personal:
        results = [r for r in results if r["section"] != "personal"]

    def _folder_archived(r) -> bool:
        # Same rule as browse(): an archived folder disappears from search
        # too, not just its own Browse tab. Reserved sections (just
        # "applications") can never have an archived folder.
        if r["section"] in RESERVED_CATEGORY_SECTIONS:
            return False
        folder = _folder_key(r.get("source_relpath"))
        return bool(folder and folder_overrides.get(folder, {}).get("archived"))

    results = [r for r in results if not _folder_archived(r)]
    return results


@app.get("/api/browse")
def browse(show_personal: bool = False, show_archived: bool = False, q: str = ""):
    """Archived status lives in overrides.db (item_overrides.archived), not
    on the items table itself, so — unlike Pipeline/Needs Attention, which
    both go through load_applications() and get this for free — Browse has
    to look it up explicitly here. Same default as everywhere else in the
    app: archived items are hidden unless show_archived is set, so
    archiving something from Pipeline actually removes it from Browse too
    instead of only hiding it from Needs Attention."""
    jt_conn, ov_conn = get_conns()
    sections = jt_conn.execute("SELECT DISTINCT section FROM items ORDER BY section").fetchall()
    folder_overrides = ov.get_all_folder_overrides(ov_conn)
    section_names = [s["section"] for s in sections if (s["section"] != "personal" or show_personal)]
    overrides = ov.get_all_overrides(ov_conn)

    out = {}
    ql = q.strip().lower()
    for section in section_names:
        items = jt_conn.execute(
            "SELECT * FROM items WHERE section = ? ORDER BY company, role_label", (section,)
        ).fetchall()
        section_items = []
        for it in items:
            is_archived = bool(overrides.get(it["item_key"], {}).get("archived"))
            if is_archived and not show_archived:
                continue
            # An archived folder (Manage's "Categories" section) disappears
            # from Browse entirely, same as how archiving an application
            # removes it from Browse too. Folder-scoped rather than
            # section-scoped since several physical folders can share one
            # tab. Reserved sections (just "applications") can never have
            # an archived folder.
            if section not in RESERVED_CATEGORY_SECTIONS:
                folder = _folder_key(it["source_relpath"])
                folder_archived = bool(folder and folder_overrides.get(folder, {}).get("archived"))
                if folder_archived and not show_archived:
                    continue
            label = it["company"] if it["role_label"] == "(root)" else f"{it['company']} — {it['role_label']}"
            if ql and ql not in label.lower():
                doc_hit = jt_conn.execute(
                    "SELECT 1 FROM documents WHERE item_id = ? AND filename LIKE ? LIMIT 1",
                    (it["id"], f"%{q}%"),
                ).fetchone()
                if not doc_hit:
                    continue
            docs = jt_conn.execute(
                "SELECT * FROM documents WHERE item_id = ? ORDER BY filename", (it["id"],)
            ).fetchall()
            item = dict(it)
            item["label"] = label
            item["archived"] = is_archived
            item_docs = db.apply_document_overrides(ov_conn, [dict(d) for d in docs])
            item["documents"] = db.annotate_duplicates(jt_conn, item_docs)
            section_items.append(item)
        out[section] = section_items
    jt_conn.close()
    ov_conn.close()
    return out


# --- manage ------------------------------------------------------------------
@app.get("/api/manage")
def manage():
    jt_conn, ov_conn = get_conns()
    apps = db.load_applications(jt_conn, ov_conn)
    aliases = ov.get_aliases(ov_conn)
    suggestions = db.suggest_duplicate_companies(apps)
    unresolved = {
        k: names for k, names in suggestions.items()
        if len({aliases.get(n, n) for n in names}) > 1
    }
    archived = [a for a in apps if a["archived"]]
    duplicate_documents = db.find_duplicate_groups(jt_conn)
    jt_conn.close()
    ov_conn.close()
    return {
        "duplicate_suggestions": unresolved,
        "aliases": aliases,
        "archived": archived,
        "duplicate_documents": duplicate_documents,
    }


@app.post("/api/manage/merge")
def merge(req: MergeRequest):
    _, ov_conn = get_conns()
    for n in req.names:
        if n != req.canonical:
            ov.set_alias(ov_conn, n, req.canonical)
    ov_conn.close()
    return {"ok": True}


@app.post("/api/manage/unmerge")
def unmerge(req: UnmergeRequest):
    _, ov_conn = get_conns()
    ov.remove_alias(ov_conn, req.alias)
    ov_conn.close()
    return {"ok": True}


# --- search hub settings (role, location, and your custom cards/links) ------
# Moved here from browser localStorage so this customization travels with
# the tracker (same overrides.db everything else in ov.* lives in) rather
# than being pinned to one browser profile — see overrides_store.py's
# get_hub_settings/set_hub_settings.
@app.get("/api/hub/settings")
def get_hub_settings():
    _, ov_conn = get_conns()
    settings = ov.get_hub_settings(ov_conn)
    ov_conn.close()
    return settings


@app.post("/api/hub/settings")
def update_hub_settings(req: dict):
    """Partial update: any of role/location/custom_links/custom_cards
    present in the body is merged in (see set_hub_settings), everything
    else is left as-is. Accepts a plain dict rather than a strict model
    since the frontend only ever sends the one or two fields that
    actually changed."""
    allowed = {"role", "location", "custom_links", "custom_cards"}
    fields = {k: v for k, v in req.items() if k in allowed}
    _, ov_conn = get_conns()
    settings = ov.set_hub_settings(ov_conn, **fields)
    ov_conn.close()
    return settings


# --- opening files locally ----------------------------------------------
@app.post("/api/open")
def open_file(req: OpenFileRequest):
    """Shell out to the OS's default opener — same cross-platform approach
    as before. Still useful for non-PDF files, or "open in my real PDF app"
    even when the inline viewer below is enough for a quick look."""
    full_path = resolve_safe(req.relpath)

    import platform
    import subprocess

    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", str(full_path)], check=False)
        elif system == "Windows":
            import os
            os.startfile(str(full_path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(full_path)], check=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Couldn't open {full_path}: {exc}") from exc
    return {"ok": True, "opened": full_path.name}


# --- opening external links in the system's default browser -------------
# Search Hub cards call this instead of the browser's own window.open(),
# because window.open() from inside the pywebview/WKWebView shell this app
# runs in does not reliably spawn the user's actual default browser (it's
# an embedded webview, not a full browser, so popups it can't handle are
# often just silently dropped). Shelling out to the OS opener sidesteps
# that entirely — same approach as /api/open above, just for URLs instead
# of local files.
_OPEN_URL_SCHEMES = ("http://", "https://", "mailto:", "tel:")


@app.post("/api/open-url")
def open_url(req: OpenUrlRequest):
    """Hands a URL to the OS's default handler. Originally http(s)-only
    (job boards, career pages); the Dossier's Contacts section also routes
    email/phone actions through here (mailto:/tel:) instead of
    window.location.href, since that's unreliable in the packaged webview
    (see openExternalUrl's comment in the frontend for why)."""
    url = (req.url or "").strip()
    if not url.startswith(_OPEN_URL_SCHEMES):
        raise HTTPException(
            status_code=400,
            detail="Only http://, https://, mailto:, and tel: URLs can be opened.",
        )

    import platform
    import subprocess

    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", url], check=False)
        elif system == "Windows":
            import os
            os.startfile(url)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", url], check=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Couldn't open {url}: {exc}") from exc
    return {"ok": True}


@app.get("/api/file")
def serve_file(relpath: str):
    """Streams a file's raw bytes so the frontend can embed it inline
    (native <iframe>/<embed> viewer) instead of always shelling out to the
    OS. Sets an explicit Content-Type for formats browsers/mimetypes often
    get wrong (.pdf, .tex, .md) so the inline viewer renders instead of
    downloading. Same locality guarantee as /api/open: only ever serves
    files inside DEFAULT_ROOT (resolve_safe blocks path traversal via
    '../' or symlink escapes), and the server itself only binds to
    127.0.0.1 (see __main__), so this never leaves your machine."""
    full_path = resolve_safe(relpath)
    # Deliberately omit `filename=` here. Starlette only emits a
    # Content-Disposition header at all when `filename` is set — and
    # defaults that header to "attachment", forcing a download regardless
    # of media_type. Passing content_disposition_type="inline" avoids the
    # forced download, but Safari has a long-standing bug where it fails to
    # render iframe-embedded content at all when a Content-Disposition
    # header is present (worse when the filename needs percent-encoding,
    # which forces Starlette into the `filename*=utf-8''...` RFC 5987 form
    # Safari handles particularly badly) — it just shows a blank frame,
    # with no console error. PDF appeared to work anyway because Safari/
    # Chrome's built-in PDF viewer overrides Content-Disposition for
    # <embed type="application/pdf">, but plain text/markdown/tex have no
    # such override. The simplest fix that works in every browser: don't
    # send Content-Disposition at all. With no `filename`, Starlette skips
    # the header entirely, and browsers render based on Content-Type alone
    # — which is exactly what this endpoint's only consumer (the inline
    # <embed>/<iframe> viewer) needs. /api/open (the "Open in OS" button)
    # is unaffected — it opens the file directly on disk via the OS, not
    # through this HTTP response.
    #
    # Text-like extensions (.txt/.tex/.md/.markdown) are wrapped in our
    # own minimal HTML instead of served raw — see TEXT_VIEWER_EXTENSIONS
    # for why (browser-native text viewer + nested iframe + dark mode =
    # invisible white-on-white text).
    if full_path.suffix.lower() in TEXT_VIEWER_EXTENSIONS:
        raw_text = full_path.read_text(encoding="utf-8", errors="replace")
        return HTMLResponse(content=_wrap_text_for_viewer(raw_text))

    return FileResponse(
        full_path,
        media_type=guess_media_type(full_path),
    )


@app.get("/api/preview-docx")
def preview_docx(relpath: str):
    """Converts a .docx to HTML on the fly for inline preview — read-only,
    the original file on disk is never touched or rewritten. Unlike
    /api/file, a raw .docx can't be handed straight to an <iframe>
    (browsers have no native Word renderer), so this returns rendered
    HTML instead of the file bytes. .doc (the old pre-2007 binary format)
    isn't supported by the underlying library — those still fall back to
    "Open" like before this endpoint existed."""
    full_path = resolve_safe(relpath)
    if full_path.suffix.lower() != ".docx":
        raise HTTPException(status_code=400, detail="Inline docx preview only supports .docx files")
    try:
        import mammoth
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail="Inline .docx preview needs the 'mammoth' package — run: pip install -r requirements.txt",
        ) from exc
    try:
        with open(full_path, "rb") as f:
            result = mammoth.convert_to_html(f)
    except Exception as exc:  # noqa: BLE001 — surface a readable message instead of a raw 500
        raise HTTPException(status_code=500, detail=f"Couldn't preview {full_path.name}: {exc}") from exc
    return {"html": result.value, "warnings": [str(w) for w in result.messages]}


# --- static frontend ----------------------------------------------------
# Mounted LAST, after every /api/* route above: Starlette matches routes in
# the order they were registered, so the explicit /api/... handlers above
# always win first and this catch-all only ever serves what's left over —
# "/", "/index.html", any future /assets/* — straight out of frontend/.
# html=True makes "/" resolve to frontend/index.html automatically. This
# is what puts the whole app on http://localhost:8000 with no separate
# dev server and no CORS/file:// limitations.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import os

    import uvicorn

    # Configurable via JOBTRACKER_PORT for desktop/launcher.py, which picks
    # a free port at runtime (a fixed port would collide if the app is ever
    # opened twice, or with anything else already using 8000). Defaults to
    # the original fixed 8000 so the existing dev workflow — `python api.py`
    # or `uvicorn api:app --reload --port 8000` — is completely unaffected.
    port = int(os.environ.get("JOBTRACKER_PORT", "8000"))

    # 127.0.0.1 only — this is a single-user local tool, never meant to be
    # exposed on your network.
    uvicorn.run("api:app", host="127.0.0.1", port=port, reload=False)
