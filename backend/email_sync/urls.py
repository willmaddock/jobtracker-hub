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

from .retained_views import (
    MailboxLineageDetail, RetainedMessageDetail, RetainedMessageList,
    RetainedObservationDetail, RetainedObservationList,
)

urlpatterns += [
    path("workspaces/<int:workspace_id>/retained-messages/", RetainedMessageList.as_view(), name="retained-message-list"),
    path("workspaces/<int:workspace_id>/retained-messages/<int:pk>/", RetainedMessageDetail.as_view(), name="retained-message-detail"),
    path("workspaces/<int:workspace_id>/retained-observations/", RetainedObservationList.as_view(), name="retained-observation-list"),
    path("workspaces/<int:workspace_id>/retained-observations/<int:pk>/", RetainedObservationDetail.as_view(), name="retained-observation-detail"),
    path("workspaces/<int:workspace_id>/mailbox-lineages/<int:pk>/", MailboxLineageDetail.as_view(), name="mailbox-lineage-detail"),
]
