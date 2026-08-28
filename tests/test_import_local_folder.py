"""Direct folder-to-folder import: /api/workspaces/import-folder-local and
its underlying workspace.import_workspace_from_local_folder(). This is
the desktop-packaged counterpart to the browser's zip/webkitdirectory
import paths (see test_workspaces.py for link, and NoTrackerOnboarding /
WorkspacePopover in the frontend for where this is triggered) -- it
copies an existing folder's contents into a brand-new, independent
tracker without ever going through a zip or an HTTP upload.

Every test here redirects ws_module._owned_siblings_dir() into a tmp
folder first, same as test_create_workspace.py -- import (unlike link)
always creates a new OWNED sibling root, and in packaged mode that
otherwise hard-codes the real ~/Documents/JobTracker Hub with no env
var to override it. See conftest.py and NOTES.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def redirect_owned_siblings_dir(ws_module, tmp_path, monkeypatch):
    owned_dir = tmp_path / "owned-siblings"
    monkeypatch.setattr(ws_module, "_owned_siblings_dir", lambda: owned_dir)
    return owned_dir


def test_import_local_folder_copies_files_into_new_tracker(client, sample_root):
    resp = client.post(
        "/api/workspaces/import-folder-local",
        json={"name": "Imported Copy", "path": str(sample_root)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["workspace"]["name"] == "Imported Copy"

    status = client.get("/api/status").json()
    assert status["workspace"]["name"] == "Imported Copy"
    assert status["index_built"] is True
    # resume.pdf + coverletter.txt from the sample_root fixture.
    assert status["doc_count"] == 2


def test_import_local_folder_is_a_copy_not_a_link(client, ws_module, sample_root):
    resp = client.post(
        "/api/workspaces/import-folder-local",
        json={"name": "Imported Copy", "path": str(sample_root)},
    )
    entry_id = resp.json()["workspace"]["id"]
    new_root = ws_module._load_raw()["workspaces"][entry_id]["root"]
    assert str(sample_root) != new_root
    # The files exist at the new location too, not just the original.
    assert (Path(new_root) / "Applications" / "Acme Co" / "Backend Engineer" / "resume.pdf").exists()


def test_import_local_folder_never_modifies_the_source_folder(client, sample_root):
    before = sorted(p.relative_to(sample_root) for p in sample_root.rglob("*"))
    client.post(
        "/api/workspaces/import-folder-local",
        json={"name": "Imported Copy", "path": str(sample_root)},
    )
    after = sorted(p.relative_to(sample_root) for p in sample_root.rglob("*"))
    assert before == after


def test_import_local_folder_rejects_nonexistent_folder(client, tmp_path):
    missing = tmp_path / "does-not-exist"
    resp = client.post(
        "/api/workspaces/import-folder-local",
        json={"name": "Ghost Import", "path": str(missing)},
    )
    assert resp.status_code == 400


def test_import_local_folder_rejects_empty_folder(client, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    resp = client.post(
        "/api/workspaces/import-folder-local",
        json={"name": "Nothing Here", "path": str(empty)},
    )
    assert resp.status_code == 400


def test_import_local_folder_from_an_already_linked_folder_still_succeeds(client, sample_root):
    # Unlike /api/workspaces/link (can't point two trackers at the same
    # path), importing COPIES the folder's contents, so a folder that's
    # already in use as another tracker is perfectly fine to import
    # from -- it just produces a second, independent tracker. This is
    # the backend half of describeFolderInspection()'s mode-aware
    # "already_linked" handling in the frontend (soft warning for
    # import, hard block for link).
    link_resp = client.post(
        "/api/workspaces/link", json={"name": "Original", "path": str(sample_root)}
    )
    assert link_resp.status_code == 200

    import_resp = client.post(
        "/api/workspaces/import-folder-local",
        json={"name": "Copy Of Original", "path": str(sample_root)},
    )
    assert import_resp.status_code == 200

    names = {w["name"] for w in client.get("/api/workspaces").json()["workspaces"]}
    assert {"Original", "Copy Of Original"} <= names


def test_import_local_folder_strips_owned_prefix_from_default_name(client, tmp_path):
    # A folder named "JobTracker — <name>" is this app's own naming
    # convention for owned trackers (see workspace._new_sibling_root /
    # _strip_owned_prefix) -- importing one shouldn't double the prefix
    # onto the new copy's name.
    owned_shaped = tmp_path / "JobTracker — Old Tracker"
    (owned_shaped / "Applications").mkdir(parents=True)
    (owned_shaped / "Applications" / "note.txt").write_text("hi")
    resp = client.post(
        "/api/workspaces/import-folder-local",
        json={"name": "JobTracker — Old Tracker", "path": str(owned_shaped)},
    )
    assert resp.status_code == 200
    assert resp.json()["workspace"]["name"] == "Old Tracker"


def test_import_local_folder_lands_under_redirected_owned_siblings_dir(
    client, ws_module, sample_root, redirect_owned_siblings_dir
):
    # Belt-and-suspenders check that the monkeypatch above is actually
    # taking effect, mirroring test_create_workspace's same check --
    # if _owned_siblings_dir() ever stopped being consulted here, every
    # other test in this file would start writing under the real
    # ~/Documents on whatever machine runs the suite instead of failing
    # loudly, so it's worth asserting directly.
    resp = client.post(
        "/api/workspaces/import-folder-local",
        json={"name": "Imported Copy", "path": str(sample_root)},
    )
    entry_id = resp.json()["workspace"]["id"]
    new_root = ws_module._load_raw()["workspaces"][entry_id]["root"]
    assert new_root.startswith(str(redirect_owned_siblings_dir))
