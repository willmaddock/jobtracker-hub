"""
Workspace (tracker) lifecycle: link an existing folder, switch between
trackers, rename, delete, and create a brand-new one.
"""

from __future__ import annotations


def test_status_before_any_workspace_exists(client):
    # Packaged mode + a freshly emptied registry (see conftest's
    # clean_registry) means there's genuinely no active tracker yet --
    # this is the exact "before first-run picker" state a fresh install
    # is in. Must be a clean 200 with workspace: None, never a 500.
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["workspace"] is None
    assert body["index_built"] is False
    assert body["packaged"] is True


def test_link_workspace_builds_index_and_becomes_active(client, sample_root):
    resp = client.post(
        "/api/workspaces/link",
        json={"name": "My Job Search", "path": str(sample_root)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["workspace"]["name"] == "My Job Search"

    status = client.get("/api/status").json()
    assert status["workspace"]["name"] == "My Job Search"
    assert status["index_built"] is True
    # resume.pdf + coverletter.txt from the sample_root fixture.
    assert status["doc_count"] == 2


def test_link_rejects_nonexistent_folder(client, tmp_path):
    missing = tmp_path / "does-not-exist"
    resp = client.post(
        "/api/workspaces/link",
        json={"name": "Ghost Tracker", "path": str(missing)},
    )
    assert resp.status_code == 400


def test_link_rejects_duplicate_name(client, sample_root, tmp_path):
    other_root = tmp_path / "other"
    (other_root / "Applications").mkdir(parents=True)

    first = client.post(
        "/api/workspaces/link", json={"name": "Dup Name", "path": str(sample_root)}
    )
    assert first.status_code == 200

    second = client.post(
        "/api/workspaces/link", json={"name": "Dup Name", "path": str(other_root)}
    )
    assert second.status_code == 400


def test_link_rejects_the_jobtracker_folder_itself(client, sample_root):
    # Regression test for the bug traced in docs/archive/handoffs/HANDOFF_SESSION16_LEGACY.md §3i: selecting a
    # tracker's own internal ".jobtracker" storage folder as a link
    # target used to succeed silently, polluting that real tracker's
    # storage with a spurious Applications/ folder and registering a
    # permanently-empty duplicate workspace. Must now be a clean 400,
    # with nothing created inside the original tracker's storage.
    client.post("/api/workspaces/link", json={"name": "Real Tracker", "path": str(sample_root)})

    # link_workspace itself only creates Applications/ -- .jobtracker/
    # (the portable overrides.db's home) is created lazily on first
    # touch of overrides.db (see test_workspace_list_includes_kind_and_
    # overrides_flag), same as it would be from real app usage. Trigger
    # that here so dot_dir exists, matching the real-world scenario this
    # guards against.
    client.get("/api/applications")
    dot_dir = sample_root / ".jobtracker"
    assert dot_dir.is_dir()

    resp = client.post(
        "/api/workspaces/link", json={"name": "Bogus", "path": str(dot_dir)}
    )
    assert resp.status_code == 400
    assert "internal data folder" in resp.json()["detail"]

    # The real tracker's internal storage must not have been polluted.
    assert not (dot_dir / "Applications").exists()
    names = {w["name"] for w in client.get("/api/workspaces").json()["workspaces"]}
    assert "Bogus" not in names


def test_link_rejects_a_folder_nested_inside_an_existing_tracker(client, sample_root):
    client.post("/api/workspaces/link", json={"name": "Parent", "path": str(sample_root)})
    nested = sample_root / "Applications"

    resp = client.post(
        "/api/workspaces/link", json={"name": "Nested Bogus", "path": str(nested)}
    )
    assert resp.status_code == 400
    assert "Parent" in resp.json()["detail"]


def test_switch_between_two_linked_workspaces(client, tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    (root_a / "Applications").mkdir(parents=True)
    (root_b / "Applications").mkdir(parents=True)

    id_a = client.post(
        "/api/workspaces/link", json={"name": "Tracker A", "path": str(root_a)}
    ).json()["workspace"]["id"]
    id_b = client.post(
        "/api/workspaces/link", json={"name": "Tracker B", "path": str(root_b)}
    ).json()["workspace"]["id"]

    # Linking B made it active; status should reflect that.
    assert client.get("/api/status").json()["workspace"]["id"] == id_b

    switch_back = client.post("/api/workspaces/switch", json={"id": id_a})
    assert switch_back.status_code == 200
    assert client.get("/api/status").json()["workspace"]["id"] == id_a


def test_switch_to_unknown_id_is_rejected(client, sample_root):
    client.post("/api/workspaces/link", json={"name": "Real One", "path": str(sample_root)})
    resp = client.post("/api/workspaces/switch", json={"id": "does-not-exist"})
    assert resp.status_code == 400


def test_rename_workspace(client, sample_root):
    entry = client.post(
        "/api/workspaces/link", json={"name": "Old Name", "path": str(sample_root)}
    ).json()["workspace"]
    resp = client.post(f"/api/workspaces/{entry['id']}/rename", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["workspace"]["name"] == "New Name"
    assert client.get("/api/status").json()["workspace"]["name"] == "New Name"


def test_delete_workspace_removes_it_from_the_list(client, sample_root, tmp_path):
    # A linked (not owned) workspace's root is registered in place --
    # delete_workspace must remove the registry entry and DB pair
    # without touching sample_root itself (see workspace.py's
    # delete_workspace docstring on why "linked" vs "owned" matters).
    entry = client.post(
        "/api/workspaces/link", json={"name": "Temp Tracker", "path": str(sample_root)}
    ).json()["workspace"]

    resp = client.delete(f"/api/workspaces/{entry['id']}")
    assert resp.status_code == 200

    remaining_ids = {w["id"] for w in client.get("/api/workspaces").json()["workspaces"]}
    assert entry["id"] not in remaining_ids
    # The linked folder itself must survive deletion untouched.
    assert (sample_root / "Applications" / "Acme Co" / "Backend Engineer" / "resume.pdf").exists()


def test_create_workspace(client, ws_module, tmp_path, monkeypatch):
    # create_workspace() in packaged mode hard-codes
    # ~/Documents/JobTracker Hub as the parent for new "owned" tracker
    # folders (see ws_module._owned_siblings_dir) -- there is no env
    # var to redirect that. Left unpatched, this test would create a
    # real folder in the real home directory of whatever machine runs
    # the suite. Redirecting it here is a workaround for a real gap;
    # see NOTES.md.
    owned_dir = tmp_path / "owned-siblings"
    monkeypatch.setattr(ws_module, "_owned_siblings_dir", lambda: owned_dir)

    resp = client.post("/api/workspaces", json={"name": "Brand New Tracker"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["workspace"]["name"] == "Brand New Tracker"

    status = client.get("/api/status").json()
    assert status["workspace"]["name"] == "Brand New Tracker"
    assert status["index_built"] is True
    assert status["doc_count"] == 0  # brand new, empty Applications/ folder

    # Confirm it really did land under our redirected siblings dir, not
    # the real ~/Documents.
    created_roots = [
        w["root"] for w in ws_module._load_raw()["workspaces"].values()
        if w["name"] == "Brand New Tracker"
    ]
    assert created_roots and created_roots[0].startswith(str(owned_dir))
