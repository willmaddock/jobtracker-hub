"""Explicit same-origin entry; only allowlisted public frontend assets are served."""
from pathlib import Path

from django.http import FileResponse, Http404, HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

FRONTEND = Path(__file__).resolve().parents[2] / "_app" / "frontend"
ASSETS = {"api-client.js", "workspace-context.js", "favicon.svg", "favicon.ico",
          "apple-touch-icon.png", "manifest.json", "icon-192.png", "icon-512.png"}


@require_GET
@never_cache
def index(request):
    html = (FRONTEND / "index.html").read_text()
    html = html.replace("<!-- DJANGO_FOUNDATION_BOOTSTRAP -->",
                        '<script>window.JTH_DJANGO = true;</script>')
    return HttpResponse(html)


@require_GET
def asset(request, name):
    if name not in ASSETS:
        raise Http404
    return FileResponse((FRONTEND / name).open("rb"))
