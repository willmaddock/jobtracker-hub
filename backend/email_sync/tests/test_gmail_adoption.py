"""Synthetic Gmail producer → retained authority acceptance; never calls Google."""
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib import admin
from django.db import OperationalError, close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.test import APIClient, APIRequestFactory

from accounts.models import User, Workspace
from applications.models import Application, StatusHistory
from documents.models import Document
from email_sync.gmail_provider import GmailProvider, _to_fetched_message
from email_sync.models import (AccountMailboxBinding, AccountMatch, Discovery, EmailAccount,
                               MailboxLineage, MailboxPrincipal, RetainedMessage,
                               RetainedObservation, RetentionKey, ThreadIdentifier)
from email_sync.retention import resolve_google_mailbox
from email_sync.sync_service import sync_account
from .test_gmail_provider import _FakeGmailService
from .test_sync_service import FakeProvider
from .test_gmail_identity import ConnectionFixture

OBSERVED = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def gmail_fixture(native='native-1', rfc='<rfc@example.test>', *, subject='Acme Robotics interview',
                  internal='1700000000123', body='Hello Acme Robotics.', html='<p>Hello</p>',
                  date='Fri, 18 Sep 2026 10:00:00 -0600', extra='', thread='thread-1'):
    headers = (f'Message-ID: {rfc}\r\n' if rfc is not None else '') + (
        f'Subject: {subject}\r\nFrom: =?utf-8?q?Recruiter?= <recruiter@example.test>\r\n'
        'To: Candidate <candidate@example.test>\r\nTo: Other <other@example.test>\r\n'
        'Reply-To: Reply <reply@example.test>\r\nCc: Copy <copy@example.test>\r\n'
        'Bcc: Hidden <hidden@example.test>\r\n')
    if date is not None:
        headers += f'Date: {date}\r\n'
    headers += f'References: <{native}-one@example.test>\r\nReferences: <{native}-two@example.test>\r\n' + extra
    source = headers + 'MIME-Version: 1.0\r\nContent-Type: multipart/alternative; boundary="synthetic"\r\n\r\n'
    for content_type, value in [('text/plain', body), ('text/html', html)]:
        if value is not None:
            source += f'--synthetic\r\nContent-Type: {content_type}; charset=utf-8\r\n\r\n{value}\r\n'
    source += '--synthetic--\r\n'
    result = {'raw': base64.urlsafe_b64encode(source.encode()).decode(), 'threadId': thread}
    if native is not None:
        result['id'] = native
    if internal is not None:
        result['internalDate'] = internal
    return result


def fetched(**kwargs):
    return replace(_to_fetched_message(gmail_fixture(**kwargs)), observed_at=OBSERVED)


class AdoptionFixtures:
    def setUp(self):
        self.user = User.objects.create_user(username='owner')
        self.ws = Workspace.objects.create(owner=self.user, name='A')
        self.account = EmailAccount.objects.create(workspace=self.ws, provider='gmail', email='candidate@example.test')
        self.mailbox = resolve_google_mailbox(actor=self.user, workspace=self.ws, verified_sub='synthetic-principal')
        AccountMailboxBinding.objects.create(account=self.account, mailbox=self.mailbox)
        self.app = Application.objects.create(workspace=self.ws, section='applications', company='Acme Robotics', role_label='Engineer')

    def sync(self, *messages, account=None):
        return sync_account(account or self.account, FakeProvider(messages), now=OBSERVED + timedelta(days=1))


