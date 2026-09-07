"""
Gmail OAuth: connect/callback flow, encrypted token storage, and the
real `service_factory` GmailProvider needs (Phase 9 OAuth slice,
docs/DJANGO_MIGRATION_PLAN.md). Everything gmail_provider.py's module
docstring flagged as deliberately deferred to a follow-up slice lives
here: where OAuth tokens come from, where they're stored, and how a
stored EmailAccount turns into an authorized Gmail API client.

Deliberately NOT here:
  - Any frontend/consent-screen UI. This module only ever hands back
    URLs and JSON; a browser client is responsible for navigating to
    build_authorization_url()'s result and for whatever it shows the
    user before/after.
  - Multi-provider abstraction. This is Gmail-specific by design --
    Outlook/IMAP will need their own oauth.py-equivalent when their
    own provider slice happens, same as gmail_provider.py itself is
    Gmail-specific rather than a generic "OAuth provider" base class.

Design note on encryption: access/refresh tokens are encrypted at the
field level with Fernet (symmetric, authenticated encryption) rather
than left to the database's own encryption-at-rest, so that a database
backup, read replica, or SQL-injection read leak alone is not enough
to use anyone's mailbox -- the Fernet key (settings.
GMAIL_TOKEN_ENCRYPTION_KEY) is a distinct secret with a narrower blast
radius than "anyone who can read the database."
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

import requests
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build as build_gmail_client

from .gmail_provider import GmailProvider
from .models import EmailAccount, GmailCredential
from .providers import ProviderAuthError, ProviderError, register_provider

_TOKEN_URI = "https://oauth2.googleapis.com/token"
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_REVOKE_URI = "https://oauth2.googleapis.com/revoke"


class OAuthConfigError(Exception):
    """settings.GOOGLE_OAUTH_CLIENT_ID/SECRET aren't configured. Not a
    ProviderError subclass -- this means the *app* was never set up
    with a Google Cloud project, not that any particular user's
    credentials are invalid, so it shouldn't be caught anywhere
    sync_service.sync_account() handles per-account failures."""


def _require_client_config() -> dict:
    if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
        raise OAuthConfigError(
            "GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET are not configured -- "
            "set them in the environment before starting a Gmail connect flow"
        )
    return {
        "web": {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
            "redirect_uris": [settings.GOOGLE_OAUTH_REDIRECT_URI],
        }
    }


def _fernet() -> Fernet:
    return Fernet(settings.GMAIL_TOKEN_ENCRYPTION_KEY.encode("ascii"))


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        # Ciphertext that doesn't decrypt under the configured key --
        # either GMAIL_TOKEN_ENCRYPTION_KEY was rotated without
        # migrating stored tokens, or the row is corrupt. Either way
        # this credential is unusable, which is exactly what a caller
        # trying to sync this account needs to hear, phrased the same
        # way an actually-revoked grant would be.
        raise ProviderAuthError(
            "stored Gmail credential can't be decrypted -- reconnect this account"
        ) from exc


def _try_decrypt(value: str) -> str | None:
    """Same as _decrypt, but returns None instead of raising --
    disconnect_gmail_account() needs to attempt revoking whatever
    token it can recover, but a credential row that's already
    undecryptable (see _decrypt's own docstring) shouldn't block the
    rest of disconnect (deleting the row, marking the account
    disconnected) from completing. There's nothing left to revoke with
    Google in that case, but the local cleanup should still happen.
    """
    if not value:
        return None
    try:
        return _decrypt(value)
    except ProviderAuthError:
        return None


def build_flow(state: str | None = None) -> Flow:
    """A google_auth_oauthlib Flow configured for this app's Google
    Cloud project. `access_type="offline"` + `prompt="consent"` are
    both required to reliably get a refresh_token back on the
    authorization_url() round trip -- Google only issues one on a
    user's *first* consent for a given client+scope combination by
    default, and this app has no use for an access-token-only grant
    since sync needs to run unattended, long after the initial
    browser flow closed."""
    flow = Flow.from_client_config(
        _require_client_config(),
        scopes=settings.GMAIL_OAUTH_SCOPES,
        state=state,
    )
    flow.redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
    return flow


def build_authorization_url() -> tuple[str, str]:
    """Returns (authorization_url, state). `state` must be stashed by
    the caller (GmailConnectView stores it in the session, alongside
    which workspace initiated the connect) and checked against what
    comes back on the callback request, standard OAuth CSRF
    protection -- without it, an attacker who can get a victim to
    visit a crafted callback URL could bind their own Google account
    to the victim's session."""
    flow = build_flow()
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    return authorization_url, state


def _store_credentials(account: EmailAccount, credentials: Credentials) -> GmailCredential:
    """Encrypt and persist `credentials` for `account`, creating or
    updating the one GmailCredential row get_or_create's uniqueness
    (account is a OneToOneField) already enforces. refresh_token is
    only overwritten when Google actually sends a new one -- a token
    refresh's response frequently omits refresh_token entirely (it
    hasn't changed), and blanking a still-valid refresh_token out on
    every routine access-token refresh would silently break every
    subsequent sync for no reason."""
    defaults = {
        "access_token": _encrypt(credentials.token) if credentials.token else "",
        "token_expiry": credentials.expiry.replace(tzinfo=dt_timezone.utc)
        if credentials.expiry
        else None,
        "scopes": " ".join(credentials.scopes or []),
    }
    if credentials.refresh_token:
        defaults["refresh_token"] = _encrypt(credentials.refresh_token)

    cred, created = GmailCredential.objects.get_or_create(account=account, defaults=defaults)
    if not created:
        for field, value in defaults.items():
            setattr(cred, field, value)
        cred.save(update_fields=list(defaults) + ["updated_at"])
    return cred


def complete_gmail_connection(workspace, code: str, state: str) -> EmailAccount:
    """The full callback-time exchange: authorization code -> tokens ->
    "whose mailbox is this" -> a connected EmailAccount with its
    GmailCredential stored. Split out from GmailOAuthCallbackView so
    the view stays thin HTTP-response shaping and this stays plain,
    directly testable Python.

    The account's `email` has to come from Google (via
    users().getProfile()), never from the client -- trusting a
    caller-supplied email here would let anyone bind an OAuth grant
    for their own mailbox to a record claiming to be someone else's
    address, which every downstream matching/dossier view treats as
    authoritative.

    get_or_create on (workspace, email, provider) rather than always
    inserting: reconnecting an account that was previously
    disconnected (status="disconnected") should revive the same
    EmailAccount row -- and its sync history (last_synced_at,
    matched_email_count, existing AccountMatch/Discovery rows) -- not
    fork a second row for the same mailbox.
    """
    flow = build_flow(state=state)
    flow.fetch_token(code=code)
    credentials = flow.credentials

    profile_service = build_gmail_client(
        "gmail", "v1", credentials=credentials, cache_discovery=False
    )
    profile = profile_service.users().getProfile(userId="me").execute()
    email = profile["emailAddress"]

    account, _created = EmailAccount.objects.get_or_create(
        workspace=workspace,
        email=email,
        provider="gmail",
        defaults={"account_name": email},
    )
    account.status = "connected"
    account.save(update_fields=["status", "updated_at"])

    _store_credentials(account, credentials)
    return account


def _load_google_credentials(account: EmailAccount) -> Credentials:
    """Rebuild a live google.oauth2.credentials.Credentials from
    account's stored, encrypted GmailCredential, refreshing the access
    token first if it's expired (or missing outright, e.g. right after
    a token exchange that only returned a refresh_token). A refresh
    that succeeds is persisted back via _store_credentials so the next
    call doesn't need to refresh again; a refresh that fails --
    because the grant was revoked, the refresh token expired from
    disuse, etc -- surfaces as ProviderAuthError, the same exception
    sync_service.sync_account() already catches from GmailProvider
    itself for API-call-time auth failures, so account.status gets
    marked "blocked" through the exact same path either way."""
    try:
        cred_row = account.gmail_credential
    except GmailCredential.DoesNotExist as exc:
        raise ProviderAuthError(
            f"no Gmail credential stored for account {account.email!r} -- connect it first"
        ) from exc

    client_config = _require_client_config()["web"]
    credentials = Credentials(
        token=_decrypt(cred_row.access_token) if cred_row.access_token else None,
        refresh_token=_decrypt(cred_row.refresh_token),
        token_uri=_TOKEN_URI,
        client_id=client_config["client_id"],
        client_secret=client_config["client_secret"],
        scopes=cred_row.scopes.split() if cred_row.scopes else settings.GMAIL_OAUTH_SCOPES,
        expiry=cred_row.token_expiry.replace(tzinfo=None) if cred_row.token_expiry else None,
    )

    if not credentials.valid:
        try:
            credentials.refresh(GoogleAuthRequest())
        except RefreshError as exc:
            raise ProviderAuthError(
                f"Gmail credential for {account.email!r} could not be refreshed "
                "-- the grant was likely revoked; reconnect this account"
            ) from exc
        _store_credentials(account, credentials)

    return credentials


def gmail_service_factory(account: EmailAccount):
    """The real `service_factory` GmailProvider takes at construction
    time (`GmailProvider(service_factory=gmail_service_factory)`) --
    everything gmail_provider.py's own module docstring deferred.
    `cache_discovery=False` avoids googleapiclient's default of
    writing a discovery-document cache file to disk, which is both
    unnecessary (the Gmail v1 discovery doc is small and this isn't a
    high-QPS service) and occasionally noisy/broken in read-only or
    containerized filesystems."""
    credentials = _load_google_credentials(account)
    return build_gmail_client("gmail", "v1", credentials=credentials, cache_discovery=False)


def revoke_gmail_token(token: str) -> None:
    """POST `token` (an access or refresh token) to Google's revoke
    endpoint. Both a 200 (revoked) and a 400 (Google's response for a
    token it doesn't recognize -- already revoked, expired from
    disuse, or simply invalid) mean the grant is no longer usable from
    this app's side, which is all disconnect_gmail_account() cares
    about; only a genuine network failure or a Google-side 5xx is
    treated as this call actually failing, since those mean the revoke
    attempt itself didn't get a real answer.
    """
    try:
        response = requests.post(_REVOKE_URI, params={"token": token}, timeout=10)
    except requests.RequestException as exc:
        raise ProviderError(f"could not reach Google's revoke endpoint: {exc}") from exc
    if response.status_code not in (200, 400):
        raise ProviderError(
            f"Google's revoke endpoint returned unexpected status {response.status_code}"
        )


def disconnect_gmail_account(account: EmailAccount) -> None:
    """The full disconnect: best-effort revoke the grant with Google,
    then always delete the local GmailCredential row and mark the
    account "disconnected" -- in that order, but the second half runs
    even if the first half can't (no stored credential at all, a
    credential that fails to decrypt, or Google's revoke endpoint
    being unreachable). A disconnect button that leaves a broken local
    row behind because Google's network call hiccuped would be worse
    than a disconnect that's locally clean but relies on Google's own
    "unused grants expire" behavior as a fallback -- so any revoke
    failure is swallowed here, not raised, and the caller (the
    disconnect view) doesn't need to distinguish "fully revoked" from
    "locally disconnected, Google-side revoke best-effort" in its
    response.

    Deleting the row (rather than blanking its token fields) matches
    GmailCredential's own docstring: "a single OAuth grant ... gone
    the moment the account is disconnected."
    """
    try:
        cred_row = account.gmail_credential
    except GmailCredential.DoesNotExist:
        cred_row = None

    if cred_row is not None:
        token = _try_decrypt(cred_row.refresh_token) or _try_decrypt(cred_row.access_token)
        if token:
            try:
                revoke_gmail_token(token)
            except ProviderError:
                # Best-effort per the docstring above -- local cleanup
                # still proceeds; the grant will simply sit unused on
                # Google's side until it expires or the user revokes
                # it themselves at myaccount.google.com/permissions.
                pass
        cred_row.delete()

    account.status = "disconnected"
    account.save(update_fields=["status", "updated_at"])


@register_provider("gmail")
class _RegisteredGmailProvider(GmailProvider):
    """Wires GmailProvider up to `get_provider("gmail")` (providers.
    get_provider() instantiates whatever's registered with a zero-arg
    constructor, but GmailProvider itself deliberately takes
    `service_factory` as a required constructor argument -- see its
    own docstring -- so no bare `GmailProvider` can be `@register_
    provider`'d directly). Registered here, in oauth.py, rather than
    in gmail_provider.py itself, so gmail_provider.py stays free of
    any dependency on real OAuth/credential-storage machinery -- it
    can be constructed and tested (as test_gmail_provider.py already
    does) with a fake service_factory with zero knowledge that this
    module, or Django's session/OAuth machinery, exists at all."""

    def __init__(self):
        super().__init__(service_factory=gmail_service_factory)
