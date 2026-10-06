"""HTTP evidence inspection contracts, using isolated retained fixtures."""
import base64
from contextlib import ExitStack
import json
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.db import OperationalError, connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from accounts.models import Workspace
from postings import extraction_contract as contract
from postings import retained_extraction_inspection as inspection
from postings import retained_extraction_views as views
from postings.models import RetainedPostingExtraction as Extraction
from postings.tests.test_retained_extractions import Fixtures, fields, spec


def token(raw):
    if isinstance(raw, str):
        raw = raw.encode()
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


class EvidenceAPITests(Fixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = self.route(self.ws.pk, self.message.pk)

    def route(self, workspace, source):
        return reverse('retained-posting-extraction-list', kwargs={
            'workspace_id': workspace, 'retained_message_id': source})

    def add(self, **changes):
        return self.record(operation_id=uuid.uuid4(), **changes)

    def cursor(self, **changes):
        return inspection.RetainedExtractionEvidenceCursor(**{
            'version': 1, 'workspace_id': self.ws.pk,
            'retained_message_id': self.message.pk, 'last_extraction_id': 1, **changes})

    def assert_response(self, response, status, body=None):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertEqual(response['Cache-Control'], 'no-store')
        if body is not None:
            self.assertEqual(response.json(), body)
        return response.json()

    def query_error(self, query):
        with patch.object(inspection, 'read_retained_extraction_evidence') as read:
            response = self.client.get(self.url + '?' + query)
            self.assert_response(response, 400, {'detail': 'Invalid extraction evidence query.',
                                                'code': 'validation_error'})
            read.assert_not_called()

    def test_route_and_empty_history(self):
        self.assertEqual(self.url, f'/api/workspaces/{self.ws.pk}/retained-messages/{self.message.pk}/posting-extractions/')
        self.assertEqual(resolve(self.url).url_name, 'retained-posting-extraction-list')
        data = self.assert_response(self.client.get(self.url), 200)
        self.assertEqual(data, {'source': {'workspace_id': self.ws.pk, 'retained_message_id': self.message.pk,
                         'retained_message_portable_id': str(self.message.portable_id), 'representation_version': 1,
                         'source_eligible': True}, 'operations': [], 'has_more': False,
                         'next_cursor': None, 'consistency': 'advisory'})

    def test_auth_and_workspace_source_nondisclosure(self):
        self.client.force_authenticate(None)
        self.assert_response(self.client.get(self.url), 401, {
            'detail': 'Authentication credentials were not provided.', 'code': 'authentication_required'})
        self.client.force_authenticate(self.user)
        foreign = Workspace.objects.create(owner=self.other, name='Foreign')
        for workspace in (foreign.pk, 2**63 - 1):
            self.assert_response(self.client.get(self.route(workspace, self.message.pk)), 404,
                                 {'detail': 'No Workspace matches the given query.', 'code': 'not_found'})
        foreign_source = self.source(self.ws2)
        for source in (foreign_source.pk, 2**63 - 1, 0):
            self.assert_response(self.client.get(self.route(self.ws.pk, source)), 404,
                                 {'detail': 'Not found.', 'code': 'not_found'})

    def test_limit_contract_and_one_reader_call(self):
        for limit in (None, '1', '2', '3', '4', '5'):
            with self.subTest(limit=limit), patch.object(
                    inspection, 'read_retained_extraction_evidence', wraps=inspection.read_retained_extraction_evidence) as read:
                response = self.client.get(self.url, {} if limit is None else {'limit': limit})
                self.assert_response(response, 200)
                read.assert_called_once_with(actor=self.user, workspace=self.ws,
                    retained_message_id=self.message.pk, cursor=None, limit=2 if limit is None else int(limit))
        for value in ('0', '6', '-1', '2.0', '', '%202', '2%20', '%2B2', '02', '%EF%BC%92', 'true', '9' * 1000):
            with self.subTest(value=value):
                self.query_error('limit=' + value)
        self.query_error('limit=2&limit=2')

    def test_query_scope_and_unknown(self):
        self.assert_response(self.client.get(self.url, {'foo': 'bar'}), 200)
        for key in ('workspace', 'workspace_id', 'owner', 'owner_id'):
            expected = {key: 'Scope is assigned by the route and authenticated user.', 'code': 'validation_error'}
            self.assert_response(self.client.get(self.url, {key: 'secret'}), 400, expected)
            self.assert_response(self.client.generic('GET', self.url, json.dumps({key: 'secret'}),
                                                     content_type='application/json'), 400, expected)
        self.query_error('retained_message_id=1')
        self.query_error('cursor=')
        self.query_error('cursor=x&cursor=x')

    def test_codec_canonical_and_boundaries(self):
        cursor = self.cursor(last_extraction_id=inspection.MAX_ID)
        encoded = views.encode_cursor(cursor)
        self.assertEqual(views.decode_cursor(encoded), cursor)
        self.assertEqual(encoded, views.encode_cursor(cursor))
        self.assertNotIn('=', encoded)
        self.assertLessEqual(len(encoded), 256)
        raw = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
        self.assertLessEqual(len(raw), 192)
        self.assertEqual(raw, json.dumps({key: getattr(cursor, key) for key in views.CURSOR_KEYS},
                                        sort_keys=True, separators=(',', ':')).encode())
        self.query_error('cursor=' + encoded + '=')
        self.query_error('cursor=' + token(json.dumps(json.loads(raw))))
        self.query_error('cursor=' + token(json.dumps(dict(reversed(list(json.loads(raw).items()))), separators=(',', ':'))))
        # Same decoded bytes but nonzero unused base64 bits must not pass canonical equality.
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
        canonical = views.encode_cursor(self.cursor())
        if len(canonical) % 4 in (2, 3):
            altered = canonical[:-1] + alphabet[alphabet.index(canonical[-1]) + 1]
            self.query_error('cursor=' + altered)

    def test_cursor_malformed_and_types(self):
        base = {key: getattr(self.cursor(), key) for key in views.CURSOR_KEYS}
        bad = [b'\xff', '{', '[]', '{}', 'null', json.dumps(base).replace('"version": 1', '"version": 1,"version": 1'),
               json.dumps({**base, 'extra': 1}), json.dumps({k: v for k, v in base.items() if k != 'version'})]
        for key in views.CURSOR_KEYS:
            for value in (True, False, 1.0, '1', None, [], {}, 0, -1, 2**63):
                bad.append(json.dumps({**base, key: value}, sort_keys=True, separators=(',', ':')))
        bad += [json.dumps({**base, 'version': 2}, sort_keys=True, separators=(',', ':')),
                json.dumps(base, sort_keys=True, separators=(',', ':')).replace('"version":1', '"version":NaN'),
                json.dumps(base, sort_keys=True, separators=(',', ':')).replace('"version":1', '"version":Infinity'),
                ' ' * 192, ' ' * 193]
        for raw in bad:
            with self.subTest(raw=raw):
                self.query_error('cursor=' + token(raw))
        for encoded in ('!', 'a', 'a' * 257, 'a' * 256, '%C3%A9'):
            with self.subTest(encoded=encoded):
                self.query_error('cursor=' + encoded)
        # Exactly 256 encoded characters decode to 192 bytes and fail schema, not cost bounds.
        self.assertEqual(len(token(b' ' * 192)), 256)

    def test_context_and_valid_boundary_edits(self):
        for changes in ({'workspace_id': self.ws2.pk}, {'retained_message_id': self.message.pk + 1}):
            response = self.client.get(self.url, {'cursor': views.encode_cursor(self.cursor(**changes))})
            self.assert_response(response, 400, {'detail': 'Invalid extraction evidence navigation.',
                                                'code': 'validation_error'})
        for boundary in (1, inspection.MAX_ID):
            self.assert_response(self.client.get(self.url, {'cursor': views.encode_cursor(
                self.cursor(last_extraction_id=boundary))}), 200)

    def test_history_schema_values_and_privacy(self):
        zero = self.add(outputs=[])
        populated = self.add(outputs=[fields(), fields(), fields('')])
        page = inspection.read_retained_extraction_evidence(actor=self.user, workspace=self.ws,
                                                            retained_message_id=self.message.pk)
        data = self.assert_response(self.client.get(self.url), 200)
        self.assertEqual(set(data), {'source', 'operations', 'has_more', 'next_cursor', 'consistency'})
        self.assertEqual(set(data['source']), {'workspace_id', 'retained_message_id',
            'retained_message_portable_id', 'representation_version', 'source_eligible'})
        self.assertEqual([o['extraction_id'] for o in data['operations']], [zero.operation.pk, populated.operation.pk])
        self.assertEqual(data['operations'][0]['outputs'], [])
        self.assertEqual(data['operations'][0]['output_count'], 0)
        for operation, dto in zip(data['operations'], page.operations):
            self.assertEqual(set(operation), {'extraction_id', 'operation_id', 'extractor_method', 'extractor_version',
                'snapshot_version', 'input_spec_json', 'extracted_at', 'recorded_at', 'output_count', 'outputs'})
            self.assertEqual(operation['input_spec_json'], contract.canonical_json(spec()).decode())
            self.assertEqual(operation['extracted_at'], dto.extracted_at)
            self.assertEqual(operation['recorded_at'], dto.recorded_at)
            self.assertEqual(operation['operation_id'], dto.operation_id)
        outputs = data['operations'][1]['outputs']
        for output in outputs:
            self.assertEqual(set(output), {'output_id', 'portable_id', 'position', 'source', 'title',
                                          'company', 'location', 'salary', 'employment_type'})
        self.assertEqual([o['position'] for o in outputs], [0, 1, 2])
        self.assertEqual(outputs[0]['title'], outputs[1]['title'])
        self.assertNotEqual(outputs[0]['portable_id'], outputs[1]['portable_id'])
        self.assertEqual(outputs[2]['title'], '')
        self.assertIsNone(outputs[0]['location'])
        self.assertIsNone(outputs[0]['employment_type'])
        self.assertEqual(outputs[0]['salary'], '')
        for value in (self.message.content['subject'], self.message.content['text']['value'],
                      self.message.locator_value, self.message.content['addresses']['from'][0]['address']):
            self.assertNotIn(value, json.dumps(data))

    def test_distinct_retained_content_sentinels_never_exposed(self):
        sentinels = ('private-subject-sentinel', 'private-body-sentinel',
                     'private-sender@example.test', 'private-provider-payload-sentinel')
        def change(content):
            content['subject'] = sentinels[0]
            content['text']['value'] = sentinels[1]
            content['addresses']['from'][0]['address'] = sentinels[2]
            content['html']['value'] = sentinels[3]
        source = self.source(self.ws, change=change)
        self.add(retained_message_id=source.pk)
        url = self.route(self.ws.pk, source.pk)
        response = self.client.get(url)
        self.assert_response(response, 200)
        for value in (*sentinels, source.locator_value, source.content_digest):
            self.assertNotIn(value, response.content.decode())
        type(source).objects.filter(pk=source.pk).update(content_digest='0' * 64)
        response = self.client.get(url)
        self.assert_response(response, 409)
        for value in sentinels:
            self.assertNotIn(value, response.content.decode())

    def test_decoded_bound_checked_before_json(self):
        with patch.object(views.base64, 'b64decode', return_value=b' ' * 193), \
             patch.object(views.json, 'loads') as loads:
            with self.assertRaises(ValidationError) as caught:
                views.decode_cursor('aaaa')
            self.assertEqual(caught.exception.detail, {'detail': 'Invalid extraction evidence query.'})
            loads.assert_not_called()

    def test_future_dto_fields_not_serialized(self):
        self.add()
        page = inspection.read_retained_extraction_evidence(actor=self.user, workspace=self.ws,
                                                            retained_message_id=self.message.pk)
        def expanded(dto, names):
            return SimpleNamespace(**{name: getattr(dto, name) for name in names}, secret='private-sentinel')
        output = expanded(page.operations[0].outputs[0], ('output_id', 'portable_id', 'position',
                           'source', 'title', 'company', 'location', 'salary', 'employment_type'))
        operation = expanded(page.operations[0], ('extraction_id', 'operation_id', 'extractor_method',
                    'extractor_version', 'snapshot_version', 'input_spec_json', 'extracted_at', 'recorded_at', 'output_count'))
        operation.outputs = (output,)
        source = expanded(page.source, ('workspace_id', 'retained_message_id', 'retained_message_portable_id',
                                       'representation_version', 'source_eligible'))
        extended = SimpleNamespace(source=source, operations=(operation,), has_more=False,
                                   next_cursor=None, consistency='advisory', secret='private-sentinel')
        with patch.object(inspection, 'read_retained_extraction_evidence', return_value=extended):
            data = self.assert_response(self.client.get(self.url), 200)
        self.assertEqual(data, views.page_json(page))
        self.assertNotIn('private-sentinel', json.dumps(data))

    def test_pagination_append_and_lookahead_corruption(self):
        rows = [self.add().operation.pk for _ in range(3)]
        Extraction.objects.filter(pk=rows[2]).update(payload_digest='0' * 64)
        first = self.assert_response(self.client.get(self.url), 200)
        self.assertEqual([o['extraction_id'] for o in first['operations']], rows[:2])
        self.assertTrue(first['has_more'])
        self.assertEqual(views.decode_cursor(first['next_cursor']).last_extraction_id, rows[1])
        self.assert_response(self.client.get(self.url, {'cursor': first['next_cursor']}), 409,
            {'detail': 'Posting extraction evidence is invalid.', 'code': 'posting_extraction_evidence_invalid'})

    def test_append_continuation_and_limits(self):
        rows = [self.add().operation.pk for _ in range(6)]
        for limit in range(1, 6):
            data = self.assert_response(self.client.get(self.url, {'limit': str(limit)}), 200)
            self.assertEqual([o['extraction_id'] for o in data['operations']], rows[:limit])
        first = self.client.get(self.url).json()
        appended = self.add().operation.pk
        found = [o['extraction_id'] for o in first['operations']]
        while first['next_cursor'] is not None:
            first = self.assert_response(self.client.get(self.url, {'cursor': first['next_cursor']}), 200)
            found.extend(o['extraction_id'] for o in first['operations'])
        self.assertEqual(found, rows + [appended])
        self.assertFalse(first['has_more'])

    def test_conflict_and_corrupt_source_and_returned_evidence(self):
        self.add()
        bad = self.add()
        type(self.message).objects.filter(pk=self.message.pk).update(has_conflict=True)
        data = self.assert_response(self.client.get(self.url), 200)
        self.assertFalse(data['source']['source_eligible'])
        Extraction.objects.filter(pk=bad.operation.pk).update(payload_digest='0' * 64)
        self.assert_response(self.client.get(self.url), 409, {'detail': 'Posting extraction evidence is invalid.',
                                                           'code': 'posting_extraction_evidence_invalid'})
        type(self.message).objects.filter(pk=self.message.pk).update(content_digest='0' * 64)
        self.assert_response(self.client.get(self.url), 409, {'detail': 'Retained source representation is invalid.',
                                                           'code': 'retained_source_invalid'})

    def test_methods_and_negotiation(self):
        for method in ('post', 'put', 'patch', 'delete'):
            response = getattr(self.client, method)(self.url)
            self.assert_response(response, 405, {'detail': f'Method "{method.upper()}" not allowed.',
                                                'code': 'method_not_allowed'})
        with patch.object(inspection, 'read_retained_extraction_evidence') as read:
            self.assert_response(self.client.options(self.url), 200)
            read.assert_not_called()
        with patch.object(inspection, 'read_retained_extraction_evidence',
                          wraps=inspection.read_retained_extraction_evidence) as read:
            response = self.client.head(self.url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b'')
            self.assertEqual(response['Content-Type'], 'application/json')
            self.assertEqual(response['Cache-Control'], 'no-store')
            read.assert_called_once()
        self.assert_response(self.client.get(self.url, HTTP_ACCEPT='text/html'), 406,
                             {'detail': 'Could not satisfy the request Accept header.', 'code': 'not_acceptable'})

    def test_safe_database_failures(self):
        secret = 'SQL SELECT private-body FROM provider-secret traceback'
        for debug in (False, True):
            for target in ('postings.retained_extraction_views.RetainedExtractionEvidenceView.get_workspace',
                           'postings.retained_extraction_inspection.read_retained_extraction_evidence'):
                with self.subTest(debug=debug, target=target), override_settings(DEBUG=debug), \
                     patch(target, side_effect=OperationalError(secret)):
                    response = self.client.get(self.url)
                    self.assert_response(response, 500, {'detail': 'Unable to inspect extraction evidence.',
                                                        'code': 'request_failed'})
                    self.assertNotIn(secret, response.content.decode())

    def table_snapshot(self):
        with connection.cursor() as cursor:
            result = {}
            for table in connection.introspection.table_names(cursor):
                cursor.execute('SELECT * FROM ' + connection.ops.quote_name(table))
                result[table] = sorted(cursor.fetchall(), key=repr)
            return result

    def assert_read_only_request(self):
        before = self.table_snapshot()
        with CaptureQueriesContext(connection) as queries:
            self.assert_response(self.client.get(self.url), 200)
        self.assertTrue(queries)
        for query in queries:
            self.assertTrue(query['sql'].lstrip().upper().startswith('SELECT'), query['sql'])
            self.assertNotIn('FOR UPDATE', query['sql'].upper())
        self.assertEqual(before, self.table_snapshot())

    def test_forced_auth_read_only_and_forbidden_authorities(self):
        self.add()
        targets = ['postings.extraction.extract_postings', 'postings.retained_extraction_producer.extract_postings',
                   'postings.retained_extraction_producer.produce_retained_job_alert_extraction',
                   'postings.retained_extractions.record_posting_extraction', 'email_sync.sync_service.sync_account',
                   'postings.services.ingest_extracted_postings', 'postings.extraction.compute_dedupe_key',
                   'postings.retained_items.associate_posting_output',
                   'postings.retained_item_corrections.correct_posting_item_association',
                   'postings.retained_interpretations.decide_posting_interpretation',
                   'postings.posting_sources.attach_posting_source', 'postings.posting_source_corrections.correct_posting_source',
                   'postings.job_posting_allocations.allocate_job_posting',
                   'postings.job_posting_interpretations.decide_job_posting_interpretation',
                   'postings.job_posting_projections.project_job_posting_descriptors',
                   'applications.creation.create_attempt', 'applications.retained_reviews.set_review_dismissal']
        with ExitStack() as stack:
            calls = [stack.enter_context(patch(target, side_effect=AssertionError(target))) for target in targets]
            self.assert_read_only_request()
            for call in calls:
                call.assert_not_called()

    def test_valid_session_read_only_after_login_setup(self):
        self.add()
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.assert_read_only_request()
        # Invalid session hashes may flush infrastructure state; preserve Django behavior.
        self.user.set_password('changed-after-login')
        self.user.save(update_fields=['password'])
        domain_before = {k: v for k, v in self.table_snapshot().items()
                         if k.startswith(('postings_', 'applications_', 'email_sync_', 'documents_'))}
        with CaptureQueriesContext(connection) as queries:
            self.assert_response(self.client.get(self.url), 401, {
                'detail': 'Authentication credentials were not provided.', 'code': 'authentication_required'})
        self.assertTrue(any('DELETE FROM "django_session"' in q['sql'] for q in queries))
        domain_after = {k: v for k, v in self.table_snapshot().items()
                        if k.startswith(('postings_', 'applications_', 'email_sync_', 'documents_'))}
        self.assertEqual(domain_before, domain_after)
