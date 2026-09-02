"""
/api/workspaces/inspect -- the read-only folder preview shown before a
user commits to linking/importing it (first-run.html and the in-app
"Link existing folder" flow). See workspace.inspect_folder's docstring
for the full shape of the response.
"""

from __future__ import annotations


def test_inspect_missing_folder_is_reported_not_raised(client, tmp_path):
    missing = tmp_path / "does-not-exist"
    resp = client.post("/api/workspaces/inspect", json={"path": str(missing)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["exists"] is False
    assert body["error"]


def test_inspect_rejects_a_file_not_a_folder(client, tmp_path):
    a_file = tmp_path / "not-a-folder.txt"
    a_file.write_text("hello")
    resp = client.post("/api/workspaces/inspect", json={"path": str(a_file)})
    body = resp.json()
    assert body["exists"] is False
    assert body["error"]


def test_inspect_empty_folder(client, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    body = client.post("/api/workspaces/inspect", json={"path": str(empty)}).json()
    assert body["exists"] is True
    assert body["error"] is None
    assert body["is_empty"] is True
    assert body["file_count"] == 0
    assert body["looks_like_tracker"] is False
    assert body["has_portable_overrides"] is False
    assert body["already_linked"] is False


def test_inspect_recognizes_tracker_shaped_folder(client, sample_root):
    # sample_root fixture has an Applications/<Company>/<Role>/ tree --
    # a top-level folder name build_index.py's own SECTION_RULES match.
    body = client.post("/api/workspaces/inspect", json={"path": str(sample_root)}).json()
    assert body["exists"] is True
    assert body["is_empty"] is False
    assert body["looks_like_tracker"] is True
    assert body["file_count"] == 2  # resume.pdf + coverletter.txt
    assert body["has_portable_overrides"] is False


def test_inspect_flags_unrecognized_but_nonempty_folder(client, tmp_path):
    random_stuff = tmp_path / "random"
    (random_stuff / "some_subfolder").mkdir(parents=True)
    (random_stuff / "some_subfolder" / "notes.txt").write_text("hi")
    body = client.post("/api/workspaces/inspect", json={"path": str(random_stuff)}).json()
    assert body["exists"] is True
    assert body["is_empty"] is False
    assert body["looks_like_tracker"] is False
    assert body["file_count"] == 1


def test_inspect_detects_existing_portable_overrides(client, sample_root):
    ov_dir = sample_root / ".jobtracker"
    ov_dir.mkdir()
    (ov_dir / "overrides.db").write_bytes(b"")
    body = client.post("/api/workspaces/inspect", json={"path": str(sample_root)}).json()
    assert body["has_portable_overrides"] is True
    # The hidden .jobtracker/ folder itself must never count toward the
    # visible file count -- should_ignore() skips dot-prefixed names.
    assert body["file_count"] == 2


def test_inspect_flags_already_linked_folder(client, sample_root):
    link_resp = client.post(
        "/api/workspaces/link", json={"name": "Already Linked", "path": str(sample_root)}
    )
    assert link_resp.status_code == 200

    body = client.post("/api/workspaces/inspect", json={"path": str(sample_root)}).json()
    assert body["already_linked"] is True
    assert body["already_linked_name"] == "Already Linked"


def test_inspect_does_not_flag_a_different_folder_as_linked(client, sample_root, tmp_path):
    client.post("/api/workspaces/link", json={"name": "Tracker One", "path": str(sample_root)})

    other = tmp_path / "unrelated"
    other.mkdir()
    body = client.post("/api/workspaces/inspect", json={"path": str(other)}).json()
    assert body["already_linked"] is False


def test_inspect_caps_file_count_on_a_huge_folder(client, tmp_path, ws_module, monkeypatch):
    monkeypatch.setattr(ws_module, "_INSPECT_FILE_SCAN_CAP", 5)
    huge = tmp_path / "huge"
    huge.mkdir()
    for i in range(20):
        (huge / f"file_{i}.txt").write_text("x")

    body = client.post("/api/workspaces/inspect", json={"path": str(huge)}).json()
    assert body["file_count"] == 5
    assert body["capped"] is True


def test_inspect_flags_the_jobtracker_folder_itself_as_internal_conflict(client, sample_root):
    # Selecting a tracker's own internal storage folder in the picker
    # (e.g. hidden files shown in Finder, one click too deep) must be
    # flagged, not silently treated as a normal empty folder. See
    # docs/archive/handoffs/HANDOFF_SESSION16_LEGACY.md §3i / §3j.5.
    dot_dir = sample_root / ".jobtracker"
    dot_dir.mkdir()
    body = client.post("/api/workspaces/inspect", json={"path": str(dot_dir)}).json()
    assert body["exists"] is True
    assert body["internal_conflict"]
    assert "internal data folder" in body["internal_conflict"]


def test_inspect_flags_any_folder_nested_inside_an_existing_tracker(client, sample_root, tmp_path):
    client.post("/api/workspaces/link", json={"name": "Parent Tracker", "path": str(sample_root)})

    nested = sample_root / "Applications"
    body = client.post("/api/workspaces/inspect", json={"path": str(nested)}).json()
    assert body["internal_conflict"]
    assert "Parent Tracker" in body["internal_conflict"]


def test_inspect_does_not_flag_the_tracker_root_itself(client, sample_root):
    # Being an already-linked root is a separate concern (already_linked)
    # -- linking the exact same folder again isn't a "nested inside
    # itself" conflict.
    client.post("/api/workspaces/link", json={"name": "Self", "path": str(sample_root)})
    body = client.post("/api/workspaces/inspect", json={"path": str(sample_root)}).json()
    assert body["internal_conflict"] is None
    assert body["already_linked"] is True


def test_inspect_does_not_flag_an_unrelated_folder(client, sample_root, tmp_path):
    client.post("/api/workspaces/link", json={"name": "Some Tracker", "path": str(sample_root)})
    other = tmp_path / "unrelated"
    other.mkdir()
    body = client.post("/api/workspaces/inspect", json={"path": str(other)}).json()
    assert body["internal_conflict"] is None


def test_workspace_list_includes_kind_and_overrides_flag(client, sample_root):
    entry = client.post(
        "/api/workspaces/link", json={"name": "My Job Search", "path": str(sample_root)}
    ).json()["workspace"]

    listed = client.get("/api/workspaces").json()["workspaces"]
    match = next(w for w in listed if w["id"] == entry["id"])
    assert match["kind"] == "linked"
    assert match["has_portable_overrides"] is False

    # Touching overrides.db at all -- even a plain read -- creates it
    # lazily inside the linked folder (see overrides_store.get_conn).
    # The list should reflect that on the next call without needing a
    # rebuild.
    client.get("/api/applications")

    listed_again = client.get("/api/workspaces").json()["workspaces"]
    match_again = next(w for w in listed_again if w["id"] == entry["id"])
    assert match_again["has_portable_overrides"] is True


def test_status_workspace_includes_kind_and_overrides_flag(client, sample_root):
    client.post("/api/workspaces/link", json={"name": "My Job Search", "path": str(sample_root)})
    status = client.get("/api/status").json()
    assert status["workspace"]["kind"] == "linked"
    assert status["workspace"]["has_portable_overrides"] is False
