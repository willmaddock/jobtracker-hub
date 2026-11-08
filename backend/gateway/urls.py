from django.urls import include, path, re_path

from accounts import urls as accounts_urls
from core.views import HealthView

from . import views

# Only the sign-in / account-security routes and the workspace list (used to detect the
# two-step screen) stay with Django; everything else under /api/ belongs to the user's own app.
_django_routes = [
    p for p in accounts_urls.urlpatterns
    if str(p.pattern).startswith(("auth/", "account/")) or str(p.pattern) == "^workspaces/$"
]

urlpatterns = [
    path("api/health", HealthView.as_view()),
    path("api/", include(_django_routes)),
    re_path(r"^api/(?P<path>.+)$", views.proxy, name="gateway-proxy"),
]
