"""Synthetic signed assertions and isolated lineage fixtures; no live Google calls."""
import base64
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase, SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from google.auth import crypt, jwt
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.helpers import credentials_from_session
from rest_framework.exceptions import NotFound
from rest_framework.test import APIClient, APIRequestFactory

from accounts.models import User, Workspace
from email_sync import oauth
from email_sync.models import (AccountMailboxBinding, EmailAccount, GmailCredential,
    MailboxLineage, MailboxPrincipal, RetainedMessage, RetainedObservation, Discovery)
from email_sync.providers import ProviderAuthError, ProviderTemporaryError
from email_sync.retention import resolve_google_mailbox, retain_observation
from .test_retention import fixture


def access_hash(token):
    return base64.urlsafe_b64encode(hashlib.sha256(token.encode('ascii')).digest()[:16]).rstrip(b'=').decode('ascii')


@override_settings(GOOGLE_OAUTH_CLIENT_ID='synthetic-client', GOOGLE_OAUTH_CLIENT_SECRET='synthetic-secret')
class AssertionTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.signer = crypt.RSASigner.from_string(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()), key_id='fixture')
        cls.public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def credentials(self, **changes):
        now = int(time.time())
        claims = dict(iss='https://accounts.google.com', aud='synthetic-client', sub='00Opaque-Subject_A',
                      iat=now-10, exp=now+3600, at_hash=access_hash('synthetic-access'))
        claims.update(changes)
        claims = {k: v for k, v in claims.items() if v is not None}
        return Credentials(token='synthetic-access', id_token=jwt.encode(self.signer, claims).decode())

    def verify(self, credentials):
        # Exercise the actual Google verifier; replace only its public-key fetch.
        with patch.object(oauth.id_token, '_fetch_certs', return_value={'fixture': self.public}):
            return oauth._verified_google_sub(credentials)

    def test_valid_signed_assertion_and_legacy_google_issuer(self):
        for issuer in ['https://accounts.google.com', 'accounts.google.com']:
            self.assertEqual(self.verify(self.credentials(iss=issuer)), '00Opaque-Subject_A')

    def test_invalid_required_claims_and_access_binding(self):
        for changes in [dict(iss='https://attacker.test'), dict(iss=None), dict(aud='other-client'),
                        dict(aud=None), dict(exp=int(time.time())-30), dict(exp=None), dict(iat=None),
                        dict(iat=int(time.time())+3600), dict(sub=None), dict(sub=''), dict(sub=123),
                        dict(sub='x'*256), dict(sub='null\x00value'), dict(sub='non-ascii-☃'), dict(at_hash=None),
                        dict(at_hash='wrong'), dict(azp='other-client')]:
            with self.subTest(changes=changes), self.assertRaises(ProviderAuthError):
                self.verify(self.credentials(**changes))

    def test_missing_malformed_unsigned_and_tampered_tokens(self):
        parts = self.credentials().id_token.split('.')
        parts[1] = base64.urlsafe_b64encode(b'{"sub":"forged"}').rstrip(b'=').decode()
        for token in [None, '', 'not-a-jwt', '.'.join(parts), 'eyJhbGciOiJub25lIn0.e30.']:
            with self.subTest(token=bool(token)), self.assertRaises(ProviderAuthError) as caught:
                self.verify(Credentials(token='synthetic-access', id_token=token))
            self.assertEqual(str(caught.exception), 'Google account identity could not be verified; authorize Gmail again.')

    def test_wrong_signature_key_rejected(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = other.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        with patch.object(oauth.id_token, '_fetch_certs', return_value={'fixture': public}), self.assertRaises(ProviderAuthError):
            oauth._verified_google_sub(self.credentials())

    def test_access_token_cannot_be_substituted(self):
        creds = self.credentials()
        creds.token = 'different-access'
        with self.assertRaises(ProviderAuthError):
            self.verify(creds)

    def test_installed_flow_exposes_id_token_without_verifying_it(self):
        original = self.credentials()
        session = SimpleNamespace(scope=list(oauth.settings.GMAIL_OAUTH_SCOPES), token={
            'access_token': original.token, 'id_token': original.id_token,
            'refresh_token': 'synthetic-refresh', 'expires_at': time.time()+3600})
        credentials = credentials_from_session(session, {'client_id': 'synthetic-client'})
        self.assertEqual(credentials.id_token, original.id_token)
        self.assertEqual(self.verify(credentials), '00Opaque-Subject_A')

    def test_exact_approved_scopes_reach_library_flow(self):
        with patch.object(oauth.Flow, 'from_client_config') as factory:
            oauth.build_flow()
        self.assertEqual(factory.call_args.kwargs['scopes'],
                         ['openid', 'email', 'https://www.googleapis.com/auth/gmail.readonly'])


class ConnectionFixture:
    def setUp(self):
        self.user = User.objects.create_user(username='identity-owner')
        self.ws = Workspace.objects.create(owner=self.user, name='Identity')

    def connect(self, sub='synthetic-A', email='old@example.test', workspace=None, refresh='new-refresh'):
        creds = SimpleNamespace(token='new-access', refresh_token=refresh, expiry=None,
                                scopes=list(oauth.settings.GMAIL_OAUTH_SCOPES), id_token='synthetic-assertion')
        flow, gmail = MagicMock(), MagicMock()
        flow.credentials = creds
        gmail.users.return_value.getProfile.return_value.execute.return_value = {'emailAddress': email}
        with patch.object(oauth, 'build_flow', return_value=flow), \
             patch.object(oauth, '_verified_google_sub', return_value=sub), \
             patch.object(oauth, 'build_gmail_client', return_value=gmail):
            result = oauth.complete_gmail_connection(workspace or self.ws, 'code', 'state', 'verifier')
        gmail.users.return_value.getProfile.assert_called_once_with(userId='me')
        return result


class ConnectionTests(ConnectionFixture, TestCase):
    def test_first_connect_replay_no_retention_or_timestamp_churn(self):
        first = self.connect()
        models = [MailboxLineage, MailboxPrincipal, AccountMailboxBinding, EmailAccount]
        before = [list(m.objects.values()) for m in models]
        again = self.connect(refresh='rotated-refresh')
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(before, [list(m.objects.values()) for m in models])
        self.assertEqual(MailboxLineage.objects.count(), 1)
        self.assertEqual(oauth._decrypt(GmailCredential.objects.get(account=first).refresh_token), 'rotated-refresh')
        for model in [RetainedMessage, RetainedObservation, Discovery]:
            self.assertFalse(model.objects.exists())
        principal = MailboxPrincipal.objects.get()
        self.assertEqual(principal.value, 'synthetic-A')
        self.assertEqual(principal.namespace, 'google_oidc_sub')
        self.assertEqual(principal.mailbox.evidence, {'method': 'google_oidc_verified_id_token', 'reference': 'google_oidc_sub'})

    @override_settings(GOOGLE_OAUTH_CLIENT_ID='synthetic-client', GOOGLE_OAUTH_CLIENT_SECRET='synthetic-secret')
    def test_legacy_refresh_missing_scopes_stays_readonly_and_unverified(self):
        account = EmailAccount.objects.create(workspace=self.ws, provider='gmail', email='legacy@example.test')
        row = GmailCredential.objects.create(account=account, access_token='',
                                             refresh_token=oauth._encrypt('legacy-refresh'), scopes='')
        real_credentials = Credentials
        def construct(**kwargs):
            self.assertEqual(kwargs['scopes'], ['https://www.googleapis.com/auth/gmail.readonly'])
            return real_credentials(**kwargs)
        def refresh(credentials, request):
            credentials.token = 'refreshed'
            # Refresh never calls identity verification or creates lineage, even
            # if the SDK happens to receive an assertion in a response.
            credentials._id_token = 'not-a-verified-assertion'
        with patch.object(oauth, 'Credentials', side_effect=construct), \
             patch.object(real_credentials, 'refresh', refresh), \
             patch.object(oauth, '_verified_google_sub', side_effect=AssertionError('no identity upgrade')):
            oauth._load_google_credentials(account)
        row.refresh_from_db()
        self.assertEqual(row.scopes, 'https://www.googleapis.com/auth/gmail.readonly')
        self.assertEqual(oauth._decrypt(row.refresh_token), 'legacy-refresh')
        self.assertEqual(oauth._decrypt(row.access_token), 'refreshed')
        self.assertFalse(MailboxPrincipal.objects.exists())
        self.assertFalse(AccountMailboxBinding.objects.exists())

    @override_settings(GOOGLE_OAUTH_CLIENT_ID='synthetic-client', GOOGLE_OAUTH_CLIENT_SECRET='synthetic-secret')
    def test_recorded_scopes_survive_refresh_without_identity_churn(self):
        account = self.connect()
        before = [list(m.objects.values()) for m in [MailboxLineage, MailboxPrincipal, AccountMailboxBinding]]
        GmailCredential.objects.filter(account=account).update(access_token='')
        account.refresh_from_db()
        real_credentials = Credentials
        def construct(**kwargs):
            self.assertEqual(kwargs['scopes'], list(oauth.settings.GMAIL_OAUTH_SCOPES))
            return real_credentials(**kwargs)
        def refresh(credentials, request):
            credentials.token = 'rotated-access'
        with patch.object(oauth, 'Credentials', side_effect=construct), patch.object(real_credentials, 'refresh', refresh):
            oauth._load_google_credentials(account)
        self.assertEqual(before, [list(m.objects.values()) for m in [MailboxLineage, MailboxPrincipal, AccountMailboxBinding]])
        self.assertEqual(oauth._decrypt(GmailCredential.objects.get(account=account).access_token), 'rotated-access')

    @override_settings(GOOGLE_OAUTH_CLIENT_ID='synthetic-client', GOOGLE_OAUTH_CLIENT_SECRET='synthetic-secret')
    def test_signed_assertion_through_callback_to_durable_principal(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        signer = crypt.RSASigner.from_string(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()), key_id='integration')
        public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        now = int(time.time())
        token = jwt.encode(signer, dict(iss='https://accounts.google.com', aud='synthetic-client',
            sub='synthetic-integrated', iat=now-10, exp=now+3600, at_hash=access_hash('synthetic-access'))).decode()
        flow, gmail = MagicMock(), MagicMock()
        flow.credentials = Credentials(token='synthetic-access', id_token=token, refresh_token='synthetic-refresh',
                                       scopes=list(oauth.settings.GMAIL_OAUTH_SCOPES))
        gmail.users.return_value.getProfile.return_value.execute.return_value = {'emailAddress': 'profile@example.test'}
        with patch.object(oauth, 'build_flow', return_value=flow), \
             patch.object(oauth, 'build_gmail_client', return_value=gmail), \
             patch.object(oauth.id_token, '_fetch_certs', return_value={'integration': public}):
            account = oauth.complete_gmail_connection(self.ws, 'synthetic-code', 'state', 'verifier')
        self.assertEqual(account.mailbox_binding.mailbox.principal.value, 'synthetic-integrated')
        identity_state = repr([list(m.objects.values()) for m in [MailboxLineage, MailboxPrincipal, AccountMailboxBinding]])
        for secret in [token, 'synthetic-access', 'synthetic-refresh', 'synthetic-code', 'synthetic-secret']:
            self.assertNotIn(secret, identity_state)
        self.assertFalse(RetainedMessage.objects.exists())

    @override_settings(GOOGLE_OAUTH_CLIENT_ID='synthetic-client', GOOGLE_OAUTH_CLIENT_SECRET='synthetic-secret')
    def test_inflight_legacy_refresh_cannot_replace_new_verified_grant(self):
        account = EmailAccount.objects.create(workspace=self.ws, provider='gmail', email='old@example.test')
        GmailCredential.objects.create(account=account, access_token='', refresh_token=oauth._encrypt('unverified-refresh'))
        def refresh(credentials, request):
            self.connect(refresh='verified-refresh')
            credentials.token = 'stale-unverified-access'
        with patch.object(Credentials, 'refresh', refresh), self.assertRaises(ProviderTemporaryError):
            oauth._load_google_credentials(account)
        row = GmailCredential.objects.get(account=account)
        self.assertEqual(oauth._decrypt(row.refresh_token), 'verified-refresh')
        self.assertEqual(oauth._decrypt(row.access_token), 'new-access')
        self.assertEqual(AccountMailboxBinding.objects.get(account=account).mailbox.principal.value, 'synthetic-A')

    @override_settings(GOOGLE_OAUTH_CLIENT_ID='synthetic-client', GOOGLE_OAUTH_CLIENT_SECRET='synthetic-secret')
    def test_inflight_refresh_cannot_recreate_disconnected_credentials(self):
        account = self.connect()
        GmailCredential.objects.filter(account=account).update(access_token='')
        account.refresh_from_db()
        def refresh(credentials, request):
            fresh_account = EmailAccount.objects.get(pk=account.pk)
            with patch.object(oauth, 'revoke_gmail_token'):
                oauth.disconnect_gmail_account(fresh_account)
            credentials.token = 'stale-access'
        with patch.object(Credentials, 'refresh', refresh), self.assertRaises(ProviderTemporaryError):
            oauth._load_google_credentials(account)
        self.assertFalse(GmailCredential.objects.filter(account=account).exists())
        self.assertTrue(AccountMailboxBinding.objects.filter(account=account).exists())

    def test_opaque_subject_is_not_normalized_and_case_is_significant(self):
        one = self.connect(sub=' 00Case ', email='one@example.test')
        two = self.connect(sub=' 00case ', email='two@example.test')
        self.assertNotEqual(one.mailbox_binding.mailbox_id, two.mailbox_binding.mailbox_id)
        self.assertEqual(one.mailbox_binding.mailbox.principal.value, ' 00Case ')

    def test_same_principal_changed_email_preserves_lineage_and_custom_name(self):
        account = self.connect()
        mailbox_id = account.mailbox_binding.mailbox_id
        account.account_name = 'My inbox'
        account.save()
        again = self.connect(email='renamed@example.test')
        self.assertEqual(again.pk, account.pk)
        self.assertEqual(again.mailbox_binding.mailbox_id, mailbox_id)
        self.assertEqual(again.email, 'renamed@example.test')
        self.assertEqual(again.account_name, 'My inbox')

    def test_default_email_display_name_tracks_changed_email(self):
        self.connect()
        self.assertEqual(self.connect(email='renamed@example.test').account_name, 'renamed@example.test')

    def test_same_email_different_principal_conflicts_with_atomic_preservation(self):
        self.connect()
        models = [EmailAccount, GmailCredential, MailboxLineage, MailboxPrincipal, AccountMailboxBinding]
        before = [list(m.objects.values()) for m in models]
        with self.assertRaises(oauth.GmailIdentityConflict):
            self.connect(sub='synthetic-B', refresh='different-refresh')
        self.assertEqual(before, [list(m.objects.values()) for m in models])

    def test_different_principals_and_addresses_remain_distinct(self):
        one = self.connect()
        two = self.connect(sub='synthetic-B', email='other@example.test')
        self.assertNotEqual(one.mailbox_binding.mailbox_id, two.mailbox_binding.mailbox_id)

    def test_address_collision_does_not_merge_unbound_legacy_account(self):
        self.connect()
        legacy = EmailAccount.objects.create(workspace=self.ws, provider='gmail', email='collision@example.test')
        with self.assertRaises(oauth.GmailIdentityConflict):
            self.connect(email=legacy.email)
        self.assertFalse(AccountMailboxBinding.objects.filter(account=legacy).exists())
        self.assertEqual(MailboxLineage.objects.count(), 1)

    def test_legacy_unverified_until_prospective_binding_without_history_rewrite(self):
        legacy = EmailAccount.objects.create(workspace=self.ws, provider='gmail', email='old@example.test',
                                           status='disconnected', matched_email_count=7)
        discovery = Discovery.objects.create(account=legacy, message_id='<legacy>', subject='Preserve')
        original = Discovery.objects.values().get(pk=discovery.pk)
        self.assertFalse(MailboxPrincipal.objects.exists())
        self.assertFalse(AccountMailboxBinding.objects.exists())
        account = self.connect()
        self.assertEqual(account.pk, legacy.pk)
        self.assertEqual(account.matched_email_count, 7)
        self.assertEqual(Discovery.objects.values().get(pk=discovery.pk), original)
        self.assertFalse(RetainedMessage.objects.exists())

    def test_ambiguous_legacy_accounts_preserved_unbound(self):
        for _ in range(2):
            EmailAccount.objects.create(workspace=self.ws, provider='gmail', email='old@example.test')
        with self.assertRaises(oauth.GmailIdentityConflict):
            self.connect()
        self.assertEqual(EmailAccount.objects.count(), 2)
        self.assertFalse(MailboxLineage.objects.exists())

    def test_legacy_refresh_token_not_adopted_as_verified(self):
        legacy = EmailAccount.objects.create(workspace=self.ws, provider='gmail', email='old@example.test')
        GmailCredential.objects.create(account=legacy, refresh_token=oauth._encrypt('unproven-refresh'))
        with self.assertRaises(ProviderAuthError):
            self.connect(refresh=None)
        self.assertFalse(MailboxLineage.objects.exists())
        self.assertEqual(oauth._decrypt(legacy.gmail_credential.refresh_token), 'unproven-refresh')

    def test_verified_binding_can_keep_existing_refresh_token(self):
        account = self.connect()
        self.connect(refresh=None)
        self.assertEqual(oauth._decrypt(account.gmail_credential.refresh_token), 'new-refresh')

    def test_workspace_isolation_and_unauthorized_resolution(self):
        other = Workspace.objects.create(owner=self.user, name='Other')
        a, b = self.connect(), self.connect(workspace=other)
        self.assertNotEqual(a.mailbox_binding.mailbox_id, b.mailbox_binding.mailbox_id)
        stranger = User.objects.create_user(username='stranger')
        with self.assertRaises(NotFound):
            resolve_google_mailbox(actor=stranger, workspace=self.ws, verified_sub='synthetic-A')
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get(f'/api/workspaces/{other.pk}/mailbox-lineages/{a.mailbox_binding.mailbox_id}/')
        self.assertEqual(response.status_code, 404)

    def test_disconnect_delete_recreation_preserve_retained_evidence(self):
        account = self.connect()
        original_pk = account.pk
        mailbox = account.mailbox_binding.mailbox
        retained = retain_observation(actor=self.user, workspace=self.ws, key='fixture', observation=fixture(mailbox))
        models = [MailboxLineage, MailboxPrincipal, RetainedMessage, RetainedObservation]
        before = [list(m.objects.values()) for m in models]
        with patch.object(oauth, 'revoke_gmail_token'):
            oauth.disconnect_gmail_account(account)
        self.assertFalse(GmailCredential.objects.exists())
        self.assertTrue(AccountMailboxBinding.objects.exists())
        self.assertEqual(self.connect().pk, original_pk)
        account.delete()
        recreated = self.connect(email='changed@example.test')
        self.assertNotEqual(recreated.pk, original_pk)
        self.assertEqual(recreated.mailbox_binding.mailbox_id, mailbox.pk)
        self.assertEqual(before, [list(m.objects.values()) for m in models])
        self.assertTrue(RetainedMessage.objects.filter(pk=retained.message_id).exists())
        with self.assertRaises(ProtectedError):
            MailboxLineage.objects.filter(pk=mailbox.pk).delete()

    def test_credential_storage_failure_rolls_back_identity_and_account(self):
        with patch.object(oauth, '_store_credentials', side_effect=RuntimeError('fixture')), self.assertRaises(RuntimeError):
            self.connect()
        for model in [MailboxLineage, MailboxPrincipal, AccountMailboxBinding, EmailAccount]:
            self.assertFalse(model.objects.exists())

    def test_invalid_profile_leaves_no_writes(self):
        for email in [None, '', 'invalid']:
            with self.subTest(email=email), self.assertRaises(ProviderAuthError):
                self.connect(email=email)
        self.assertFalse(MailboxLineage.objects.exists())

    def test_unverified_assertion_stops_before_gmail_and_database_writes(self):
        with patch.object(oauth, 'build_flow') as flow, patch.object(oauth, 'build_gmail_client') as gmail:
            flow.return_value.credentials.id_token = None
            with self.assertRaises(ProviderAuthError):
                oauth.complete_gmail_connection(self.ws, 'code', 'state')
        gmail.assert_not_called()
        self.assertFalse(EmailAccount.objects.exists())

    def test_admin_scope_immutability_and_database_uniqueness(self):
        account = self.connect()
        request = APIRequestFactory().get('/')
        request.user = self.user
        for model in [MailboxPrincipal, AccountMailboxBinding]:
            row = model.objects.get()
            with self.assertRaises(ValidationError):
                row.save()
            values = model.objects.values().get(pk=row.pk)
            with self.assertRaises(ValidationError):
                model(**values).save()
            ma = admin.site._registry[model]
            self.assertFalse(ma.has_add_permission(request))
            self.assertFalse(ma.has_change_permission(request, row))
            self.assertFalse(ma.has_delete_permission(request, row))
        account.provider = 'imap'
        with self.assertRaises(ValidationError):
            account.save()
        values = MailboxPrincipal.objects.values().get()
        del values['id']
        other = MailboxLineage.objects.create(workspace=self.ws, provider='gmail', evidence={})
        values['mailbox_id'] = other.pk
        with self.assertRaises(IntegrityError), transaction.atomic():
            MailboxPrincipal.objects.create(**values)

    def test_cross_workspace_binding_and_principal_rejected(self):
        account = self.connect()
        other = Workspace.objects.create(owner=self.user, name='Other')
        mailbox = MailboxLineage.objects.create(workspace=other, provider='gmail', evidence={})
        with self.assertRaises(ValidationError):
            AccountMailboxBinding.objects.create(account=account, mailbox=mailbox)
        with self.assertRaises(ValidationError):
            MailboxPrincipal.objects.create(workspace=self.ws, provider='gmail', namespace='google_oidc_sub', value='other', mailbox=mailbox)

    def test_inspection_read_only_without_subject_exposure(self):
        account = self.connect()
        client = APIClient()
        client.force_authenticate(self.user)
        url = f'/api/workspaces/{self.ws.pk}/mailbox-lineages/{account.mailbox_binding.mailbox_id}/'
        with patch.object(oauth, 'complete_gmail_connection', side_effect=AssertionError('no OAuth')):
            for method in ['get', 'head']:
                with CaptureQueriesContext(connection) as queries:
                    response = getattr(client, method)(url)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(all(q['sql'].lstrip().upper().startswith('SELECT') for q in queries))
                self.assertNotIn(b'synthetic-A', response.content)

    def test_callback_errors_safe_and_consume_state(self):
        client = APIClient()
        for error, status, code in [(oauth.GmailIdentityConflict('secret'), 409, 'gmail_identity_conflict'),
                                    (ProviderAuthError('secret'), 400, 'gmail_identity_unverified'),
                                    (OperationalError('database is locked'), 503, 'gmail_connection_busy')]:
            session = client.session
            session.update({'gmail_oauth_state': 'state', 'gmail_oauth_workspace_id': self.ws.pk, 'gmail_oauth_code_verifier': 'verifier'})
            session.save()
            with patch.object(oauth, 'complete_gmail_connection', side_effect=error):
                response = client.get(reverse('gmail-oauth-callback'), {'code': 'synthetic-code', 'state': 'state'})
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.data['code'], code)
            self.assertNotIn(b'secret', response.content)
            self.assertNotIn('gmail_oauth_state', client.session)


