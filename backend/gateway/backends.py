"""One private copy of the original app per signed-in user.

Each user gets their own uvicorn process (127.0.0.1, random port, secret token) with its own
state directory and HOME, so their trackers, databases and uploaded documents are separate files.
Several web workers may share this: a file lock plus backend.json coordinate who starts the process.
Unix only (fcntl).
"""
from __future__ import annotations

import fcntl
import http.client
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


class BackendError(Exception):
    pass


@dataclass
class Backend:
    port: int
    token: str


class Backends:
    def __init__(self, data_dir: Path, app_source: Path, idle_minutes: int = 30):
        self.data_dir = Path(data_dir)
        self.app_source = Path(app_source)
        self.idle_seconds = idle_minutes * 60

    # --- paths -------------------------------------------------------------
    def user_dir(self, user_id) -> Path:
        return self.data_dir / "users" / str(int(user_id))

    def _info_path(self, d: Path) -> Path:
        return d / "backend.json"

    # --- liveness ------------------------------------------------------------
    @staticmethod
    def _pid_alive(pid) -> bool:
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ValueError, TypeError):
            return False

    @staticmethod
    def _healthy(port: int, token: str, timeout: float = 2.0) -> bool:
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
            c.request("GET", "/api/health", headers={"X-JTH-Gateway-Token": token})
            ok = c.getresponse().status == 200
            c.close()
            return ok
        except OSError:
            return False

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    # --- public ----------------------------------------------------------------
    def ensure(self, user) -> Backend:
        d = self.user_dir(user.pk)
        for sub in ("state", "home", "tmp", "logs"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        with open(d / "backend.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                info = self._read(d)
                if info and self._pid_alive(info["pid"]) and self._healthy(info["port"], info["token"]):
                    self._touch(d, info)
                    return Backend(info["port"], info["token"])
                info = self._spawn(d)
                return Backend(info["port"], info["token"])
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def stop_user(self, user_id) -> bool:
        d = self.user_dir(user_id)
        info = self._read(d)
        if not info:
            return False
        try:
            os.killpg(int(info["pid"]), signal.SIGTERM)
        except (OSError, ValueError):
            pass
        try:
            self._info_path(d).unlink()
        except FileNotFoundError:
            pass
        return True

    def stop_idle(self) -> int:
        stopped = 0
        users = self.data_dir / "users"
        if not users.is_dir():
            return 0
        for d in users.iterdir():
            info = self._read(d)
            if info and time.time() - info.get("last_used", 0) > self.idle_seconds:
                stopped += self.stop_user(d.name)
        return stopped

    def stop_all(self) -> int:
        users = self.data_dir / "users"
        return sum(self.stop_user(d.name) for d in users.iterdir()) if users.is_dir() else 0

    # --- internals ---------------------------------------------------------------
    def _read(self, d: Path):
        try:
            return json.loads(self._info_path(d).read_text())
        except (OSError, ValueError):
            return None

    def _write(self, d: Path, info: dict) -> None:
        p = self._info_path(d)
        tmp = p.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(info, f)
        os.replace(tmp, p)

    def _touch(self, d: Path, info: dict) -> None:
        if time.time() - info.get("last_used", 0) > 30:
            info["last_used"] = time.time()
            self._write(d, info)

    def _spawn(self, d: Path) -> dict:
        old = self._read(d)
        if old and self._pid_alive(old["pid"]):
            try:
                os.killpg(int(old["pid"]), signal.SIGTERM)  # unhealthy leftover
            except OSError:
                pass
        port, token = self._free_port(), secrets.token_urlsafe(32)
        # A fresh, minimal environment: the child must not inherit Django secrets or cloud credentials.
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PYTHONUNBUFFERED": "1",
            "HOME": str(d / "home"),
            "TMPDIR": str(d / "tmp"),
            "JOBTRACKER_PACKAGED": "1",          # no shared default tracker; state lives in STATE_DIR
            "JOBTRACKER_STATE_DIR": str(d / "state"),
            "JOBTRACKER_PORT": str(port),
            "JTH_GATEWAY_TOKEN": token,
        }
        log = open(d / "logs" / "app.log", "ab")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "gateway_asgi:app", "--app-dir", str(self.app_source),
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=str(self.app_source), env=env, stdout=log, stderr=log, start_new_session=True,
        )
        deadline = time.time() + 40
        while time.time() < deadline:
            if proc.poll() is not None:
                raise BackendError("Your private workspace server exited at startup (see logs/app.log).")
            if self._healthy(port, token, timeout=1.0):
                info = {"pid": proc.pid, "port": port, "token": token, "last_used": time.time()}
                self._write(d, info)
                return info
            time.sleep(0.25)
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        raise BackendError("Your private workspace server did not start in time.")
