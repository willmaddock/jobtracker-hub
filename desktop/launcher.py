"""
Desktop entry point for JobTracker Hub.

Flow:
    1. Pick a free localhost port and spawn the bundled FastAPI backend
       as a subprocess on it, with JOBTRACKER_PACKAGED=1 and
       JOBTRACKER_STATE_DIR set so it writes to Application Support
       instead of trying to write inside the read-only .app bundle.
    2. Poll /api/health until the subprocess is actually serving.
    3. If no tracker has been linked/created yet (GET /api/workspaces
       returns active: None), show the local first_run.html page and
       let the user pick a folder via a native dialog. Once picked, call
       the real /api/workspaces/link endpoint over HTTP -- same code
       path the web UI would use -- then navigate the window to the app.
    4. Otherwise, skip straight to opening the window on the running app.
    5. On window close, terminate the backend subprocess.

This file assumes `pywebview` is installed (desktop/requirements.txt).
It was written and syntax-checked in an environment without pywebview or
network access, so import and syntax correctness were verified, but the
actual GUI window has not been opened. Run it for real on your Mac
(`python desktop/launcher.py`, or via the PyInstaller build) before
shipping.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import paths

APP_NAME = paths.APP_NAME


def _free_port() -> int:
    """Binds to port 0 to let the OS hand back an unused port, then
    releases it immediately. There's a small unavoidable race between
    releasing it here and the backend binding it a moment later, but
    it's the same approach every "let the OS pick" tool uses, and the
    window is milliseconds."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _api_base(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _http_json(url: str, method: str = "GET", payload: dict | None = None, timeout: float = 5.0) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _log_path(state_dir: Path) -> Path:
    """Where the backend subprocess's stdout/stderr get redirected.
    Lives next to the per-workspace data in Application Support, so it
    survives across launches (a fresh file each time -- see
    _spawn_backend) and is one click away from Settings > Diagnostics."""
    return state_dir / "backend.log"


def _spawn_backend(port: int, state_dir: Path) -> subprocess.Popen:
    """Runs the bundled backend as a subprocess of this launcher. In a
    frozen build, this launcher and the backend are the SAME executable
    (see scripts/jobtracker-hub.spec) -- `--serve` tells it to act as
    the backend instead of the launcher. In a dev checkout (running
    launcher.py directly with `python`), fall back to invoking
    `python _app/api.py` instead, since there's no single frozen
    executable to re-invoke.

    The subprocess's stdout/stderr are redirected to a log file instead
    of being silently discarded -- in a packaged GUI app there's no
    attached terminal to see them in, and "check Console.app" only
    actually has something useful in it for uncaught native crashes,
    not for a Python traceback the backend printed on its own stderr."""
    env = {
        "JOBTRACKER_PACKAGED": "1",
        "JOBTRACKER_PORT": str(port),
        "JOBTRACKER_STATE_DIR": str(state_dir),
    }
    import os
    full_env = {**os.environ, **env}

    # Fresh log each launch -- this is "what happened just now", not a
    # growing history. Opened in the parent and handed to the child so
    # it stays valid (and flushed on process exit) even after this
    # function returns.
    log_file = open(_log_path(state_dir), "w", encoding="utf-8")

    if getattr(sys, "frozen", False):
        return subprocess.Popen(
            [sys.executable, "--serve"], env=full_env, stdout=log_file, stderr=subprocess.STDOUT,
        )

    app_dir = paths.get_app_dir()
    return subprocess.Popen(
        [sys.executable, str(app_dir / "api.py")],
        env=full_env, cwd=str(app_dir), stdout=log_file, stderr=subprocess.STDOUT,
    )


def _show_fatal_error(message: str, log_path: Path) -> None:
    """Native, OS-level alert for startup failures -- deliberately NOT a
    webview window, since if webview itself is the thing that's broken
    (or the backend never came up so there's nothing for a window to
    point at), a webview-based error dialog could fail for the exact
    same reason as the thing it's reporting. Falls back to stderr if
    even the native call doesn't work, so this can never raise past
    main()'s exception handling."""
    full_message = f"{message}\n\nLog file:\n{log_path}"
    try:
        if sys.platform == "darwin":
            script = (
                f'display dialog "{full_message}" '
                f'with title "{APP_NAME}" buttons {{"OK"}} default button "OK" '
                f'with icon caution'
            )
            subprocess.run(["osascript", "-e", script], check=False)
        elif sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, full_message, APP_NAME, 0x10)  # MB_ICONERROR
        else:
            subprocess.run(["zenity", "--error", "--title", APP_NAME, "--text", full_message], check=False)
    except Exception:
        pass
    print(f"[{APP_NAME}] FATAL: {full_message}", file=sys.stderr)


