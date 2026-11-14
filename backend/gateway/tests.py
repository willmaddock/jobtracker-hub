"""Gateway tests. The private app is replaced by a stub HTTP server, so no FastAPI is needed."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings
from django.urls import include, path

from gateway import session_context, views
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


urlpatterns = [path("", views.index), path("", include("gateway.urls"))]


@override_settings(ROOT_URLCONF="gateway.tests", MFA_REQUIRED=False, JTH_ALLOW_LOCAL_LINK=False, JTH_GATEWAY=True)
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

    def bind(self):
        response = self.client.get("/")
        page = json.loads(re.search(r"window.JTH_GATEWAY_PAGE = (\{.*?\});", response.content.decode()).group(1))
        self.client.defaults["HTTP_X_JTH_CONTEXT"] = page["binding"]
        return page["binding"]

    def login(self, user=None):
        user = user or self.user
        binding = self.bind()
        response = self.client.post('/api/auth/login', {'username':user.username, 'password':'pw-not-used-12345'},
                                    content_type='application/json', HTTP_X_JTH_CONTEXT=binding)
        self.assertEqual(response.status_code, 200, response.content)
        self.client.defaults['HTTP_X_JTH_CONTEXT'] = response[session_context.HEADER]
        return response[session_context.HEADER]

    def test_anonymous_is_refused_and_nothing_is_forwarded(self):
        r = self.client.get("/api/applications")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(SEEN, [])

    def test_signed_in_request_is_forwarded_with_token_and_without_cookies(self):
        self.login()
        r = self.client.get("/api/applications?x=1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b'{"ok": true}')
        self.assertEqual(SEEN[0]["path"], "/api/applications?x=1")
        self.assertEqual(SEEN[0]["token"], "tok")
        self.assertIsNone(SEEN[0]["cookie"])
        self.assertNotIn("leak", r.cookies)

    def test_desktop_only_endpoints_are_blocked(self):
        self.login()
        for method, url in (("post", "/api/open"), ("post", "/api/open-url"), ("get", "/api/diagnostics"),
                            ("post", "/api/workspaces/link"), ("post", "/api/accounts/mail-app/connect")):
            r = getattr(self.client, method)(url, data="{}", content_type="application/json",
                                             HTTP_SEC_FETCH_SITE="same-origin") if method == "post" else self.client.get(url)
            self.assertEqual(r.status_code, 403, url)
        self.assertEqual(SEEN, [])

    @override_settings(JTH_ALLOW_LOCAL_LINK=True)
    def test_link_needs_superuser_even_when_enabled(self):
        self.login()
        r = self.client.post("/api/workspaces/link", data="{}", content_type="application/json",
                             HTTP_SEC_FETCH_SITE="same-origin")
        self.assertEqual(r.status_code, 403)

    def test_cross_site_post_is_refused(self):
        self.login()
        r = self.client.post("/api/applications/new", data="{}", content_type="application/json",
                             HTTP_SEC_FETCH_SITE="cross-site")
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/applications/new", data="{}", content_type="application/json",
                             HTTP_ORIGIN="https://evil.example")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(SEEN, [])

    def test_same_origin_post_body_is_forwarded(self):
        self.login()
        r = self.client.post("/api/applications/new", data='{"a": 1}', content_type="application/json",
                             HTTP_SEC_FETCH_SITE="same-origin")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(SEEN[0]["body"], b'{"a": 1}')

    @override_settings(JTH_MAX_UPLOAD_MB=1)
    def test_oversized_upload_is_refused_and_names_the_limit(self):
        self.login()
        r = self.client.post("/api/applications/new", data=b"x" * (1024 * 1024 + 1),
                             content_type="application/octet-stream", HTTP_SEC_FETCH_SITE="same-origin")
        self.assertEqual(r.status_code, 413)
        self.assertIn("limit is 1 MB", r.json()["detail"])
        self.assertEqual(SEEN, [])  # refused before anything reached the private app

    def test_status_reports_not_packaged_to_the_browser(self):
        self.login()
        self.assertEqual(self.client.get("/api/status").json()["packaged"], False)

    def test_missing_binding_is_rejected_before_starting_backend(self):
        self.login()
        self.client.defaults.pop("HTTP_X_JTH_CONTEXT")
        with mock.patch.object(views, "_connect") as connect:
            response = self.client.get("/api/applications")
        self.assertEqual(response.status_code, 409)
        self.assertIn(response.json()["code"], {"gateway_context_changed", "gateway_lineage_expired"})
        connect.assert_not_called()

    def test_forged_binding_is_not_identity_authority(self):
        self.login()
        for token in (str(self.user.pk), "invalid", self.bind() + "tampered"):
            self.assertEqual(self.client.post("/api/applications/new", {},
                HTTP_X_JTH_CONTEXT=token, HTTP_SEC_FETCH_SITE="same-origin").status_code, 409)
        self.assertEqual(SEEN, [])

    def test_old_page_cannot_read_or_write_under_another_account(self):
        other = get_user_model().objects.create_user(username="other", password="unused")
        self.login()
        self.client.force_login(other)  # retains the old page's binding
        for method in ("get", "post"):
            response = getattr(self.client, method)("/api/applications", HTTP_SEC_FETCH_SITE="same-origin")
            self.assertEqual(response.status_code, 409)
        self.assertEqual(SEEN, [])

    def test_binding_does_not_authenticate_a_logged_out_user(self):
        self.login()
        self.client.logout()
        self.assertEqual(self.client.get("/api/applications").status_code, 409)
        self.assertEqual(SEEN, [])

    def test_authenticated_file_fetch_uses_header_without_forwarding_it(self):
        token = self.login()
        response = self.client.get("/api/file", {"relpath": "fixture.pdf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b'{"ok": true}')
        self.assertEqual(SEEN[0]["path"], "/api/file?relpath=fixture.pdf")
        self.assertNotIn(token, SEEN[0]["path"])
        self.assertIn("no-store", response["Cache-Control"])

    def test_context_in_query_is_always_rejected(self):
        token = self.login()
        for route in ("file", "applications"):
            for key in ("_jth_page", "_jth_context"):
                response = self.client.get("/api/" + route, {key: token})
                self.assertEqual(response.status_code, 409)
        self.assertEqual(SEEN, [])

    def test_expired_binding_is_rejected(self):
        self.login()
        value = signing.loads(self.bind(), salt=session_context.SALT)
        with mock.patch("django.core.signing.time.time", return_value=0):
            token = signing.dumps(value, salt=session_context.SALT)
        self.assertEqual(self.client.get("/api/applications", HTTP_X_JTH_CONTEXT=token).status_code, 409)
        self.assertEqual(SEEN, [])

    def test_stale_file_header_is_not_served_to_another_account(self):
        self.login()
        other = get_user_model().objects.create_user(username="other", password="unused")
        self.client.force_login(other)
        response = self.client.get("/api/file", {"relpath": "fixture.pdf"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(SEEN, [])

    @override_settings(MFA_REQUIRED=True)
    def test_session_without_mfa_is_refused(self):
        self.login()
        self.assertEqual(self.client.get("/api/applications").status_code, 403)


@override_settings(MFA_REQUIRED=False, JTH_GATEWAY=True, ROOT_URLCONF="gateway.tests")
class GatewayIndexTests(TestCase):
    def test_anonymous_gets_login_screens(self):
        r = self.client.get("/")
        self.assertContains(r, "window.JTH_DJANGO = true;")

    def test_anonymous_is_not_marked_as_gateway_app(self):
        # The page's own code reads window.JTH_GATEWAY, so check for the assignment the server injects.
        self.assertNotContains(self.client.get("/"), "window.JTH_GATEWAY = true;")

    def test_signed_in_gets_original_app(self):
        user = get_user_model().objects.create_user(username="u2", password="pw-not-used-12345")
        page = self.client.get('/')
        binding = json.loads(re.search(r"window.JTH_GATEWAY_PAGE = (\{.*?\});", page.content.decode()).group(1))['binding']
        self.client.post('/api/auth/login', {'username':user.username,'password':'pw-not-used-12345'}, content_type='application/json', HTTP_X_JTH_CONTEXT=binding)
        r = self.client.get("/")
        self.assertNotContains(r, "window.JTH_DJANGO = true;")
        self.assertContains(r, "window.JTH_GATEWAY = true;")
        self.assertNotContains(r, "Sign out of JobTracker Hub")  # no floating button any more

    def test_page_binding_is_server_generated_and_not_cached(self):
        user = get_user_model().objects.create_user(username="bound", password="pw-not-used-12345")
        page = self.client.get('/')
        binding = json.loads(re.search(r"window.JTH_GATEWAY_PAGE = (\{.*?\});", page.content.decode()).group(1))['binding']
        self.client.post('/api/auth/login', {'username':user.username,'password':'pw-not-used-12345'}, content_type='application/json', HTTP_X_JTH_CONTEXT=binding)
        response = self.client.get("/")
        self.assertContains(response, '"actor": "' + str(user.pk) + '"')
        self.assertContains(response, '"binding":')
        self.assertContains(response, '/gateway-session.js')
        self.assertIn("no-store", response["Cache-Control"])

    def test_login_screen_marks_gateway_cache_cleanup(self):
        self.assertContains(self.client.get("/"), "window.JTH_GATEWAY_LOGIN = true;")
