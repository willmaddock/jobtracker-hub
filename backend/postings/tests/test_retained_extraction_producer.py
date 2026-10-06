"""Explicit execution/replay acceptance using isolated authoritative retention."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields as dataclass_fields
from datetime import datetime, timezone
from threading import Barrier, Event
from unittest.mock import patch
import json
import uuid

from django.contrib.auth.models import AnonymousUser
from django.db import OperationalError, close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import APIException

from accounts.models import User
from email_sync.models import RetainedMessage
from postings import retained_extraction_producer as service, extraction_contract as contract
from postings.extraction import extract_postings
from postings.models import RetainedPostingExtraction as Extraction, RetainedPostingExtractionOutput as Output
from postings.tests.test_retained_extractions import Fixtures, fields, spec
from postings.tests.test_extraction import linkedin_body, handshake_body, lensa_body, indeed_digest_body


class ProducerFixtures(Fixtures):
    def produce(self, **changes):
        args = {k: deepcopy(v) for k, v in self.kw.items() if k not in {'outputs', 'extracted_at'}}
        args.update(changes)
        return service.produce_retained_job_alert_extraction(**args)

    def source_args(self, sender, subject, body, *, unavailable=False):
        def change(content):
            content['addresses']['from'] = [{'name': 'Display name', 'address': sender}] if sender else []
            content['subject'] = subject
            content['text'] = {'value': body, 'completeness': 'unavailable' if unavailable else 'complete'}
        return self.source(self.ws, change=change)

    def reject_without_parser(self, changes, code, status=400):
        with patch.object(service, 'extract_postings', side_effect=AssertionError('parser called')):
            self.error(code, lambda: self.produce(**changes), status)


class ProducerTests(ProducerFixtures, TestCase):
    def test_real_fixture_batches(self):
        cases = [('jobalerts-noreply@linkedin.com', 'Software Engineer at Haystack', linkedin_body(), 6),
                 ('mail@joinhandshake.com', 'Weekly jobs', handshake_body(), 5),
                 ('mail@lensa.com', 'Worky and 5 more', lensa_body(), 6),
                 ('mail@indeed.com', 'HackerEarth and 18 more', indeed_digest_body(), 19)]
        for sender, subject, body, minimum in cases:
            with self.subTest(sender=sender):
                source = self.source_args(sender, subject, body)
                expected = extract_postings(sender, subject, body)
                self.assertGreaterEqual(len(expected), minimum)
                result = self.produce(retained_message_id=source.pk)
                self.assertEqual([dict((k, getattr(o, k)) for k in contract.FIELDS) for o in result.outputs], expected)
                self.assertEqual([o.position for o in result.outputs], list(range(len(expected))))
                self.assertEqual(len({o.portable_id for o in result.outputs}), len(expected))
                self.assertTrue(all(uuid.UUID(o.portable_id).version == 4 for o in result.outputs))

    def test_real_fallback_and_empty_cases(self):
        for sender, subject, body, n in [('noreply@honeywell.com', 'Engineer at Honeywell', 'Apply now', 1),
                ('mail@ziprecruiter.com', 'Jobs', 'Unparsed', 0),
                ('mail@linkedin.com', 'Jobs', '', 0),
                ('mail@linkedin.com', 'Jobs', 'Unextractable', 0)]:
            source = self.source_args(sender, subject, body)
            self.assertEqual(len(self.produce(retained_message_id=source.pk).outputs), n)

    def test_exact_arguments_and_explicit_selectors(self):
        for role, index in [('from', 0), ('from', 1), ('sender', 0)]:
            def change(content):
                content['addresses']['sender'] = [{'name': 'Sender display', 'address': 'sender@example.test'}]
                content['subject'] = '  Subject &amp;\n'
                content['text']['value'] = '  Body &amp;\n'
            source = self.source(self.ws, change=change)
            declared = spec(); declared['selectors']['sender'] = {'role': role, 'index': index}
            with patch.object(service, 'extract_postings', return_value=[]) as parser:
                self.produce(retained_message_id=source.pk, input_spec=declared)
                parser.assert_called_once_with(source.content['addresses'][role][index]['address'],
                                               '  Subject &amp;\n', '  Body &amp;\n')

    def test_null_unavailable_no_html_fallback(self):
        source = self.source_args(None, None, None, unavailable=True)
        declared = spec(); declared['selectors']['sender'] = None
        with patch.object(service, 'extract_postings', return_value=[]) as parser:
            result = self.produce(retained_message_id=source.pk, input_spec=declared)
            parser.assert_called_once_with(None, None, None)
        self.assertEqual(result.outputs, ())

    def test_authorization_and_identity_matrix(self):
        for actor in (self.other, AnonymousUser(), None, User(username='unsaved')):
            self.reject_without_parser({'actor': actor}, 'not_found', 404)
        for value in (None, True, '1', 0, -1, 2**63, 999999):
            self.reject_without_parser({'retained_message_id': value}, 'not_found', 404)
        self.reject_without_parser({'workspace': self.ws2}, 'not_found', 404)
        for value in (None, True, 1, 'bad', uuid.uuid1(), self.kw['operation_id'].hex):
            self.reject_without_parser({'operation_id': value}, 'invalid_posting_extraction')

    def test_spec_and_version_rejection(self):
        cases = []
        for selector in (None, {'role': 'from', 'index': True}, {'role': 'from', 'index': 99},
                         {'role': 'to', 'index': 0}):
            changed = spec(); changed['selectors']['sender'] = selector; cases.append(changed)
        for key, value in [('body', 'content.html.value'), ('subject', 'x' * 3000)]:
            changed = spec(); changed['selectors'][key] = value; cases.append(changed)
        changed = spec(); changed['extra'] = 'x' * 3000; cases.append(changed)
        for declared in cases:
            self.reject_without_parser({'input_spec': declared}, 'invalid_posting_extraction')
        for changes in ({'extractor_version': '2'}, {'extractor_version': 1}, {'extractor_method': 'other'}):
            self.reject_without_parser(changes, 'invalid_posting_extraction')

    def test_source_scope_and_integrity_matrix(self):
        original = RetainedMessage.objects.values().get(pk=self.message.pk)
        for change, code in [({'provider': 'outlook'}, 'not_found'),
                             ({'workspace_id': self.ws2.pk}, 'not_found'),
                             ({'content_digest': '0' * 64}, 'retained_source_invalid'),
                             ({'representation_version': 2}, 'retained_source_invalid')]:
            RetainedMessage.objects.filter(pk=self.message.pk).update(**change)
            self.reject_without_parser({}, code, 404 if code == 'not_found' else 409)
            RetainedMessage.objects.filter(pk=self.message.pk).update(**{k: original[k] for k in change})
        content = deepcopy(self.message.content); content['provider_received']['source'] = 'graph_received_datetime'
        RetainedMessage.objects.filter(pk=self.message.pk).update(content=content, content_digest=contract.digest(content))
        self.reject_without_parser({}, 'retained_source_invalid', 409)

    def test_timestamp_metadata_digest_and_replay_without_clock_or_parser(self):
        instant = datetime(2026, 10, 5, 12, 34, 56, 123456, tzinfo=timezone.utc)
        with patch.object(service, 'extract_postings', return_value=[fields('B'), fields('A')]), \
             patch.object(service.timezone, 'now', return_value=instant):
            first = self.produce()
        row = Extraction.objects.get(pk=first.extraction_id)
        self.assertEqual(first.completed_at, contract.timestamp(instant.isoformat()))
        self.assertEqual(row.extracted_at, instant)
        self.assertEqual(first.recorded_at, contract.timestamp(row.recorded_at.isoformat()))
        self.assertEqual(first.snapshot_version, 1)
        self.assertEqual(first.workspace_id, self.ws.pk)
        self.assertEqual(first.retained_message_portable_id, str(self.message.portable_id))
        self.assertEqual(first.extractor_method, contract.EXTRACTOR_METHOD)
        self.assertEqual(first.extractor_version, contract.EXTRACTOR_VERSION)
        envelope = contract.validate_envelope(row.operation_id, row.extractor_method, row.extractor_version,
            row.input_spec, row.extracted_at.isoformat(), [fields('B'), fields('A')])
        self.assertEqual(first.payload_digest, contract.replay_digest(envelope, {
            'workspace_id': self.ws.pk, 'retained_message_id': self.message.pk,
            'retained_message_portable_id': str(self.message.portable_id),
            'representation_version': 1, 'content_digest': self.message.content_digest}))
        before = self.snapshot()
        with patch.object(service, 'extract_postings', side_effect=AssertionError('parser')), \
             patch.object(service.timezone, 'now', side_effect=AssertionError('clock')):
            second = self.produce(input_spec=dict(reversed(list(spec().items()))))
        self.assertTrue(second.replay)
        for field in dataclass_fields(first):
            if field.name != 'replay':
                self.assertEqual(getattr(first, field.name), getattr(second, field.name))
        self.assertEqual(before, self.snapshot())

    def test_zero_output_historical_replay(self):
        with patch.object(service, 'extract_postings', return_value=[]):
            first = self.produce()
        with patch.object(service, 'extract_postings', return_value=[fields()]) as parser:
            second = self.produce()
            parser.assert_not_called()
        self.assertEqual(first.outputs, second.outputs)
        self.assertEqual(first.completed_at, second.completed_at)
        self.assertEqual(Extraction.objects.count(), 1)
        self.assertEqual(Output.objects.count(), 0)

    def test_changed_intent_and_source_scoped_operation(self):
        with patch.object(service, 'extract_postings', return_value=[fields()]):
            first = self.produce()
            other_source = self.source(self.ws)
            other = self.produce(retained_message_id=other_source.pk)
        self.assertNotEqual(first.extraction_id, other.extraction_id)
        declared = spec(); declared['selectors']['sender']['index'] = 1
        self.reject_without_parser({'input_spec': declared}, 'idempotency_key_reused', 409)
        self.reject_without_parser({'extractor_version': '2'}, 'invalid_posting_extraction')

    def test_conflict_new_work_and_historical_replay(self):
        with patch.object(service, 'extract_postings', return_value=[fields()]):
            first = self.produce()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        with patch.object(service, 'extract_postings', side_effect=AssertionError('parser')):
            replay = self.produce()
        self.assertFalse(replay.source_eligible)
        self.assertEqual(first.extraction_id, replay.extraction_id)
        self.reject_without_parser({'operation_id': uuid.uuid4()}, 'retained_source_ineligible', 409)

    def test_corrupted_historical_siblings_reject_before_parsing(self):
        with patch.object(service, 'extract_postings', return_value=[fields(), fields('Sibling')]):
            result = self.produce()
        sibling = Output.objects.get(pk=result.outputs[1].output_id)
        for change in ({'fields': fields('Tampered')}, {'position': 9}, {'portable_id': uuid.uuid1()}):
            Output.objects.filter(pk=sibling.pk).update(**change)
            self.reject_without_parser({}, 'posting_extraction_evidence_invalid', 409)
            Output.objects.filter(pk=sibling.pk).update(**{k: getattr(sibling, k) for k in change})
        row = Extraction.objects.get(pk=result.extraction_id)
        for change in ({'snapshot_version': 2}, {'payload_digest': '0' * 64}, {'extractor_version': '2'}):
            Extraction.objects.filter(pk=row.pk).update(**change)
            self.reject_without_parser({}, 'posting_extraction_evidence_invalid', 409)
            Extraction.objects.filter(pk=row.pk).update(**{k: getattr(row, k) for k in change})

    def test_parser_failure_and_explicit_retry(self):
        before = self.snapshot()
        with patch.object(service, 'extract_postings', side_effect=RuntimeError('parser failed')):
            with self.assertRaises(RuntimeError):
                self.produce()
        self.assertEqual(before, self.snapshot())
        with patch.object(service, 'extract_postings', return_value=[]) as parser:
            self.assertFalse(self.produce().replay)
            parser.assert_called_once()

    def test_invalid_output_bounds_atomic(self):
        cases = [None, (), [fields() | {'url': 'x'}], [{'source': 'linkedin'}],
                 [fields()] * 1001, [fields('é' * 2049)], [fields() | {'source': 'unknown'}],
                 [fields() | {'title': '\x00'}], [fields('x' * 4096)] * 520]
        for outputs in cases:
            with self.subTest(kind=type(outputs), count=len(outputs) if isinstance(outputs, (tuple, list)) else None):
                with patch.object(service, 'extract_postings', return_value=outputs):
                    self.error('invalid_posting_extraction', self.produce)

    def test_insertion_and_receipt_failure_roll_back(self):
        for target in ('postings.retained_extractions.RetainedPostingExtraction.objects.create',
                       'postings.retained_extractions.RetainedPostingExtractionOutput.objects.create',
                       'postings.retained_extraction_producer.receipt'):
            with patch.object(service, 'extract_postings', return_value=[fields(), fields('Second')]), \
                 patch(target, side_effect=RuntimeError('injected')):
                before = self.snapshot()
                with self.assertRaises(RuntimeError):
                    self.produce()
                self.assertEqual(before, self.snapshot())
        real = Output.save; count = 0
        def fail_second(instance, *args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError('second output')
            return real(instance, *args, **kwargs)
        with patch.object(service, 'extract_postings', return_value=[fields(), fields('Second')]), \
             patch.object(Output, 'save', fail_second):
            with self.assertRaises(RuntimeError):
                self.produce()
        self.assertEqual(Extraction.objects.count(), 0)
        self.assertEqual(Output.objects.count(), 0)

    def test_recorder_revalidates_source_after_parser(self):
        def parser(*args):
            RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
            return [fields()]
        with patch.object(service, 'extract_postings', parser):
            self.error('retained_source_ineligible', self.produce, 409)
        self.assertFalse(RetainedMessage.objects.get(pk=self.message.pk).has_conflict)
        def corrupt(*args):
            RetainedMessage.objects.filter(pk=self.message.pk).update(content_digest='0' * 64)
            return [fields()]
        with patch.object(service, 'extract_postings', corrupt):
            self.error('retained_source_invalid', self.produce, 409)

    def test_caller_spec_detached_before_parser_and_receipt_has_no_lazy_queries(self):
        declared = spec()
        def parser(*args):
            declared['selectors']['sender']['index'] = 1
            return [fields()]
        with patch.object(service, 'extract_postings', parser):
            result = self.produce(input_spec=declared)
        self.assertEqual(result.input_spec_json, contract.canonical_json(spec()).decode())
        declared.clear()
        with self.assertNumQueries(0):
            repr(result); self.assertEqual(result, result)
            for field in dataclass_fields(result):
                getattr(result, field.name)
            for output in result.outputs:
                for field in dataclass_fields(output):
                    getattr(output, field.name)
        with self.assertRaises(FrozenInstanceError):
            result.replay = True
        with self.assertRaises(FrozenInstanceError):
            result.outputs[0].title = 'Changed'
        self.assertEqual(Extraction.objects.get(pk=result.extraction_id).input_spec, spec())

    def test_authority_isolation_all_other_tables_and_forbidden_calls(self):
        def snapshot():
            excluded = {Extraction._meta.db_table, Output._meta.db_table}
            with connection.cursor() as cursor:
                data = {}
                for table in connection.introspection.table_names():
                    if table not in excluded:
                        cursor.execute(f'SELECT * FROM {connection.ops.quote_name(table)} ORDER BY 1')
                        data[table] = cursor.fetchall()
                return data
        from contextlib import ExitStack
        targets = ['postings.services.ingest_extracted_postings', 'postings.extraction.compute_dedupe_key',
                   'email_sync.sync_service.sync_account', 'email_sync.gmail_provider.GmailProvider.fetch_messages',
                   'postings.retained_items.associate_posting_output',
                   'postings.retained_interpretations.decide_posting_interpretation',
                   'postings.posting_sources.attach_posting_source',
                   'postings.job_posting_allocations.allocate_job_posting',
                   'postings.job_posting_interpretations.decide_job_posting_interpretation',
                   'postings.job_posting_projections.project_job_posting_descriptors']
        before = snapshot()
        with ExitStack() as stack:
            for target in targets:
                stack.enter_context(patch(target, side_effect=AssertionError(target)))
            stack.enter_context(patch.object(service, 'extract_postings', return_value=[fields(), fields()]))
            self.produce(); self.produce()
        self.assertEqual(before, snapshot())


class ProducerConcurrencyTests(ProducerFixtures, TransactionTestCase):
    def race(self, conflicting=False, different_operations=False):
        barrier = Barrier(2)
        declared = spec(); declared['selectors']['sender']['index'] = 1
        operations = [self.kw['operation_id'], uuid.uuid4() if different_operations else self.kw['operation_id']]
        def attempt(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.produce(operation_id=operations[index],
                    input_spec=declared if conflicting and index else spec())
            except OperationalError as exc:
                if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower():
                    raise
                return None  # Caller-visible SQLite contention, no hidden retry.
            except APIException as exc:
                self.assertEqual(exc.get_codes(), 'idempotency_key_reused')
                return None
            finally:
                close_old_connections()
        with patch.object(service, 'extract_postings', return_value=[fields()]), ThreadPoolExecutor(max_workers=2) as pool:
            first_attempts = list(pool.map(attempt, range(2)))
        if connection.vendor == "postgresql":
            self.assertEqual(sum(r is not None for r in first_attempts), 2 - int(conflicting))
            self.assertEqual(sum(r.replay for r in first_attempts if r is not None), int(not conflicting and not different_operations))
        successes = []; conflicts = 0
        for index in range(2):
            try:
                # Explicit caller retry after independent connections have ended.
                with patch.object(service, 'extract_postings', return_value=[fields()]):
                    successes.append(self.produce(operation_id=operations[index],
                        input_spec=declared if conflicting and index else spec()))
            except APIException as exc:
                self.assertEqual(exc.get_codes(), 'idempotency_key_reused'); conflicts += 1
        self.assertEqual(Extraction.objects.count(), 2 if different_operations else 1)
        self.assertEqual(conflicts, int(conflicting))
        for result in successes:
            with patch.object(service, 'extract_postings', side_effect=AssertionError('retry parser')):
                replay = self.produce(operation_id=result.operation_id,
                    input_spec=json.loads(result.input_spec_json))
            self.assertTrue(replay.replay)
            self.assertEqual(replay.extraction_id, result.extraction_id)

    def test_same_operation_independent_connections(self):
        self.race()

    def test_conflicting_intent_independent_connections(self):
        self.race(conflicting=True)

    def test_different_operations_same_source(self):
        self.race(different_operations=True)

    def test_cooperating_source_conflict_during_execution(self):
        from django.db import transaction
        from applications.creation import lock_workspace
        started, attempted = Event(), Event()
        def parser(*args):
            started.set()
            self.assertTrue(attempted.wait(timeout=10))
            return [fields()]
        def conflict():
            close_old_connections()
            try:
                self.assertTrue(started.wait(timeout=10))
                attempted.set()
                with transaction.atomic():
                    lock_workspace(self.user, self.ws)
                    RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
                return True
            except OperationalError as exc:
                if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower():
                    raise
                return False  # Explicit caller retry below after winner commits.
            finally:
                close_old_connections()
        with patch.object(service, 'extract_postings', parser), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(conflict)
            first = self.produce()
            succeeded = future.result(timeout=15)
            if connection.vendor == "postgresql":
                self.assertTrue(succeeded)
        with transaction.atomic():
            lock_workspace(self.user, self.ws)
            RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        with patch.object(service, 'extract_postings', side_effect=AssertionError('historical parser')):
            replay = self.produce()
        self.assertEqual(first.extraction_id, replay.extraction_id)
        self.assertFalse(replay.source_eligible)
        self.reject_without_parser({'operation_id': uuid.uuid4()}, 'retained_source_ineligible', 409)
