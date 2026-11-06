"""Production-only liveness responder for TLS-terminating load balancers."""
from django.http import JsonResponse


class HealthCheckMiddleware:
    """Answer GET/HEAD /api/health before host validation and the HTTPS redirect.

    Load-balancer probes arrive over plain HTTP with the target IP as Host, which
    ALLOWED_HOSTS and SECURE_SSL_REDIRECT would otherwise reject. Liveness only:
    no database or service access, same body as core.views.HealthView.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info == "/api/health" and request.method in ("GET", "HEAD"):
            return JsonResponse({"ok": True})
        return self.get_response(request)
