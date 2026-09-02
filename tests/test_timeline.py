"""
Tests for Item 7 v1's doc-derived Timeline events: one entry per
application_confirmation or interview_notice document that has a
detected date (see dossier.py's TIMELINE_EVENT_DOC_TYPES and
docs/specs/ITEM7_TIMELINE_FDD_DRAFT.md's "v1 scope"). Exercised end-to-end through
the real API/index/extraction stack, same pattern as test_dossier.py.

Deliberately NOT covered here: the "Current status" entry (that's
item-level, backed by status_history -- see test_status_history.py).
"""

from __future__ import annotations


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


def test_confirmation_event_extraction(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Confirm Co", role="Analyst")
    (folder / "Thank you for applying.txt").write_text(
        "Date: July 10, 2025 at 10:56 AM\nThanks for applying.\n"
    )

    client.post("/api/workspaces/link", json={"name": "Confirm Event Test", "path": str(root)})
    item_id = _find_item_id(client, "Confirm Co", "Analyst")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert len(body["timeline_events"]) == 1
    event = body["timeline_events"][0]
    assert event["date"] == "2025-07-10"
    assert event["doc_type"] == "application_confirmation"
    assert event["relpath"].endswith("Thank you for applying.txt")


def test_interview_event_extraction(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Interview Co", role="Engineer")
    (folder / "Interview Request.txt").write_text(
        "Date: August 20, 2025 at 1:50 PM\nWe'd like to schedule an interview.\n"
    )

    client.post("/api/workspaces/link", json={"name": "Interview Event Test", "path": str(root)})
    item_id = _find_item_id(client, "Interview Co", "Engineer")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert len(body["timeline_events"]) == 1
    event = body["timeline_events"][0]
    assert event["date"] == "2025-08-20"
    assert event["doc_type"] == "interview_notice"
    assert event["relpath"].endswith("Interview Request.txt")


def test_multiple_interview_notices_each_produce_their_own_event(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Magnite", role="SWE")
    (folder / "Phone Screen Request.txt").write_text(
        "Date: August 1, 2025 at 5:51 AM\nCan we set up a phone screen?\n"
    )
    (folder / "Interview Request.txt").write_text(
        "Date: August 20, 2025 at 1:50 PM\nLet's schedule your interview.\n"
    )

    client.post("/api/workspaces/link", json={"name": "Multi Interview Test", "path": str(root)})
    item_id = _find_item_id(client, "Magnite", "SWE")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    # Two separate interview_notice documents -> two separate events, never
    # merged into one -- see dossier.py module docstring.
    assert len(body["timeline_events"]) == 2
    assert all(e["doc_type"] == "interview_notice" for e in body["timeline_events"])
    assert [e["date"] for e in body["timeline_events"]] == ["2025-08-01", "2025-08-20"]


def test_events_sort_chronologically_across_doc_types(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Chrono Inc", role="Writer")
    # Confirmation dated AFTER the interview notice -- events must still
    # come out in date order, not doc-type-priority order.
    (folder / "Interview Request.txt").write_text(
        "Date: August 1, 2025 at 9:00 AM\nLet's schedule your interview.\n"
    )
    (folder / "Thank you for applying.txt").write_text(
        "Date: July 10, 2025 at 10:56 AM\nThanks for applying.\n"
    )

    client.post("/api/workspaces/link", json={"name": "Chrono Test", "path": str(root)})
    item_id = _find_item_id(client, "Chrono Inc", "Writer")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert [e["doc_type"] for e in body["timeline_events"]] == [
        "application_confirmation",
        "interview_notice",
    ]
    assert [e["date"] for e in body["timeline_events"]] == ["2025-07-10", "2025-08-01"]


def test_same_date_events_break_ties_deterministically_confirmation_first(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Tie Co", role="Analyst")
    (folder / "Interview Request.txt").write_text(
        "Date: July 10, 2025 at 9:00 AM\nLet's schedule your interview.\n"
    )
    (folder / "Thank you for applying.txt").write_text(
        "Date: July 10, 2025 at 10:56 AM\nThanks for applying.\n"
    )

    client.post("/api/workspaces/link", json={"name": "Tie Test", "path": str(root)})
    item_id = _find_item_id(client, "Tie Co", "Analyst")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert len(body["timeline_events"]) == 2
    assert body["timeline_events"][0]["date"] == body["timeline_events"][1]["date"] == "2025-07-10"
    assert [e["doc_type"] for e in body["timeline_events"]] == [
        "application_confirmation",
        "interview_notice",
    ]


def test_no_dated_evidence_produces_an_empty_timeline(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Blank Co", role="Support")
    (folder / "resume.txt").write_text("Jane Doe -- jane.doe@example.com")
    (folder / "coverletter.txt").write_text("No dates anywhere in this document.")

    client.post("/api/workspaces/link", json={"name": "Blank Timeline Test", "path": str(root)})
    item_id = _find_item_id(client, "Blank Co", "Support")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert body["timeline_events"] == []


def test_timeline_events_present_alongside_existing_checkpoint6_autofill(client, tmp_path):
    """A confirmation document should populate BOTH the pre-existing
    Checkpoint 6 date_applied auto-fill AND the new timeline_events list
    from the same single request -- Item 7 adds to the dossier payload
    without disturbing what Checkpoint 6 already does with it."""
    root, folder = _make_application_folder(tmp_path, company="Both Co", role="PM")
    (folder / "Thank you for applying.txt").write_text(
        "Date: July 10, 2025 at 10:56 AM\nThanks for applying.\n"
    )

    client.post("/api/workspaces/link", json={"name": "Both Test", "path": str(root)})
    item_id = _find_item_id(client, "Both Co", "PM")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert body["date_applied_auto_filled"] is True
    assert body["detected_date_applied"] == "2025-07-10"
    assert len(body["timeline_events"]) == 1
    assert body["timeline_events"][0]["date"] == "2025-07-10"
