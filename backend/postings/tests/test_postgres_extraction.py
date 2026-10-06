"""First-attempt PostgreSQL evidence, independent connections and observed blockers."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from queue import Queue
from threading import Event, Lock
import time
import uuid
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.db import connection, connections, transaction
from django.test import TransactionTestCase
from rest_framework.exceptions import APIException

from accounts.models import User, Workspace
from email_sync.models import RetainedMessage, RetainedObservation
from email_sync.retention import retain_observation
from email_sync.tests.test_retention import fixture
from postings import retained_extraction_producer as producer
from postings.models import RetainedPostingExtraction as Extraction, RetainedPostingExtractionOutput as Output
from postings.retained_extractions import record_posting_extraction, scoped_source
from postings.tests.test_retained_extractions import Fixtures, fields, spec


class PostgresExtractionTests(Fixtures, TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL-only concurrency evidence")
        super().setUp()
        self.entered, self.release = Event(), Event()
        self.parser_lock = Lock()
        self.parser_calls = 0

    def args(self, **changes):
        args = deepcopy(self.kw)
        args.update(changes)
        args['actor'] = User.objects.get(pk=args['actor'].pk)
        args['workspace'] = Workspace.objects.get(pk=args['workspace'].pk)
        return args

    def produce(self, **changes):
        args = self.args(**changes)
        args.pop('outputs'); args.pop('extracted_at')
        return producer.produce_retained_job_alert_extraction(**args)

    def record(self, **changes):
        result = record_posting_extraction(**self.args(**changes))
        return (result.operation.pk, result.replay, tuple(o.pk for o in result.outputs))

    def parser(self, *args):
        with self.parser_lock:
            self.parser_calls += 1
            first = self.parser_calls == 1
        if first:
            self.entered.set()
            if not self.release.wait(10):
                raise AssertionError("Held parser was not released")
        return [fields('A'), fields('B')]

    def worker(self, queue, call):
        connections.close_all()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '15s'")
                cursor.execute("SET statement_timeout = '30s'")
                cursor.execute("SELECT pg_backend_pid()")
                queue.put(cursor.fetchone()[0])
            return call()
        finally:
            connections.close_all()

    def blocked(self, waiter, holder):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_blocking_pids(%s)", [waiter])
                if holder in cursor.fetchone()[0]:
                    return
            time.sleep(.01)
        self.fail(f"Backend {waiter} did not block on {holder}")

    def pair(self, left, right, *, independent=False, parser=True):
        pids = [Queue(), Queue()]
        pool = ThreadPoolExecutor(max_workers=2)
        futures = []
        try:
            context = patch.object(producer, 'extract_postings', self.parser) if parser else patch.object(producer, 'extract_postings', return_value=[])
            with context as installed_parser:
                self.installed_parser = installed_parser
                futures.append(pool.submit(self.worker, pids[0], left))
                holder = pids[0].get(timeout=5)
                self.assertTrue(self.entered.wait(5), "First worker did not reach held section")
                futures.append(pool.submit(self.worker, pids[1], right))
                waiter = pids[1].get(timeout=5)
                if independent:
                    second = futures[1].result(timeout=5)
                    self.assertFalse(futures[0].done())
                else:
                    self.blocked(waiter, holder)
                    self.assertFalse(futures[1].done())
                self.release.set()
                first = futures[0].result(timeout=40)
                if not independent:
                    second = futures[1].result(timeout=40)
                return first, second
        finally:
            self.release.set()
            errors = []
            try:
                for future in futures:
                    try:
                        future.result(timeout=40)
                    except Exception as error:
                        errors.append(error)
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
            if errors:
                raise ExceptionGroup("Concurrency worker failures", errors)

    def reject(self, call, code, status=409):
        try:
            call()
        except APIException as exc:
            self.assertEqual(exc.status_code, status)
            self.assertEqual(exc.get_codes(), code)
            return code
        self.fail("Expected explicit domain rejection")

    def assert_batches(self, count, outputs=2):
        self.assertEqual(Extraction.objects.count(), count)
        self.assertEqual(Output.objects.count(), count * outputs)
        for row in Extraction.objects.all():
            self.assertEqual(list(row.outputs.order_by('position').values_list('position', flat=True)), list(range(outputs)))

    def conflict(self):
        message = RetainedMessage.objects.get(pk=self.message.pk)
        data = fixture(message.mailbox)
        # Use the existing raw observation fixture; stored content includes
        # normalized version/timestamp metadata not accepted by the input API.
        data['content']['addresses'] = deepcopy(message.content['addresses'])
        data['content']['subject'] = 'Conflicting source content'
        return retain_observation(actor=User.objects.get(pk=self.user.pk),
            workspace=Workspace.objects.get(pk=self.ws.pk), key='conflicting-observation', observation=data)

    def test_equivalent_producer_first_attempts(self):
        first, second = self.pair(self.produce, self.produce)
        self.assertFalse(first.replay); self.assertTrue(second.replay)
        self.assertEqual(first.extraction_id, second.extraction_id)
        self.assertEqual(first.outputs, second.outputs)
        self.assertEqual(first.completed_at, second.completed_at)
        self.assertEqual(self.parser_calls, 1)
        self.assert_batches(1)

    def test_conflicting_specifications_first_attempts(self):
        declared = spec(); declared['selectors']['sender']['index'] = 1
        first, code = self.pair(self.produce, lambda: self.reject(
            lambda: self.produce(input_spec=declared), 'idempotency_key_reused'))
        self.assertEqual(code, 'idempotency_key_reused')
        self.assertFalse(first.replay)
        self.assertEqual(Extraction.objects.get().input_spec, spec())
        self.assertEqual([o.fields for o in Output.objects.order_by('position')], [fields('A'), fields('B')])
        self.assertEqual(self.parser_calls, 1)
        self.assert_batches(1)

    def test_different_operations_one_source(self):
        first, second = self.pair(self.produce, lambda: self.produce(operation_id=uuid.uuid4()))
        self.assertFalse(first.replay); self.assertFalse(second.replay)
        self.assertNotEqual(first.extraction_id, second.extraction_id)
        self.assertEqual(self.parser_calls, 2)
        self.assert_batches(2)

    def test_producer_before_real_retention_conflict(self):
        original = deepcopy(self.message.content)
        first, conflict = self.pair(self.produce, self.conflict)
        self.assertEqual(conflict.state, 'conflict')
        self.assertEqual(conflict.message_id, self.message.pk)
        self.message.refresh_from_db()
        self.assertTrue(self.message.has_conflict)
        self.assertEqual(self.message.content, original)
        self.assertEqual(RetainedObservation.objects.filter(message=self.message).count(), 2)
        with patch.object(producer, 'extract_postings', side_effect=AssertionError('Replay/rejection parsed')):
            replay = self.produce()
            self.assertTrue(replay.replay); self.assertFalse(replay.source_eligible)
            self.assertEqual(first.outputs, replay.outputs)
            self.reject(lambda: self.produce(operation_id=uuid.uuid4()), 'retained_source_ineligible')
        self.assertEqual(self.parser_calls, 1)
        self.assert_batches(1)

    def test_retention_conflict_before_producer(self):
        def held_conflict():
            with transaction.atomic():
                result = self.conflict()
                self.entered.set()
                self.assertTrue(self.release.wait(10))
                return result
        conflict, code = self.pair(held_conflict, lambda: self.reject(self.produce, 'retained_source_ineligible'), parser=False)
        self.assertEqual(conflict.state, 'conflict')
        self.assertEqual(code, 'retained_source_ineligible')
        self.installed_parser.assert_not_called()
        self.assert_batches(0)
        self.assertTrue(RetainedMessage.objects.get(pk=self.message.pk).has_conflict)

    def test_same_workspace_different_sources(self):
        other = self.source(self.ws)
        first, second = self.pair(self.produce, lambda: self.produce(retained_message_id=other.pk))
        self.assertNotEqual(first.retained_message_id, second.retained_message_id)
        self.assertEqual(self.parser_calls, 2)
        self.assert_batches(2)

    def test_independent_workspace_progress(self):
        other = self.source(self.ws2)
        first, second = self.pair(self.produce, lambda: self.produce(workspace=self.ws2,
            retained_message_id=other.pk), independent=True)
        self.assertNotEqual(first.workspace_id, second.workspace_id)
        self.assertEqual(self.parser_calls, 2)
        self.assert_batches(2)

    def test_source_row_lock_independently_of_workspace_gate(self):
        def hold_source():
            with transaction.atomic():
                scoped_source(Workspace.objects.get(pk=self.ws.pk), self.message.pk, lock=True)
                self.entered.set()
                self.assertTrue(self.release.wait(10))
        self.pair(hold_source, self.produce, parser=False)
        self.assert_batches(1, outputs=0)

    def test_later_output_failure_standalone_and_nested(self):
        real = Output.save
        for nested in (False, True):
            with self.subTest(nested=nested):
                count = 0
                def fail_second(instance, *args, **kwargs):
                    nonlocal count
                    count += 1
                    if count == 2:
                        raise RuntimeError('injected second-output failure')
                    return real(instance, *args, **kwargs)
                with patch.object(Output, 'save', fail_second), patch.object(producer, 'extract_postings', return_value=[fields('A'), fields('B')]) as parser:
                    with self.assertRaisesRegex(RuntimeError, 'second-output'):
                        self.produce() if nested else self.record(outputs=[fields('A'), fields('B')])
                    self.assertEqual(parser.call_count, int(nested))
                self.assert_batches(0)

    def test_caller_outer_rollback_and_uncommitted_visibility(self):
        class Rollback(Exception):
            pass
        queue = Queue()
        with patch.object(producer, 'extract_postings', return_value=[fields()]) as parser:
            with self.assertRaises(Rollback):
                with transaction.atomic():
                    receipt = self.produce()
                    self.assertEqual(Extraction.objects.count(), 1)
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(self.worker, queue, lambda: (Extraction.objects.count(), Output.objects.count()))
                        self.assertEqual(future.result(timeout=5), (0, 0))
                    self.assertFalse(receipt.replay)
                    raise Rollback()
            self.assert_batches(0)
            retry = self.produce()
            self.assertFalse(retry.replay)
            self.assertEqual(parser.call_count, 2)
            self.assert_batches(1, outputs=1)

    def test_unauthorized_and_cross_workspace(self):
        foreign = self.source(self.ws2)
        before = self.snapshot()
        with patch.object(producer, 'extract_postings', side_effect=AssertionError('Unauthorized parse')) as parser:
            for call in (self.produce, self.record):
                self.reject(lambda: call(actor=self.other), 'not_found', 404)
                self.reject(lambda: call(retained_message_id=foreign.pk), 'not_found', 404)
                self.reject(lambda: call(workspace=self.ws2), 'not_found', 404)
            args = self.args(); args['actor'] = AnonymousUser()
            self.reject(lambda: record_posting_extraction(**args), 'not_found', 404)
            args.pop('outputs'); args.pop('extracted_at')
            self.reject(lambda: producer.produce_retained_job_alert_extraction(**args), 'not_found', 404)
            parser.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def recorder_pair(self, conflicting):
        # Hold the real first recorder after operation insertion, before outputs.
        real = Output.save
        def hold(instance, *args, **kwargs):
            self.entered.set()
            self.assertTrue(self.release.wait(10))
            return real(instance, *args, **kwargs)
        with patch.object(Output, 'save', hold):
            return self.pair(self.record, (lambda: self.reject(lambda: self.record(outputs=[fields('different')]),
                'idempotency_key_reused')) if conflicting else self.record, parser=False)

    def test_equivalent_recorder_first_attempts(self):
        first, second = self.recorder_pair(False)
        self.assertFalse(first[1]); self.assertTrue(second[1])
        self.assertEqual(first[0], second[0]); self.assertEqual(first[2], second[2])
        self.assert_batches(1, outputs=1)

    def test_conflicting_recorder_first_attempts(self):
        first, code = self.recorder_pair(True)
        self.assertFalse(first[1]); self.assertEqual(code, 'idempotency_key_reused')
        self.assertEqual(Output.objects.get().fields, fields())
        self.assert_batches(1, outputs=1)
