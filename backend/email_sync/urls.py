from django.urls import path

from .views import (
    EmailAccountDisconnectView,
    EmailAccountSyncAllView,
    EmailAccountSyncView,
    GmailConnectView,
    GmailOAuthCallbackView,
    ImapConnectView,
    OutlookConnectView,
    OutlookOAuthCallbackView,
)

urlpatterns = [
    path("email-accounts/gmail/connect", GmailConnectView.as_view(), name="gmail-oauth-connect"),
    path(
        "email-accounts/gmail/callback",
        GmailOAuthCallbackView.as_view(),
        name="gmail-oauth-callback",
    ),
    path(
        "email-accounts/outlook/connect",
        OutlookConnectView.as_view(),
        name="outlook-oauth-connect",
    ),
    path(
        "email-accounts/outlook/callback",
        OutlookOAuthCallbackView.as_view(),
        name="outlook-oauth-callback",
    ),
    path(
        "email-accounts/imap/connect",
        ImapConnectView.as_view(),
        name="imap-connect",
    ),
    path(
        "email-accounts/<int:pk>/sync",
        EmailAccountSyncView.as_view(),
        name="email-account-sync",
    ),
    path(
        "email-accounts/sync-all",
        EmailAccountSyncAllView.as_view(),
        name="email-account-sync-all",
    ),
    path(
        "email-accounts/<int:pk>/disconnect",
        EmailAccountDisconnectView.as_view(),
        name="email-account-disconnect",
    ),
]