def _wait_for_health(port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    url = f"{_api_base(port)}/api/health"
    while time.monotonic() < deadline:
        try:
            result = _http_json(url, timeout=1.0)
            if result.get("ok"):
                return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.2)
    return False


def _needs_first_run(port: int) -> bool:
    result = _http_json(f"{_api_base(port)}/api/workspaces")
    return result.get("active") is None


class Api:
    """pywebview js_api bridge -- methods here are callable from
    first_run.html as window.pywebview.api.<name>(...)."""

    def __init__(self, port: int, window_ref: list):
        self._port = port
        self._window_ref = window_ref  # 1-element list, filled in after webview.create_window

    def choose_folder(self) -> dict:
        import webview

        window = self._window_ref[0]
        result = window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return {"error": None}  # user cancelled -- not an error, just no-op
        folder = result[0]
        name = Path(folder).name or "My Job Search"
        try:
            _http_json(
                f"{_api_base(self._port)}/api/workspaces/link",
                method="POST",
                payload={"name": name, "path": folder},
            )
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            detail = str(e)
            if isinstance(e, urllib.error.HTTPError):
                try:
                    detail = json.loads(e.read().decode("utf-8")).get("detail", detail)
                except Exception:
                    pass
            return {"error": detail}

        # The first-run window was deliberately created small and
        # non-resizable (it's just a "pick a folder" prompt). pywebview
        # doesn't support changing a window's size/resizable flag after
        # creation, so navigating this same window to the main app in
        # place (the old approach) left it permanently stuck at 520x420
        # until the whole app was quit and relaunched. Instead, open a
        # proper full-size resizable window for the real app now, and
        # close this one a moment later -- the short delay just gives
        # this call's own result time to finish crossing back over the
        # JS bridge before its window disappears.
        import threading

        main_window = webview.create_window(
            APP_NAME, _api_base(self._port), width=1200, height=800, js_api=self,
        )
        self._window_ref[0] = main_window
        threading.Timer(0.5, window.destroy).start()

        return {"error": None}


def main() -> None:
    port = _free_port()
    state_dir = paths.get_state_dir()
    log_path = _log_path(state_dir)
    backend = _spawn_backend(port, state_dir)

    try:
        if not _wait_for_health(port, timeout=20.0):
            _show_fatal_error(
                f"{APP_NAME}'s backend didn't start in time. Try relaunching the app; "
                "if this keeps happening, open the log file below (also reachable from "
                "Settings > Diagnostics once the app is running) and check the last few lines.",
                log_path,
            )
            return

        # webview is imported only once health is confirmed -- if webview
        # itself is broken/missing, that's a separate, less common failure
        # mode, and _show_fatal_error above must not depend on it anyway.
        import webview

        first_run = _needs_first_run(port)
        window_ref: list = [None]
        api = Api(port, window_ref)

        if first_run:
            first_run_page = str(Path(__file__).resolve().parent / "first_run.html")
            window = webview.create_window(
                APP_NAME, first_run_page, width=560, height=560, resizable=False, js_api=api,
            )
        else:
            window = webview.create_window(APP_NAME, _api_base(port), width=1200, height=800, js_api=api)

        # js_api methods are only invoked from JS after the window has
        # loaded, i.e. strictly after create_window() returns here, so
        # this is set in time for choose_folder()'s use of it.
        window_ref[0] = window

        webview.start()
    except Exception as e:
        # Catches webview import/start failures and anything else
        # unexpected -- the whole point of this handler is that nothing
        # after backend spawn should be able to quit the app silently.
        _show_fatal_error(f"{APP_NAME} hit an unexpected error and needs to close:\n{e}", log_path)
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend.kill()


if __name__ == "__main__":
    main()
