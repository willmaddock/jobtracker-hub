"""ASGI entry for a per-user hosted copy of the original app.

Wraps api.app (unchanged) so that it only answers requests carrying the gateway's secret token,
and re-applies the same endpoint policy the Django proxy uses. Started by backend/gateway/backends.py:
    python -m uvicorn gateway_asgi:app --app-dir _app --host 127.0.0.1 --port N
"""
import hmac
import json
import os

import gateway_policy
from api import app as _inner

_TOKEN = os.environ.get("JTH_GATEWAY_TOKEN", "")


async def _deny(send, status, detail):
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        return await _inner(scope, receive, send)
    if scope["type"] != "http":
        return  # no websockets here
    headers = {k.lower(): v for k, v in scope["headers"]}
    given = headers.get(b"x-jth-gateway-token", b"").decode("latin-1")
    if not _TOKEN or not hmac.compare_digest(given, _TOKEN):
        return await _deny(send, 403, "Forbidden.")
    allow_local = headers.get(b"x-jth-allow-local") == b"1"
    ok, reason = gateway_policy.decide(scope["method"], scope["path"], allow_local)
    if not ok:
        return await _deny(send, 403, reason)
    return await _inner(scope, receive, send)