class GmailAdoptionTests(AdoptionFixtures, TestCase):
    def test_real_producer_contract_through_sync(self):
        service = _FakeGmailService(list_pages=[{'messages': [{'id': 'native-1'}]}], messages_by_id={'native-1': gmail_fixture()})
        with patch('email_sync.gmail_provider.time.sleep'):
            result = sync_account(self.account, GmailProvider(lambda account: service))
        self.assertEqual(result.new_matches, 1)
        retained = RetainedMessage.objects.get()
        self.assertEqual((retained.workspace_id, retained.mailbox_id, retained.locator_value), (self.ws.pk, self.mailbox.pk, 'native-1'))
        self.assertEqual(retained.locator_kind, 'gmail_message_id')
        self.assertEqual(AccountMatch.objects.get().message_id, '<rfc@example.test>')
        self.assertEqual(service.get_calls, ['native-1'])

    def test_missing_rfc_header_retains_without_projection_or_fabrication(self):
        message = fetched(rfc=None)
        self.sync(message)
        self.assertEqual(message.rfc_message_id, '')
        self.assertEqual(RetainedMessage.objects.get().locator_value, 'native-1')
        for model in [AccountMatch, Discovery, ThreadIdentifier]:
            self.assertFalse(model.objects.exists())
        self.assertNotIn('message-id', [h[0] for h in RetainedMessage.objects.get().content['headers']])

    def test_same_attempt_replay_and_fresh_fetch_converge(self):
        message = fetched()
        self.sync(message)
        before = list(RetainedMessage.objects.values()), list(RetainedObservation.objects.values())
        self.sync(message)
        self.assertEqual(before, (list(RetainedMessage.objects.values()), list(RetainedObservation.objects.values())))
        self.sync(fetched())
        self.assertEqual(RetainedMessage.objects.count(), 1)
        self.assertEqual(RetainedObservation.objects.count(), 2)
        self.assertFalse(RetainedMessage.objects.get().has_conflict)
        self.assertEqual(AccountMatch.objects.count(), 1)

    def test_same_rfc_and_thread_different_native_ids_stay_distinct(self):
        self.sync(fetched(), fetched(native='native-2'))
        self.assertEqual(set(RetainedMessage.objects.values_list('locator_value', flat=True)), {'native-1', 'native-2'})
        self.assertEqual(AccountMatch.objects.count(), 1)
        self.assertEqual(set(RetainedMessage.objects.values_list('content__conversation_id', flat=True)), {'thread-1'})
        self.assertFalse(ThreadIdentifier.objects.filter(message_id='thread-1').exists())

    def test_same_native_changed_rfc_preserves_conflict_without_new_projection(self):
        self.sync(fetched())
        before = RetainedMessage.objects.get().content
        self.sync(fetched(rfc='<changed@example.test>'))
        row = RetainedMessage.objects.get()
        self.assertEqual(row.content, before)
        self.assertTrue(row.has_conflict)
        self.assertEqual(RetainedObservation.objects.get(state='conflict').conflict_reason, 'source_content_conflict')
        self.assertEqual(AccountMatch.objects.count(), 1)

    def test_reused_observation_key_preserves_variant(self):
        first = fetched()
        self.sync(first)
        self.sync(replace(first, text_body='changed material'))
        self.assertEqual(RetainedMessage.objects.count(), 1)
        self.assertEqual(RetainedObservation.objects.count(), 2)
        self.assertTrue(RetentionKey.objects.get().has_conflict)
        self.assertEqual(RetainedObservation.objects.get(state='conflict').conflict_reason, 'observation_key_reused')

    def test_missing_native_id_is_unresolved(self):
        self.sync(fetched(native=None))
        self.assertFalse(RetainedMessage.objects.exists())
        self.assertEqual(RetainedObservation.objects.get().state, 'unresolved')
        self.assertEqual(AccountMatch.objects.count(), 1)  # transitional compatibility

    def test_unbound_account_is_unresolved_not_guessed_by_address(self):
        legacy = EmailAccount.objects.create(workspace=self.ws, provider='gmail', email=self.account.email)
        self.sync(fetched(), account=legacy)
        self.assertFalse(RetainedMessage.objects.exists())
        row = RetainedObservation.objects.get()
        self.assertIsNone(row.mailbox_id)
        self.assertEqual(row.state, 'unresolved')
        self.assertEqual(MailboxLineage.objects.count(), 1)
        self.assertFalse(AccountMailboxBinding.objects.filter(account=legacy).exists())

    def test_binding_without_verified_principal_is_unresolved(self):
        MailboxPrincipal.objects.all().delete()  # privileged malformed fixture
        self.sync(fetched())
        self.assertEqual(RetainedObservation.objects.get().state, 'unresolved')
        self.assertFalse(RetainedMessage.objects.exists())

    def test_wrong_workspace_binding_rejected(self):
        other = Workspace.objects.create(owner=self.user, name='B')
        mailbox = resolve_google_mailbox(actor=self.user, workspace=other, verified_sub='synthetic-principal')
        AccountMailboxBinding.objects.filter(account=self.account).update(mailbox=mailbox)
        with self.assertRaises(NotFound):
            self.sync(fetched())
        self.assertFalse(RetainedObservation.objects.exists())
        self.assertFalse(AccountMatch.objects.exists())

    def test_workspace_namespace_isolation(self):
        for owner in [self.user, User.objects.create_user(username='other')]:
            other = Workspace.objects.create(owner=owner, name='other')
            mailbox = resolve_google_mailbox(actor=owner, workspace=other, verified_sub='synthetic-principal')
            account = EmailAccount.objects.create(workspace=other, provider='gmail', email=self.account.email)
            AccountMailboxBinding.objects.create(account=account, mailbox=mailbox)
            self.sync(fetched(subject='Thank you for applying', body='Thanks'), account=account)
        self.sync(fetched())
        self.assertEqual(RetainedMessage.objects.count(), 3)
        self.assertEqual(len(set(RetainedMessage.objects.values_list('mailbox_id', flat=True))), 3)

    def test_existing_relevance_paths_and_irrelevant_message(self):
        self.sync(fetched(subject='Weekend picnic', body='See you Saturday', native='irrelevant'))
        self.assertFalse(RetainedObservation.objects.exists())
        self.sync(fetched())
        self.sync(fetched(native='posting', rfc='<posting@example.test>', subject='Acme Robotics just posted a 92% match Engineer'))
        self.sync(fetched(native='general', rfc='<general@example.test>', subject='Thank you for applying', body='Thanks'))
        Application.objects.create(workspace=self.ws, section='applications', company='Acme Robotics', role_label='Designer')
        self.sync(fetched(native='ambiguous', rfc='<ambiguous@example.test>'))
        reasons = {r.payload['source']['value']: r.payload['reason'] for r in RetainedObservation.objects.all()}
        self.assertEqual(reasons, {'native-1': 'application_evidence', 'posting': 'posting_source', 'general': 'discovery_review', 'ambiguous': 'discovery_review'})
        self.assertEqual(Discovery.objects.filter(kind='posting').count(), 1)
        self.assertEqual(Discovery.objects.get(match_kind='ambiguous').candidate_applications.count(), 2)

    def test_rfc_thread_trust_qualifies_without_native_thread_inference(self):
        ThreadIdentifier.objects.create(application=self.app, message_id='<native-1-one@example.test>')
        self.sync(fetched(subject='Re: quick question', body='Fine', rfc=None))
        self.assertEqual(RetainedObservation.objects.get().payload['reason'], 'application_evidence')
        self.assertFalse(AccountMatch.objects.exists())

    def test_all_timestamp_channels_are_separate_and_no_application_activity(self):
        before = list(Application.objects.values()), list(StatusHistory.objects.values())
        self.sync(fetched())
        row, observation = RetainedMessage.objects.get(), RetainedObservation.objects.get()
        self.assertEqual(row.content['provider_received']['source'], 'gmail_internal_date')
        self.assertEqual(row.content['provider_received']['value'], '2023-11-14T22:13:20.123000+00:00')
        self.assertEqual(row.content['header_sent']['value'], '2026-09-18T16:00:00+00:00')
        self.assertEqual(row.content['header_sent']['source_utc_offset_seconds'], -21600)
        self.assertEqual(observation.observed_at, OBSERVED)
        self.assertNotEqual(row.retained_at, observation.observed_at)
        self.assertEqual(before, (list(Application.objects.values()), list(StatusHistory.objects.values())))
        self.assertFalse(Document.objects.exists())

    def test_missing_and_invalid_internal_date_stay_unknown(self):
        for n, value in enumerate([None, 'garbage', '', '1.5', '-1', True, '9' * 1000]):
            with self.subTest(value=value):
                message = fetched(native=f'unknown-{n}', rfc=f'<unknown-{n}@example.test>', internal=value)
                self.sync(message)
                self.assertIsNone(message.provider_internal_at)
                self.assertEqual(RetainedMessage.objects.get(locator_value=f'unknown-{n}').content['provider_received'], {'precision': 'unknown', 'value': None, 'source': 'unknown'})

    def test_date_only_uncertain_and_missing_header_time(self):
        for n, (date, precision) in enumerate([('2026-09-18', 'date'), ('Fri, 18 Sep 2026 10:00:00 -0000', 'uncertain'), ('nonsense', 'uncertain'), (None, 'unknown')]):
            self.sync(fetched(native=f'date-{n}', rfc=f'<date-{n}@example.test>', date=date))
            claim = RetainedMessage.objects.get(locator_value=f'date-{n}').content['header_sent']
            self.assertEqual(claim['precision'], precision)
            if precision == 'date':
                self.assertEqual(claim['value'], date)

    @override_settings(RETAINED_EMAIL_TEXT_BYTES=12, RETAINED_EMAIL_HTML_BYTES=10)
    def test_bounded_content_repeated_headers_and_structured_addresses(self):
        self.sync(fetched(body='Acme Robotics.\r\n' + 'é' * 30, html='<p>' + 'é' * 30 + '</p>'))
        content = RetainedMessage.objects.get().content
        for name, limit in [('text', 12), ('html', 10)]:
            self.assertLessEqual(len(content[name]['value'].encode()), limit)
            self.assertEqual(content[name]['completeness'], 'partial')
            self.assertEqual(content[name]['reason'], 'retention_byte_limit')
            self.assertEqual(content[name]['truncation']['location'], 'utf8_prefix')
        self.assertEqual([h for h in content['headers'] if h[0] == 'references'], [['references', '<native-1-one@example.test>'], ['references', '<native-1-two@example.test>']])
        self.assertEqual(content['addresses']['from'], [{'name': 'Recruiter', 'address': 'recruiter@example.test'}])
        self.assertEqual(len(content['addresses']['to']), 2)
        self.assertEqual(set(content['addresses']), {'from', 'reply_to', 'to', 'cc', 'bcc'})
        self.assertNotIn('raw', content)
        self.assertNotIn('raw_source', content)

    def test_html_only_and_unavailable_content(self):
        self.sync(fetched(body=None))
        self.assertEqual(RetainedMessage.objects.get().content['text']['completeness'], 'unavailable')
        self.assertEqual(RetainedMessage.objects.get().content['html']['value'], '<p>Hello</p>')
        self.sync(fetched(native='no-body', rfc='<no-body@example.test>', body=None, html=None))
        content = RetainedMessage.objects.get(locator_value='no-body').content
        self.assertEqual(content['html']['completeness'], 'unavailable')
        self.assertEqual(content['text']['completeness'], 'unavailable')

    def test_projection_failure_rolls_back_retention_and_preserves_cursor(self):
        with patch('email_sync.sync_service._record_thread', side_effect=RuntimeError('synthetic failure')), self.assertRaises(RuntimeError):
            self.sync(fetched())
        for model in [RetainedMessage, RetainedObservation, RetentionKey, AccountMatch, ThreadIdentifier]:
            self.assertFalse(model.objects.exists())
        self.account.refresh_from_db()
        self.assertIsNone(self.account.last_synced_at)

    def test_retention_failure_prevents_projection(self):
        with self.assertRaises(ValidationError):
            self.sync(fetched(native='x' * 513))
        self.assertFalse(AccountMatch.objects.exists())
        self.assertFalse(RetainedMessage.objects.exists())

    def test_binding_changed_while_fetching_is_rejected(self):
        AccountMailboxBinding.objects.all().delete()
        def fetch(account, terms, since=None):
            AccountMailboxBinding.objects.create(account=self.account, mailbox=self.mailbox)
            return [fetched()]
        provider = FakeProvider()
        provider.fetch_messages = fetch
        with self.assertRaises(ValidationError):
            sync_account(self.account, provider)
        self.assertFalse(RetainedObservation.objects.exists())

    def test_native_thread_does_not_make_an_irrelevant_message_relevant(self):
        self.sync(fetched())
        self.sync(fetched(native='unrelated', rfc='<unrelated@example.test>', subject='Weekend picnic', body='Hello'))
        self.assertEqual(RetainedMessage.objects.count(), 1)

    def test_projection_replay_preserves_dismissal_and_posting_urls(self):
        message = fetched(subject='Acme Robotics just posted a 92% match Engineer',
                          body='https://jobs.example.test/role')
        self.sync(message)
        discovery = Discovery.objects.get()
        self.assertEqual(discovery.posting_urls, ['https://jobs.example.test/role'])
        discovery.status = 'dismissed'
        discovery.save()
        self.sync(message)
        self.assertEqual(Discovery.objects.get().status, 'dismissed')
        self.assertEqual(RetainedMessage.objects.count(), 1)

    def test_attachment_and_nested_message_bodies_are_not_retained(self):
        source = ('Subject: Acme Robotics interview\r\nContent-Type: multipart/mixed; boundary=m\r\n\r\n'
                  '--m\r\nContent-Type: text/plain\r\nContent-Disposition: attachment; filename=a.txt\r\n\r\nATTACHMENT\r\n'
                  '--m\r\nContent-Type: text/html; name=inline.html\r\nContent-Disposition: inline; filename=inline.html\r\n\r\n<p>NAMED-FILE</p>\r\n'
                  '--m\r\nContent-Type: message/rfc822\r\nContent-Disposition: attachment\r\n\r\n'
                  'Subject: forwarded\r\nContent-Type: text/html\r\n\r\n<p>NESTED</p>\r\n'
                  '--m\r\nContent-Type: text/plain\r\n\r\nINLINE\r\n--m--\r\n')
        message = _to_fetched_message({'id': 'attachment-test', 'raw': base64.urlsafe_b64encode(source.encode()).decode()})
        self.sync(message)
        content = RetainedMessage.objects.get().content
        self.assertEqual(content['text']['value'], 'INLINE')
        self.assertEqual(content['html']['completeness'], 'unavailable')
        self.assertNotIn('ATTACHMENT', str(content))
        self.assertNotIn('NESTED', str(content))
        self.assertNotIn('NAMED-FILE', str(content))

    def test_empty_plain_body_is_available_and_missing_optional_headers_are_safe(self):
        source = 'Subject: Acme Robotics interview\r\nContent-Type: text/plain\r\n\r\n'
        message = _to_fetched_message({'id': 'empty', 'raw': base64.urlsafe_b64encode(source.encode()).decode()})
        self.sync(message)
        content = RetainedMessage.objects.get().content
        self.assertEqual(content['text'], {'value': '', 'completeness': 'complete', 'reason': ''})
        self.assertEqual(content['addresses'], {})
        self.assertEqual(content['header_sent']['precision'], 'unknown')

    def test_provider_rejects_mismatched_native_response_id(self):
        service = _FakeGmailService(list_pages=[{'messages': [{'id': 'native-1'}]}],
                                    messages_by_id={'native-1': gmail_fixture(native='wrong')})
        with patch('email_sync.gmail_provider.time.sleep'):
            result = sync_account(self.account, GmailProvider(lambda account: service))
        self.assertFalse(result.ok)
        self.assertFalse(RetainedMessage.objects.exists())

    def test_read_only_inspection_and_admin(self):
        self.sync(fetched())
        row = RetainedMessage.objects.get()
        client = APIClient()
        client.force_authenticate(self.user)
        url = f'/api/workspaces/{self.ws.pk}/retained-messages/{row.pk}/'
        before = list(RetainedObservation.objects.values())
        self.assertEqual(client.get(url).status_code, 200)
        for method in ['post', 'patch', 'delete']:
            self.assertEqual(getattr(client, method)(url, {}, format='json').status_code, 405)
        request = APIRequestFactory().get('/')
        request.user = self.user
        for model in [RetainedMessage, RetainedObservation, MailboxLineage]:
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
        self.assertEqual(before, list(RetainedObservation.objects.values()))


