"""
/api/file — the endpoint the inline PDF/document viewer (and the new
"Download" button) both point at. resolve_safe() is the only thing
standing between a relpath typed into a URL bar and the rest of the
user's filesystem, so its rejection paths get exercised directly here,
not just the happy path.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def linked(client, sample_root):
    """Link sample_root and return its relpaths for convenience."""
    client.post("/api/workspaces/link", json={"name": "Files Test", "path": str(sample_root)})
    return sample_root


def test_serves_pdf_with_correct_content_type(client, linked):
    resp = client.get(
        "/api/file",
        params={"relpath": "Applications/Acme Co/Backend Engineer/resume.pdf"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content.startswith(b"%PDF")


def test_txt_is_wrapped_as_html_for_the_inline_viewer(client, linked):
    # See api.py's TEXT_VIEWER_EXTENSIONS comment: raw text/plain in an
    # iframe renders invisible in dark mode, so .txt gets wrapped in
    # our own minimal HTML instead of served as-is.
    resp = client.get(
        "/api/file",
        params={"relpath": "Applications/Acme Co/Backend Engineer/coverletter.txt"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Dear hiring manager" in resp.text


def test_missing_file_is_404(client, linked):
    resp = client.get(
        "/api/file",
        params={"relpath": "Applications/Acme Co/Backend Engineer/does-not-exist.pdf"},
    )
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "traversal_relpath",
    [
        "../../../../../../etc/passwd",
        "Applications/../../../../etc/passwd",
    ],
)
def test_path_traversal_is_rejected(client, linked, traversal_relpath):
    resp = client.get("/api/file", params={"relpath": traversal_relpath})
    # resolve_safe() must refuse anything that resolves outside the
    # workspace root -- either a clean 403 (escapes root) or a 404 (if
    # the traversal happens to land somewhere that also doesn't exist),
    # but under no circumstances a 200 with real file content.
    assert resp.status_code in (403, 404)
    assert b"root:" not in resp.content  # /etc/passwd's tell-tale first line


def test_symlink_escape_is_rejected(client, sample_root, tmp_path):
    # A symlink *inside* the tracker root pointing back out at the
    # filesystem is a different escape route than plain '../' segments
    # -- resolve_safe() uses .resolve() specifically to catch this too.
    secret = tmp_path / "outside-secret.txt"
    secret.write_text("do not serve this")

    link_path = sample_root / "Applications" / "escape-link"
    link_path.symlink_to(secret)

    client.post("/api/workspaces/link", json={"name": "Symlink Test", "path": str(sample_root)})

    resp = client.get("/api/file", params={"relpath": "Applications/escape-link"})
    assert resp.status_code in (403, 404)
    assert resp.content != b"do not serve this"
