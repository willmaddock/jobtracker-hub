"""Search Hub settings (role, location, custom link overrides, custom
cards) used to live only in browser localStorage -- device-local and
tied to one browser profile. They're now persisted server-side in the
same overrides.db every other piece of your data lives in, via
GET/POST /api/hub/settings and overrides_store.get_hub_settings /
set_hub_settings. See the comments at the top of SearchHubPage in
_app/frontend/index.html for the frontend half of this.

These tests need an active, linked workspace first -- /api/hub/settings
reads/writes the *active* workspace's overrides.db, same as notes and
manual statuses do (see get_conns() in api.py).
"""

from __future__ import annotations


def _link(client, sample_root, name="Hub Settings"):
    return client.post(
        "/api/workspaces/link", json={"name": name, "path": str(sample_root)}
    ).json()["workspace"]


def test_hub_settings_defaults_are_empty_before_anything_is_saved(client, sample_root):
    _link(client, sample_root)
    resp = client.get("/api/hub/settings")
    assert resp.status_code == 200
    assert resp.json() == {
        "role": "",
        "location": "",
        "custom_links": {},
        "custom_cards": {},
    }


def test_saving_role_does_not_clobber_previously_saved_location(client, sample_root):
    _link(client, sample_root)
    client.post("/api/hub/settings", json={"location": "Denver, CO"})
    resp = client.post("/api/hub/settings", json={"role": "Backend Engineer"})
    assert resp.status_code == 200
    body = resp.json()
    # This is the whole point of the partial-merge shape in
    # set_hub_settings: the frontend only ever sends the one field the
    # user just edited (debounced per-keystroke), so a role save must
    # not wipe out a location saved moments earlier.
    assert body["role"] == "Backend Engineer"
    assert body["location"] == "Denver, CO"

    refetched = client.get("/api/hub/settings").json()
    assert refetched["role"] == "Backend Engineer"
    assert refetched["location"] == "Denver, CO"


def test_custom_link_override_round_trips(client, sample_root):
    _link(client, sample_root)
    override = {"Handshake": {"title": "My Handshake", "url": "https://example.com/h"}}
    resp = client.post("/api/hub/settings", json={"custom_links": override})
    assert resp.status_code == 200
    assert resp.json()["custom_links"] == override
    assert client.get("/api/hub/settings").json()["custom_links"] == override


def test_custom_link_override_can_be_cleared_back_to_empty(client, sample_root):
    _link(client, sample_root)
    client.post(
        "/api/hub/settings",
        json={"custom_links": {"Handshake": {"url": "https://example.com/h"}}},
    )
    resp = client.post("/api/hub/settings", json={"custom_links": {}})
    assert resp.status_code == 200
    assert resp.json()["custom_links"] == {}


def test_custom_cards_persist_keyed_by_category(client, sample_root):
    _link(client, sample_root)
    cards = {
        "mainstream": [
            {"id": "c1", "title": "My Recruiter's Portal", "url": "https://example.com", "note": ""},
        ]
    }
    resp = client.post("/api/hub/settings", json={"custom_cards": cards})
    assert resp.status_code == 200
    assert resp.json()["custom_cards"] == cards
    assert client.get("/api/hub/settings").json()["custom_cards"] == cards


def test_unrecognized_fields_in_the_request_body_are_ignored(client, sample_root):
    # update_hub_settings() filters the incoming dict down to the
    # allowed set (role/location/custom_links/custom_cards) before
    # handing it to set_hub_settings -- this locks in that an unknown
    # key can't reach the DB layer or blow up the request.
    _link(client, sample_root)
    resp = client.post(
        "/api/hub/settings", json={"role": "PM", "not_a_real_field": "whatever"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "PM"
    assert "not_a_real_field" not in body


def test_hub_settings_are_isolated_per_workspace(client, sample_root, tmp_path):
    entry_a = _link(client, sample_root, name="Tracker A")
    client.post("/api/hub/settings", json={"role": "Tracker A role"})

    other_root = tmp_path / "other-tracker"
    (other_root / "Applications").mkdir(parents=True)
    (other_root / "Applications" / "note.txt").write_text("hi")
    entry_b = client.post(
        "/api/workspaces/link", json={"name": "Tracker B", "path": str(other_root)}
    ).json()["workspace"]

    # Switching active workspace should not carry Tracker A's hub
    # settings along -- each tracker's overrides.db (and therefore its
    # hub_settings row) is independent, same as notes/statuses are.
    assert client.get("/api/hub/settings").json()["role"] == ""

    client.post("/api/hub/settings", json={"role": "Tracker B role"})
    client.post("/api/workspaces/switch", json={"id": entry_a["id"]})
    assert client.get("/api/hub/settings").json()["role"] == "Tracker A role"

    client.post("/api/workspaces/switch", json={"id": entry_b["id"]})
    assert client.get("/api/hub/settings").json()["role"] == "Tracker B role"
