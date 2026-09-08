"""
Generic IMAP: connect/verify flow, encrypted credential storage, and
the real `client_factory` ImapProvider needs (Phase 9 third-provider
slice, docs/DJANGO_MIGRATION_PLAN.md). Same split as oauth.py/
outlook_oauth.py: everything imap_provider.py's module docstring
flagged as deliberately deferred lives here.

Unlike Gmail/Outlook, there is no OAuth redirect/consent flow here at
all -- generic IMAP means username + an app-specific password (RFC
3501 LOGIN), supplied directly by the user, not obtained via a
provider's own authorization server. So this module has no
build_authorization_url()/complete_*_connection(code, state) pair;
instead connect_imap_account() takes the mailbox's host/port/username
/password directly, verifies them with a *real* IMAP login (and an
INBOX SELECT) before storing anything, and returns the connected
EmailAccount immediately -- there is no separate callback step because
there is no redirect to come back from.

Design note on encryption: the app password is encrypted at the field
level with Fernet, same reasoning as oauth.py/outlook_oauth.py's own
design notes -- a database backup/replica/read leak alone shouldn't be
enough to log into anyone's mailbox. A *separate* key (settings.
IMAP_TOKEN_ENCRYPTION_KEY, not GMAIL_TOKEN_ENCRYPTION_KEY or
MICROSOFT_TOKEN_ENCRYPTION_KEY) is used so that rotating or leaking
one provider's key never touches another provider's already-stored
credentials.

Design note on blocked domains: Microsoft retired IMAP basic-auth
(username + password) for outlook.com/hotmail.com/live.com/msn.com
consumer mailboxes in favor of OAuth-only access -- a LOGIN attempt
against those domains fails with an authentication error that looks,
from the outside, just like a wrong password, which would be a
confusing dead end for a user who typed their password correctly.
connect_imap_account() rejects those domains up front with a message
pointing at the Outlook OAuth flow (outlook_oauth.py) instead of
letting the LOGIN attempt fail opaquely.

Design note on revocation: like outlook_oauth.py's own docstring
notes for Microsoft, there is no application-callable "revoke this
credential" API for generic IMAP -- it is, after all, just a password.
disconnect_imap_account() is local-only: it deletes the stored
IMAPCredential so this app can no longer use it, but the password
itself remains valid for the mailbox until the user changes or
revokes the app password themselves on their provider's side.
"""
from __future__ import annotations

import imaplib
import socket

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

from .imap_provider import ImapProvider
from .models import EmailAccount, IMAPCredential
from .providers import ProviderAuthError, ProviderError, register_provider

# Consumer Microsoft mailboxes only -- Microsoft 365/work-or-school
# tenants can still have basic auth enabled by their admin, but there
# is no way to tell that from the address alone, so this only blocks
# the domains Microsoft is known to have fully retired basic auth for.
# An address on one of these domains should use outlook_oauth.py's
# flow instead (see email_sync.models.EmailAccount.PROVIDER_CHOICES'
# "outlook" entry).
_MICROSOFT_BASIC_AUTH_RETIRED_DOMAINS = {
    "outlook.com",
    "hotmail.com",
    "live.com",
    "msn.com",
}

# Real IMAP servers occasionally hang rather than cleanly refuse a bad
# host/port -- this bounds how long connect_imap_account() (and every
# later sync's client_factory call) will wait before treating the
# server as unreachable, mirroring outlook_oauth.py's own `timeout=10`
# /`timeout=30` calls on its `requests` calls for the same reason.
_CONNECT_TIMEOUT_SECONDS = 15

_DEFAULT_PORT = 993


class ImapConnectionError(ProviderError):
    """The host/port couldn't be reached at all (DNS failure, refused
    connection, timeout) -- distinct from ProviderAuthError (the
    server was reached but the LOGIN itself was rejected), since a
    connect-time host typo and a wrong password are different problems
    a user needs different guidance to fix."""


def _fernet() -> Fernet:
    return Fernet(settings.IMAP_TOKEN_ENCRYPTION_KEY.encode("ascii"))


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        # Same story as oauth._decrypt/outlook_oauth._decrypt: either
        # IMAP_TOKEN_ENCRYPTION_KEY was rotated without migrating
        # stored credentials, or the row is corrupt -- either way this
        # credential is unusable, phrased the same way an actually-
        # wrong/changed password would be so callers don't need a
        # third failure mode to handle.
        raise ProviderAuthError(
            "stored IMAP credential can't be decrypted -- reconnect this account"
        ) from exc


def _domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


def _reject_if_basic_auth_retired(email: str) -> None:
    domain = _domain_of(email)
    if domain in _MICROSOFT_BASIC_AUTH_RETIRED_DOMAINS:
        raise ProviderError(
            f"{domain} no longer supports IMAP username/password login -- "
            "connect this mailbox with the Outlook sign-in flow instead."
        )


