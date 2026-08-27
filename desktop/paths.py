"""
Path resolution for the packaged desktop app.

Two things the plain dev workflow (`python _app/api.py`) never has to
think about, but a frozen PyInstaller build does:

1. Where does the bundled backend code actually live? A PyInstaller
   onedir build unpacks everything next to the executable at
   Contents/MacOS/_internal (sys._MEIPASS) -- not next to this file.

2. Where does the app write its own data? A packaged .app's own folder
   is read-only (or at least not something you should write into), so
   the workspace registry, per-workspace DB pairs, and any app-created
   ("owned") tracker folders need a real per-app writable location --
   ~/Library/Application Support/<AppName> on macOS.

Both are no-ops in dev mode: get_app_dir() falls back to the real repo's
_app/ folder, and get_state_dir() is only ever consulted when
JOBTRACKER_PACKAGED is set (see _app/workspace.py), so dev mode never
calls it at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "JobTracker Hub"


def get_app_dir() -> Path:
    """Directory containing _app/ -- the FastAPI backend and its
    frontend/ folder. In a frozen build, PyInstaller unpacks bundled
    data next to sys._MEIPASS; in a normal Python process (including
    `python desktop/launcher.py` run straight from a checkout), it's
    just this file's repo."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "_app"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent / "_app"


def get_state_dir() -> Path:
    """Per-app writable data directory. Only meaningful in packaged
    mode -- dev mode never calls this (workspace.py only consults
    JOBTRACKER_STATE_DIR when JOBTRACKER_PACKAGED is set, and the
    launcher only sets that env var for the subprocess it spawns)."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        import os
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        import os
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    state_dir = base / APP_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir
