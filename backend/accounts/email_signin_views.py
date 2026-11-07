"""Passwordless email sign-in endpoints, all under /api/auth/ (open to the MFA middleware).

``start`` emails a code; ``verify`` checks it. What happens next follows the account:

* has an authenticator app  -> the usual pending-MFA step (a mailbox never downgrades an account);
* ``MFA_REQUIRED`` and not ``EMAIL_SIGNIN_SATISFIES_MFA`` -> signed in but unverified, so only
  authenticator enrolment works (same as a password sign-in today);
* otherwise -> fully signed in, with the session marked verified.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import login
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import email_signin, mfa, mfa_session, passkeys
from .serializers import UserSerializer
from .throttles import EmailSignInThrottle
from .views import _complete_login, _mfa_error

_STATUS = {
    "email_signin_unavailable": status.HTTP_404_NOT_FOUND,
    "email_invalid": status.HTTP_400_BAD_REQUEST,
    "email_code_send_failed": status.HTTP_502_BAD_GATEWAY,
    "email_code_wait": status.HTTP_429_TOO_MANY_REQUESTS,
    "email_code_invalid": status.HTTP_401_UNAUTHORIZED,
}
_MESSAGES = {
    "email_signin_unavailable": "Sign-in by email is not available on this server.",
    "email_invalid": "Enter a valid email address.",
    "email_code_send_failed": "The code could not be sent. Try again later.",
    "email_code_wait": "A code was sent recently. Wait a moment before asking for another.",
    "email_code_invalid": "That code is not valid or has expired.",
}


def _error(error):
    response = _mfa_error(error.code, _MESSAGES.get(error.code, "Sign-in failed."),
                          _STATUS.get(error.code, status.HTTP_400_BAD_REQUEST))
    if isinstance(error, email_signin.TooSoon):
        response["Retry-After"] = str(error.retry_after)
        response.data["retry_after"] = error.retry_after
    return response


class _StartSerializer(serializers.Serializer):
    email = serializers.CharField(max_length=320, trim_whitespace=True)


class _VerifySerializer(_StartSerializer):
    code = serializers.CharField(max_length=32, trim_whitespace=True, style={"input_type": "password"})


@method_decorator(never_cache, name="dispatch")
class SignInOptionsView(APIView):
    """Which sign-in methods this server offers, so the screen shows only working buttons."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"email_signin": email_signin.available(), "signup_open": email_signin.signup_open()})


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class SignInStartView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [EmailSignInThrottle]

    def post(self, request):
        serializer = _StartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            email_signin.request_code(serializer.validated_data["email"])
        except email_signin.SignInError as error:
            return _error(error)
        return Response({"sent": True})  # the same answer whether or not an account exists


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class SignInVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [EmailSignInThrottle]

    def post(self, request):
        serializer = _VerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user, created = email_signin.verify_code(
                serializer.validated_data["email"], serializer.validated_data["code"])
        except email_signin.SignInError as error:
            return _error(error)
        if mfa.is_enrolled(user):
            # The mailbox replaced the password only: the authenticator app is still required.
            mfa_session.start_pending(request, user)
            return Response({
                "mfa_required": True,
                "passkey_available": passkeys.has_passkeys(user),
                "email_code_available": False,  # the mailbox was just used; offering it again is no second factor
            })
        if settings.MFA_REQUIRED and not getattr(settings, "EMAIL_SIGNIN_SATISFIES_MFA", False):
            mfa_session.clear_pending(request)
            login(request, user)
            return Response({**UserSerializer(user).data, "mfa_enrollment_required": True, "new_account": created})
        _complete_login(request, user)
        return Response({**UserSerializer(user).data, "mfa_method": "email_signin", "new_account": created})
