"""Stable error codes alongside the existing DRF detail/field representations."""
from django.http import JsonResponse
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None
    code = getattr(exc, "default_code", None)
    if code != "csrf_failed":
        code = {401: "authentication_required", 403: "permission_denied",
                404: "not_found", 400: "validation_error"}.get(response.status_code, code or "request_failed")
    if isinstance(response.data, dict):
        response.data = {**response.data, "code": code}
    else:
        response.data = {"detail": response.data, "code": code}
    return response


def csrf_failure(request, reason=""):
    return JsonResponse({"code": "csrf_failed", "detail": "CSRF verification failed. Refresh and try again."}, status=403)
