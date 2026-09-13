"""Product access uses sessions, with distinct authentication and CSRF failures."""
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied


class CsrfFailed(PermissionDenied):
    default_detail = "CSRF verification failed. Refresh and try again."
    default_code = "csrf_failed"


class ProductSessionAuthentication(SessionAuthentication):
    def authenticate_header(self, request):
        # A challenge keeps DRF from converting missing authentication to 403.
        return "Session"

    def enforce_csrf(self, request):
        try:
            super().enforce_csrf(request)
        except PermissionDenied as exc:
            raise CsrfFailed() from exc
