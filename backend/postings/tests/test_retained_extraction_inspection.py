"""Source evidence inspection acceptance; isolated recorder-created history."""
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, fields as dto_fields, is_dataclass, replace
from unittest.mock import patch
import json
import re
import uuid

from django.contrib.auth.models import AnonymousUser
from django.db import OperationalError, connection, models
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import APIException

from postings import extraction_contract as contract
from postings import retained_extraction_inspection as service
from postings import retained_extractions as authority
from postings.models import RetainedPostingExtraction as Extraction, RetainedPostingExtractionOutput as Output
from postings.tests.test_retained_extractions import Fixtures, fields, spec


class InspectionTests(Fixtures, TestCase):
    def read(self, **changes):
        return service.read_retained_extraction_evidence(**{
            'actor': self.user, 'workspace': self.ws, 'retained_message_id': self.message.pk, **changes})

    def add(self, **changes):
        return self.record(operation_id=uuid.uuid4(), **changes)

    def error(self, code, **changes):
        with self.assertRaises(APIException) as caught:
            self.read(**changes)
        self.assertEqual(caught.exception.get_codes(), code)

    def test_no_history(self):
        page = self.read()
        self.assertEqual(page.operations, ())
        self.assertFalse(page.has_more)
        self.assertIsNone(page.next_cursor)
        self.assertEqual(page.consistency, 'advisory')
        self.assertEqual(page.source.workspace_id, self.ws.pk)
        self.assertEqual(page.source.retained_message_id, self.message.pk)
        self.assertEqual(page.source.retained_message_portable_id, str(self.message.portable_id))
        self.assertEqual(page.source.representation_version, 1)
        self.assertTrue(page.source.source_eligible)

    def test_authorization_and_source_ids(self):
        for actor in (self.other, AnonymousUser(), None):
            self.error('not_found', actor=actor)
        for source in (True, False, 0, -1, 2**63, 1.0, '1', None, 2**63 - 1):
            self.error('not_found', retained_message_id=source)
        self.error('not_found', workspace=self.ws2)
        other_source = self.source(self.ws2)
        self.error('not_found', retained_message_id=other_source.pk)
        self.other.is_staff = self.other.is_superuser = True
        self.other.save()
        self.error('not_found', actor=self.other)

    def test_inactive_owner_preserves_existing_policy(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.assertEqual(self.read().operations, ())

    def test_source_integrity_and_provider_scope(self):
        type(self.message).objects.filter(pk=self.message.pk).update(content_digest='0' * 64)
        self.error('retained_source_invalid')
        type(self.message).objects.filter(pk=self.message.pk).update(content_digest=self.message.content_digest,
                                                                     provider='outlook')
        self.error('not_found')

    def test_conflict_and_current_state_between_calls(self):
        recorded = self.add()
        first = self.read()
        type(self.message).objects.filter(pk=self.message.pk).update(has_conflict=True)
        second = self.read()
        self.assertTrue(first.source.source_eligible)
        self.assertFalse(second.source.source_eligible)
        self.assertEqual(first.operations, second.operations)
        self.assertEqual(second.operations[0].extraction_id, recorded.operation.pk)

    def test_zero_output_and_metadata(self):
        recorded = self.add(outputs=[])
        operation = self.read().operations[0]
        self.assertEqual(operation.output_count, 0)
        self.assertEqual(operation.outputs, ())
        self.assertEqual(operation.extraction_id, recorded.operation.pk)
        self.assertEqual(operation.operation_id, str(recorded.operation.operation_id))
        self.assertEqual(operation.extractor_method, 'job_alert_rules')
        self.assertEqual(operation.extractor_version, '1')
        self.assertEqual(operation.snapshot_version, 1)
        self.assertEqual(operation.extracted_at, contract.timestamp(recorded.operation.extracted_at.isoformat()))
        self.assertEqual(operation.recorded_at, contract.timestamp(recorded.operation.recorded_at.isoformat()))
        self.assertEqual(operation.input_spec_json, contract.canonical_json(spec()).decode())

    def test_order_is_pk_not_timestamp(self):
        first = self.add(extracted_at='2026-09-29T12:00:00Z')
        second = self.add(extracted_at='2026-09-28T12:00:00Z')
        page = self.read()
        self.assertEqual([o.extraction_id for o in page.operations], [first.operation.pk, second.operation.pk])
        self.assertGreater(page.operations[0].extracted_at, page.operations[1].extracted_at)
        self.assertEqual([o.operation_id for o in page.operations],
                         [str(first.operation.operation_id), str(second.operation.operation_id)])

    def test_ordered_duplicate_outputs_preserve_values(self):
        recorded = self.add(outputs=[fields(), fields(), fields('')])
        outputs = self.read().operations[0].outputs
        self.assertEqual([o.position for o in outputs], [0, 1, 2])
        self.assertEqual([o.output_id for o in outputs], [o.pk for o in recorded.outputs])
        self.assertEqual([o.portable_id for o in outputs], [str(o.portable_id) for o in recorded.outputs])
        self.assertNotEqual(outputs[0].portable_id, outputs[1].portable_id)
        self.assertEqual(outputs[0].title, outputs[1].title)
        self.assertIsNone(outputs[0].location)
        self.assertIsNone(outputs[0].employment_type)
        self.assertEqual(outputs[0].salary, '')
        self.assertEqual(outputs[2].title, '')

    def test_limits_and_navigation_errors(self):
        for limit in (True, False, 0, -1, 6, '2', 2.0, None):
            self.error('invalid_extraction_evidence_navigation', limit=limit)
        base = service.RetainedExtractionEvidenceCursor(1, self.ws.pk, self.message.pk, 1)
        for cursor in ('encoded', 1, (), {}, replace(base, version=True), replace(base, version=2),
                       replace(base, workspace_id=self.ws2.pk), replace(base, retained_message_id=self.message.pk + 1)):
            self.error('invalid_extraction_evidence_navigation', cursor=cursor)
        for name in ('workspace_id', 'retained_message_id', 'last_extraction_id'):
            for value in (True, 0, -1, 2**63, 1.0, '1'):
                self.error('invalid_extraction_evidence_navigation', cursor=replace(base, **{name: value}))
        self.assertEqual(self.read(cursor=replace(base, last_extraction_id=2**63 - 1)).operations, ())

    def test_pagination_default_explicit_and_lookahead(self):
        rows = [self.add().operation.pk for _ in range(6)]
        page = self.read()
        self.assertEqual([o.extraction_id for o in page.operations], rows[:2])
        self.assertTrue(page.has_more)
        self.assertEqual(page.next_cursor, service.RetainedExtractionEvidenceCursor(1, self.ws.pk, self.message.pk, rows[1]))
        second = self.read(cursor=page.next_cursor)
        self.assertEqual([o.extraction_id for o in second.operations], rows[2:4])
        final = self.read(cursor=second.next_cursor)
        self.assertEqual([o.extraction_id for o in final.operations], rows[4:])
        self.assertFalse(final.has_more)
        self.assertIsNone(final.next_cursor)
        for limit in range(1, 6):
            self.assertEqual(len(self.read(limit=limit).operations), limit)
        self.assertEqual(self.read(cursor=replace(page.next_cursor, last_extraction_id=2**63 - 1)).operations, ())

    def test_missing_deleted_anchor_and_append(self):
        rows = [self.add().operation.pk for _ in range(3)]
        first = self.read()
        cursor = first.next_cursor
        # Privileged fixture maintenance only; no ordinary evidence deletion.
        Output.objects.filter(extraction_id=cursor.last_extraction_id)._raw_delete('default')
        Extraction.objects.filter(pk=cursor.last_extraction_id)._raw_delete('default')
        appended = self.add().operation.pk
        second = self.read(cursor=cursor)
        self.assertEqual([o.extraction_id for o in second.operations], [rows[2], appended])
        self.assertEqual([o.extraction_id for o in first.operations], rows[:2])
        self.assertFalse(second.has_more)

    def test_validator_reuse_and_bounded_history(self):
        rows = [self.add().operation.pk for _ in range(7)]
        real = authority.validate_extraction_batch
        with patch.object(authority, 'validate_extraction_batch', wraps=real) as validate, \
             CaptureQueriesContext(connection) as queries:
            page = self.read()
        self.assertEqual([c.args[0] for c in validate.call_args_list], rows[:2])
        self.assertTrue(all(c.kwargs['using'] == 'default' for c in validate.call_args_list))
        navigation = [q['sql'] for q in queries
                      if 'postings_retainedpostingextraction' in q['sql']
                      and 'postings_retainedpostingextractionoutput' not in q['sql']
                      and re.search(r'\bLIMIT\s+\d+\b', q['sql'], re.IGNORECASE)]
        # Validator row lookups use LIMIT 1; navigation selects only the PK.
        navigation = [sql for sql in navigation if not re.search(
            r'\bLIMIT\s+1\b', sql, re.IGNORECASE)]
        self.assertEqual(len(navigation), 1)
        limit_token = re.search(r'\bLIMIT\s+(\d+)\b', navigation[0], re.IGNORECASE)
        self.assertEqual(int(limit_token.group(1)), 3)
        self.assertTrue(page.has_more)

    def test_sql_limit_token_does_not_accept_numeric_prefix(self):
        for sql, expected in [('LIMIT 3', 3), ('limit\n  3', 3),
                              ('LIMIT 30', 30), ('LIMIT 31', 31), ('LIMIT 300', 300)]:
            token = re.search(r'\bLIMIT\s+(\d+)\b', sql, re.IGNORECASE)
            self.assertEqual(int(token.group(1)), expected)
            if expected != 3:
                self.assertNotEqual(int(token.group(1)), 3)

    def test_lookahead_corruption_waits_until_requested(self):
        rows = [self.add().operation.pk for _ in range(3)]
        Extraction.objects.filter(pk=rows[2]).update(payload_digest='0' * 64)
        first = self.read()
        self.assertEqual([o.extraction_id for o in first.operations], rows[:2])
        self.error('posting_extraction_evidence_invalid', cursor=first.next_cursor)

    def test_corrupt_later_operation_fails_entire_page(self):
        self.add()
        bad = self.add()
        changes = [({'snapshot_version': 2}, None), ({'extractor_version': '2'}, None),
                   ({'payload_digest': '0' * 64}, None),
                   ({'extracted_at': '2026-09-28T12:00:00Z'}, None),
                   ({'input_spec': {**spec(), 'version': 2}}, None),
                   ({}, {'fields': fields('changed')}), ({}, {'position': 9}),
                   ({}, {'portable_id': uuid.uuid1()})]
        original_row = Extraction.objects.filter(pk=bad.operation.pk).values().get()
        original_output = Output.objects.filter(pk=bad.outputs[0].pk).values().get()
        for row_changes, output_changes in changes:
            with self.subTest(row=row_changes, output=output_changes):
                Extraction.objects.filter(pk=bad.operation.pk).update(**row_changes)
                if output_changes:
                    Output.objects.filter(pk=bad.outputs[0].pk).update(**output_changes)
                self.error('posting_extraction_evidence_invalid')
                Extraction.objects.filter(pk=bad.operation.pk).update(**{k: v for k, v in original_row.items() if k != 'id'})
                Output.objects.filter(pk=bad.outputs[0].pk).update(**{k: v for k, v in original_output.items() if k != 'id'})

    def test_recording_timestamp_conversion_failure(self):
        self.add()
        real = authority.validate_extraction_batch
        def invalid(*args, **kwargs):
            row, outputs, envelope = real(*args, **kwargs)
            row.recorded_at = None
            return row, outputs, envelope
        with patch.object(authority, 'validate_extraction_batch', side_effect=invalid):
            self.error('posting_extraction_evidence_invalid')

    def test_frozen_detached_private_and_zero_lazy_queries(self):
        self.add(outputs=[fields(), fields()])
        page = self.read()
        def check(value):
            self.assertNotIsInstance(value, (dict, list, models.Model, models.QuerySet))
            if is_dataclass(value):
                self.assertFalse(hasattr(value, '__dict__'))
                for field in dto_fields(value):
                    check(getattr(value, field.name))
            elif isinstance(value, tuple):
                for child in value:
                    check(child)
        with self.assertNumQueries(0):
            check(page)
            repr(page)
            self.assertEqual(page, page)
            for operation in page.operations:
                json.loads(operation.input_spec_json)
                for output in operation.outputs:
                    self.assertEqual(output.company, 'Acme')
        for value in (page, page.source, page.operations[0], page.operations[0].outputs[0]):
            with self.assertRaises(FrozenInstanceError):
                setattr(value, dto_fields(value)[0].name, None)
        self.assertEqual(set(f.name for f in dto_fields(page.source)),
                         {'workspace_id', 'retained_message_id', 'retained_message_portable_id', 'representation_version', 'source_eligible'})
        self.assertEqual(set(f.name for f in dto_fields(page.operations[0])),
                         {'extraction_id', 'operation_id', 'extractor_method', 'extractor_version', 'snapshot_version',
                          'input_spec_json', 'extracted_at', 'recorded_at', 'output_count', 'outputs'})
        self.assertEqual(set(f.name for f in dto_fields(page.operations[0].outputs[0])),
                         {'output_id', 'portable_id', 'position', 'source', 'title', 'company', 'location', 'salary', 'employment_type'})
        for address in self.message.content['addresses']['from']:
            self.assertNotIn(address['address'], page.operations[0].input_spec_json)
        self.assertNotIn(self.message.content['subject'], page.operations[0].input_spec_json)
        Output.objects.all().update(fields=fields('mutated'))
        self.assertEqual(page.operations[0].outputs[0].title, 'Engineer')

    def test_sql_read_only_and_query_growth(self):
        def count():
            with CaptureQueriesContext(connection) as queries:
                self.read(limit=5)
            for query in queries:
                self.assertTrue(query['sql'].lstrip().upper().startswith('SELECT'), query['sql'])
                self.assertNotIn('FOR UPDATE', query['sql'].upper())
            return len(queries)
        self.assertEqual(count(), 3)
        self.add(outputs=[fields() for _ in range(20)])
        self.assertEqual(count(), 5)
        for _ in range(4):
            self.add()
        self.assertEqual(count(), 13)

    def test_all_tables_unchanged(self):
        self.add()
        def snapshot():
            with connection.cursor() as cursor:
                result = {}
                for table in connection.introspection.table_names(cursor):
                    cursor.execute('SELECT * FROM ' + connection.ops.quote_name(table))
                    result[table] = sorted(cursor.fetchall(), key=repr)
                return result
        before = snapshot()
        self.read()
        self.assertEqual(before, snapshot())

    def test_forbidden_authorities(self):
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
            self.read()
            for call in calls:
                call.assert_not_called()

    def test_database_failure_propagates(self):
        with patch.object(authority, 'validate_extraction_batch', side_effect=OperationalError('isolated failure')):
            self.add()
            with self.assertRaises(OperationalError):
                self.read()

    def test_cursor_is_frozen_and_has_exact_fields(self):
        for _ in range(3):
            self.add()
        cursor = self.read().next_cursor
        self.assertFalse(hasattr(cursor, '__dict__'))
        self.assertEqual([f.name for f in dto_fields(cursor)],
                         ['version', 'workspace_id', 'retained_message_id', 'last_extraction_id'])
        with self.assertRaises(FrozenInstanceError):
            cursor.version = 2
