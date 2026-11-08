"""The gateway. Django signs people in (email code + MFA); everything else is the original app.

After sign-in, "/" serves the original UI and every other /api/* request is forwarded to the
signed-in user's own private process (see backends.py). Nothing reaches that process without a
valid, MFA-complete Django session, and desktop-only endpoints are refused (policy.py).
"""
from __future__ import annotations

import http.client
import json
import logging
from urllib.parse import quote, urlsplit

from django.conf import settings
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from accounts import mfa_session
from core.frontend import FRONTEND

from . import policy
from .backends import Backends, BackendError

log = logging.getLogger(__name__)
_backends = None

_MARKER = "<!-- DJANGO_FOUNDATION_BOOTSTRAP -->"

# Shown to people who are not fully signed in: Django's own sign-in + MFA screens. Once the
# screen reaches "Signed in as ...", reload so the server can hand over the real app.
_LOGIN_SNIPPET = """<script>window.JTH_DJANGO = true;
(function(){
  var done = false;
  function check(){
    if (done || !/Signed in as/.test(document.body ? document.body.innerText : "")) return;
    var last = Number(sessionStorage.getItem("jth-reload") || 0);
    if (Date.now() - last < 10000) return;
    done = true; sessionStorage.setItem("jth-reload", String(Date.now())); location.reload();
  }
  new MutationObserver(check).observe(document.documentElement, {childList:true, subtree:true, characterData:true});
})();</script>"""

# Shown to fully signed-in people: the original app, plus session-expiry handling. JTH_GATEWAY
# tells the app it is served by the gateway, so it shows the account controls (signed-in email,
# Security, Sign out) in its own tracker menu, rail and Settings.
_APP_SNIPPET = """<script>window.JTH_GATEWAY = true;
(function(){
  var f = window.fetch;
  window.fetch = function(){
    return f.apply(this, arguments).then(function(r){
      if (r.status === 401 && String(r.url).indexOf("/api/auth/") < 0) location.reload();
      return r;
    });
  };
})();</script>"""


def backends() -> Backends:
    global _backends
    if _backends is None:
        _backends = Backends(settings.JTH_DATA_DIR, settings.JTH_APP_SOURCE, settings.JTH_IDLE_MINUTES)
    return _backends


def _fully_signed_in(request) -> bool:
    if not request.user.is_authenticated:
        return False
    return (not settings.MFA_REQUIRED) or mfa_session.is_verified(request)


@require_GET
@never_cache
def index(request):
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    snippet = _APP_SNIPPET if _fully_signed_in(request) else _LOGIN_SNIPPET
    return HttpResponse(html.replace(_MARKER, snippet))


# --- proxy ---------------------------------------------------------------------------------
_FORWARD_REQUEST_HEADERS = {
    "content-type": "Content-Type", "accept": "Accept", "accept-language": "Accept-Language",
    "range": "Range", "if-none-match": "If-None-Match", "if-modified-since": "If-Modified-Since",
}
_DROP_RESPONSE_HEADERS = {
    "connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authenticate",
    "proxy-authorization", "set-cookie", "server", "date",
}
_SAFE_PATH_CHARS = "/:@!$&'()*+,;=-._~"


def _same_origin(request) -> bool:
    """CSRF defence for the forwarded API: browsers label cross-site requests, so refuse them."""
    site = request.headers.get("Sec-Fetch-Site")
    if site is not None:
        return site in ("same-origin", "none")
    origin = request.headers.get("Origin")
    return bool(origin) and urlsplit(origin).netloc == request.get_host()


def _json(detail, status, **extra):
    r = JsonResponse({"detail": detail, **extra}, status=status)
    r["Cache-Control"] = "no-store"
    return r


def _connect(user, allow_local):
    be = backends().ensure(user)
    conn = http.client.HTTPConnection("127.0.0.1", be.port, timeout=600)
    conn.connect()
    return be, conn


def _body_iter(resp, conn):
    try:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            yield chunk
    finally:
        conn.close()


@csrf_exempt  # replaced by _same_origin() + session cookies; this view must not parse request.POST
@xframe_options_sameorigin  # the original app shows documents in same-origin iframes
def proxy(request, path):
    if not _fully_signed_in(request):
        return _json("Sign in required.", 401, code="authentication_required")

    api_path = request.path_info
    allow_local = bool(settings.JTH_ALLOW_LOCAL_LINK and request.user.is_superuser)
    ok, reason = policy.decide(request.method, api_path, allow_local)
    if not ok:
        return _json(reason, 403)
    if request.method in policy.UNSAFE_METHODS and not _same_origin(request):
        return _json("Cross-site request refused.", 403)

    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return _json("Bad Content-Length.", 400)
    if length > settings.JTH_MAX_UPLOAD_MB * 1024 * 1024:
        return _json(f"Upload too large (the limit is {settings.JTH_MAX_UPLOAD_MB} MB).", 413)

    try:
        try:
            be, conn = _connect(request.user, allow_local)
        except OSError:  # process died since last check: ensure() restarts it on the retry
            be, conn = _connect(request.user, allow_local)
    except BackendError as exc:
        return _json(str(exc), 503)
    except OSError:
        return _json("Your private workspace server is not reachable.", 503)

    target = quote(api_path, safe=_SAFE_PATH_CHARS)
    qs = request.META.get("QUERY_STRING", "")
    if qs:
        target += "?" + qs
    try:
        conn.putrequest(request.method, target, skip_accept_encoding=True)
        for src, dst in _FORWARD_REQUEST_HEADERS.items():
            value = request.headers.get(src)
            if value:
                conn.putheader(dst, value)
        conn.putheader("X-JTH-Gateway-Token", be.token)
        if allow_local:
            conn.putheader("X-JTH-Allow-Local", "1")
        if length or request.method in ("POST", "PUT", "PATCH"):
            conn.putheader("Content-Length", str(length))
        conn.endheaders()
        remaining = length
        while remaining > 0:
            chunk = request.read(min(65536, remaining))
            if not chunk:
                break
            conn.send(chunk)
            remaining -= len(chunk)
        resp = conn.getresponse()
    except (OSError, http.client.HTTPException) as exc:
        conn.close()
        log.warning("gateway: backend request failed for user %s: %s", request.user.pk, exc)
        return _json("Your private workspace server did not answer.", 502)

    # The packaged flag only exists so the desktop shell can swap in native file pickers; a
    # browser must keep the upload-based flows, so report "not packaged" to the UI.
    if api_path.rstrip("/") == "/api/status" and resp.status == 200:
        try:
            data = json.loads(resp.read())
            data["packaged"] = False
            out = JsonResponse(data)
        except ValueError:
            out = _json("Unexpected response from workspace server.", 502)
        conn.close()
        out["Cache-Control"] = "no-store"
        return out

    out = StreamingHttpResponse(_body_iter(resp, conn), status=resp.status, reason=resp.reason)
    for name, value in resp.getheaders():
        low = name.lower()
        if low in _DROP_RESPONSE_HEADERS:
            continue
        if low == "location":
            parts = urlsplit(value)
            value = parts.path + ("?" + parts.query if parts.query else "")
        out[name] = value
    out.setdefault("Cache-Control", "private, no-cache")
    out["Vary"] = "Cookie"
    return out
