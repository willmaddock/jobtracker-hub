"""
GET /api/workspaces/{id}/export — the endpoint launcher.py's native
export_workspace() bridge method fetches bytes from. This is a good
place to catch a regression like the original zip-export bug: a
200 response whose body isn't actually a valid, complete zip.
"""

from __future__ import annotations

import io
import zipfile


def test_export_produces_a_valid_zip_with_the_workspace_contents(client, sample_root):
    entry = client.post(
        "/api/workspaces/link", json={"name": "Export Me", "path": str(sample_root)}
    ).json()["workspace"]

    resp = client.get(f"/api/workspaces/{entry['id']}/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert zf.testzip() is None  # None means every member's CRC checks out

    names = set(zf.namelist())
    assert any(n.endswith("resume.pdf") for n in names)
    assert any(n.endswith("coverletter.txt") for n in names)

    resume_bytes = next(
        zf.read(n) for n in names if n.endswith("resume.pdf")
    )
    assert resume_bytes.startswith(b"%PDF")


def test_export_unknown_workspace_id_is_400_not_500(client):
    resp = client.get("/api/workspaces/does-not-exist/export")
    assert resp.status_code == 400


def test_export_never_modifies_the_source_folder(client, sample_root):
    entry = client.post(
        "/api/workspaces/link", json={"name": "Read Only Export", "path": str(sample_root)}
    ).json()["workspace"]

    before = sorted(p.relative_to(sample_root) for p in sample_root.rglob("*") if p.is_file())
    client.get(f"/api/workspaces/{entry['id']}/export")
    after = sorted(p.relative_to(sample_root) for p in sample_root.rglob("*") if p.is_file())

    assert before == after
