"""
PyInstaller entry point. The frozen build is a single executable that
plays two roles, selected by an argv flag:

  - no args        -> launcher.main(): opens the native window, spawning
                       a copy of THIS SAME executable (with --serve) as
                       the backend subprocess.
  - --serve        -> runs the FastAPI backend directly via uvicorn,
                       reading JOBTRACKER_PORT / JOBTRACKER_PACKAGED /
                       JOBTRACKER_STATE_DIR from the environment
                       launcher.py._spawn_backend() sets.

This split exists because a PyInstaller onefile/onedir build produces one
executable, not two -- there's no separate "backend binary" to invoke.

Not run end-to-end (no PyInstaller build was possible in the sandbox
that wrote this -- no network to install build-time deps for a real
frozen test). Syntax-checked only.
"""

from __future__ import annotations

import os
import sys


def _run_backend() -> None:
    # sys._MEIPASS is where PyInstaller unpacks bundled data at runtime;
    # _app/ is bundled there via the datas=[...] entry in the .spec file.
    app_dir = os.path.join(sys._MEIPASS, "_app")  # type: ignore[attr-defined]
    sys.path.insert(0, app_dir)
    os.chdir(app_dir)

    import uvicorn
    import api  # explicit import so PyInstaller's static analysis bundles fastapi/pydantic/etc.

    port = int(os.environ.get("JOBTRACKER_PORT", "8000"))
    uvicorn.run(api.app, host="127.0.0.1", port=port, reload=False)


def main() -> None:
    if "--serve" in sys.argv:
        _run_backend()
        return

    import launcher

    launcher.main()


if __name__ == "__main__":
    main()
