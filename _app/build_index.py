"""
Walks a JobTracker root directory and (re)builds jobtracker.db.

Usage:
    python build_index.py                    # indexes the parent of _app/
    python build_index.py /some/other/path    # explicit override
    python build_index.py --db jobtracker.db

`_app/` lives *inside* the JobTracker folder it indexes (see DEFAULT_ROOT
below), so the default scan target is simply ".." — the folder _app/ was
dropped into. That folder never needs to be typed in or configured. The
walk explicitly skips `_app/` itself (and therefore jobtracker.db and
overrides.db, which only ever live there), every hidden dir/file (name
starting with "."), dependency folders (`node_modules`, `.venv`, `venv`,
`env`), and archive/db files (`.zip`, `.tar`, `.tar.gz`, `.db`, `.sqlite*`)
anywhere in the tree — see classify.should_ignore for the full list — so
the app never indexes its own code/databases or stray archive exports.

Safe to re-run any time you add a new folder — it fully rebuilds the index
from the current filesystem state each time (the DB is a disposable cache,
never a second source of truth). Your files are never modified or moved.

Your manual edits (status corrections, notes, next actions, company merges)
do NOT live in this database — they're in overrides.db, keyed by a stable
`item_key` computed here, so rebuilding this index never loses them as long
as your folder structure (company/role folder names) stays the same.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from classify import (
    NESTED_APPLICATION_MARKERS,
    classify_doc_type,
    classify_section,
    infer_status,
    is_source_file,
    normalize_for_search,
    should_ignore,
)

# _app/ is nested one level inside the JobTracker root it indexes, so ".."
# from this file's directory *is* that root — no path input required.
APP_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = APP_DIR.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT NOT NULL UNIQUE,  -- stable key, survives rebuilds: section|company|role_label|source_relpath
    section TEXT NOT NULL,        -- applications | credentials | network |
                                   -- resume_library | leads | personal | compliance | misc
    company TEXT NOT NULL,        -- company name (applications) or group label (others)
    role_label TEXT NOT NULL,     -- subfolder distinguishing multiple roles/entries
    source_relpath TEXT NOT NULL, -- folder path relative to JobTracker root
    status TEXT NOT NULL,         -- applied | interviewing | rejected | drafted | unknown | n/a  (auto-inferred)
    last_activity TEXT,           -- ISO date of the newest file in this item (by mtime — see README caveat)
    first_activity TEXT,          -- ISO date of the oldest file in this item
    UNIQUE(section, company, role_label, source_relpath)
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    doc_type TEXT NOT NULL,
    filename TEXT NOT NULL,
    relpath TEXT NOT NULL UNIQUE,  -- full path relative to JobTracker root
    ext TEXT NOT NULL,
    mtime TEXT NOT NULL,           -- ISO datetime of last modification
    content_hash TEXT,             -- SHA-256 of file bytes; powers duplicate detection (never used to delete/merge)
    is_source INTEGER NOT NULL DEFAULT 0  -- 1 for .tex/etc — hidden from default document lists in the UI, never from the index/search
);

CREATE INDEX IF NOT EXISTS idx_documents_item ON documents(item_id);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_items_section ON items(section);
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    filename, company, role_label, content=''
);
"""


def iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def sha256_of(path: Path) -> str | None:
    """SHA-256 of a file's bytes, used only for duplicate *detection*
    (grouping identical documents in the UI) — never for any write/merge/
    delete decision. Returns None if the file can't be read (e.g. a broken
    symlink) rather than failing the whole index build."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def make_item_key(section: str, company: str, role_label: str, source_relpath: str) -> str:
    return f"{section}|{company}|{role_label}|{source_relpath}"


# --- Creating a brand-new application from the UI --------------------------
# There is deliberately no separate "draft application" concept anywhere in
# this app — an item only exists once build() finds a real folder with a
# real file in it under Applications/. These two helpers are shared by both
# UIs (app.py's "+ New Application" form and api.py's POST
# /api/applications/new) so "adding an application" always means exactly
# the same thing a manually-created folder would: create the folder, make
# sure it isn't empty, then let the normal indexing pass in build() pick it
# up like anything else in Applications/.
_UNSAFE_NAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def sanitize_folder_name(name: str) -> str:
    """Turns a user-typed company/role name into one safe folder-name
    component: strips characters that would change directory structure
    (path separators) or aren't valid on Windows/macOS filesystems, and
    collapses whitespace. Raises ValueError on an empty/invalid result —
    callers should surface that as a 400 to the user, not a 500."""
    cleaned = _UNSAFE_NAME_CHARS.sub("", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or cleaned in (".", ".."):
        raise ValueError("Please enter a valid company name.")
    return cleaned


def create_application_folder(root: Path, company: str, role_label: str | None = None) -> Path:
    """Creates Applications/<Company>/[<Role>/] under `root` and returns
    the new folder's path. Refuses to create anything outside
    Applications/ (defense in depth against a sanitize_folder_name bug,
    since this is reachable from the browser via api.py), and refuses to
    reuse an existing, non-empty folder so this can never silently merge
    into — or overwrite documents in — an application that already
    exists. Does NOT call build() itself; callers rebuild the index
    afterward so the new folder shows up the exact same way any other
    manually-created one would."""
    company_name = sanitize_folder_name(company)
    role_name = sanitize_folder_name(role_label) if role_label and role_label.strip() else None

    apps_root = (root / "Applications").resolve()
    dest = apps_root / company_name
    if role_name:
        dest = dest / role_name
    dest = dest.resolve()
    try:
        dest.relative_to(apps_root)
    except ValueError:
        raise ValueError("Invalid company/role name.")
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(
            f"'{dest.relative_to(root)}' already exists and has files in it — "
            "open it from Pipeline/Browse instead of creating a duplicate."
        )
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def create_category_folder(root: Path, name: str) -> Path:
    """Creates a brand-new top-level folder directly under `root` — e.g.
    root/"Case Management" or root/"Solar Panel Docs" — so it becomes its
    own Browse section (see classify.classify_section) on the next
    rebuild. Sibling to create_application_folder() above, but for
    *categories* rather than individual applications: no Company/Role
    nesting, just one flat folder. Refuses to collide with `Applications`
    (that's a reserved, specially-handled section) or with `_app` (the
    app's own home, which should_ignore() always skips), and — like
    create_application_folder — refuses to reuse an existing non-empty
    folder so this can never silently merge into a category that already
    has files in it. Does NOT call build() itself; the caller rebuilds
    the index afterward, same as every other folder-creating endpoint."""
    clean_name = sanitize_folder_name(name)
    if clean_name.lower() in {"applications", "_app"}:
        raise ValueError(f"'{clean_name}' is a reserved name — pick a different category name.")

    root = root.resolve()
    dest = (root / clean_name).resolve()
    try:
        dest.relative_to(root)
    except ValueError:
        raise ValueError("Invalid category name.")
    if dest.parent != root:
        raise ValueError("Invalid category name.")
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(
            f"'{clean_name}' already exists and has files in it — "
            "open it from Browse instead of creating a duplicate."
        )
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def ensure_not_empty(folder: Path) -> None:
    """Drops a tiny notes.txt placeholder into `folder` if nothing was
    uploaded into it. group_applications() below only ever turns a folder
    into a tracked item once it contains at least one real, non-ignored
    file — a bare empty folder is invisible to build() — so without this,
    an application created with no starting document would silently not
    appear after the caller's rebuild."""
    if not any(folder.iterdir()):
        (folder / "notes.txt").write_text(
            "Created from JobTracker Hub. Add a resume, cover letter, or "
            "any other document to this folder (or drag one in from the "
            "app), then Rebuild index.\n"
        )


def walk_files(root: Path):
    """Yield every non-ignored file under root, as a path relative to root."""
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if any(should_ignore(part) for part in path.parts):
            continue
        yield path.relative_to(root)


def group_applications(
    root: Path, app_files: list[Path]
) -> dict[tuple[str, str, str], tuple[list[Path], bool]]:
    """
    Group files under Applications/ into (company, role_label, source_relpath)
    buckets. Each value is (files, is_compliance) — is_compliance is True
    only for the catch-all bucket of a nested-application marker folder
    (see classify.NESTED_APPLICATION_MARKERS), so the caller can section it
    as "compliance" rather than counting it as a real job application.

    Nested-application markers (opt-in, off by default — see
    classify_config.json) handle folders like a state workforce-center
    compliance folder whose "Jobs Applied For/<Month>/<Company>/" contains
    real, dated job applications that should be tracked individually rather
    than lumped into one blob. Everything else directly under a marker
    folder (case-management reports, workshop notices, a general resume) is
    bucketed separately as compliance, not treated as a job application.
    """
    markers_by_folder = {m["folder"]: m for m in NESTED_APPLICATION_MARKERS}

    groups: dict[tuple[str, str, str], tuple[list[Path], bool]] = {}

    def add(key: tuple[str, str, str], relpath: Path, is_compliance: bool) -> None:
        files, _ = groups.setdefault(key, ([], is_compliance))
        files.append(relpath)

    for relpath in app_files:
        parts = relpath.parts  # ('Applications', 'Company', ...)
        if len(parts) < 2:
            continue
        company_folder = parts[1]
        marker = markers_by_folder.get(company_folder)

        matched_nested = False
        if marker:
            after = tuple(marker.get("path_after_folder", []))
            n = len(after)
            # parts: Applications / <folder> / <after...> / <date_segment> / <company> / ...
            if len(parts) >= 3 + n + 1 and parts[2 : 2 + n] == after:
                date_segment = parts[2 + n]
                company = parts[3 + n]
                role_label = marker.get(
                    "role_label_template", "via {folder} ({date_segment})"
                ).format(folder=company_folder, date_segment=date_segment)
                source_relpath = str(Path(*parts[: 3 + n + 1]))
                add((company, role_label, source_relpath), relpath, is_compliance=False)
                matched_nested = True

        if matched_nested:
            continue
        if marker:
            # Falls under the marker folder but not the dated-application
            # shape (e.g. case-management reports, workshop notices).
            add(
                (company_folder, "(case management)", str(Path(*parts[:2]))),
                relpath,
                is_compliance=True,
            )
            continue

        company = company_folder
        role_label = parts[2] if len(parts) > 3 else "(root)"
        source_relpath = str(Path(*parts[: min(3, len(parts) - 1)]))
        add((company, role_label, source_relpath), relpath, is_compliance=False)

    return groups


def build(root: Path, db_path: Path) -> None:
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    # A linked/owned workspace's db directory (_app/workspaces/<id>/) is
    # created once, at link/create time (see workspace.py's ws_dir.mkdir
    # calls) -- but nothing re-creates it before a LATER rebuild if that
    # folder goes missing in the meantime (a fresh checkout that never
    # restored gitignored runtime state, an external cleanup tool, a
    # workspaces.json copied/restored without its sibling data folder,
    # etc.). Without this, sqlite3.connect() below fails with the opaque
    # "unable to open database file" instead of just recreating the
    # folder, since SQLite never creates missing parent directories on
    # its own. overrides_store.get_conn() already guards the equivalent
    # case for overrides.db -- this mirrors that same defense here.
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript("DROP TABLE IF EXISTS documents_fts;")
    conn.executescript("DROP TABLE IF EXISTS documents;")
    conn.executescript("DROP TABLE IF EXISTS items;")
    conn.executescript(SCHEMA)

    all_files = list(walk_files(root))
    app_files = [p for p in all_files if p.parts and p.parts[0] == "Applications"]
    other_files = [p for p in all_files if not (p.parts and p.parts[0] == "Applications")]

    item_cache: dict[tuple[str, str, str, str], int] = {}

    def get_item_id(section: str, company: str, role_label: str, source_relpath: str) -> int:
        key = (section, company, role_label, source_relpath)
        if key in item_cache:
            return item_cache[key]
        item_key = make_item_key(section, company, role_label, source_relpath)
        cur = conn.execute(
            "INSERT INTO items (item_key, section, company, role_label, source_relpath, status, last_activity, first_activity) "
            "VALUES (?, ?, ?, ?, ?, 'unknown', NULL, NULL)",
            (item_key, section, company, role_label, source_relpath),
        )
        item_cache[key] = cur.lastrowid
        return cur.lastrowid

    def insert_document(item_id: int, relpath: Path) -> None:
        filename = relpath.name
        conn.execute(
            "INSERT OR IGNORE INTO documents "
            "(item_id, doc_type, filename, relpath, ext, mtime, content_hash, is_source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item_id,
                classify_doc_type(filename),
                filename,
                str(relpath),
                relpath.suffix.lower(),
                iso_mtime(root / relpath),
                sha256_of(root / relpath),
                int(is_source_file(filename)),
            ),
        )

    # --- Applications/ (with any enabled nested-application markers) -------
    for (company, role_label, source_relpath), (files, is_compliance) in group_applications(
        root, app_files
    ).items():
        section = "compliance" if is_compliance else "applications"
        item_id = get_item_id(section, company, role_label, source_relpath)
        for f in files:
            insert_document(item_id, f)

    # --- Everything else, grouped by top-level folder -----------------------
    for relpath in other_files:
        parts = relpath.parts
        if len(parts) < 2:
            # A loose file directly at the JobTracker root (e.g. README.md).
            top_folder = "(root)"
            section = "misc"
            role_label = "(root)"
            source_relpath = ""
        else:
            top_folder = parts[0]
            section = classify_section(top_folder)
            role_label = parts[1] if len(parts) > 2 else "(root)"
            source_relpath = str(Path(*parts[: min(2, len(parts) - 1)]))

        item_id = get_item_id(section, top_folder, role_label, source_relpath)
        insert_document(item_id, relpath)

    # --- Roll up status + activity dates per application item ---------------
    for (item_id,) in conn.execute("SELECT id FROM items WHERE section = 'applications'").fetchall():
        rows = conn.execute("SELECT doc_type, mtime FROM documents WHERE item_id = ?", (item_id,)).fetchall()
        doc_types = {r[0] for r in rows}
        status = infer_status(doc_types)
        mtimes = [r[1] for r in rows]
        last_activity = max(mtimes, default=None)
        first_activity = min(mtimes, default=None)
        conn.execute(
            "UPDATE items SET status = ?, last_activity = ?, first_activity = ? WHERE id = ?",
            (status, last_activity, first_activity, item_id),
        )

    # Non-application items: status is not meaningful, just record recency.
    for (item_id,) in conn.execute("SELECT id FROM items WHERE section != 'applications'").fetchall():
        rows = conn.execute("SELECT mtime FROM documents WHERE item_id = ?", (item_id,)).fetchall()
        mtimes = [r[0] for r in rows]
        conn.execute(
            "UPDATE items SET status = 'n/a', last_activity = ?, first_activity = ? WHERE id = ?",
            (max(mtimes, default=None), min(mtimes, default=None), item_id),
        )

    # --- Full-text search index --------------------------------------------
    conn.execute("DELETE FROM documents_fts")
    for row in conn.execute(
        "SELECT d.id, d.filename, i.company, i.role_label FROM documents d JOIN items i ON i.id = d.item_id"
    ).fetchall():
        doc_id, filename, company, role_label = row
        conn.execute(
            "INSERT INTO documents_fts (rowid, filename, company, role_label) VALUES (?, ?, ?, ?)",
            (
                doc_id,
                normalize_for_search(filename),
                normalize_for_search(company),
                normalize_for_search(role_label),
            ),
        )

    conn.commit()

    n_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    n_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    n_companies = conn.execute(
        "SELECT COUNT(DISTINCT company) FROM items WHERE section = 'applications'"
    ).fetchone()[0]
    n_dupe_groups = conn.execute(
        "SELECT COUNT(*) FROM (SELECT content_hash FROM documents "
        "WHERE content_hash IS NOT NULL GROUP BY content_hash HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    n_source = conn.execute("SELECT COUNT(*) FROM documents WHERE is_source = 1").fetchone()[0]
    conn.close()
    print(
        f"Indexed {n_docs} documents across {n_items} items ({n_companies} companies) -> {db_path}"
    )
    print(f"  {n_source} source files (.tex) hidden by default; {n_dupe_groups} duplicate-content groups detected")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root", type=Path, nargs="?", default=None,
        help="Path to your JobTracker root directory (default: .. — the "
             "folder _app/ is nested inside)",
    )
    parser.add_argument("--db", type=Path, default=APP_DIR / "jobtracker.db")
    args = parser.parse_args()
    root = (args.root or DEFAULT_ROOT).expanduser().resolve()
    build(root, args.db)


if __name__ == "__main__":
    main()