class ConcurrencyTests(ConnectionFixture, TransactionTestCase):
    def test_concurrent_first_establishment_and_explicit_retry_converge(self):
        barrier = Barrier(2)
        def establish(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return resolve_google_mailbox(actor=self.user, workspace=self.ws, verified_sub='race-sub').pk
            except OperationalError as exc:
                if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower():
                    raise
                return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(establish, range(2)))
        ids = [resolve_google_mailbox(actor=self.user, workspace=self.ws, verified_sub='race-sub').pk for _ in range(2)]
        self.assertEqual(ids[0], ids[1])
        self.assertTrue(all(result is None or result == ids[0] for result in results))
        self.assertEqual(MailboxLineage.objects.count(), 1)
        self.assertEqual(MailboxPrincipal.objects.count(), 1)

    def test_concurrent_connections_bind_one_account_and_one_credential(self):
        barrier = Barrier(2)
        flow, gmail = MagicMock(), MagicMock()
        flow.credentials = SimpleNamespace(token='race-access', refresh_token='race-refresh', expiry=None,
                                           scopes=list(oauth.settings.GMAIL_OAUTH_SCOPES))
        gmail.users.return_value.getProfile.return_value.execute.return_value = {'emailAddress': 'race@example.test'}
        def connect(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return oauth.complete_gmail_connection(self.ws, 'code', 'state', 'verifier').pk
            except OperationalError as exc:
                if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower():
                    raise
                return None
            finally:
                close_old_connections()
        with patch.object(oauth, 'build_flow', return_value=flow), \
             patch.object(oauth, '_verified_google_sub', return_value='race-sub'), \
             patch.object(oauth, 'build_gmail_client', return_value=gmail):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(connect, range(2)))
            account = oauth.complete_gmail_connection(self.ws, 'new-code', 'new-state', 'new-verifier')
        self.assertTrue(all(result is None or result == account.pk for result in results))
        for model in [EmailAccount, GmailCredential, AccountMailboxBinding, MailboxPrincipal, MailboxLineage]:
            self.assertEqual(model.objects.count(), 1)