class GmailConnectionAdoptionTests(ConnectionFixture, TestCase):
    def test_reconnect_email_change_disconnect_and_recreation_keep_source_namespace(self):
        from email_sync import oauth
        account = self.connect()
        sync_account(account, FakeProvider([fetched(subject='Thank you for applying', body='Thanks')]))
        original = RetainedMessage.objects.get()
        with patch.object(oauth, 'revoke_gmail_token'):
            oauth.disconnect_gmail_account(account)
        self.assertTrue(RetainedMessage.objects.filter(pk=original.pk).exists())
        account = self.connect(email='changed@example.test')
        sync_account(account, FakeProvider([fetched(subject='Thank you for applying', body='Thanks')]))
        account.delete()
        account = self.connect(email='again@example.test')
        sync_account(account, FakeProvider([fetched(subject='Thank you for applying', body='Thanks')]))
        self.assertEqual(RetainedMessage.objects.get().pk, original.pk)
        self.assertEqual(account.mailbox_binding.mailbox_id, original.mailbox_id)
        self.assertFalse(RetainedMessage.objects.get().has_conflict)


class GmailTransactionTests(AdoptionFixtures, TransactionTestCase):
    def test_network_outside_transaction_and_bounded_partial_failure_retry(self):
        first, second = fetched(), fetched(native='second', rfc='<second@example.test>')
        def fetch(account, terms, since=None):
            self.assertFalse(connection.in_atomic_block)
            return [first, second]
        provider = FakeProvider()
        provider.fetch_messages = fetch
        from email_sync.sync_service import _project_message
        def project(account, message, classification, result):
            self.assertTrue(connection.in_atomic_block)
            if message.provider_message_id == 'second':
                raise RuntimeError('synthetic second-message failure')
            return _project_message(account, message, classification, result)
        with patch('email_sync.sync_service._project_message', side_effect=project), self.assertRaises(RuntimeError):
            sync_account(self.account, provider)
        self.assertEqual(RetainedMessage.objects.count(), 1)
        self.assertEqual(AccountMatch.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertIsNone(self.account.last_synced_at)
        sync_account(self.account, provider)
        self.assertEqual(RetainedMessage.objects.count(), 2)
        self.assertEqual(RetainedObservation.objects.count(), 2)
        self.assertEqual(AccountMatch.objects.count(), 2)

    def test_equivalent_concurrent_attempts_converge_after_explicit_retry(self):
        barrier = Barrier(2)
        message = fetched()
        def compete(n):
            close_old_connections()
            try:
                account = EmailAccount.objects.get(pk=self.account.pk)
                barrier.wait(timeout=10)
                return sync_account(account, FakeProvider([message]))
            except OperationalError:
                return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(compete, range(2)))
        for _ in range(2):
            self.sync(message)
        self.assertEqual(RetainedMessage.objects.count(), 1)
        self.assertEqual(RetainedObservation.objects.count(), 1)
        self.assertEqual(AccountMatch.objects.count(), 1)
        self.assertFalse(RetainedMessage.objects.get().has_conflict)
