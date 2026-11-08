"""Which original-app endpoints are safe on a shared server. Pure stdlib; imported by both the
Django gateway (by file path) and gateway_asgi.py, so there is one list.

The desktop app trusts its user with the whole machine. A hosted copy must not: these endpoints
open files with the OS, read arbitrary server folders, or drive macOS Mail.
"""
from __future__ import annotations

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# (method or "*", exact path) -- always refused on a server.
_BLOCKED_EXACT = {
    ("*", "/api/open"), ("*", "/api/open-url"),
    ("*", "/api/diagnostics"), ("*", "/api/diagnostics/reveal-log"),
    ("*", "/api/workspaces/import-folder-local"),
    ("*", "/api/accounts/reset-email-sync"),
}
# Paths whose whole subtree is refused (macOS Mail.app / connected-mailbox control).
_BLOCKED_PREFIX = ("/api/accounts/mail-app",)
# Refused unless the operator turned on JTH_ALLOW_LOCAL_LINK and the user is a superuser.
_LOCAL_ONLY_EXACT = {("*", "/api/workspaces/link"), ("*", "/api/workspaces/inspect")}

MESSAGE = "This action is only available in the desktop app, not on the hosted version."


def normalize(path: str) -> str | None:
    """Return a canonical path, or None if it is suspicious (dot segments, doubled slashes)."""
    if not path.startswith("/") or "\\" in path or "\x00" in path or "//" in path:
        return None
    if any(seg in (".", "..") for seg in path.split("/")):
        return None
    return path.rstrip("/") or "/"


def decide(method: str, path: str, allow_local: bool = False) -> tuple[bool, str]:
    p = normalize(path)
    if p is None:
        return False, "Invalid path."
    m = method.upper()
    for meth, exact in _BLOCKED_EXACT:
        if p == exact and meth in ("*", m):
            return False, MESSAGE
    if p.startswith(_BLOCKED_PREFIX):
        return False, MESSAGE
    # /api/accounts/{id}/sync|discover and DELETE /api/accounts/{id} drive the Mail.app bridge.
    if p.startswith("/api/accounts/") and m != "GET":
        return False, MESSAGE
    for meth, exact in _LOCAL_ONLY_EXACT:
        if p == exact and meth in ("*", m) and not allow_local:
            return False, MESSAGE
    return True, ""
