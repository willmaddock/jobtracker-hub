"""
Tests for /api/applications/{item_id}/dossier -- Checkpoint 3 (Application
Dossier assembly). See dossier.py's module docstring for the job-posting
tiebreak rule and contact-aggregation behavior this exercises end-to-end
through the real API/index/extraction stack (link -> rebuild -> dossier).

Doc-type classification (classify.POSTING_RE) keys off the FILENAME, so
every fixture here names its "job posting" file with a substring that
regex matches (e.g. "Job Description ...txt") rather than relying on
sample_root's generic resume.pdf/coverletter.txt, which never classify
as job_posting.
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


def test_dossier_happy_path_merges_contacts_and_uses_job_posting_role_sections(client, tmp_path):
    root, folder = _make_application_folder(tmp_path)
    (folder / "Job Description.txt").write_text(
        "Job Description\n"
        "Build and maintain backend services.\n"
        "Responsibilities\n"
        "Design APIs and review code.\n"
        "Qualifications\n"
        "3+ years of Python experience.\n"
        "Desired\n"
        "Familiarity with FastAPI.\n"
    )
    (folder / "resume.txt").write_text("Jane Doe -- jane.doe@example.com")
    (folder / "coverletter.txt").write_text("Reach me at 303-555-1234 or via recruiter@acme.com.")

    resp = client.post("/api/workspaces/link", json={"name": "Dossier Test", "path": str(root)})
    assert resp.status_code == 200

    item_id = _find_item_id(client, "Acme Co", "Backend Engineer")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert body["job_posting_relpath"].endswith("Job Description.txt")
    assert body["job_posting_candidates"] == [body["job_posting_relpath"]]
    assert "Build and maintain backend services" in body["role_summary"]
    assert "Design APIs" in body["duties"]
    assert "3+ years of Python" in body["required_qualifications"]
    assert "FastAPI" in body["preferred_qualifications"]

    # Contacts merged (deduped) across resume + cover letter + posting.
    assert "jane.doe@example.com" in body["contacts"]["emails"]
    assert "recruiter@acme.com" in body["contacts"]["emails"]
    assert any("303" in p for p in body["contacts"]["phones"])
    assert body["extraction_errors"] == []


def test_dossier_with_no_job_posting_document_reports_not_detected(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Beta Inc", role="QA Analyst")
    (folder / "resume.txt").write_text("Contact: qa.candidate@example.com")
    (folder / "coverletter.txt").write_text("No headers here at all.")

    client.post("/api/workspaces/link", json={"name": "No Posting Test", "path": str(root)})
    item_id = _find_item_id(client, "Beta Inc", "QA Analyst")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert body["job_posting_relpath"] is None
    assert body["job_posting_candidates"] == []
    assert body["role_summary"] == "Not detected"
    assert body["duties"] == "Not detected"
    assert body["required_qualifications"] == "Not detected"
    assert body["preferred_qualifications"] == "Not detected"
    # Contacts still gathered from whatever documents ARE present.
    assert "qa.candidate@example.com" in body["contacts"]["emails"]


def test_dossier_with_multiple_job_postings_picks_alphabetically_first_relpath(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Gamma LLC", role="Data Analyst")
    # "A" sorts before "B" -- ALPHA's role sections should win.
    (folder / "Job Description A.txt").write_text(
        "Job Description\nALPHA_POSTING summary.\n"
        "Responsibilities\nALPHA duties.\n"
        "Qualifications\nALPHA quals.\n"
    )
    (folder / "Job Description B.txt").write_text(
        "Job Description\nBETA_POSTING summary.\n"
        "Responsibilities\nBETA duties.\n"
        "Qualifications\nBETA quals.\n"
    )

    client.post("/api/workspaces/link", json={"name": "Multi Posting Test", "path": str(root)})
    item_id = _find_item_id(client, "Gamma LLC", "Data Analyst")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert body["job_posting_relpath"].endswith("Job Description A.txt")
    assert len(body["job_posting_candidates"]) == 2
    assert body["job_posting_candidates"][0].endswith("Job Description A.txt")
    assert body["job_posting_candidates"][1].endswith("Job Description B.txt")
    assert "ALPHA_POSTING" in body["role_summary"]
    assert "BETA_POSTING" not in body["role_summary"]
    assert "ALPHA duties" in body["duties"]


def test_dossier_unknown_item_id_returns_404(client, sample_root):
    client.post("/api/workspaces/link", json={"name": "Basic", "path": str(sample_root)})
    resp = client.get("/api/applications/99999/dossier")
    assert resp.status_code == 404


# --- Checkpoint 5: date-applied evidence -------------------------------------

def test_dossier_detects_date_from_application_confirmation_email(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Extend Co", role="Data Scientist")
    (folder / "Thank you for applying to Extend.txt").write_text(
        "From: no-reply@us.greenhouse-mail.io\n"
        "Subject: Thank you for applying to Extend\n"
        "Date: July 10, 2025 at 10:56 AM\n"
        "To: candidate@example.com\n"
        "Thanks for applying to Extend.\n"
    )
    (folder / "resume.txt").write_text("Jane Doe -- jane.doe@example.com")

    client.post("/api/workspaces/link", json={"name": "Date Evidence Test", "path": str(root)})
    item_id = _find_item_id(client, "Extend Co", "Data Scientist")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert body["detected_date_applied"] == "2025-07-10"
    assert body["detected_date_source_relpath"].endswith("Thank you for applying to Extend.txt")


def test_dossier_prefers_confirmation_date_over_job_posting_date(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Delta LLC", role="Platform Engineer")
    (folder / "Job Description.txt").write_text(
        "Date: January 1, 2025 at 9:00 AM\nJob Description\nBuild things.\n"
    )
    (folder / "Thank you for applying.txt").write_text(
        "Date: July 10, 2025 at 10:56 AM\nThanks for applying.\n"
    )

    client.post("/api/workspaces/link", json={"name": "Priority Test", "path": str(root)})
    item_id = _find_item_id(client, "Delta LLC", "Platform Engineer")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    # application_confirmation beats job_posting even though the posting's
    # own date would sort earlier -- see dossier.py's DATE_EVIDENCE_DOC_TYPES.
    assert body["detected_date_applied"] == "2025-07-10"
    assert body["detected_date_source_relpath"].endswith("Thank you for applying.txt")


def test_dossier_with_no_detectable_date_reports_none(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Epsilon Inc", role="Support Rep")
    (folder / "resume.txt").write_text("Jane Doe -- jane.doe@example.com")
    (folder / "coverletter.txt").write_text("No dates anywhere in this document.")

    client.post("/api/workspaces/link", json={"name": "No Date Test", "path": str(root)})
    item_id = _find_item_id(client, "Epsilon Inc", "Support Rep")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert body["detected_date_applied"] is None
    assert body["detected_date_source_relpath"] is None


# --- Checkpoint 6: auto-fill vs. suggest, split by evidence tier -------------
#
# Rule under test (see api.py's application_dossier docstring):
#   - date_applied unset + confirmation-tier evidence -> auto-filled, silently
#   - date_applied unset + posting-tier evidence only -> stays unset, suggested
#   - date_applied already set (typed or auto-filled) -> NEVER touched again,
#     regardless of what's later detected
#
# _find_item_id's return value is stable across a plain GET, but rebuilds
# reset item.id -- these tests all use /api/rebuild (not another /link)
# to refresh the index in place, since re-linking under a new name would
# also register a second, unrelated workspace.

def test_empty_date_applied_plus_confirmation_date_auto_fills(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Zeta Corp", role="Analyst")
    (folder / "Thank you for applying.txt").write_text(
        "Date: July 10, 2025 at 10:56 AM\nThanks for applying.\n"
    )

    client.post("/api/workspaces/link", json={"name": "Auto Fill Test", "path": str(root)})
    item_id = _find_item_id(client, "Zeta Corp", "Analyst")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert body["detected_date_evidence_tier"] == "confirmation"
    assert body["date_applied_auto_filled"] is True

    apps = client.get("/api/applications").json()
    app = next(a for a in apps if a["id"] == item_id)
    assert app["date_applied"] == "2025-07-10"
    assert app["date_applied_source"] == "confirmation"


def test_empty_date_applied_plus_posting_only_date_stays_unset_and_suggests(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Eta LLC", role="Recruiter")
    (folder / "Job Description.txt").write_text(
        "Date: January 1, 2025 at 9:00 AM\nJob Description\nBuild things.\n"
    )

    client.post("/api/workspaces/link", json={"name": "Posting Only Test", "path": str(root)})
    item_id = _find_item_id(client, "Eta LLC", "Recruiter")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert body["detected_date_evidence_tier"] == "posting"
    assert body["detected_date_applied"] == "2025-01-01"
    assert body["date_applied_auto_filled"] is False

    apps = client.get("/api/applications").json()
    app = next(a for a in apps if a["id"] == item_id)
    assert app["date_applied"] is None
    assert app["date_applied_source"] is None


def test_existing_date_plus_different_confirmation_date_is_preserved_not_overwritten(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Theta Inc", role="Designer")
    (folder / "Thank you for applying.txt").write_text(
        "Date: July 10, 2025 at 10:56 AM\nThanks for applying.\n"
    )

    client.post("/api/workspaces/link", json={"name": "Preserve Test", "path": str(root)})
    item_id = _find_item_id(client, "Theta Inc", "Designer")

    # User already typed their own date before ever opening the dossier.
    r = client.post(f"/api/applications/{item_id}/override", json={"date_applied": "2025-06-01"})
    assert r.status_code == 200

    body = client.get(f"/api/applications/{item_id}/dossier").json()
    assert body["detected_date_applied"] == "2025-07-10"
    assert body["date_applied_auto_filled"] is False  # already set -- never touched

    apps = client.get("/api/applications").json()
    app = next(a for a in apps if a["id"] == item_id)
    assert app["date_applied"] == "2025-06-01"  # untouched
    assert app["date_applied_source"] is None    # manual, no stale label


def test_existing_date_matching_detected_date_produces_no_conflict_signal(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Iota Co", role="Writer")
    (folder / "Thank you for applying.txt").write_text(
        "Date: July 10, 2025 at 10:56 AM\nThanks for applying.\n"
    )

    client.post("/api/workspaces/link", json={"name": "Match Test", "path": str(root)})
    item_id = _find_item_id(client, "Iota Co", "Writer")
    client.post(f"/api/applications/{item_id}/override", json={"date_applied": "2025-07-10"})

    body = client.get(f"/api/applications/{item_id}/dossier").json()
    assert body["detected_date_applied"] == "2025-07-10"
    assert body["date_applied_auto_filled"] is False

    apps = client.get("/api/applications").json()
    app = next(a for a in apps if a["id"] == item_id)
    assert app["date_applied"] == "2025-07-10"


def test_auto_filled_date_is_preserved_when_a_later_detected_date_differs(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Kappa Ltd", role="Engineer")
    conf = folder / "Thank you for applying.txt"
    conf.write_text("Date: July 10, 2025 at 10:56 AM\nThanks for applying.\n")

    client.post("/api/workspaces/link", json={"name": "Auto Then Change Test", "path": str(root)})
    item_id = _find_item_id(client, "Kappa Ltd", "Engineer")

    first = client.get(f"/api/applications/{item_id}/dossier").json()
    assert first["date_applied_auto_filled"] is True
    apps = client.get("/api/applications").json()
    app = next(a for a in apps if a["id"] == item_id)
    assert app["date_applied"] == "2025-07-10"
    assert app["date_applied_source"] == "confirmation"

    # A duplicate confirmation email with a different timestamp shows up later
    # (e.g. a resend). date_applied already has a value now (auto-filled, but
    # that's indistinguishable from manual to this check) -- it must stay put.
    (folder / "Thank you for applying again.txt").write_text(
        "Date: August 1, 2025 at 9:00 AM\nThanks again for applying.\n"
    )
    client.post("/api/rebuild")
    item_id = _find_item_id(client, "Kappa Ltd", "Engineer")

    second = client.get(f"/api/applications/{item_id}/dossier").json()
    assert second["date_applied_auto_filled"] is False

    apps = client.get("/api/applications").json()
    app = next(a for a in apps if a["id"] == item_id)
    assert app["date_applied"] == "2025-07-10"  # unchanged
    assert app["date_applied_source"] == "confirmation"  # unchanged


def test_confirmation_evidence_still_takes_priority_and_auto_fills_over_posting(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Lambda LLC", role="PM")
    (folder / "Job Description.txt").write_text(
        "Date: January 1, 2025 at 9:00 AM\nJob Description\nBuild things.\n"
    )
    (folder / "Thank you for applying.txt").write_text(
        "Date: July 10, 2025 at 10:56 AM\nThanks for applying.\n"
    )

    client.post("/api/workspaces/link", json={"name": "Priority Auto Fill Test", "path": str(root)})
    item_id = _find_item_id(client, "Lambda LLC", "PM")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert body["detected_date_evidence_tier"] == "confirmation"
    assert body["date_applied_auto_filled"] is True

    apps = client.get("/api/applications").json()
    app = next(a for a in apps if a["id"] == item_id)
    assert app["date_applied"] == "2025-07-10"  # confirmation date, not the posting's


def test_missing_dates_never_produce_a_false_automatic_value(client, tmp_path):
    root, folder = _make_application_folder(tmp_path, company="Mu Inc", role="Support")
    (folder / "resume.txt").write_text("Jane Doe -- jane.doe@example.com")
    (folder / "coverletter.txt").write_text("No dates anywhere in this document.")

    client.post("/api/workspaces/link", json={"name": "No False Positive Test", "path": str(root)})
    item_id = _find_item_id(client, "Mu Inc", "Support")
    body = client.get(f"/api/applications/{item_id}/dossier").json()

    assert body["detected_date_evidence_tier"] is None
    assert body["date_applied_auto_filled"] is False

    apps = client.get("/api/applications").json()
    app = next(a for a in apps if a["id"] == item_id)
    assert app["date_applied"] is None
    assert app["date_applied_source"] is None
