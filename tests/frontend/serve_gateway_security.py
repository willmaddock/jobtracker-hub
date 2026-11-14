"""Loopback-only gateway browser regressions with synthetic users and a stub backend.

Run from the repository root with backend/venv/bin/python. Never starts the
private tracker or reads .env. Database, media and gateway state are disposable.
"""
import argparse
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import signal
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server
from socketserver import ThreadingMixIn

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=18765)
args = parser.parse_args()
# The runner terminates this owned fixture; unwind temporary DB/media storage.
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "_app"))
sys.path.insert(0, str(ROOT / "tests"))
sys.argv = ["manage.py", "test"]  # dev settings must never load backend/.env
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test_sqlite"
os.environ["JTH_GATEWAY"] = "true"

from django.conf import settings

with tempfile.TemporaryDirectory(prefix="jth-gateway-browser-") as directory:
    settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(Path(directory) / "test.sqlite3")}}
    settings.MEDIA_ROOT = str(Path(directory) / "media")
    settings.JTH_DATA_DIR = Path(directory) / "gateway-unused"
    settings.ROOT_URLCONF = __name__
    settings.ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
    settings.MFA_REQUIRED = False
    settings.X_FRAME_OPTIONS = "DENY"  # regressions use real top-level tabs
    settings.SESSION_COOKIE_NAME = "jth_gateway_test_session"
    settings.CSRF_COOKIE_NAME = "jth_gateway_test_csrf"

    import django
    django.setup()
    from django.core.management import call_command
    from django.contrib import admin
    from django.contrib.auth import get_user_model
    from django.http import HttpResponse, JsonResponse
    from django.urls import include, path
    from django.views.decorators.csrf import csrf_exempt
    from accounts.models import Workspace
    from applications.models import Application
    from django.template import Template, RequestContext
    from django.contrib.staticfiles.views import serve as static_serve
    from web.urls import urlpatterns as web_patterns
    from accounts import totp
    from accounts.views import MeView
    from core.frontend import asset
    from gateway import views
    from gateway.backends import Backend

    call_command("migrate", verbosity=0)  # only the new temporary test database
    actors = {}
    for label in ("A", "B"):
        user = get_user_model().objects.create_user(username="audit" + label, password="synthetic-test-password")
        if label == 'A':
            user.is_staff = user.is_superuser = True
            user.save(update_fields=['is_staff','is_superuser'])
        workspace = Workspace.objects.create(owner=user, name="Fixture " + label)
        Application.objects.create(workspace=workspace, section='applications', company='NATIVE_'+label,
                                   role_label='Synthetic native role', status='applied')
        actors[str(user.pk)] = label

    get_user_model().objects.create_user(username='auditOperator', password='synthetic-test-password',
                                         is_staff=True, is_superuser=True)

    mfa_fixture_user = get_user_model().objects.create_user(username='auditM', password='synthetic-test-password')
    Workspace.objects.create(owner=mfa_fixture_user, name='Fixture M')
    actors[str(mfa_fixture_user.pk)] = 'M'

    def native_multipart(request):
        if not request.user.is_authenticated:
            return HttpResponse(status=403)
        if request.method == 'POST':
            import hashlib
            data = request.FILES['file'].read()
            return JsonResponse({'actor':request.user.username, 'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()})
        html = '{% load gateway_forms %}<form method="post" enctype="multipart/form-data">{% csrf_token %}{% gateway_context %}<input name="file" type="file"><button>Upload</button></form>'
        return HttpResponse(Template(html).render(RequestContext(request)))

    controls = {}
    seen = []
    requests = []
    delays = {name: threading.Event() for name in ("csrf", "native", "context", "headers", "preview", "file_body")}
    for delay in delays.values():
        delay.set()
    gates = {label: threading.Event() for label in ("A", "B", "M")}
    for gate in gates.values():
        gate.set()

    def synthetic_pdf():
        stream = b"BT /F1 18 Tf 35 100 Td (Synthetic gateway PDF) Tj ET"
        objects = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
                   b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 320 200]/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>",
                   b"<</Length " + str(len(stream)).encode() + b">>\nstream\n" + stream + b"\nendstream",
                   b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
        content = b"%PDF-1.4\n"
        offsets = []
        for number, value in enumerate(objects, 1):
            offsets.append(len(content))
            content += str(number).encode() + b" 0 obj\n" + value + b"\nendobj\n"
        start = len(content)
        content += b"xref\n0 6\n0000000000 65535 f \n"
        for offset in offsets:
            content += f"{offset:010d} 00000 n \n".encode()
        return content + b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n" + str(start).encode() + b"\n%%EOF\n"

    PDF = synthetic_pdf()
    from test_docx_preview import make_docx
    from docx_preview import convert_docx
    DOCX = make_docx()
    TEXT = b'<!doctype html><html><body><pre>Synthetic text &lt;script&gt;never execute&lt;/script&gt;</pre></body></html>'

    class Stub(BaseHTTPRequestHandler):
        def handle_request(self):
            label = actors[self.headers["X-JTH-Gateway-Token"]]
            from urllib.parse import parse_qs
            route = urlsplit(self.path).path
            name = parse_qs(urlsplit(self.path).query).get('relpath', [''])[0]
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            observation = {"actor": label, "path": route, "method": self.command, "relpath":name}
            seen.append(observation)
            status = 200
            if self.command == "POST" and controls.get("hold_write") == label:
                gates[label].wait(20)
                if controls.get("fail_write") == label:
                    status = 503
            if route == "/api/status":
                data = {"workspace": {"id": label, "name": "Fixture " + label}, "index_built": True,
                        "packaged": False, "root": "/synthetic", "status_order": ["drafted", "applied", "interviewing", "ghosted", "rejected", "unknown"]}
            elif route == "/api/applications":
                data = [{"id": 1 if label == "A" else 2, "company": "PRIVATE_" + label,
                         "effective_company": "PRIVATE_" + label, "notes": "NOTE_" + label,
                         "item_key": "applications|PRIVATE_" + label, "role_label": "Synthetic role",
                         "section": "applications", "status": "applied", "effective_status": "applied",
                         "archived": False, "is_snoozed": False, "is_stale": False, "next_action_due": False}]
                gates[label].wait(20)
                if controls.get("fail_apps") == label:
                    data, status = {"detail": "Synthetic read failure"}, 503
            elif route.endswith("/dossier"):
                data = {"contacts": {"emails": [], "phones": [], "urls": []}, "timeline_events": [], "account_matches": []}
            elif route.endswith("/documents"):
                data = [{"id":100 + i, "filename":name, "ext":Path(name).suffix,
                         "relpath":name, "doc_type":"resume"}
                        for i, name in enumerate(('synthetic.pdf', 'hostile.docx', 'slow.docx', 'notes.txt'))]
            elif route == '/api/preview-docx':
                if controls.get('hold_preview') and name == 'slow.docx':
                    delays['preview'].wait(20)
                data = convert_docx(io.BytesIO(DOCX))
            elif route == "/api/discoveries":
                data = []
            else:
                data = {"ok": True, "actor": label}
            if route == "/api/file":
                if controls.get("file401") == label:
                    status = 401
                if controls.get("hold_file") == label:
                    gates[label].wait(20)
                body, content_type = (DOCX, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') if name.endswith('.docx') else (TEXT, 'text/html') if name.endswith('.txt') else (PDF, 'application/pdf')
            else:
                body = json.dumps(data).encode()
                content_type = "application/json"
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if route == '/api/file' and controls.get('hold_file_body'):
                    self.wfile.write(body[:1]); self.wfile.flush()
                    observation['body_started'] = True
                    delays['file_body'].wait(20)
                    self.wfile.write(body[1:])
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # an invalidated page intentionally abandons old requests
            finally:
                observation.update(complete=True, response_status=status)
        do_GET = do_POST = do_DELETE = handle_request
        def log_message(self, *args):
            pass

    stub = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()

    class FakeBackends:
        def ensure(self, user):
            return Backend(stub.server_address[1], str(user.pk))
    views._backends = FakeBackends()

    @csrf_exempt
    def configure(request):
        data = json.loads(request.body or b"{}")
        for name, delay in delays.items():
            delay.clear() if data.get("hold_" + name) else delay.set()
        controls.clear()
        controls.update(data)
        settings.MFA_REQUIRED = bool(data.get("mfa_required"))
        if data.get('reset_mfa') == 'auditM':
            # Loopback fixture only: simulate the permitted operator reset for
            # this single disposable user while its own verified browser stays open.
            from accounts.models import MfaDevice
            operator = get_user_model().objects.get(username='auditOperator')
            assert operator.is_active and operator.is_staff and operator.is_superuser
            MfaDevice.objects.filter(user=mfa_fixture_user).delete()
        for label, gate in gates.items():
            gate.clear() if label in (data.get("hold_apps"), data.get("hold_write"), data.get("hold_file")) else gate.set()
        return JsonResponse({"ok": True})

    @csrf_exempt
    def code(request):
        return JsonResponse({"code": totp.totp_at(json.loads(request.body)["secret"], __import__("time").time())})

    def observations(request):
        return JsonResponse({"seen": seen, "requests": requests})

    def document_network(request):
        requests.append({'path':'DOCUMENT_NETWORK_BEACON','method':request.method})
        return HttpResponse('Forbidden document resource')

    def me(request):
        if controls.get("fail_me"):
            return JsonResponse({"detail": "Synthetic authentication outage"}, status=503)
        return MeView.as_view()(request)

    def logout(request):
        if controls.get("fail_logout"):
            return JsonResponse({"detail": "Synthetic logout failure"}, status=503)
        return views.context_logout(request)

    def harness(request):
        return HttpResponse((ROOT / "tests/frontend/gateway-security-browser.html").read_text())

    def transport_only(request):
        # Measure direct reads without React initialization or tab lifecycle work.
        # Lifecycle behavior remains exercised in the real application tabs.
        import re
        response = views.index(request)
        html = re.sub(r'<script type="text/babel"[^>]*>.*?</script>', '', response.content.decode(), flags=re.S)
        quiet = '<script>Object.defineProperty(document,"visibilityState",{get:()=>"hidden"});window.addEventListener("focus",e=>e.stopImmediatePropagation(),true);document.addEventListener("visibilitychange",e=>e.stopImmediatePropagation(),true);</script>'
        response.content = html.replace('<script src="/gateway-session.js">', quiet + '<script src="/gateway-session.js">')
        return response

    def index(request):
        return transport_only(request) if request.GET.get('__transport') else views.index(request)

    @csrf_exempt
    def report(request):
        result = json.loads(request.body)
        print("BROWSER_RESULTS " + json.dumps(result), flush=True)
        return JsonResponse({"ok": True})

    urlpatterns = [
        path('app/', include((web_patterns + [path('multipart/', native_multipart, name='application-action')], 'web'))),
        path('admin/', admin.site.urls),
        path('static/<path:path>', lambda request, path: static_serve(request, path, insecure=True)),
        path("__test/config", configure), path("__test/seen", observations), path("__test/code", code),
        path("__test/report", report), path("__test/gateway-security", harness),
        path('__test/docx-network', document_network),
        path("api/auth/me", me, name="auth-me"), path("api/auth/logout", logout, name="auth-logout"),
        path("", index), path("<str:name>", asset), path("", include("gateway.urls")),
    ]
    from django.core.wsgi import get_wsgi_application
    application = get_wsgi_application()
    def instrumented(environ, start_response):
        route = environ["PATH_INFO"]
        requests.append({"path": route, "method": environ["REQUEST_METHOD"]})
        if route == "/api/auth/csrf" and controls.get("hold_csrf"):
            delays["csrf"].wait(15)
        if route == "/api/gateway/context":
            if controls.get("hold_context"):
                delays["context"].wait(15)
            if controls.get("fail_context"):
                start_response("503 Service Unavailable", [("Content-Type", "application/json")])
                return [b'{"detail":"Synthetic context outage"}']
        held_headers = environ.get('HTTP_X_JTH_TEST_HOLD') == 'auth-header'
        broken_body = environ.get('HTTP_X_JTH_TEST_BREAK_BODY') == 'yes'
        captured = []
        def capture(status, headers, exc_info=None):
            captured.append((status, headers, exc_info))
        body = application(environ, capture if held_headers else start_response)
        if held_headers:
            requests.append({'path':route, 'method':environ['REQUEST_METHOD'], 'committed':True,
                             'marker':'held-auth-header','status':int(captured[0][0].split()[0])})
            delays['headers'].wait(20)
            start_response(*captured[0])
        if broken_body:
            def broken():
                try:
                    for part in body:
                        yield part[:1]  # original Content-Length makes the browser detect truncation
                        return
                finally:
                    if hasattr(body, 'close'): body.close()
            return broken()
        if route == "/api/auth/me" and controls.get("hold_native"):
            # Flush headers (including cookies) before delaying the body. Session
            # saves/locks are complete; this models an in-flight native reply.
            def delayed():
                try:
                    for part in body:
                        yield part[:1]
                        delays["native"].wait(15)
                        yield part[1:]
                finally:
                    if hasattr(body, "close"):
                        body.close()
            return delayed()
        return body

    class Server(ThreadingMixIn, WSGIServer):
        daemon_threads = True
    class Quiet(WSGIRequestHandler):
        def log_message(self, *args):
            pass
    try:
        with make_server("127.0.0.1", args.port, instrumented, server_class=Server, handler_class=Quiet) as server:
            print(f"READY http://127.0.0.1:{args.port}/__test/gateway-security (disposable data: {directory})", flush=True)
            server.serve_forever()
    finally:
        for gate in gates.values():
            gate.set()
        for delay in delays.values():
            delay.set()
        stub.shutdown()
        stub.server_close()
