"""
Shared fixtures for the backend test suite.

Why this is more than boilerplate:

workspace.py resolves STATE_DIR (where workspaces.json and every
workspace's DB pair live) from the JOBTRACKER_STATE_DIR env var, but it
does so as a MODULE-LEVEL constant, read once at import time. That means
the env var has to be set before `import api` (which itself does
`import workspace as ws`) ever runs for the first time in this process
-- setting it inside a test, or even inside a fixture that runs after
collection has already imported the module, is a no-op. Hence importing
`api` lazily, only from inside the `app` fixture below, after `state_dir`
has already set the environment.

Second gotcha found while writing this: JOBTRACKER_PACKAGED=1 makes
create_workspace() and both import-folder paths call
_owned_siblings_dir(), which for packaged mode hard-codes
~/Documents/JobTracker Hub with no env-var override at all (see
workspace.py). Left alone, a test that exercises create_workspace would
actually create a folder in the *real* ~/Documents on whatever machine
runs the suite. test_create_workspace.py works around this with
monkeypatch rather than trying to fix that from here, since it's a
real product gap worth flagging on its own -- see NOTES.md.
"""

from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "_app"
sys.path.insert(0, str(APP_DIR))


@pytest.fixture(scope="session")
def state_dir(tmp_path_factory):
    """A throwaway per-session directory standing in for
    ~/Library/Application Support/JobTracker Hub. Setting
    JOBTRACKER_PACKAGED=1 also means workspace.py never self-heals a
    "default" workspace pointing at this real checkout (see
    workspace._empty_registry) -- every test starts from a genuinely
    empty registry and has to link/create its own workspace."""
    d = tmp_path_factory.mktemp("jobtracker_state")
    os.environ["JOBTRACKER_PACKAGED"] = "1"
    os.environ["JOBTRACKER_STATE_DIR"] = str(d)
    return d


@pytest.fixture(scope="session")
def api_module(state_dir):
    """Imports api.py exactly once per test run, after the env vars
    above are already set. Do not import api at module level anywhere
    in this test suite -- always go through this fixture."""
    import api as api_module  # noqa: F401
    return api_module


@pytest.fixture(scope="session")
def ws_module(api_module):
    import workspace as ws
    return ws


@pytest.fixture(scope="session")
def client(api_module):
    from fastapi.testclient import TestClient
    return TestClient(api_module.app)


@pytest.fixture(autouse=True)
def clean_registry(ws_module, state_dir):
    """Every test function starts from a blank workspace registry and
    a blank workspaces/ DB-pair directory, regardless of what an
    earlier test created or linked. Nothing under state_dir survives
    between tests; anything a test links from tmp_path is separate
    and cleaned up by pytest's own tmp_path teardown."""
    ws_module._save_raw(ws_module._empty_registry())
    db_dir = ws_module.WORKSPACES_DB_DIR
    if db_dir.exists():
        shutil.rmtree(db_dir)
    yield


@pytest.fixture
def sample_root(tmp_path):
    """A minimal but real tracker root: one company/role application
    folder with a resume (actual, tiny, valid PDF bytes -- enough for
    a PDF reader to open it) and a plain-text cover letter, plus a
    second document type so classify.py has more than one extension to
    sort. Deliberately hand-built rather than reusing sample-tracker/
    at the repo root, so this suite doesn't silently start failing if
    that folder's contents ever change for demo/doc purposes.

    Lives one level *below* tmp_path (tmp_path / "tracker"), not at
    tmp_path itself -- tests that need a location genuinely outside the
    tracker root (e.g. test_symlink_escape_is_rejected's "secret" file)
    write to tmp_path directly, which only stays outside the root if
    the root is a subdirectory of it, not tmp_path itself."""
    root = tmp_path / "tracker"
    role_dir = root / "Applications" / "Acme Co" / "Backend Engineer"
    role_dir.mkdir(parents=True)

    minimal_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n"
    )
    (role_dir / "resume.pdf").write_bytes(minimal_pdf)
    (role_dir / "coverletter.txt").write_text("Dear hiring manager,\n")

    return root
