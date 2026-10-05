"""Read-only evidence, examined-row navigation and unchanged mutation authorities."""
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, fields as dataclass_fields, replace
from unittest.mock import patch
import uuid

from django.db import connection
from django.db.models.functions import Collate
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from email_sync.models import AccountMailboxBinding, EmailAccount, RetainedMessage
from postings import retained_posting_candidates as discovery
from postings import retained_interpretations as interpretation
from postings import posting_sources, posting_source_corrections, job_posting_allocations
from postings import job_posting_interpretations, job_posting_projections
from postings.models import JobPosting, PostingApplicationConversion
from postings.tests.test_retained_interpretations import Fixtures
from postings.tests.test_retained_extractions import fields, spec
from postings.retained_extractions import record_posting_extraction


class CandidateTests(Fixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.select()

    def posting(self, **changes):
        return super().posting(**({"title": "A"} | changes))

    def discover(self, **changes):
        return discovery.discover_retained_posting_candidates(**dict(
            actor=self.user, workspace=self.ws, item_id=self.a.pk) | changes)

    def ids(self, result):
        return tuple(c.posting_id for c in result.candidates)

    def new_evidence(self, **changes):
        output = record_posting_extraction(**dict(self.kw, operation_id=uuid.uuid4(),
            outputs=[fields("A") | changes], input_spec=spec())).outputs[0]
        item = self.decide(output).item
        interpretation.decide_posting_interpretation(actor=self.user, workspace=self.ws,
            item_id=item.pk, operation_id=uuid.uuid4(), expected_revision=0, mode='select',
            output_id=output.pk, expected_membership_revision=0)
        return item

    def test_multiple_neutral_order_and_no_winner(self):
        result = self.discover()
        self.assertEqual(self.ids(result), (self.p.pk, self.q.pk))
        self.assertTrue(result.exhausted)
        self.assertEqual(result.outcome, 'evaluated')
        self.assertEqual(result.consistency, 'advisory')
        self.assertEqual(result.candidates[0].reasons, ('company_exact_equal', 'title_exact_equal'))
        forbidden = {'score', 'confidence', 'recommended', 'selected', 'can_attach', 'posting_url'}
        self.assertFalse(forbidden & {f.name for f in dataclass_fields(result.candidates[0])})

    def test_zero_and_one(self):
        JobPosting.objects.filter(pk=self.q.pk).update(company='Different')
        self.assertEqual(self.ids(self.discover()), (self.p.pk,))
        JobPosting.objects.filter(pk=self.p.pk).update(title='Different')
        result = self.discover()
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.outcome, 'evaluated')
        self.assertTrue(result.exhausted)

    def test_exact_only(self):
        for company, title in [('acme', 'A'), (' Acme', 'A'),
                ('Acme ', 'A'), ('Acme.', 'A'), ('Acme', 'a'),
                ('Acme', 'A '), ('Acme', 'A!'), ('Acme', 'Enginéer')]:
            self.posting(company=company, title=title)
        self.assertEqual(self.ids(self.discover()), (self.p.pk, self.q.pk))

    def test_unicode_not_normalized(self):
        item = self.new_evidence(company='Café', title='Rôle')
        exact = self.posting(company='Café', title='Rôle')
        self.posting(company='Cafe\u0301', title='Rôle')
        self.posting(company='Café', title='Ro\u0302le')
        self.assertEqual(self.ids(self.discover(item_id=item.pk)), (exact.pk,))

    def test_unusable_fields_skip_canonical_query(self):
        for name in ('company', 'title'):
            for value in (None, '', ' \t\n'):
                item = self.new_evidence(**{name: value})
                with patch.object(discovery, '_canonical_rows', side_effect=AssertionError('query')):
                    result = self.discover(item_id=item.pk)
                self.assertEqual(result.outcome, 'no_applicable_evidence')
                self.assertEqual(result.candidates, ())

    def test_interpretation_states_no_fallback(self):
        for action in (lambda: None, self.move, self.withdraw):
            action()
            item_id = self.b.pk if action.__name__ == '<lambda>' else self.a.pk
            with patch.object(discovery, '_canonical_rows', side_effect=AssertionError('query')):
                result = self.discover(item_id=item_id)
            self.assertEqual(result.outcome, 'no_applicable_evidence')
            self.assertEqual(result.candidates, ())

    def test_location_factual_only(self):
        for value in ('Remote', '', ' ', None):
            item = self.new_evidence(location=value)
            result = self.discover(item_id=item.pk)
            self.assertEqual(self.ids(result), (self.p.pk, self.q.pk))
            self.assertEqual(len(result.candidates[0].reasons), 3 if value == 'Remote' else 2)
        item = self.new_evidence(location='remote')
        self.assertEqual(len(self.discover(item_id=item.pk).candidates[0].reasons), 2)

    def test_workspace_and_account_scope(self):
        account = EmailAccount.objects.create(workspace=self.ws2, email='foreign@test.invalid')
        self.posting(workspace=self.ws2, account=account)
        self.posting(account=account)
        self.assertEqual(self.ids(self.discover()), (self.p.pk, self.q.pk))
        self.error('not_found', lambda: self.discover(workspace=self.ws2), 404)
        self.error('not_found', lambda: self.discover(actor=self.other), 404)

    def test_lifecycle_and_mapping_do_not_exclude(self):
        JobPosting.objects.filter(pk=self.p.pk).update(status='dismissed', saved=True)
        self.attach()
        posting_source_corrections.correct_posting_source(actor=self.user, workspace=self.ws,
            item_id=self.a.pk, operation_id=uuid.uuid4(), expected_revision=0,
            mode='associate', target_posting_id=self.q.pk)
        PostingApplicationConversion.objects.create(workspace=self.ws, posting=self.p,
                                                     application_portable_id=uuid.uuid4())
        self.assertEqual(self.ids(self.discover()), (self.p.pk, self.q.pk))
        self.assertEqual(self.discover().candidates[0].status, 'dismissed')

    def test_allocated_posting_eligible(self):
        self.account.provider = self.message.provider
        self.account.save()
        AccountMailboxBinding.objects.create(account=self.account, mailbox=self.message.mailbox)
        item = self.new_evidence()
        allocated = job_posting_allocations.allocate_job_posting(actor=self.user, workspace=self.ws,
            item_id=item.pk, operation_id=uuid.uuid4(), expected_interpretation_revision=1)
        selected = job_posting_interpretations.decide_job_posting_interpretation(
            actor=self.user, workspace=self.ws, posting_id=allocated.allocation.posting_id,
            operation_id=uuid.uuid4(), expected_revision=0, mode='select', item_id=item.pk,
            expected_interpretation_revision=1, expected_mapping_revision=0)
        job_posting_projections.project_job_posting_descriptors(actor=self.user, workspace=self.ws,
            posting_id=allocated.allocation.posting_id, operation_id=uuid.uuid4(), expected_projection_revision=0,
            expected_arbitration_revision=selected.decision.revision,
            expected_descriptor_digest=job_posting_projections.descriptor_digest(
                job_posting_projections.descriptor_snapshot(
                    JobPosting.objects.get(pk=allocated.allocation.posting_id))))
        self.assertIn(allocated.allocation.posting_id, self.ids(self.discover()))

    def test_same_postings_for_multiple_items(self):
        item = self.new_evidence()
        self.assertEqual(self.ids(self.discover()), self.ids(self.discover(item_id=item.pk)))

    def test_keyset_lookahead_and_no_omissions(self):
        expected = [self.p.pk, self.q.pk] + [self.posting().pk for _ in range(5)]
        cursor, found = None, []
        while True:
            result = self.discover(limit=2, cursor=cursor)
            found.extend(self.ids(result))
            if result.exhausted: break
            self.assertEqual(result.next_cursor.last_examined_pk, result.candidates[-1].posting_id)
            cursor = result.next_cursor
        self.assertEqual(found, expected)
        self.assertEqual(len(found), len(set(found)))

    def test_anchor_need_not_survive(self):
        first = self.discover(limit=1)
        self.p.delete()
        self.assertEqual(self.ids(self.discover(limit=1, cursor=first.next_cursor)), (self.q.pk,))

    def test_cursor_context_and_navigation_validation(self):
        cursor = self.discover(limit=1).next_cursor
        for name in ('rule_version', 'workspace_id', 'item_id', 'interpretation_revision',
                     'applicable_output_id', 'membership_revision'):
            self.error('invalid_posting_candidate_navigation', lambda: self.discover(
                cursor=replace(cursor, **{name: getattr(cursor, name) + 1})), 400)
        for limit in (True, 0, 201, '1', None):
            self.error('invalid_posting_candidate_navigation', lambda: self.discover(limit=limit), 400)
        for value in ((), 'bad', replace(cursor, last_examined_pk=True),
                      replace(cursor, membership_revision=-1)):
            self.error('invalid_posting_candidate_navigation', lambda: self.discover(cursor=value), 400)
        self.withdraw()
        self.error('invalid_posting_candidate_navigation', lambda: self.discover(cursor=cursor), 400)

    def test_coarse_false_positives_empty_page_and_lookahead(self):
        rows = list(JobPosting.objects.order_by('pk').values('id', 'portable_id', 'company',
                      'title', 'location', 'status', 'saved'))
        rows[0]['company'] = 'acme'
        def coarse(workspace_id, company, title, last, limit):
            return tuple(row for row in rows if row['id'] > last)[:limit + 1]
        with patch.object(discovery, '_canonical_rows', coarse):
            first = self.discover(limit=1)
            self.assertEqual(first.candidates, ())
            self.assertFalse(first.exhausted)
            self.assertEqual(first.next_cursor.last_examined_pk, self.p.pk)
            second = self.discover(limit=1, cursor=first.next_cursor)
            self.assertEqual(self.ids(second), (self.q.pk,))
            self.assertTrue(second.exhausted)

    def test_real_sqlite_collation_false_positive(self):
        if connection.vendor != 'sqlite': self.skipTest('SQLite NOCASE demonstration')
        false = self.posting(company='acme')
        def coarse(workspace_id, company, title, last, limit):
            return tuple(JobPosting.objects.filter(workspace_id=workspace_id,
                account__workspace_id=workspace_id, title=title, pk__gt=last)
                .alias(coarse_company=Collate('company', 'nocase')).filter(coarse_company=company)
                .order_by('pk').values('id', 'portable_id', 'company', 'title', 'location',
                                      'status', 'saved')[:limit + 1])
        self.assertIn(false.pk, [r['id'] for r in coarse(self.ws.pk, 'Acme', 'A', 0, 100)])
        with patch.object(discovery, '_canonical_rows', coarse):
            self.assertEqual(self.ids(self.discover()), (self.p.pk, self.q.pk))

    def test_sql_reads_only_query_count_and_detachment(self):
        with CaptureQueriesContext(connection) as small:
            first = self.discover()
        for _ in range(10): self.posting()
        with CaptureQueriesContext(connection) as large:
            second = self.discover()
            repeated = self.discover()
        self.assertEqual(len(large), 2 * len(small))
        self.assertTrue(all(q['sql'].lstrip().upper().startswith('SELECT') for q in large))
        canonical = [q for q in small if 'FROM "postings_jobposting"' in q['sql']]
        self.assertEqual(len(canonical), 1)
        self.assertIn('LIMIT 101', canonical[0]['sql'])
        with self.assertNumQueries(0):
            self.assertEqual(second, repeated)
            repr(first); tuple(second.candidates)
            self.assertEqual(second.interpretation.evidence.company, 'Acme')
        with self.assertRaises(FrozenInstanceError): second.outcome = 'bad'
        with self.assertRaises(FrozenInstanceError): second.candidates[0].company = 'bad'

    def test_forbidden_commands_and_domain_state_unchanged(self):
        from applications import creation, retained_reviews
        from django.apps import apps
        targets = [(posting_sources, 'attach_posting_source'),
                   (posting_source_corrections, 'correct_posting_source'),
                   (job_posting_allocations, 'allocate_job_posting'),
                   (interpretation, 'decide_posting_interpretation'),
                   (job_posting_interpretations, 'decide_job_posting_interpretation'),
                   (job_posting_projections, 'project_job_posting_descriptors'),
                   (creation, 'create_attempt'), (retained_reviews, 'set_review_dismissal')]
        def domain_snapshot():
            return tuple((model._meta.label, list(model.objects.order_by('pk').values()))
                for model in apps.get_models() if model._meta.app_label in
                {'postings', 'applications', 'documents', 'email_sync'})
        before = domain_snapshot()
        with ExitStack() as stack:
            for module, name in targets:
                stack.enter_context(patch.object(module, name, side_effect=AssertionError(name)))
            self.discover(); self.discover()
        self.assertEqual(before, domain_snapshot())

    def test_conflict_observed_without_hiding_candidates(self):
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        result = self.discover()
        self.assertFalse(result.interpretation.source_eligible)
        self.assertEqual(self.ids(result), (self.p.pk, self.q.pk))

    def test_stale_presentation_attach_uses_own_rules(self):
        self.assertIn(self.p.pk, self.ids(self.discover()))
        JobPosting.objects.filter(pk=self.p.pk).update(company='Changed')
        self.assertNotIn(self.p.pk, self.ids(self.discover()))
        attached = self.attach()
        self.assertEqual(attached.posting.pk, self.p.pk)
        self.error('posting_source_conflict', lambda: self.attach(posting_id=self.q.pk), 409)

    def test_stale_presentation_source_conflict_blocks_actual_attach(self):
        self.discover()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        self.error('retained_source_ineligible', self.attach, 409)


    def test_corruption_propagates_not_zero_results(self):
        RetainedMessage.objects.filter(pk=self.message.pk).update(content_digest='0' * 64)
        self.error('retained_source_invalid', self.discover, 409)

    def test_maximum_examined_page(self):
        with patch.object(discovery, '_canonical_rows', wraps=discovery._canonical_rows) as query:
            self.discover(limit=200)
            self.assertEqual(query.call_args.args[-1], 200)

    def test_cursor_frozen_and_evidence_changes_reject(self):
        cursor = self.discover(limit=1).next_cursor
        with self.assertRaises(FrozenInstanceError): cursor.last_examined_pk = 99
        self.select(operation_id=uuid.uuid4(), expected_revision=1, output_id=self.outputs[2].pk)
        self.error('invalid_posting_candidate_navigation', lambda: self.discover(cursor=cursor), 400)

    def test_stale_presentation_deleted_posting_rejected(self):
        posting_id = self.p.pk
        self.discover()
        self.p.delete()
        self.error('not_found', lambda: self.attach(posting_id=posting_id), 404)


    def test_whitespace_is_not_trimmed_for_equality(self):
        item = self.new_evidence(company=' Acme ', title=' A ')
        exact = self.posting(company=' Acme ', title=' A ')
        self.assertEqual(self.ids(self.discover(item_id=item.pk)), (exact.pk,))
