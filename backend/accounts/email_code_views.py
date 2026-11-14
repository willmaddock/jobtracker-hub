"""Emailed-code endpoints. Management lives under /api/account/mfa/email/ (verified sessions only,
guarded by the MFA middleware). Sign-in lives under /api/auth/mfa/email/ and completes the same
pending login as an authenticator code or passkey does."""
from __future__ import annotations

from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import email_codes, mfa
from .passkey_views import _device_for
from .serializers import MfaCodeSerializer, UserSerializer
from .throttles import MfaThrottle
from . import mfa_session
from .views import _complete_login, _mfa_error

_STATUS = {
    "email_codes_unavailable": status.HTTP_404_NOT_FOUND,
    "email_codes_not_enabled": status.HTTP_400_BAD_REQUEST,
    "email_address_missing": status.HTTP_400_BAD_REQUEST,
    "email_code_send_failed": status.HTTP_502_BAD_GATEWAY,
    "email_code_wait": status.HTTP_429_TOO_MANY_REQUESTS,
    "mfa_locked": status.HTTP_403_FORBIDDEN,
}
_MESSAGES = {
    "email_codes_unavailable": "Emailed codes are not available on this server.",
    "email_codes_not_enabled": "Emailed codes are not turned on for this account.",
    "email_address_missing": "Your account has no email address. Ask an administrator to add one.",
    "email_code_send_failed": "The code could not be sent. Try again later.",
    "email_code_wait": "A code was sent recently. Wait a moment before asking for another.",
    "email_code_invalid": "That code is not valid or has expired.",
    "mfa_locked": "Too many incorrect codes. Ask an administrator to reset your account.",
}


def _email_error(error, *, invalid_status=status.HTTP_400_BAD_REQUEST):
    http_status = _STATUS.get(error.code, invalid_status)
    response = _mfa_error(error.code, _MESSAGES.get(error.code, "Emailed code request failed."), http_status)
    if isinstance(error, email_codes.TooSoon):
        response["Retry-After"] = str(error.retry_after)
        response.data["retry_after"] = error.retry_after
    return response


# --- management (verified sessions) --------------------------------------------------------

@method_decorator(never_cache, name="dispatch")
class EmailCodeSettingsView(APIView):
    def get(self, request):
        device = _device_for(request.user)
        address = device.email_codes_address if device else ""
        return Response({
            "available": email_codes.available(),
            "enabled": bool(address),
            "address": email_codes.mask(address) if address else None,
            "pending_address": email_codes.pending_enable_address(device) if device and not address else None,
            "has_email_on_file": bool((request.user.email or "").strip()),
        })

    def delete(self, request):
        device = _device_for(request.user)
        if device is not None:
            email_codes.disable(device)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(never_cache, name="dispatch")
class EmailCodeBeginView(APIView):
    throttle_classes = [MfaThrottle]

    def post(self, request):
        device = _device_for(request.user)
        if device is None:
            return _mfa_error("mfa_not_enrolled", "Set up an authenticator app first.", status.HTTP_400_BAD_REQUEST)
        try:
            sent_to = email_codes.begin_enable(request.user, device)
        except email_codes.EmailCodeError as error:
            return _email_error(error)
        return Response({"sent_to": sent_to})


@method_decorator(never_cache, name="dispatch")
class EmailCodeConfirmView(APIView):
    throttle_classes = [MfaThrottle]

    def post(self, request):
        serializer = MfaCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = _device_for(request.user)
        if device is None:
            return _mfa_error("mfa_not_enrolled", "Set up an authenticator app first.", status.HTTP_400_BAD_REQUEST)
        try:
            address = email_codes.confirm_enable(device, serializer.validated_data["code"])
        except email_codes.EmailCodeError as error:
            return _email_error(error)
        return Response({"enabled": True, "address": address})


# --- sign-in (second step) -----------------------------------------------------------------

@method_decorator(csrf_protect, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class EmailSignInSendView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [MfaThrottle]

    def post(self, request):
        user = mfa_session.second_step_user(request)
        if user is None:
            return _mfa_error("mfa_session_expired", "Sign in again.", status.HTTP_401_UNAUTHORIZED)
        device = _device_for(user)
        if device is None:
            return _mfa_error("mfa_not_enrolled", "Multi-factor authentication is not set up.", status.HTTP_400_BAD_REQUEST)
        if device.locked_at is not None:
            return _email_error(email_codes.Locked())
        try:
            sent_to = email_codes.send_signin_code(device)
        except email_codes.EmailCodeError as error:
            return _email_error(error)
        return Response({"sent_to": sent_to})


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class EmailSignInVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [MfaThrottle]

    def post(self, request):
        serializer = MfaCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = mfa_session.second_step_user(request)
        if user is None:
            return _mfa_error("mfa_session_expired", "Sign in again.", status.HTTP_401_UNAUTHORIZED)
        device = _device_for(user)
        if device is None:
            return _mfa_error("mfa_not_enrolled", "Multi-factor authentication is not set up.", status.HTTP_400_BAD_REQUEST)
        try:
            email_codes.verify_signin_code(device, serializer.validated_data["code"])
        except email_codes.EmailCodeError as error:
            return _email_error(error, invalid_status=status.HTTP_401_UNAUTHORIZED)
        _complete_login(request, user)
        return Response({
            **UserSerializer(user).data,
            "mfa_method": "email",
            "recovery_codes_remaining": mfa.remaining_recovery_codes(user),
        })
