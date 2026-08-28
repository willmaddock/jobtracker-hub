"""
Notes/status/dates (overrides.db) used to live in this app's own private
storage, keyed only by workspace id -- completely disconnected from the
tracker folder itself. That meant unlinking and relinking the exact same
folder, or exporting a tracker and reimporting it, silently started your
notes over from scratch.

overrides.db now lives inside the workspace's own root, under a hidden
.jobtracker/ folder (see workspace._portable_ov_db_path), so it travels
with the folder automatically. These tests cover the three ways that
used to lose data: relink, legacy-path migration, and export/import.
"""

from __future__ import annotations

import io
import zipfile


def test_unlinking_and_relinking_the_same_folder_keeps_notes(client, sample_root, api_module):
    ws = api_module.ws
    import overrides_store as ov

    entry = client.post(
        "/api/workspaces/link", json={"name": "Keeps Notes", "path": str(sample_root)}
    ).json()["workspace"]

    ov_db_path = sample_root / ".jobtracker" / "overrides.db"
    assert ov_db_path.parent.parent == sample_root

    conn = ov.get_conn(ws.resolve_active()[2])
    conn.execute(
        "INSERT INTO item_overrides (item_key, notes, updated_at) VALUES (?,?,?)",
        ("Acme Co||Backend Engineer", "waiting to hear back", ov.now_iso()),
    )
    conn.commit()
    conn.close()
    assert ov_db_path.exists()

    # Unlink: registry entry gone, but the folder (and its hidden
    # .jobtracker/overrides.db) must survive untouched.
    resp = client.delete(f"/api/workspaces/{entry['id']}")
    assert resp.status_code == 200
    assert ov_db_path.exists()

    # Relink the same folder as a brand-new workspace id.
    entry2 = client.post(
        "/api/workspaces/link", json={"name": "Keeps Notes Again", "path": str(sample_root)}
    ).json()["workspace"]
    assert entry2["id"] != entry["id"]

    conn2 = ov.get_conn(ws.resolve_active()[2])
    row = conn2.execute(
        "SELECT notes FROM item_overrides WHERE item_key=?", ("Acme Co||Backend Engineer",)
    ).fetchone()
    conn2.close()
    assert row is not None
    assert row["notes"] == "waiting to hear back"


def test_legacy_overrides_db_is_migrated_into_the_tracker_folder(client, sample_root, ws_module, api_module):
    import overrides_store as ov

    entry = client.post(
        "/api/workspaces/link", json={"name": "Legacy", "path": str(sample_root)}
    ).json()["workspace"]

    # Simulate a registry entry saved before overrides.db became portable:
    # point ov_db_path back at the old external location and put real,
    # pre-upgrade data there.
    data = ws_module._load_raw()
    old_dir = ws_module.WORKSPACES_DB_DIR / entry["id"]
    old_dir.mkdir(parents=True, exist_ok=True)
    old_path = old_dir / "overrides.db"
    legacy_conn = ov.get_conn(old_path)
    legacy_conn.execute(
        "INSERT INTO item_overrides (item_key, notes, updated_at) VALUES (?,?,?)",
        ("Acme Co||Backend Engineer", "pre-upgrade note", ov.now_iso()),
    )
    legacy_conn.commit()
    legacy_conn.close()
    data["workspaces"][entry["id"]]["ov_db_path"] = str(old_path)
    ws_module._save_raw(data)

    # The next status check (any read through resolve_active) should
    # migrate the file automatically -- no explicit "migrate" step, no
    # user-visible prompt.
    status = client.get("/api/status").json()
    assert status["workspace"]["id"] == entry["id"]

    new_path = sample_root / ".jobtracker" / "overrides.db"
    assert new_path.exists()
    assert not old_path.exists()

    conn = ov.get_conn(new_path)
    row = conn.execute(
        "SELECT notes FROM item_overrides WHERE item_key=?", ("Acme Co||Backend Engineer",)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["notes"] == "pre-upgrade note"


def test_export_then_import_round_trips_notes_and_status(client, sample_root, api_module):
    import overrides_store as ov

    entry = client.post(
        "/api/workspaces/link", json={"name": "Round Trip", "path": str(sample_root)}
    ).json()["workspace"]

    conn = ov.get_conn(api_module.ws.resolve_active()[2])
    conn.execute(
        "INSERT INTO item_overrides (item_key, manual_status, notes, updated_at) VALUES (?,?,?,?)",
        ("Acme Co||Backend Engineer", "interviewing", "exported note", ov.now_iso()),
    )
    conn.commit()
    conn.close()

    export_resp = client.get(f"/api/workspaces/{entry['id']}/export")
    assert export_resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(export_resp.content))
    assert ".jobtracker/overrides.db" in zf.namelist()

    import_resp = client.post(
        "/api/workspaces/import",
        data={"name": "Reimported"},
        files={"file": ("export.zip", export_resp.content, "application/zip")},
    )
    assert import_resp.status_code == 200
    imported_id = import_resp.json()["workspace"]["id"]
    assert imported_id != entry["id"]

    status = client.get("/api/status").json()
    assert status["workspace"]["id"] == imported_id

    conn2 = ov.get_conn(api_module.ws.resolve_active()[2])
    row = conn2.execute(
        "SELECT manual_status, notes FROM item_overrides WHERE item_key=?",
        ("Acme Co||Backend Engineer",),
    ).fetchone()
    conn2.close()
    assert row is not None
    assert row["notes"] == "exported note"
    assert row["manual_status"] == "interviewing"


def test_export_then_import_round_trips_hub_settings(client, sample_root):
    # hub_settings lives in the same overrides.db as notes/statuses (see
    # test_hub_settings.py for the dedicated coverage of the endpoint
    # itself) -- this just confirms it travels through export/import
    # the same way, since that's the whole reason it was moved out of
    # localStorage in the first place.
    entry = client.post(
        "/api/workspaces/link", json={"name": "Hub Round Trip", "path": str(sample_root)}
    ).json()["workspace"]

    client.post("/api/hub/settings", json={"role": "Backend Engineer", "location": "Denver, CO"})

    export_resp = client.get(f"/api/workspaces/{entry['id']}/export")
    assert export_resp.status_code == 200

    import_resp = client.post(
        "/api/workspaces/import",
        data={"name": "Hub Reimported"},
        files={"file": ("export.zip", export_resp.content, "application/zip")},
    )
    assert import_resp.status_code == 200

    settings = client.get("/api/hub/settings").json()
    assert settings["role"] == "Backend Engineer"
    assert settings["location"] == "Denver, CO"
