"""
/api/open-url — hands a URL to the OS's default handler. Originally
http(s)-only (job boards, career pages); Checkpoint 4 extended the
allowlist to mailto:/tel: so the Dossier's Contacts section can route
email/phone actions through the same OS-opener path instead of
window.location.href (unreliable in the packaged webview). The allowlist
is the only thing standing between this endpoint and an arbitrary
subprocess-adjacent call (os.startfile / xdg-open / open), so every
branch of it is exercised directly here, with subprocess.run and
os.startfile monkeypatched so nothing actually shells out.
"""

from __future__ import annotations

import os
import subprocess

import pytest


@pytest.fixture
def no_shellout(monkeypatch):
    """Prevents open_url from actually invoking the OS opener, while still
    letting us assert it *would have* been called with the right URL.
    open_url does `import subprocess`/`import os` locally inside the
    function rather than at api.py's module level, but every `import X`
    anywhere in the process resolves to the same sys.modules[X] object,
    so patching the real subprocess/os modules here still intercepts it."""
    calls = []

    def fake_run(args, check=False):  # noqa: ARG001
        calls.append(args)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(os, "startfile", lambda url: calls.append(["startfile", url]), raising=False)
    return calls


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/acme/jobs/123",
        "http://example.com/careers",
        "mailto:recruiter@acme.com",
        "tel:+15551234567",
    ],
)
def test_allowed_schemes_return_ok(client, no_shellout, url):
    resp = client.post("/api/open-url", json={"url": url})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "ftp://example.com/file",
        "not-a-url-at-all",
        "",
        "  ",
    ],
)
def test_disallowed_schemes_are_rejected(client, no_shellout, url):
    resp = client.post("/api/open-url", json={"url": url})
    assert resp.status_code == 400
    assert "http://" in resp.json()["detail"]
    assert "mailto:" in resp.json()["detail"]
    # Rejected before any attempt to shell out.
    assert no_shellout == []


def test_mailto_with_query_params_is_allowed(client, no_shellout):
    # mailto: supports ?subject=&body=&cc= etc. — a real value the
    # Contacts section could plausibly build.
    resp = client.post(
        "/api/open-url",
        json={"url": "mailto:jane@example.com?subject=Following%20up"},
    )
    assert resp.status_code == 200


def test_whitespace_around_url_is_trimmed(client, no_shellout):
    resp = client.post("/api/open-url", json={"url": "  https://example.com  "})
    assert resp.status_code == 200
