from django.urls import path
from rest_framework.routers import DefaultRouter

from .email_code_views import (
    EmailCodeBeginView, EmailCodeConfirmView, EmailCodeSettingsView, EmailSignInSendView, EmailSignInVerifyView,
)
from .passkey_views import (
    PasskeyDetailView, PasskeyListView, PasskeyRegisterOptionsView, PasskeyRegisterVerifyView,
    PasskeySignInOptionsView, PasskeySignInVerifyView,
)
from .email_signin_views import SignInOptionsView, SignInStartView, SignInVerifyView
from .views import (
    CsrfView, LoginView, LogoutView, MeView, MfaEnrollBeginView, MfaEnrollConfirmView,
    MfaStatusView, MfaVerifyView, WorkspaceViewSet,
)

router = DefaultRouter()
router.register(r"workspaces", WorkspaceViewSet, basename="workspace")

urlpatterns = [
    path("auth/csrf", CsrfView.as_view(), name="auth-csrf"),
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("auth/me", MeView.as_view(), name="auth-me"),
    path("auth/options", SignInOptionsView.as_view(), name="auth-options"),
    path("auth/email/start", SignInStartView.as_view(), name="auth-email-start"),
    path("auth/email/verify", SignInVerifyView.as_view(), name="auth-email-verify"),
    path("auth/mfa/verify", MfaVerifyView.as_view(), name="auth-mfa-verify"),
    path("auth/mfa/status", MfaStatusView.as_view(), name="auth-mfa-status"),
    path("auth/mfa/enroll/begin", MfaEnrollBeginView.as_view(), name="auth-mfa-enroll-begin"),
    path("auth/mfa/enroll/confirm", MfaEnrollConfirmView.as_view(), name="auth-mfa-enroll-confirm"),
    path("auth/mfa/passkey/options", PasskeySignInOptionsView.as_view(), name="auth-mfa-passkey-options"),
    path("auth/mfa/passkey/verify", PasskeySignInVerifyView.as_view(), name="auth-mfa-passkey-verify"),
    path("auth/mfa/email/send", EmailSignInSendView.as_view(), name="auth-mfa-email-send"),
    path("auth/mfa/email/verify", EmailSignInVerifyView.as_view(), name="auth-mfa-email-verify"),
    path("account/mfa/email/", EmailCodeSettingsView.as_view(), name="account-mfa-email"),
    path("account/mfa/email/begin", EmailCodeBeginView.as_view(), name="account-mfa-email-begin"),
    path("account/mfa/email/confirm", EmailCodeConfirmView.as_view(), name="account-mfa-email-confirm"),
    path("account/passkeys/", PasskeyListView.as_view(), name="account-passkeys"),
    path("account/passkeys/register/options", PasskeyRegisterOptionsView.as_view(), name="account-passkey-register-options"),
    path("account/passkeys/register/verify", PasskeyRegisterVerifyView.as_view(), name="account-passkey-register-verify"),
    path("account/passkeys/<int:pk>/", PasskeyDetailView.as_view(), name="account-passkey-detail"),
] + router.urls
