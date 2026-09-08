"""
Microsoft OAuth: connect/callback flow, encrypted token storage, and the
real `session_factory` OutlookProvider needs (Phase 9 second-provider
slice, docs/DJANGO_MIGRATION_PLAN.md). Same split as oauth.py/
gmail_provider.py: everything outlook_provider.py's module docstring
flagged as deliberately deferred lives here -- where OAuth tokens come
from, where they're stored, and how a stored EmailAccount turns into
an authorized Graph-calling session.

Deliberately NOT here, same as oauth.py's own docstring:
  - Any frontend/consent-screen UI. This module only ever hands back
    URLs and JSON; a browser client navigates to
    build_authorization_url()'s result and shows the user whatever it
    wants before/after.
  - A shared multi-provider abstraction. This is Microsoft-specific by
    design, same as oauth.py is Gmail-specific -- IMAP will need its
    own equivalent when that slice happens.

Uses the Microsoft identity platform's v2.0 authorization-code flow
directly via `requests` rather than the `msal` library: the flow
itself is three plain REST calls (authorize redirect, token exchange,
token refresh) and this project already depends on `requests` for
oauth.py's own Google-revoke call, so pulling in a second OAuth-
specific SDK for symmetry with google-auth-oauthlib wasn't worth a new
dependency.

Design note on encryption: access/refresh tokens are encrypted at the
field level with Fernet, same reasoning as oauth.py's own design note
-- a database backup/replica/read leak alone shouldn't be enough to
use anyone's mailbox. A *separate* key (settings.
MICROSOFT_TOKEN_ENCRYPTION_KEY, not GMAIL_TOKEN_ENCRYPTION_KEY) is
used so that rotating or leaking one provider's key never touches the
other provider's already-stored tokens.

Design note on revocation: unlike Google's OAuth2 v2 endpoint, the
Microsoft identity platform's v2.0 flow has no equivalent
application-callable "revoke this refresh token" REST endpoint for
work/school or personal Microsoft accounts -- a user revokes app
access themselves, at https://account.live.com/consent/Manage
(personal) or via their organization's admin (work/school).
disconnect_outlook_account() is therefore local-only: it deletes the
stored OutlookCredential so this app can no longer use the grant, but
cannot invalidate the refresh token on Microsoft's side the way
oauth.disconnect_gmail_account() can with Google. The stored refresh
token remains valid (unused) until it expires from disuse or the user
revokes it themselves.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlencode
from uuid import uuid4

import requests
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

from .models import EmailAccount, OutlookCredential
from .outlook_provider import OutlookProvider
from .providers import ProviderAuthError, ProviderError, register_provider

_AUTHORITY = "https://login.microsoftonline.com/common/oauth2/v2.0"
_AUTH_URI = f"{_AUTHORITY}/authorize"
_TOKEN_URI = f"{_AUTHORITY}/token"
_GRAPH_ME_URI = "https://graph.microsoft.com/v1.0/me"

# offline_access is required to get a refresh_token back at all (the
# v2.0 endpoint otherwise only issues a short-lived access token);
# Mail.Read is the least-privilege Graph scope covering
# outlook_provider.py's read-only /me/messages + $value usage; openid
# + email are requested so the id_token/userinfo round trip reliably
# includes an email claim, though complete_outlook_connection() below
# still confirms the address against Graph's own /me rather than
# trusting a token claim.
OUTLOOK_OAUTH_SCOPES = ["offline_access", "Mail.Read", "openid", "email"]

# access tokens are treated as expired this many seconds before their
# actual expiry, so a session built from a "still valid" token doesn't
# turn invalid mid-sync from clock drift or the time _load_graph_
# credentials() itself takes to run.
_EXPIRY_SKEW = timedelta(seconds=60)


class OAuthConfigError(Exception):
    """settings.MICROSOFT_OAUTH_CLIENT_ID/SECRET aren't configured.
    Not a ProviderError subclass, same reasoning as oauth.
    OAuthConfigError: this means the *app* was never registered in an
    Azure AD app registration, not that any particular user's
    credentials are invalid, so it shouldn't be caught anywhere
    sync_service.sync_account() handles per-account failures."""


def _require_client_config() -> dict:
    if not settings.MICROSOFT_OAUTH_CLIENT_ID or not settings.MICROSOFT_OAUTH_CLIENT_SECRET:
        raise OAuthConfigError(
            "MICROSOFT_OAUTH_CLIENT_ID/MICROSOFT_OAUTH_CLIENT_SECRET are not configured -- "
            "set them in the environment before starting an Outlook connect flow"
        )
    return {
        "client_id": settings.MICROSOFT_OAUTH_CLIENT_ID,
        "client_secret": settings.MICROSOFT_OAUTH_CLIENT_SECRET,
        "redirect_uri": settings.MICROSOFT_OAUTH_REDIRECT_URI,
    }


def _fernet() -> Fernet:
    return Fernet(settings.MICROSOFT_TOKEN_ENCRYPTION_KEY.encode("ascii"))


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        # Same story as oauth._decrypt: either MICROSOFT_TOKEN_
        # ENCRYPTION_KEY was rotated without migrating stored tokens,
        # or the row is corrupt -- either way this credential is
        # unusable, phrased the same way an actually-revoked grant
        # would be so callers don't need a third failure mode to
        # handle.
        raise ProviderAuthError(
            "stored Outlook credential can't be decrypted -- reconnect this account"
        ) from exc


def build_authorization_url() -> tuple[str, str]:
    """Returns (authorization_url, state). `state` must be stashed by
    the caller (OutlookConnectView stores it in the session, alongside
    which workspace initiated the connect) and checked against what
    comes back on the callback request -- standard OAuth CSRF
    protection, same purpose as oauth.build_authorization_url()'s own
    state handling. A random `state` is minted here directly (rather
    than via a Flow object, since this module doesn't use one) with
    `uuid4().hex`, which is unguessable enough for this purpose."""
    config = _require_client_config()
    state = uuid4().hex
    params = {
        "client_id": config["client_id"],
        "response_type": "code",
        "redirect_uri": config["redirect_uri"],
        "response_mode": "query",
        "scope": " ".join(OUTLOOK_OAUTH_SCOPES),
        "state": state,
        "prompt": "consent",
    }
    return f"{_AUTH_URI}?{urlencode(params)}", state


def _exchange_code_for_tokens(code: str) -> dict:
    config = _require_client_config()
    response = requests.post(
        _TOKEN_URI,
        data={
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config["redirect_uri"],
            "scope": " ".join(OUTLOOK_OAUTH_SCOPES),
        },
        timeout=10,
    )
    if response.status_code != 200:
        raise OAuthConfigError(
            f"Microsoft token endpoint rejected the authorization code exchange "
            f"({response.status_code}): {response.text[:500]}"
        )
    return response.json()


def _refresh_tokens(refresh_token: str) -> dict:
    config = _require_client_config()
    response = requests.post(
        _TOKEN_URI,
        data={
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join(OUTLOOK_OAUTH_SCOPES),
        },
        timeout=10,
    )
    if response.status_code != 200:
        # A refresh failing is what a revoked/expired grant looks
        # like from this endpoint -- same ProviderAuthError path
        # sync_service.sync_account() already catches from
        # OutlookProvider itself for API-call-time auth failures, so
        # account.status gets marked "blocked" through the exact same
        # path either way, same as oauth._load_google_credentials's
        # own RefreshError handling.
        raise ProviderAuthError(
            f"Outlook credential could not be refreshed ({response.status_code}) -- "
            "the grant was likely revoked; reconnect this account"
        )
    return response.json()


def _store_credentials(account: EmailAccount, token_response: dict) -> OutlookCredential:
    """Encrypt and persist `token_response` (a Microsoft token-endpoint
    JSON body) for `account`, creating or updating the one
    OutlookCredential row get_or_create's uniqueness (account is a
    OneToOneField) already enforces. refresh_token is only overwritten
    when Microsoft actually sends a new one -- same reasoning as
    oauth._store_credentials: a refresh response can omit it, and
    blanking a still-valid refresh_token on every routine access-token
    refresh would silently break every subsequent sync for no
    reason."""
    expires_in = token_response.get("expires_in")
    defaults = {
        "access_token": _encrypt(token_response["access_token"]),
        "token_expiry": (
            datetime.now(tz=dt_timezone.utc) + timedelta(seconds=int(expires_in))
            if expires_in is not None
            else None
        ),
        "scopes": token_response.get("scope", ""),
    }
    refresh_token = token_response.get("refresh_token")
    if refresh_token:
        defaults["refresh_token"] = _encrypt(refresh_token)

    cred, created = OutlookCredential.objects.get_or_create(account=account, defaults=defaults)
    if not created:
        for field, value in defaults.items():
            setattr(cred, field, value)
        cred.save(update_fields=list(defaults) + ["updated_at"])
    return cred


def complete_outlook_connection(workspace, code: str, state: str) -> EmailAccount:
    """The full callback-time exchange: authorization code -> tokens ->
    "whose mailbox is this" -> a connected EmailAccount with its
    OutlookCredential stored. Split out from OutlookOAuthCallbackView
    for the same reason oauth.complete_gmail_connection() is split out
    of GmailOAuthCallbackView: the view stays thin HTTP-response
    shaping and this stays plain, directly testable Python.

    The account's `email` has to come from Graph's own /me endpoint,
    never from the client or an unverified token claim -- same
    reasoning as complete_gmail_connection()'s own docstring: trusting
    a caller-supplied email would let anyone bind an OAuth grant for
    their own mailbox to a record claiming to be someone else's
    address.

    get_or_create on (workspace, email, provider), same as
    complete_gmail_connection(): reconnecting a previously-disconnected
    account revives the same EmailAccount row -- and its sync history
    -- rather than forking a second row for the same mailbox.
    """
    token_response = _exchange_code_for_tokens(code)
    access_token = token_response["access_token"]

    profile_response = requests.get(
        _GRAPH_ME_URI,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if profile_response.status_code != 200:
        raise OAuthConfigError(
            f"Could not read the connected mailbox's address from Microsoft Graph "
            f"({profile_response.status_code}): {profile_response.text[:500]}"
        )
    profile = profile_response.json()
    # mail is null for some account configurations (e.g. no mailbox
    # license); userPrincipalName is Graph's own recommended fallback
    # and is always present for an authenticated /me call.
    email = profile.get("mail") or profile["userPrincipalName"]

    account, _created = EmailAccount.objects.get_or_create(
        workspace=workspace,
        email=email,
        provider="outlook",
        defaults={"account_name": email},
    )
    account.status = "connected"
    account.save(update_fields=["status", "updated_at"])

    _store_credentials(account, token_response)
    return account


def _load_access_token(account: EmailAccount) -> str:
    """The account's current, live Graph access token, refreshing
    first if the stored one is expired (or missing outright). A
    refresh that succeeds is persisted back via _store_credentials so
    the next call doesn't need to refresh again."""
    try:
        cred_row = account.outlook_credential
    except OutlookCredential.DoesNotExist as exc:
        raise ProviderAuthError(
            f"no Outlook credential stored for account {account.email!r} -- connect it first"
        ) from exc

    expired = (
        cred_row.token_expiry is None
        or cred_row.token_expiry <= datetime.now(tz=dt_timezone.utc) + _EXPIRY_SKEW
    )
    if not expired and cred_row.access_token:
        return _decrypt(cred_row.access_token)

    refresh_token = _decrypt(cred_row.refresh_token)
    token_response = _refresh_tokens(refresh_token)
    _store_credentials(account, token_response)
    return token_response["access_token"]


