"""
Tests for build_index.py's build() -- specifically the fix for a real
crash reported against Checkpoint 3: /api/rebuild returning a bare 500
with `sqlite3.OperationalError: unable to open database file` whenever
db_path's containing folder doesn't already exist on disk.

This happens for any workspace whose db directory
(_app/workspaces/<id>/) was created once at link/create time but later
went missing -- a fresh checkout that never restored gitignored runtime
state, an external cleanup tool, a workspaces.json copied/restored
without its sibling data folder, etc. SQLite never creates missing
parent directories on its own, so build() must, exactly like
overrides_store.get_conn() already does for overrides.db.

Standalone module, no workspace/app state -- just needs sys.path (set
up by conftest.py).
"""

from __future__ import annotations

import sqlite3

import build_index


def _make_tracker_root(tmp_path):
    root = tmp_path / "Tracker"
    role_dir = root / "Applications" / "Acme Co" / "Backend Engineer"
    role_dir.mkdir(parents=True)
    (role_dir / "resume.txt").write_text("Jane Doe, jane@example.com")
    return root


def test_build_creates_missing_db_directory_instead_of_crashing(tmp_path):
    root = _make_tracker_root(tmp_path)
    # Simulates a registered-but-missing workspace directory: nothing
    # under tmp_path/workspaces/some-id/ exists yet.
    db_path = tmp_path / "workspaces" / "some-id" / "jobtracker.db"
    assert not db_path.parent.exists()

    build_index.build(root, db_path)

    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.close()
    assert count == 1


def test_build_still_works_when_db_directory_already_exists(tmp_path):
    # The already-exists path must remain a no-op, never an error
    # (exist_ok=True) -- covers the normal/common case unchanged.
    root = _make_tracker_root(tmp_path)
    db_dir = tmp_path / "workspaces" / "some-id"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "jobtracker.db"

    build_index.build(root, db_path)
    build_index.build(root, db_path)  # rebuild, same path -- must not raise

    assert db_path.exists()
