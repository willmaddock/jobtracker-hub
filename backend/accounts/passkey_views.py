"""Passkey endpoints. Management lives under /api/account/passkeys/ (guarded by the MFA
middleware: verified sessions only). Sign-in lives under /api/auth/mfa/passkey/ and completes the
same pending login as an authenticator code does."""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import mfa, mfa_session, passkeys
from .models import MfaDevice, PasskeyCredential
from .serializers import PasskeyCredentialSerializer, PasskeyRegisterSerializer, UserSerializer
from .throttles import MfaThrottle
from .views import _complete_login, _mfa_error

_ERROR_STATUS = {
    "passkeys_unavailable": status.HTTP_404_NOT_FOUND,
    "passkey_not_registered": status.HTTP_400_BAD_REQUEST,
    "passkey_challenge_invalid": status.HTTP_400_BAD_REQUEST,
    "passkey_limit_reached": status.HTTP_409_CONFLICT,
}
_MESSAGES = {
    "passkeys_unavailable": "Passkeys are not available on this server.",
    "passkey_not_registered": "No passkey is registered for this account.",
    "passkey_challenge_invalid": "That passkey request expired. Try again.",
    "passkey_invalid": "That passkey was not accepted.",
    "passkey_limit_reached": "The passkey limit has been reached. Remove one first.",
}


def _passkey_error(error, *, invalid_status=status.HTTP_400_BAD_REQUEST):
    http_status = _ERROR_STATUS.get(error.code, invalid_status)
    return _mfa_error(error.code, _MESSAGES.get(error.code, "Passkey request failed."), http_status)


def _device_for(user):
    return MfaDevice.objects.filter(user=user, confirmed_at__isnull=False).first()


def _second_step_user(request):
    return mfa_session.second_step_user(request)


# --- management (verified sessions) --------------------------------------------------------

@method_decorator(never_cache, name="dispatch")
class PasskeyListView(APIView):
    def get(self, request):
        rows = PasskeyCredential.objects.filter(
            device__user=request.user, device__confirmed_at__isnull=False
        ).order_by("created_at")
        return Response({
            "available": passkeys.available(),
            "passkeys": [
                {"id": r.pk, "name": r.name, "created_at": r.created_at, "last_used_at": r.last_used_at} for r in rows
            ],
        })


class PasskeyDetailView(APIView):
    def delete(self, request, pk):
        get_object_or_404(PasskeyCredential, pk=pk, device__user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(never_cache, name="dispatch")
class PasskeyRegisterOptionsView(APIView):
    throttle_classes = [MfaThrottle]

    def post(self, request):
        if not passkeys.available():
            return _passkey_error(passkeys.Unavailable())
        device = _device_for(request.user)
        if device is None:
            return _mfa_error("mfa_not_enrolled", "Set up an authenticator app first.", status.HTTP_400_BAD_REQUEST)
        try:
            return Response(passkeys.registration_options(request, device))
        except passkeys.PasskeyError as error:
            return _passkey_error(error)


@method_decorator(never_cache, name="dispatch")
class PasskeyRegisterVerifyView(APIView):
    throttle_classes = [MfaThrottle]

    def post(self, request):
        serializer = PasskeyRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = _device_for(request.user)
        if device is None:
            return _mfa_error("mfa_not_enrolled", "Set up an authenticator app first.", status.HTTP_400_BAD_REQUEST)
        try:
            row = passkeys.register(
                request, device, serializer.validated_data["credential"], serializer.validated_data.get("name", ""),
            )
        except passkeys.PasskeyError as error:
            return _passkey_error(error)
        return Response(
            {"id": row.pk, "name": row.name, "created_at": row.created_at, "last_used_at": row.last_used_at},
            status=status.HTTP_201_CREATED,
        )


# --- sign-in (second step) -----------------------------------------------------------------

@method_decorator(csrf_protect, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class PasskeySignInOptionsView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [MfaThrottle]

    def post(self, request):
        if not passkeys.available():
            return _passkey_error(passkeys.Unavailable())
        user = _second_step_user(request)
        if user is None:
            return _mfa_error("mfa_session_expired", "Sign in again.", status.HTTP_401_UNAUTHORIZED)
        device = _device_for(user)
        if device is None:
            return _mfa_error("mfa_not_enrolled", "Multi-factor authentication is not set up.", status.HTTP_400_BAD_REQUEST)
        if device.locked_at is not None:
            return _mfa_error("mfa_locked", "Too many incorrect codes. Ask an administrator to reset your account.", status.HTTP_403_FORBIDDEN)
        try:
            return Response(passkeys.authentication_options(request, device))
        except passkeys.PasskeyError as error:
            return _passkey_error(error)


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class PasskeySignInVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [MfaThrottle]

    def post(self, request):
        serializer = PasskeyCredentialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = _second_step_user(request)
        if user is None:
            return _mfa_error("mfa_session_expired", "Sign in again.", status.HTTP_401_UNAUTHORIZED)
        device = _device_for(user)
        if device is None:
            return _mfa_error("mfa_not_enrolled", "Multi-factor authentication is not set up.", status.HTTP_400_BAD_REQUEST)
        if device.locked_at is not None:
            return _mfa_error("mfa_locked", "Too many incorrect codes. Ask an administrator to reset your account.", status.HTTP_403_FORBIDDEN)
        try:
            passkeys.authenticate(request, device, serializer.validated_data["credential"])
        except passkeys.PasskeyError as error:
            return _passkey_error(error, invalid_status=status.HTTP_401_UNAUTHORIZED)
        _complete_login(request, user)
        return Response({
            **UserSerializer(user).data,
            "mfa_method": "passkey",
            "recovery_codes_remaining": mfa.remaining_recovery_codes(user),
        })