class _GraphSession:
    """Thin `requests`-backed session carrying the account's bearer
    token on every call -- what OutlookProvider's `session_factory`
    actually returns in production. A plain wrapper rather than
    handing OutlookProvider a raw `requests.Session` with a default
    header set on it, so a fresh access token (post-refresh) is read
    lazily off `account` rather than baked in once at construction
    time; a single OutlookProvider.fetch_messages() call only ever
    constructs one of these, so "lazily" here just means "after
    _load_access_token()'s own refresh-if-needed check has already
    run," not a token refresh mid-request."""

    def __init__(self, access_token: str):
        self._access_token = access_token

    def get(self, url: str, params: dict | None = None, headers: dict | None = None):
        merged_headers = {"Authorization": f"Bearer {self._access_token}"}
        if headers:
            merged_headers.update(headers)
        return requests.get(url, params=params, headers=merged_headers, timeout=30)


def outlook_session_factory(account: EmailAccount) -> _GraphSession:
    """The real `session_factory` OutlookProvider takes at
    construction time (`OutlookProvider(session_factory=
    outlook_session_factory)`) -- everything outlook_provider.py's own
    module docstring deferred."""
    access_token = _load_access_token(account)
    return _GraphSession(access_token)


def disconnect_outlook_account(account: EmailAccount) -> None:
    """The full disconnect: delete the local OutlookCredential row and
    mark the account "disconnected". See this module's docstring for
    why, unlike oauth.disconnect_gmail_account(), there's no Microsoft-
    side revoke call made here -- the v2.0 endpoint has no equivalent
    application-callable revoke API. Deleting the row (rather than
    blanking its token fields) matches OutlookCredential's own
    docstring and GmailCredential's precedent: a single OAuth grant is
    gone the moment the account is disconnected, as far as this app is
    concerned.
    """
    try:
        cred_row = account.outlook_credential
    except OutlookCredential.DoesNotExist:
        cred_row = None

    if cred_row is not None:
        cred_row.delete()

    account.status = "disconnected"
    account.save(update_fields=["status", "updated_at"])


@register_provider("outlook")
class _RegisteredOutlookProvider(OutlookProvider):
    """Wires OutlookProvider up to `get_provider("outlook")`, same
    pattern as oauth._RegisteredGmailProvider: providers.get_provider()
    instantiates whatever's registered with a zero-arg constructor,
    but OutlookProvider itself deliberately takes `session_factory` as
    a required constructor argument, so no bare `OutlookProvider` can
    be `@register_provider`'d directly. Registered here, in
    outlook_oauth.py, rather than in outlook_provider.py itself, for
    the same reason oauth.py does it: outlook_provider.py stays free
    of any dependency on real OAuth/credential-storage machinery.
    """

    def __init__(self):
        super().__init__(session_factory=outlook_session_factory)
