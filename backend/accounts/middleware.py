"""Refuse data access to logged-in sessions that have not completed MFA.

Enforced only when ``settings.MFA_REQUIRED`` is true (production forces it). This closes the
bypass in which a password-only session, for example from Django's own /admin/ login, would
otherwise reach product data: the check runs on every request, whichever view or login form
created the session.
"""
from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse

from . import mfa, mfa_session

_OPEN_PREFIXES = ("/api/auth/", "/static/")
_OPEN_EXACT = {"/api/health"}


def _guarded(path: str) -> bool:
    if path in _OPEN_EXACT or path.startswith(_OPEN_PREFIXES):
        return False
    return (path.startswith("/api/") or path == "/admin" or path.startswith("/admin/")
            or path == "/app" or path.startswith("/app/"))


class MfaEnforcementMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (settings.MFA_REQUIRED and request.user.is_authenticated
                and not mfa_session.is_verified(request) and _guarded(request.path_info)):
            if request.path_info.startswith("/api/"):
                code = "mfa_required" if mfa.is_enrolled(request.user) else "mfa_enrollment_required"
                response = JsonResponse({"code": code, "detail": "Multi-factor authentication is required."}, status=403)
                response["Cache-Control"] = "no-store"
                return response
            return HttpResponseRedirect("/")  # the app's sign-in completes verification
        return self.get_response(request)
