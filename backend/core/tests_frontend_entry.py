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
