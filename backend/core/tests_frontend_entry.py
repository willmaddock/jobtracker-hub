from django.test import SimpleTestCase
from core.frontend import FRONTEND


class FrontendEntryTests(SimpleTestCase):
    def test_explicit_django_entry_and_legacy_source(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "window.JTH_DJANGO = true;")
        self.assertContains(response, "<DjangoFoundation /> : <App />")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("window.JTH_DJANGO = true;", (FRONTEND / "index.html").read_text())

    def test_only_public_assets(self):
        for name in ("api-client.js", "workspace-context.js", "favicon.svg"):
            response = self.client.get("/" + name)
            self.assertEqual(response.status_code, 200)
            response.close()
        self.assertEqual(self.client.get("/api.py").status_code, 404)
        self.assertEqual(self.client.get("/../api.py").status_code, 404)

    def test_security_panel_can_set_up_the_authenticator_app(self):
        """Passkeys and emailed codes need an authenticator app, so the Security dialog must offer to
        set one up (users who sign in by emailed code are never prompted at login)."""
        html = (FRONTEND / "index.html").read_text()
        panel = html[html.index("function SecurityPanel("):html.index("function CodeBoxes(")]
        self.assertIn("/api/auth/mfa/status", panel)
        self.assertIn("/api/auth/mfa/enroll/begin", panel)
        self.assertIn("/api/auth/mfa/enroll/confirm", panel)
        self.assertIn("Set up authenticator app", panel)
        self.assertNotIn("is not available from this screen yet", panel)
        # "Two-step verification is on" is only shown for an enrolled account, never unconditionally.
        self.assertEqual(panel.count("Two-step verification is on"), 1)
        self.assertIn("enrolled ? <p>Two-step verification is on", panel)
