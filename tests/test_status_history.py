"""
Tests for Item 7 v1's status_history table (overrides_store.py) and the
"Current status" half of the Timeline it powers (api.py's
application_dossier, save_override, bulk_override).

Two layers, same split as test_overrides_store.py / test_dossier.py:
  - direct unit tests against overrides_store.py's new functions, no
    FastAPI client needed (conftest.py already puts _app/ on sys.path).
  - end-to-end tests through the real API, using resolve_active() +
    overrides_store directly (see test_overrides_portability.py's
    pattern) wherever a test needs to inspect status_history rows the
    public API doesn't expose directly.

See docs/specs/ITEM7_TIMELINE_FDD_DRAFT.md: this table can only answer "when did
this become X" for changes made after it shipped -- a status set before
that (including anything already in a real tracker today) has no
recoverable date, and current_status_date/current_status_date_known
must say so honestly rather than guess.
"""

from __future__ import annotations

import sqlite3

import overrides_store as ov


# --- direct unit tests (overrides_store.py) ----------------------------------

def test_fresh_overrides_db_has_status_history_table(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "status_history" in tables


def test_append_and_get_status_history(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    ov.append_status_history(conn, "k1", "applied")
    history = ov.get_status_history(conn, "k1")
    assert len(history) == 1
    assert history[0]["status"] == "applied"
    assert history[0]["source"] == "manual"
    assert history[0]["changed_at"]


def test_repeated_save_of_same_status_does_not_duplicate_history(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    ov.append_status_history(conn, "k1", "applied")
    ov.append_status_history(conn, "k1", "applied")
    ov.append_status_history(conn, "k1", "applied")
    assert len(ov.get_status_history(conn, "k1")) == 1


def test_status_change_from_one_value_to_another_is_recorded(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    ov.append_status_history(conn, "k1", "applied")
    ov.append_status_history(conn, "k1", "interviewing")
    ov.append_status_history(conn, "k1", "rejected")
    history = ov.get_status_history(conn, "k1")
    assert [r["status"] for r in history] == ["applied", "interviewing", "rejected"]


def test_get_latest_status_change_returns_most_recent_matching_entry(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    ov.append_status_history(conn, "k1", "applied")
    ov.append_status_history(conn, "k1", "interviewing")
    ov.append_status_history(conn, "k1", "rejected")
    ov.append_status_history(conn, "k1", "interviewing")  # re-opened after rejection
    latest_interviewing = ov.get_latest_status_change(conn, "k1", "interviewing")
    latest_applied = ov.get_latest_status_change(conn, "k1", "applied")
    assert latest_interviewing["status"] == "interviewing"
    # It's the SECOND interviewing row, not the first -- confirm via count of
    # rows at-or-before it (id-ordering, see overrides_store.py).
    history = ov.get_status_history(conn, "k1")
    assert latest_interviewing["id"] == history[-1]["id"]
    assert latest_applied["id"] == history[0]["id"]


def test_get_latest_status_change_returns_none_when_never_recorded(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    assert ov.get_latest_status_change(conn, "k1", "rejected") is None
    ov.append_status_history(conn, "k1", "applied")
    # "applied" has history, but "rejected" specifically never happened.
    assert ov.get_latest_status_change(conn, "k1", "rejected") is None


def test_delete_status_history_removes_only_that_items_rows(tmp_path):
    conn = ov.get_conn(tmp_path / "overrides.db")
    ov.append_status_history(conn, "k1", "applied")
    ov.append_status_history(conn, "k2", "applied")
    ov.delete_status_history(conn, "k1")
    assert ov.get_status_history(conn, "k1") == []
    assert len(ov.get_status_history(conn, "k2")) == 1


def test_fresh_legacy_db_migration_does_not_break_on_status_history(tmp_path):
    # Same reasoning as test_overrides_store.py's migration test -- a
    # pre-Item-7 overrides.db has no status_history table at all; get_conn's
    # CREATE TABLE IF NOT EXISTS must add it without choking on the
    # pre-existing item_overrides rows.
    db_path = tmp_path / "legacy_overrides.db"
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        "CREATE TABLE item_overrides (item_key TEXT PRIMARY KEY, manual_status TEXT, updated_at TEXT)"
    )
    legacy.execute(
        "INSERT INTO item_overrides (item_key, manual_status, updated_at) VALUES (?, ?, ?)",
        ("applications|Acme|Role|x", "rejected", "2025-01-01T00:00:00+00:00"),
    )
    legacy.commit()
    legacy.close()

    conn = ov.get_conn(db_path)
    # The pre-existing "rejected" status has no history -- unknown date,
    # exactly as the FDD requires for statuses set before this shipped.
    assert ov.get_latest_status_change(conn, "applications|Acme|Role|x", "rejected") is None


# --- end-to-end tests (through the real API) ---------------------------------

def _make_application_folder(tmp_path, company="Acme Co", role="Backend Engineer"):
    root = tmp_path / "tracker"
    folder = root / "Applications" / company / role
    folder.mkdir(parents=True)
    return root, folder


def _find_item_id(client, company, role):
    apps = client.get("/api/applications").json()
    for a in apps:
        if a["company"] == company and a["role_label"] == role:
            return a["id"]
    raise AssertionError(f"No item found for {company}/{role} in {apps}")


def _item_key(db_path, item_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT item_key FROM items WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    return row["item_key"]


def test_dossier_current_status_with_no_override_shows_auto_status_and_unknown_date(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Auto Co", role="Support")
    (folder / "resume.txt").write_text("Jane Doe -- jane.doe@example.com")

    client.post("/api/workspaces/link", json={"name": "Auto Status Test", "path": str(root)})
    item_id = _find_item_id(client, "Auto Co", "Support")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    # No manual_status has ever been set -- auto-detected from documents
    # (resume-only -> "drafted", see classify.STATUS_PRIORITY) with no
    # status_history entry, since nothing has changed since this shipped.
    assert body["current_status"] == "drafted"
    assert body["current_status_date"] is None
    assert body["current_status_date_known"] is False


def test_dossier_current_status_after_manual_change_has_a_known_date(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Manual Co", role="Engineer")
    (folder / "resume.txt").write_text("Jane Doe -- jane.doe@example.com")

    client.post("/api/workspaces/link", json={"name": "Manual Status Test", "path": str(root)})
    item_id = _find_item_id(client, "Manual Co", "Engineer")

    r = client.post(f"/api/applications/{item_id}/override", json={"manual_status": "interviewing"})
    assert r.status_code == 200

    body = client.get(f"/api/applications/{item_id}/dossier").json()
    assert body["current_status"] == "interviewing"
    assert body["current_status_date_known"] is True
    assert body["current_status_date"] is not None
    assert len(body["current_status_date"]) == 10  # YYYY-MM-DD


def test_repeated_save_of_same_manual_status_does_not_duplicate_status_history(client, tmp_path, api_module):
    root, folder = _make_application_folder(tmp_path, company="Repeat Co", role="Analyst")
    (folder / "resume.txt").write_text("Jane Doe -- jane.doe@example.com")

    client.post("/api/workspaces/link", json={"name": "Repeat Status Test", "path": str(root)})
    item_id = _find_item_id(client, "Repeat Co", "Analyst")

    client.post(f"/api/applications/{item_id}/override", json={"manual_status": "interviewing"})
    client.post(f"/api/applications/{item_id}/override", json={"manual_status": "interviewing"})
    client.post(f"/api/applications/{item_id}/override", json={"manual_status": "interviewing"})

    root_p, db_path, ov_db_path, _entry = api_module.ws.resolve_active()
    item_key = _item_key(db_path, item_id)
    conn = ov.get_conn(ov_db_path)
    assert len(ov.get_status_history(conn, item_key)) == 1


def test_reset_status_is_recorded_as_a_transition_to_the_auto_status(client, tmp_path, api_module):
    root, folder = _make_application_folder(tmp_path, company="Reset Co", role="Writer")
    (folder / "resume.txt").write_text("Jane Doe -- jane.doe@example.com")

    client.post("/api/workspaces/link", json={"name": "Reset Status Test", "path": str(root)})
    item_id = _find_item_id(client, "Reset Co", "Writer")

    client.post(f"/api/applications/{item_id}/override", json={"manual_status": "rejected"})
    first = client.get(f"/api/applications/{item_id}/dossier").json()
    assert first["current_status"] == "rejected"
    assert first["current_status_date_known"] is True

    r = client.post(f"/api/applications/{item_id}/override", json={"reset_status": True})
    assert r.status_code == 200

    second = client.get(f"/api/applications/{item_id}/dossier").json()
    # Reverts to the auto-detected status (resume-only -> "drafted"), and
    # that reversion is itself a real, findable transition -- not a gap.
    assert second["current_status"] == "drafted"
    assert second["current_status_date_known"] is True

    root_p, db_path, ov_db_path, _entry = api_module.ws.resolve_active()
    item_key = _item_key(db_path, item_id)
    conn = ov.get_conn(ov_db_path)
    history = ov.get_status_history(conn, item_key)
    assert [r["status"] for r in history] == ["rejected", "drafted"]


def test_bulk_override_status_change_recorded_per_item(client, tmp_path, api_module):
    root, folder_a = _make_application_folder(tmp_path, company="Bulk A", role="Role A")
    (folder_a / "resume.txt").write_text("A")
    folder_b = root / "Applications" / "Bulk B" / "Role B"
    folder_b.mkdir(parents=True)
    (folder_b / "resume.txt").write_text("B")

    client.post("/api/workspaces/link", json={"name": "Bulk Status Test", "path": str(root)})
    id_a = _find_item_id(client, "Bulk A", "Role A")
    id_b = _find_item_id(client, "Bulk B", "Role B")

    r = client.post(
        "/api/applications/bulk-override",
        json={"item_ids": [id_a, id_b], "manual_status": "rejected"},
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2

    for item_id in (id_a, id_b):
        body = client.get(f"/api/applications/{item_id}/dossier").json()
        assert body["current_status"] == "rejected"
        assert body["current_status_date_known"] is True


def test_deleting_an_application_clears_its_status_history(client, tmp_path, api_module):
    root, folder = _make_application_folder(tmp_path, company="Delete Co", role="Analyst")
    (folder / "resume.txt").write_text("Jane Doe -- jane.doe@example.com")

    client.post("/api/workspaces/link", json={"name": "Delete Status Test", "path": str(root)})
    item_id = _find_item_id(client, "Delete Co", "Analyst")
    client.post(f"/api/applications/{item_id}/override", json={"manual_status": "interviewing"})

    root_p, db_path, ov_db_path, _entry = api_module.ws.resolve_active()
    item_key = _item_key(db_path, item_id)
    conn = ov.get_conn(ov_db_path)
    assert len(ov.get_status_history(conn, item_key)) == 1
    conn.close()

    r = client.post(f"/api/applications/{item_id}/delete")
    assert r.status_code == 200

    # No ghost row left behind for an item_key that no longer exists
    # anywhere -- same guarantee delete_override already provides for
    # item_overrides (see api.py's _delete_application).
    conn = ov.get_conn(ov_db_path)
    assert ov.get_status_history(conn, item_key) == []