def _open_connection(host: str, port: int, username: str, password: str) -> imaplib.IMAP4_SSL:
    """Open a real TLS IMAP connection and log in, raising
    ImapConnectionError for an unreachable host/port and
    ProviderAuthError for a reachable server that rejects the LOGIN --
    the same two-failure-mode split _open_connection's own class
    docstrings describe. Used both at connect time (to verify
    credentials before anything is stored) and by every later sync's
    imap_client_factory -- there's no separate "verify" vs. "connect
    for real" code path to keep in sync with each other.
    """
    try:
        connection = imaplib.IMAP4_SSL(host, port, timeout=_CONNECT_TIMEOUT_SECONDS)
    except (socket.error, socket.gaierror, OSError) as exc:
        raise ImapConnectionError(f"could not reach {host}:{port} -- {exc}") from exc

    try:
        connection.login(username, password)
    except imaplib.IMAP4.error as exc:
        connection.logout()
        raise ProviderAuthError(
            f"IMAP login rejected for {username!r} at {host}:{port} -- {exc}"
        ) from exc

    return connection


def connect_imap_account(
    workspace,
    email: str,
    password: str,
    host: str,
    port: int = _DEFAULT_PORT,
    username: str | None = None,
) -> EmailAccount:
    """The full connect flow: verify the given host/port/username/
    password with a *real* IMAP login + INBOX SELECT, then create or
    reactivate the EmailAccount and store the encrypted credential --
    only after verification succeeds, so a typo'd password never
    leaves a "connected" EmailAccount with credentials that don't
    actually work sitting around (unlike the OAuth flows, there's no
    later sync to discover that and flip the account to "blocked";
    this is the only chance to catch it).

    `username` defaults to `email` -- true for most providers, but
    some IMAP servers use a separate mailbox username distinct from
    the address mail is delivered to, hence the override.

    get_or_create on (workspace, email, provider), same as
    complete_gmail_connection()/complete_outlook_connection():
    reconnecting a previously-disconnected account revives the same
    EmailAccount row -- and its sync history -- rather than forking a
    second row for the same mailbox.
    """
    _reject_if_basic_auth_retired(email)
    login_username = username or email

    connection = _open_connection(host, port, login_username, password)
    try:
        typ, _data = connection.select("INBOX")
        if typ != "OK":
            raise ProviderAuthError(
                f"could not select INBOX for {login_username!r} at {host}:{port}"
            )
    finally:
        connection.logout()

    account, _created = EmailAccount.objects.get_or_create(
        workspace=workspace,
        email=email,
        provider="imap",
        defaults={"account_name": email},
    )
    account.status = "connected"
    account.save(update_fields=["status", "updated_at"])

    IMAPCredential.objects.update_or_create(
        account=account,
        defaults={
            "host": host,
            "port": port,
            "username": login_username,
            "password": _encrypt(password),
        },
    )
    return account


def imap_client_factory(account: EmailAccount) -> imaplib.IMAP4_SSL:
    """The real `client_factory` ImapProvider takes at construction
    time (`ImapProvider(client_factory=imap_client_factory)`) --
    everything imap_provider.py's own module docstring deferred. Opens
    a fresh connection and selects INBOX on every call, same
    "credentials are checked fresh, not cached as a live connection
    across syncs" spirit as outlook_oauth.outlook_session_factory
    refreshing a token per call.
    """
    try:
        cred_row = account.imap_credential
    except IMAPCredential.DoesNotExist as exc:
        raise ProviderAuthError(
            f"no IMAP credential stored for account {account.email!r} -- connect it first"
        ) from exc

    password = _decrypt(cred_row.password)
    connection = _open_connection(cred_row.host, cred_row.port, cred_row.username, password)
    typ, _data = connection.select("INBOX")
    if typ != "OK":
        connection.logout()
        raise ProviderAuthError(
            f"could not select INBOX for {cred_row.username!r} at {cred_row.host}:{cred_row.port}"
        )
    return connection


def disconnect_imap_account(account: EmailAccount) -> None:
    """The full disconnect: delete the local IMAPCredential row and
    mark the account "disconnected". See this module's docstring for
    why, unlike oauth.disconnect_gmail_account(), there's no provider-
    side revoke call made here -- an app password isn't a grant this
    app can revoke, only one the user can change or delete themselves.
    Deleting the row (rather than blanking its password field) matches
    GmailCredential/OutlookCredential's precedent: a single credential
    is gone the moment the account is disconnected, as far as this app
    is concerned.
    """
    try:
        cred_row = account.imap_credential
    except IMAPCredential.DoesNotExist:
        cred_row = None

    if cred_row is not None:
        cred_row.delete()

    account.status = "disconnected"
    account.save(update_fields=["status", "updated_at"])


@register_provider("imap")
class _RegisteredImapProvider(ImapProvider):
    """Wires ImapProvider up to `get_provider("imap")`, same pattern as
    oauth._RegisteredGmailProvider/outlook_oauth._RegisteredOutlookProvider:
    providers.get_provider() instantiates whatever's registered with a
    zero-arg constructor, but ImapProvider itself deliberately takes
    `client_factory` as a required constructor argument, so no bare
    `ImapProvider` can be `@register_provider`'d directly. Registered
    here, in imap_auth.py, rather than in imap_provider.py itself, for
    the same reason oauth.py/outlook_oauth.py do it: imap_provider.py
    stays free of any dependency on real connection/credential-storage
    machinery.
    """

    def __init__(self):
        super().__init__(client_factory=imap_client_factory)
