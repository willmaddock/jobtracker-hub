"""Gateway tests. The private app is replaced by a stub HTTP server, so no FastAPI is needed."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import include, path

from gateway import views
from gateway.backends import Backend

SEEN = []


class _Stub(BaseHTTPRequestHandler):
    def _go(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        SEEN.append({"method": self.command, "path": self.path, "token": self.headers.get("X-JTH-Gateway-Token"),
                     "cookie": self.headers.get("Cookie"), "body": body})
        if self.path.startswith("/api/status"):
            payload = json.dumps({"packaged": True, "index_built": False}).encode()
        else:
            payload = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Set-Cookie", "leak=1")
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_DELETE = _go

    def log_message(self, *args):
        pass


class _FakeBackends:
    def __init__(self, port):
        self.port = port

    def ensure(self, user):
        return Backend(self.port, "tok")


urlpatterns = [path("", include("gateway.urls"))]


@override_settings(ROOT_URLCONF="gateway.tests", MFA_REQUIRED=False, JTH_ALLOW_LOCAL_LINK=False)
class GatewayProxyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        super().tearDownClass()

    def setUp(self):
        SEEN.clear()
        self.user = get_user_model().objects.create_user(username="u1", password="pw-not-used-12345")
        patcher = mock.patch.object(views, "_backends", _FakeBackends(self.server.server_address[1]))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_anonymous_is_refused_and_nothing_is_forwarded(self):
        r = self.client.get("/api/applications")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(SEEN, [])

    def test_signed_in_request_is_forwarded_with_token_and_without_cookies(self):
        self.client.force_login(self.user)
        r = self.client.get("/api/applications?x=1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b'{"ok": true}')
        self.assertEqual(SEEN[0]["path"], "/api/applications?x=1")
        self.assertEqual(SEEN[0]["token"], "tok")
        self.assertIsNone(SEEN[0]["cookie"])
        self.assertNotIn("leak", r.cookies)

    def test_desktop_only_endpoints_are_blocked(self):
        self.client.force_login(self.user)
        for method, url in (("post", "/api/open"), ("post", "/api/open-url"), ("get", "/api/diagnostics"),
                            ("post", "/api/workspaces/link"), ("post", "/api/accounts/mail-app/connect")):
            r = getattr(self.client, method)(url, data="{}", content_type="application/json",
                                             HTTP_SEC_FETCH_SITE="same-origin") if method == "post" else self.client.get(url)
            self.assertEqual(r.status_code, 403, url)
        self.assertEqual(SEEN, [])

    @override_settings(JTH_ALLOW_LOCAL_LINK=True)
    def test_link_needs_superuser_even_when_enabled(self):
        self.client.force_login(self.user)
        r = self.client.post("/api/workspaces/link", data="{}", content_type="application/json",
                             HTTP_SEC_FETCH_SITE="same-origin")
        self.assertEqual(r.status_code, 403)

    def test_cross_site_post_is_refused(self):
        self.client.force_login(self.user)
        r = self.client.post("/api/applications/new", data="{}", content_type="application/json",
                             HTTP_SEC_FETCH_SITE="cross-site")
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/applications/new", data="{}", content_type="application/json",
                             HTTP_ORIGIN="https://evil.example")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(SEEN, [])

    def test_same_origin_post_body_is_forwarded(self):
        self.client.force_login(self.user)
        r = self.client.post("/api/applications/new", data='{"a": 1}', content_type="application/json",
                             HTTP_SEC_FETCH_SITE="same-origin")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(SEEN[0]["body"], b'{"a": 1}')

    def test_status_reports_not_packaged_to_the_browser(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/api/status").json()["packaged"], False)

    @override_settings(MFA_REQUIRED=True)
    def test_session_without_mfa_is_refused(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/api/applications").status_code, 403)


@override_settings(MFA_REQUIRED=False)
class GatewayIndexTests(TestCase):
    def test_anonymous_gets_login_screens(self):
        r = self.client.get("/")
        self.assertContains(r, "window.JTH_DJANGO = true;")

    def test_signed_in_gets_original_app(self):
        user = get_user_model().objects.create_user(username="u2", password="pw-not-used-12345")
        self.client.force_login(user)
        r = self.client.get("/")
        self.assertNotContains(r, "window.JTH_DJANGO = true;")
        self.assertContains(r, "Sign out of JobTracker Hub")
