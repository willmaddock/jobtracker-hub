"""
email_sync views: the Gmail and Outlook OAuth connect/callback
endpoints plus the manual "sync now" trigger (Phase 9,
docs/DJANGO_MIGRATION_PLAN.md).

The OAuth views return JSON, never an HTTP redirect to a frontend
route -- there's no frontend route to redirect to yet (no Phase 8
email-sync UI has been built), and a JSON response is trivially
adaptable by whatever frontend eventually calls this vs. a redirect
target baked in here that a later slice would just have to change
anyway.

EmailAccountSyncView and EmailAccountDisconnectView are deliberately
the smallest possible next slices on top of that: the former wires the
already-fully-tested sync_service.sync_account() up to something
callable at all, ahead of any real Celery/background scheduling; the
latter closes the gap oauth.py's own module docstring used to flag --
revoking a Gmail grant with Google, not just deleting the local row.
No Discovery/AccountMatch CRUD views live here yet -- reviewing what a
sync actually found is still a later slice.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Workspace

from . import imap_auth, oauth, outlook_oauth
from .imap_auth import ImapConnectionError
from .models import EmailAccount
from .oauth import OAuthConfigError
from .providers import ProviderAuthError, ProviderError, get_provider
from .sync_service import sync_account
from .tasks import sync_account_task

# Session keys used to carry OAuth CSRF state + which workspace
# initiated the connect across the redirect to Google and back --
# there is no other place to put this: the callback request is a
# fresh top-level navigation from Google, not a follow-up to the
# connect call a client could pass its own context on.
_SESSION_STATE_KEY = "gmail_oauth_state"
_SESSION_WORKSPACE_KEY = "gmail_oauth_workspace_id"
# PKCE verifier for the in-flight Gmail connect flow -- see
# oauth.build_flow()'s docstring for why this has to be threaded
# through the same session round trip as state, rather than left for
# the callback-time Flow to generate its own.
_SESSION_VERIFIER_KEY = "gmail_oauth_code_verifier"

# Same purpose as the Gmail session keys above, kept as separate keys
# (rather than reusing the Gmail ones) so a user could in principle
# have both a Gmail and an Outlook connect flow in flight in the same
# session without one clobbering the other's stashed state.
_OUTLOOK_SESSION_STATE_KEY = "outlook_oauth_state"
_OUTLOOK_SESSION_WORKSPACE_KEY = "outlook_oauth_workspace_id"


class GmailConnectView(APIView):
    """GET /api/email-accounts/gmail/connect?workspace=<id>

    Starts a Gmail OAuth connect flow: returns the Google consent-
    screen URL for the client to navigate the user to. Requires
    `workspace` so the eventual callback knows which of the user's
    workspaces the resulting EmailAccount belongs to -- EmailAccount
    is workspace-scoped, not user-scoped, same as every other owned
    resource in this codebase.
    """

    def get(self, request):
        workspace_id = request.query_params.get("workspace")
        if not workspace_id:
            return Response(
                {"detail": "workspace query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Ownership check mirrors WorkspaceViewSet.get_queryset -- a
        # user should never be able to kick off a connect flow that
        # lands an EmailAccount in a workspace they don't own.
        try:
            workspace = Workspace.objects.get(id=workspace_id, owner=request.user)
        except (Workspace.DoesNotExist, ValueError):
            return Response(
                {"detail": "No such workspace."}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            authorization_url, state, code_verifier = oauth.build_authorization_url()
        except OAuthConfigError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        request.session[_SESSION_STATE_KEY] = state
        request.session[_SESSION_WORKSPACE_KEY] = workspace.id
        request.session[_SESSION_VERIFIER_KEY] = code_verifier
        return Response({"authorization_url": authorization_url})


class GmailOAuthCallbackView(APIView):
    """GET /api/email-accounts/gmail/callback?code=...&state=...

    Google redirects the user's browser here after consent. permission
    AllowAny -- this is a top-level navigation initiated by Google, not
    a same-session API call the frontend makes, but the Django session
    cookie still rides along on that navigation (first-party, top-
    level), which is what lets this view recover which workspace/state
    GmailConnectView stashed without trusting anything the query string
    itself claims about them.
    """

    permission_classes = []
    authentication_classes = []

    def get(self, request):
        error = request.query_params.get("error")
        if error:
            return Response(
                {"detail": f"Gmail authorization was not granted: {error}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        if not code or not state:
            return Response(
                {"detail": "Missing code or state on Gmail OAuth callback."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        expected_state = request.session.get(_SESSION_STATE_KEY)
        workspace_id = request.session.get(_SESSION_WORKSPACE_KEY)
        if not expected_state or state != expected_state or not workspace_id:
            # Missing/mismatched state means this request didn't
            # originate from a GmailConnectView call this session made
            # -- classic OAuth CSRF, refuse rather than guess.
            return Response(
                {"detail": "Invalid or expired OAuth state."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            workspace = Workspace.objects.get(id=workspace_id)
        except Workspace.DoesNotExist:
            return Response(
                {"detail": "Workspace for this connect attempt no longer exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        code_verifier = request.session.get(_SESSION_VERIFIER_KEY)
        try:
            account = oauth.complete_gmail_connection(
                workspace, code=code, state=state, code_verifier=code_verifier
            )
        except OAuthConfigError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        finally:
            # One-time-use state regardless of outcome -- a failed
            # exchange shouldn't leave a replayable state (or PKCE
            # verifier) hanging around in the session.
            request.session.pop(_SESSION_STATE_KEY, None)
            request.session.pop(_SESSION_WORKSPACE_KEY, None)
            request.session.pop(_SESSION_VERIFIER_KEY, None)

        return Response(
            {"id": account.id, "email": account.email, "status": account.status},
            status=status.HTTP_200_OK,
        )


class OutlookConnectView(APIView):
    """GET /api/email-accounts/outlook/connect?workspace=<id>

    Starts an Outlook/Microsoft Graph OAuth connect flow: returns the
    Microsoft consent-screen URL for the client to navigate the user
    to. Mirrors GmailConnectView field-for-field -- same workspace-
    ownership check, same session-stashing of state, same 503 on a
    missing app registration.
    """

    def get(self, request):
        workspace_id = request.query_params.get("workspace")
        if not workspace_id:
            return Response(
                {"detail": "workspace query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            workspace = Workspace.objects.get(id=workspace_id, owner=request.user)
        except (Workspace.DoesNotExist, ValueError):
            return Response(
                {"detail": "No such workspace."}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            authorization_url, state = outlook_oauth.build_authorization_url()
        except outlook_oauth.OAuthConfigError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        request.session[_OUTLOOK_SESSION_STATE_KEY] = state
        request.session[_OUTLOOK_SESSION_WORKSPACE_KEY] = workspace.id
        return Response({"authorization_url": authorization_url})


class OutlookOAuthCallbackView(APIView):
    """GET /api/email-accounts/outlook/callback?code=...&state=...

    Microsoft redirects the user's browser here after consent. Mirrors
    GmailOAuthCallbackView field-for-field, including the AllowAny
    permission for the same reason: this is a top-level navigation
    initiated by Microsoft, not a same-session API call, but the
    Django session cookie still rides along on that navigation.
    """

    permission_classes = []
    authentication_classes = []

    def get(self, request):
        error = request.query_params.get("error")
        if error:
            return Response(
                {"detail": f"Outlook authorization was not granted: {error}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        if not code or not state:
            return Response(
                {"detail": "Missing code or state on Outlook OAuth callback."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        expected_state = request.session.get(_OUTLOOK_SESSION_STATE_KEY)
        workspace_id = request.session.get(_OUTLOOK_SESSION_WORKSPACE_KEY)
        if not expected_state or state != expected_state or not workspace_id:
            return Response(
                {"detail": "Invalid or expired OAuth state."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            workspace = Workspace.objects.get(id=workspace_id)
        except Workspace.DoesNotExist:
            return Response(
                {"detail": "Workspace for this connect attempt no longer exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            account = outlook_oauth.complete_outlook_connection(workspace, code=code, state=state)
        except outlook_oauth.OAuthConfigError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        finally:
            request.session.pop(_OUTLOOK_SESSION_STATE_KEY, None)
            request.session.pop(_OUTLOOK_SESSION_WORKSPACE_KEY, None)

        return Response(
            {"id": account.id, "email": account.email, "status": account.status},
            status=status.HTTP_200_OK,
        )


class ImapConnectView(APIView):
    """POST /api/email-accounts/imap/connect

    Body: {"workspace": <id>, "email": "...", "password": "...",
    "host": "...", "port": 993, "username": "..." (optional, defaults
    to email)}

    Unlike GmailConnectView/OutlookConnectView, this is not a redirect
    -into-a-consent-screen flow -- generic IMAP has no authorization
    server to redirect to, only a username/password the user already
    has (typically an app-specific password, per imap_auth.py's own
    module docstring). So this single POST both verifies the
    credentials with a real IMAP login and, on success, connects the
    account -- there is no separate callback view the way the OAuth
    providers need one.

    Ownership check mirrors GmailConnectView/OutlookConnectView: a
    user should never be able to land an EmailAccount in a workspace
    they don't own.
    """

    def post(self, request):
        workspace_id = request.data.get("workspace")
        email = request.data.get("email")
        password = request.data.get("password")
        host = request.data.get("host")
        port = request.data.get("port") or 993
        username = request.data.get("username") or None

        missing = [
            name
            for name, value in (
                ("workspace", workspace_id),
                ("email", email),
                ("password", password),
                ("host", host),
            )
            if not value
        ]
        if missing:
            return Response(
                {"detail": f"Missing required field(s): {', '.join(missing)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            port = int(port)
        except (TypeError, ValueError):
            return Response(
                {"detail": "port must be an integer."}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            workspace = Workspace.objects.get(id=workspace_id, owner=request.user)
        except (Workspace.DoesNotExist, ValueError):
            return Response(
                {"detail": "No such workspace."}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            account = imap_auth.connect_imap_account(
                workspace,
                email=email,
                password=password,
                host=host,
                port=port,
                username=username,
            )
        except ImapConnectionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except ProviderAuthError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except ProviderError as exc:
            # _reject_if_basic_auth_retired's plain ProviderError (a
            # domain known to no longer support IMAP basic auth at
            # all) -- a config/support-matrix gap, not a bad-password
            # gap, but still a 400: the request as given can never
            # succeed, regardless of retry.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"id": account.id, "email": account.email, "status": account.status},
            status=status.HTTP_200_OK,
        )


class EmailAccountSyncView(APIView):
    """POST /api/email-accounts/<id>/sync

    Runs one sync_service.sync_account() pass for a single, already-
    connected EmailAccount and returns its SyncResult as JSON. This is
    a manual trigger only -- no scheduling, no "sync all accounts,"
    and nothing calls this on its own; a real background scheduler
    (Celery/Django-Q) is a later slice, same as
    docs/DJANGO_BACKEND_HANDOFF.md's Known Gaps section says.

    get_object() is scoped to workspace__owner=request.user, same
    ownership pattern as every other per-object action in this
    codebase (see postings/views.py's JobPostingViewSet) -- a 404, not
    a 403, on another user's account so this endpoint never confirms
    that an id belongs to someone else.
    """

    def _get_account(self, request, pk):
        try:
            return EmailAccount.objects.get(pk=pk, workspace__owner=request.user)
        except (EmailAccount.DoesNotExist, ValueError):
            return None

    def post(self, request, pk=None):
        account = self._get_account(request, pk)
        if account is None:
            return Response({"detail": "No such email account."}, status=status.HTTP_404_NOT_FOUND)

        if account.status == "disconnected":
            return Response(
                {"detail": "This account is disconnected. Reconnect it before syncing."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            provider = get_provider(account.provider)
        except ProviderError as exc:
            # No provider registered for account.provider yet (e.g. a
            # legacy mail_app row, or a not-yet-built Outlook/IMAP
            # provider) -- this is a config/support-matrix gap, not a
            # per-sync-attempt failure, so it doesn't touch
            # account.status the way sync_account()'s own
            # ProviderAuthError handling does.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        result = sync_account(account, provider)
        body = {
            "account_id": result.account_id,
            "ok": result.ok,
            "error": result.error,
            "messages_seen": result.messages_seen,
            "new_matches": result.new_matches,
            "new_discoveries": result.new_discoveries,
            "skipped_existing": result.skipped_existing,
            "status": account.status,
        }
        # A sync that ran but found the account's credentials revoked
        # (result.ok=False, account now "blocked") is a legitimate,
        # already-handled outcome of sync_account() itself -- not a
        # server error -- so this still returns 200, same way
        # sync_account() itself doesn't raise for that case.
        return Response(body, status=status.HTTP_200_OK)


class EmailAccountSyncAllView(APIView):
    """POST /api/email-accounts/sync-all

    User-triggered counterpart to the sync_all_accounts_task Celery
    Beat schedule (config/settings/base.py, email_sync/tasks.py):
    dispatches one sync_account_task.delay(account.id) per currently-
    connected EmailAccount owned by request.user, across all of their
    workspaces, and returns immediately with the ids it queued rather
    than waiting for any of them to finish. This is the "sync all of a
    workspace's accounts" bulk endpoint flagged as missing in
    docs/DJANGO_BACKEND_HANDOFF.md §4 -- deliberately a background
    dispatch, not a loop calling sync_account() inline the way
    EmailAccountSyncView.post() does for a single account, since a
    user with several slow/large mailboxes shouldn't have this
    request block on all of them in series.

    Scoped to workspace__owner=request.user, same ownership pattern as
    every other per-user action in this module -- a user only ever
    dispatches syncs for their own accounts, never anyone else's.
    There's no id in this URL to leak a 404-vs-403 distinction over,
    unlike EmailAccountSyncView/EmailAccountDisconnectView.
    """

    def post(self, request):
        account_ids = list(
            EmailAccount.objects.filter(
                workspace__owner=request.user, status="connected"
            ).values_list("id", flat=True)
        )
        for account_id in account_ids:
            sync_account_task.delay(account_id)
        return Response(
            {"dispatched": len(account_ids), "account_ids": account_ids},
            status=status.HTTP_200_OK,
        )


class EmailAccountDisconnectView(APIView):
    """POST /api/email-accounts/<id>/disconnect

    Disconnects an EmailAccount: for a Gmail account, revokes the
    stored grant with Google (best-effort -- see
    oauth.disconnect_gmail_account's own docstring) and deletes the
    local GmailCredential row; for an Outlook account, deletes the
    local OutlookCredential row (no Microsoft-side revoke call is
    possible -- see outlook_oauth.disconnect_outlook_account's own
    docstring for why); for an IMAP account, deletes the local
    IMAPCredential row (no revoke call is possible there either -- see
    imap_auth.disconnect_imap_account's own docstring for why); for any
    other provider there's no credential model to clean up, so this is
    just a status flip. In
    both cases the EmailAccount row itself is kept, not deleted -- its
    sync history (AccountMatch/Discovery/ThreadIdentifier rows,
    matched_email_count) stays intact, and oauth.
    complete_gmail_connection()'s own get_or_create-by-(workspace,
    email, provider) already knows how to revive a disconnected row on
    reconnect rather than forking a duplicate.

    Idempotent: disconnecting an already-disconnected account just
    re-confirms that status rather than erroring, since there's
    nothing left to revoke or delete the second time.
    """

    def _get_account(self, request, pk):
        try:
            return EmailAccount.objects.get(pk=pk, workspace__owner=request.user)
        except (EmailAccount.DoesNotExist, ValueError):
            return None

    def post(self, request, pk=None):
        account = self._get_account(request, pk)
        if account is None:
            return Response({"detail": "No such email account."}, status=status.HTTP_404_NOT_FOUND)

        if account.status != "disconnected":
            if account.provider == "gmail":
                oauth.disconnect_gmail_account(account)
            elif account.provider == "outlook":
                outlook_oauth.disconnect_outlook_account(account)
            elif account.provider == "imap":
                imap_auth.disconnect_imap_account(account)
            else:
                # No credential model exists for any other provider
                # (e.g. a legacy mail_app/icloud row), so there's
                # nothing to revoke: just flip the status.
                account.status = "disconnected"
                account.save(update_fields=["status", "updated_at"])

        return Response({"id": account.id, "status": account.status}, status=status.HTTP_200_OK)
