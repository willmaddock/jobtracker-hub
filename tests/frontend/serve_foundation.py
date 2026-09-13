"""Disposable browser test server. Run with backend/venv/bin/python from repo root.

All database/media state lives in a new TemporaryDirectory. No tracker data or
.env database settings are used. Test-only routes are absent from product URLs.
"""
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.dev"

from django.conf import settings

with tempfile.TemporaryDirectory(prefix="jth-foundation-") as directory:
    settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(Path(directory) / "browser.sqlite3")}}
    settings.MEDIA_ROOT = str(Path(directory) / "media")
    settings.SESSION_COOKIE_NAME = "jth_foundation_session"
    settings.CSRF_COOKIE_NAME = "jth_foundation_csrf"
    settings.SECRET_KEY = "isolated-browser-test-only"
    settings.ROOT_URLCONF = __name__
    import django
    django.setup()
    from django.core.management import call_command
    from django.contrib.auth import get_user_model
    from django.http import HttpResponse, JsonResponse
    from django.urls import path
    from django.views.decorators.csrf import csrf_protect
    from accounts.models import Workspace
    from config.urls import urlpatterns as product_urls
    from rest_framework.views import APIView
    from rest_framework.response import Response
    call_command("migrate", verbosity=0)
    for username, names in (("alice", ["A", "B"]), ("bob", ["C"])):
        user = get_user_model().objects.create_user(username=username, password="browser-fixture-only")
        for name in names:
            Workspace.objects.create(owner=user, name=name)

    class UploadProbe(APIView):
        def post(self, request):
            file = request.FILES.get("file")
            return Response({"actor": request.user.username, "label": request.data.get("label"),
                             "filename": file.name if file else None,
                             "content": file.read().decode() if file else None})

    class SlowProbe(APIView):
        def get(self, request):
            time.sleep(1)
            return Response({"ok": True})

    def harness(request):
        return HttpResponse((ROOT / "tests/frontend/foundation-browser.html").read_text())

    urlpatterns = [path("foundation-tests", harness),
                   path("api/test-only/upload", UploadProbe.as_view()),
                   path("api/test-only/slow", SlowProbe.as_view())] + product_urls
    print("Disposable fixtures: alice / bob; password browser-fixture-only; workspaces A=1 B=2 C=3", flush=True)
    call_command("runserver", "127.0.0.1:8765", use_reloader=False)
