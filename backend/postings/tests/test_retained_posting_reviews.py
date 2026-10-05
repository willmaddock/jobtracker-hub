"""Real phase commits, detached receipts and advisory reads; no outer test atomic."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from threading import Barrier
from unittest.mock import patch
import uuid

from django.apps import apps
from django.db import connection, transaction, close_old_connections, OperationalError, IntegrityError
from django.test import TransactionTestCase, TestCase, SimpleTestCase
from rest_framework.exceptions import APIException

from accounts.models import Workspace
from email_sync.models import RetainedMessage
from postings import retained_posting_reviews as review
from postings import job_posting_interpretations as arbitration, job_posting_projections as projection
from postings import posting_source_corrections as mappings
from postings.models import (JobPosting, PostingSource, JobPostingAllocation,
    JobPostingInterpretationDecision, JobPostingDescriptorProjection, DESCRIPTOR_FIELDS)
from postings.tests.test_job_posting_allocations import Fixtures
from postings.tests.test_retained_extractions import fields


def raw_command(action='allocate_new', phases=3, target=1, digest=None):
    result = {'mapping': ({'action': action, 'operation_id': str(uuid.uuid4()),
        'expected_interpretation_revision': 1} if action == 'allocate_new' else
        {'action': action, 'target_posting_id': target})}
    if phases >= 2:
        result['selection'] = {'operation_id': str(uuid.uuid4()), 'expected_arbitration_revision': 0,
            'expected_interpretation_revision': 1, 'expected_mapping_revision': 0}
    if phases >= 3:
        result['projection'] = {'operation_id': str(uuid.uuid4()), 'expected_projection_revision': 0,
            'expected_descriptor_digest': digest or projection.descriptor_digest(dict.fromkeys(DESCRIPTOR_FIELDS))}
    return result


class ShapeTests(SimpleTestCase):
    def invalid(self, data):
        with self.assertRaises(review.InvalidRetainedPostingReview) as caught:
            review.parse_review_command(data)
        self.assertEqual(caught.exception.get_codes(), 'invalid_retained_posting_review')

    def test_normalized_frozen_dtos(self):
        command = review.parse_review_command(raw_command())
        self.assertIsInstance(command.mapping.operation_id, uuid.UUID)
        self.assertEqual(command.mapping.action, review.MappingAction.ALLOCATE_NEW)
        with self.assertRaises(FrozenInstanceError):
            command.selection = None
        self.assertFalse(hasattr(command, '__dict__'))

    def test_unknown_keys_every_level(self):
        for part in (None, 'mapping', 'selection', 'projection'):
            data = raw_command()
            (data if part is None else data[part])['extra'] = 1
            self.invalid(data)

    def test_missing_fields(self):
        for part in ('mapping', 'selection', 'projection'):
            for key in raw_command()[part]:
                data = raw_command(); del data[part][key]
                self.invalid(data)
        self.invalid({})
        self.invalid({'mapping': {'action': 'attach_existing'}})

    def test_unused_fields_and_phase_combinations(self):
        bad = []
        data = raw_command('attach_existing'); data['mapping']['operation_id'] = str(uuid.uuid4()); bad.append(data)
        data = raw_command('attach_existing'); data['mapping']['expected_interpretation_revision'] = 1; bad.append(data)
        data = raw_command(); data['mapping']['target_posting_id'] = 1; bad.append(data)
        data = raw_command(); del data['selection']; bad.append(data)
        data = raw_command(); data['selection'] = None; bad.append(data)
        for data in bad: self.invalid(data)

    def test_actions_types_and_integer_bounds(self):
        for action in ('remap', '', None, True, 1):
            data = raw_command(); data['mapping']['action'] = action; self.invalid(data)
        for part, key, minimum in (('mapping', 'expected_interpretation_revision', 1),
                ('selection', 'expected_arbitration_revision', 0),
                ('selection', 'expected_interpretation_revision', 1),
                ('selection', 'expected_mapping_revision', 0),
                ('projection', 'expected_projection_revision', 0)):
            for value in (True, False, -1, review.MAX + 1, '1', 1.0, None, minimum - 1):
                data = raw_command(); data[part][key] = value; self.invalid(data)
        for value in (True, 0, -1, review.MAX + 1, '1', None):
            self.invalid(raw_command('attach_existing', target=value))

    def test_uuid_and_digest_validation(self):
        for part in ('mapping', 'selection', 'projection'):
            for value in (None, True, '', 'bad', str(uuid.uuid1()), str(uuid.uuid4()).upper()):
                data = raw_command(); data[part]['operation_id'] = value; self.invalid(data)
        for value in (None, True, 'A' * 64, 'a' * 63, 'g' * 64, 'a' * 64 + '\n'):
            data = raw_command(); data['projection']['expected_descriptor_digest'] = value; self.invalid(data)

    def test_duplicate_normalized_uuids(self):
        for first, second in (('mapping', 'selection'), ('mapping', 'projection'), ('selection', 'projection')):
            data = raw_command(); data[second]['operation_id'] = uuid.UUID(data[first]['operation_id'])
            self.invalid(data)

    def test_interpretation_mismatch(self):
        data = raw_command(); data['selection']['expected_interpretation_revision'] = 2
        self.invalid(data)

    def test_arbitrary_objects_and_mappings_rejected_as_dtos(self):
        for value in (object(), raw_command(), None):
            with self.assertRaises(review.InvalidRetainedPostingReview): review._validated(value)
        with self.assertRaises(review.InvalidRetainedPostingReview):
            review._validated(review.RetainedPostingReviewCommand(object()))


class ReviewTests(Fixtures, TransactionTestCase):
    def command(self, action='allocate_new', phases=3, **changes):
        digest = projection.descriptor_digest(projection.descriptor_snapshot(self.p)) if action == 'attach_existing' else None
        data = raw_command(action, phases, self.p.pk, digest)
        data.update(changes)
        return review.parse_review_command(data)

    def run_review(self, command=None, **changes):
        return review.review_retained_posting(**dict(actor=self.user, workspace=self.ws,
            item_id=self.a.pk, command=command or self.command()) | changes)

    def state(self, **changes):
        return review.read_retained_posting_review_state(**dict(actor=self.user, workspace=self.ws,
                                                               item_id=self.a.pk) | changes)

    def failure(self, command, phase, code, **changes):
        with self.assertRaises(review.RetainedPostingReviewPhaseError) as caught:
            self.run_review(command, **changes)
        error = caught.exception
        self.assertEqual(error.context.failed_phase, phase)
        self.assertEqual(error.context.domain_error.codes, code)
        self.assertEqual(error.context.domain_error.status_code, error.__cause__.status_code)
        self.assertEqual(error.context.domain_error.detail, review._freeze(error.__cause__.detail))
        self.assertFalse(error.context.outcome_may_be_unknown)
        return error

    def counts(self):
        return tuple(model.objects.count() for model in (JobPosting, PostingSource,
            JobPostingAllocation, JobPostingInterpretationDecision, JobPostingDescriptorProjection))

    def test_allocate_only(self):
        before = self.counts()
        result = self.run_review(self.command(phases=1))
        self.assertEqual(self.counts(), tuple(a + b for a, b in zip(before, (1, 1, 1, 0, 0))))
        row = JobPosting.objects.get(pk=result.posting_id)
        self.assertEqual([getattr(row, f) for f in DESCRIPTOR_FIELDS], [None] * 6)
        self.assertEqual([p.status for p in result.phases], ['completed', 'unrequested', 'unrequested'])

    def test_allocate_select_without_projection(self):
        result = self.run_review(self.command(phases=2))
        row = JobPosting.objects.get(pk=result.posting_id)
        self.assertEqual([getattr(row, f) for f in DESCRIPTOR_FIELDS], [None] * 6)
        self.assertEqual(JobPostingInterpretationDecision.objects.count(), 1)
        self.assertEqual(JobPostingDescriptorProjection.objects.count(), 0)

    def test_allocate_full_and_exact_replay(self):
        command = self.command()
        first = self.run_review(command); before = self.counts()
        again = self.run_review(command)
        self.assertEqual(self.counts(), before)
        self.assertEqual(first.posting_id, again.posting_id)
        self.assertEqual([p.status for p in again.phases], ['replayed'] * 3)
        self.assertEqual(again.phases[2].receipt.arbitration_revision, first.phases[1].receipt.revision)
        self.assertEqual(JobPosting.objects.get(pk=first.posting_id).title, self.outputs[0].fields['title'])

    def test_attach_only(self):
        before = self.counts()
        command = self.command('attach_existing', 1)
        self.run_review(command); replay = self.run_review(command)
        self.assertEqual(self.counts(), tuple(a + b for a, b in zip(before, (0, 1, 0, 0, 0))))
        self.assertEqual(replay.phases[0].status, 'replayed')

    def test_attach_select_without_projection(self):
        before = projection.descriptor_snapshot(self.p)
        self.run_review(self.command('attach_existing', 2))
        self.p.refresh_from_db()
        self.assertEqual(projection.descriptor_snapshot(self.p), before)
        self.assertFalse(JobPostingDescriptorProjection.objects.exists())

    def test_attach_full_and_replay(self):
        command = self.command('attach_existing')
        result = self.run_review(command); before = self.counts()
        self.assertEqual(result.posting_id, self.p.pk)
        self.assertEqual([p.status for p in self.run_review(command).phases], ['replayed'] * 3)
        self.assertEqual(before, self.counts())

    def test_attach_conflict_and_effective_target_not_initial(self):
        self.attach()
        command = replace(self.command('attach_existing', 1), mapping=review.MappingRequest('attach_existing', self.q.pk))
        self.failure(command, 'mapping', 'posting_source_conflict')
        self.remap()
        self.failure(command, 'mapping', 'posting_source_conflict')

    def test_withdrawn_mapping_is_not_restored(self):
        command = self.command('attach_existing', 1)
        self.run_review(command)
        self.remap(mode='withdraw', target_posting_id=None)
        self.assertEqual(self.run_review(command).phases[0].status, 'replayed')
        self.assertIsNone(self.state().mapping.effective_posting_id)

    def test_allocate_rejects_prior_mapping(self):
        self.attach()
        self.failure(self.command(phases=1), 'mapping', 'retained_item_initial_mapping_exists')

    def test_another_item_attaches_to_allocated_posting(self):
        result = self.run_review(self.command(phases=1))
        self.select(item_id=self.b.pk, output_id=self.outputs[1].pk, operation_id=uuid.uuid4())
        command = review.parse_review_command(raw_command('attach_existing', 2, result.posting_id))
        self.run_review(command, item_id=self.b.pk)
        self.assertEqual(PostingSource.objects.filter(posting_id=result.posting_id).count(), 2)
        self.assertEqual(JobPostingInterpretationDecision.objects.get().selected_interpretation.item_id, self.b.pk)

    def test_no_application_or_disposition_side_effects(self):
        models = [m for m in apps.get_models() if m._meta.app_label == 'applications']
        before = {m: list(m.objects.order_by('pk').values()) for m in models}
        self.run_review()
        self.assertEqual(before, {m: list(m.objects.order_by('pk').values()) for m in models})

    def test_selection_failure_after_attach_and_retry(self):
        command = self.command('attach_existing', 2)
        bad = replace(command, selection=replace(command.selection, expected_arbitration_revision=1))
        error = self.failure(bad, 'selection', 'stale_revision')
        self.assertEqual(error.context.phase_progress[0].status, 'completed')
        self.assertEqual(PostingSource.objects.count(), 1)
        self.assertFalse(JobPostingInterpretationDecision.objects.exists())
        self.assertEqual(self.run_review(command).phases[0].status, 'replayed')

    def test_selection_failure_after_allocation_and_retry(self):
        command = self.command(phases=2)
        bad = replace(command, selection=replace(command.selection, expected_mapping_revision=1))
        self.failure(bad, 'selection', 'stale_mapping_revision')
        posting_id = JobPostingAllocation.objects.get().posting_id
        self.assertEqual(self.run_review(command).posting_id, posting_id)
        self.assertEqual(JobPostingAllocation.objects.count(), 1)

    def test_projection_digest_failure_and_retry(self):
        command = self.command()
        bad = replace(command, projection=replace(command.projection, expected_descriptor_digest='0' * 64))
        error = self.failure(bad, 'projection', 'stale_descriptor_digest')
        self.assertEqual([p.status for p in error.context.phase_progress], ['completed', 'completed', 'failed_known'])
        self.assertEqual(JobPostingInterpretationDecision.objects.count(), 1)
        self.assertFalse(JobPostingDescriptorProjection.objects.exists())
        result = self.run_review(command)
        self.assertEqual([p.status for p in result.phases], ['replayed', 'replayed', 'completed'])

    def test_projection_revision_failure_and_retry(self):
        command = self.command()
        bad = replace(command, projection=replace(command.projection, expected_projection_revision=1))
        self.failure(bad, 'projection', 'stale_projection_revision')
        self.assertEqual(self.run_review(command).phases[2].status, 'completed')

    def test_capacity_failure_preserves_structured_error_and_prior_phases(self):
        output = self.record(operation_id=uuid.uuid4(), outputs=[fields('x' * 256)]).outputs[0]
        item = self.decide(output).item
        self.select(item_id=item.pk, output_id=output.pk, operation_id=uuid.uuid4())
        command = self.command()
        error = self.failure(command, 'projection', {'fields': ({'field': 'projection_capacity_exceeded',
            'limit': 'projection_capacity_exceeded'},)}, item_id=item.pk)
        self.assertEqual(error.context.domain_error.detail['fields'][0]['field'], 'title')
        with self.assertRaises(TypeError): error.context.domain_error.detail['fields'][0]['field'] = 'other'
        self.assertTrue(JobPostingAllocation.objects.filter(item=item).exists())
        self.assertFalse(JobPostingDescriptorProjection.objects.exists())
        repeated = self.failure(command, 'projection', error.context.domain_error.codes, item_id=item.pk)
        self.assertEqual([p.status for p in repeated.context.phase_progress][:2], ['replayed', 'replayed'])

    def test_changed_completed_operation_payload_propagates(self):
        command = self.command()
        self.run_review(command)
        bad = replace(command, projection=replace(command.projection, expected_projection_revision=1))
        self.failure(bad, 'projection', 'idempotency_key_reused')

    def test_selection_unchanged_is_not_replay(self):
        command = self.command(phases=2); self.run_review(command)
        changed = replace(command, selection=replace(command.selection, operation_id=uuid.uuid4(),
                                                      expected_arbitration_revision=1))
        self.failure(changed, 'selection', 'job_posting_interpretation_unchanged')

    def test_projection_unchanged_is_not_replay(self):
        command = self.command(); self.run_review(command)
        changed = replace(command, projection=replace(command.projection, operation_id=uuid.uuid4(),
            expected_projection_revision=1, expected_descriptor_digest=projection.descriptor_digest(self.outputs[0].fields)))
        self.failure(changed, 'projection', 'job_posting_projection_unchanged')

    def test_unexpected_failure_after_actual_commit_and_replay(self):
        command = self.command()
        original = review.allocation.allocate_job_posting
        def lost(**kwargs):
            original(**kwargs)
            raise OperationalError('simulated lost response')
        with patch.object(review.allocation, 'allocate_job_posting', lost), self.assertRaises(review.RetainedPostingReviewPhaseError) as caught:
            self.run_review(command)
        error = caught.exception
        self.assertTrue(error.context.outcome_may_be_unknown)
        self.assertIsInstance(error.__cause__, OperationalError)
        self.assertEqual([p.status for p in error.context.phase_progress], ['failed_outcome_unknown', 'unattempted', 'unattempted'])
        self.assertEqual(JobPostingAllocation.objects.count(), 1)
        self.assertEqual(self.run_review(command).phases[0].status, 'replayed')

    def test_integrity_error_is_conservatively_unknown(self):
        with patch.object(review.allocation, 'allocate_job_posting', side_effect=IntegrityError('fixture')), self.assertRaises(review.RetainedPostingReviewPhaseError) as caught:
            self.run_review()
        self.assertTrue(caught.exception.context.outcome_may_be_unknown)
        self.assertIsNone(caught.exception.context.domain_error)

    def test_receipt_failure_preserves_completed_or_replayed_status(self):
        command = self.command()
        for status in ('completed', 'replayed'):
            with patch.object(review, '_mapping_receipt', side_effect=RuntimeError('detach')), self.assertRaises(review.RetainedPostingReviewPhaseError) as caught:
                self.run_review(command)
            error = caught.exception
            self.assertEqual(error.context.failure_stage, 'receipt')
            self.assertEqual(error.context.phase_progress[0].status, status)
            self.assertFalse(error.context.outcome_may_be_unknown)
            self.assertFalse(JobPostingInterpretationDecision.objects.exists())
        self.assertEqual(JobPostingAllocation.objects.count(), 1)

    def test_receipt_helpers_and_result_access_use_zero_queries(self):
        for action in ('attach_existing', 'allocate_new'):
            item = self.a if action == 'attach_existing' else self.b
            if item == self.b: self.select(item_id=item.pk, output_id=self.outputs[1].pk, operation_id=uuid.uuid4())
            command = self.command(action)
            originals = {name: getattr(review, name) for name in ('_mapping_receipt', '_selection_receipt', '_projection_receipt')}
            def wrapped(name):
                def call(*args):
                    with self.assertNumQueries(0): return originals[name](*args)
                return call
            with patch.object(review, '_mapping_receipt', wrapped('_mapping_receipt')), patch.object(review, '_selection_receipt', wrapped('_selection_receipt')), patch.object(review, '_projection_receipt', wrapped('_projection_receipt')):
                for repeat in range(2):
                    result = self.run_review(command, item_id=item.pk)
                    with self.assertNumQueries(0):
                        repr(result)
                        self.assertEqual(result.phases[2].receipt.arbitration_revision, result.phases[1].receipt.revision)

    def test_actual_commit_boundaries(self):
        original = review._mapping_receipt
        commits = []
        def detach(*args):
            self.assertFalse(connection.in_atomic_block)
            self.assertTrue(connection.get_autocommit())
            transaction.on_commit(lambda: commits.append('mapping'))
            self.assertEqual(commits, ['mapping'])
            return original(*args)
        with patch.object(review, '_mapping_receipt', detach): self.run_review()

    def test_context_guard_precedes_authorization_for_command_and_reader(self):
        for call in (self.run_review, self.state):
            with transaction.atomic(), patch.object(review, 'authorize_owner', side_effect=AssertionError('authorization queried')):
                with self.assertRaises(review.RetainedPostingReviewTransactionContextInvalid): call()
            connection.set_autocommit(False)
            try:
                with self.assertRaises(review.RetainedPostingReviewTransactionContextInvalid): call()
            finally:
                connection.rollback()
                connection.set_autocommit(True)

    def test_dto_revalidation_before_phase_execution(self):
        for command in (raw_command(), replace(self.command(), projection=review.ProjectionRequest(True, 0, 'a'*64))):
            before = self.counts()
            with self.assertRaises(review.InvalidRetainedPostingReview): self.run_review(command)
            self.assertEqual(before, self.counts())

    def test_ownership_transfer_between_phases(self):
        command = self.command()
        original = review._mapping_receipt
        def transfer(*args):
            receipt = original(*args)
            Workspace.objects.filter(pk=self.ws.pk).update(owner=self.other)
            return receipt
        with patch.object(review, '_mapping_receipt', transfer):
            self.failure(command, 'selection', 'not_found')
        result = self.run_review(command, actor=self.other)
        self.assertEqual(result.phases[0].receipt.actor_id, self.user.pk)
        self.assertEqual(result.phases[1].receipt.actor_id, self.other.pk)

    def test_source_conflict_between_phases(self):
        command = self.command()
        original = review._mapping_receipt
        def conflict(*args):
            receipt = original(*args)
            RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
            return receipt
        with patch.object(review, '_mapping_receipt', conflict):
            self.failure(command, 'selection', 'retained_source_ineligible')
        self.assertEqual(JobPostingAllocation.objects.count(), 1)
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=False)
        self.assertEqual(self.run_review(command).phases[0].status, 'replayed')

    def test_correction_between_phases_does_not_redirect(self):
        command = self.command()
        original = review._mapping_receipt
        def remap(*args):
            receipt = original(*args); self.remap(); return receipt
        with patch.object(review, '_mapping_receipt', remap):
            self.failure(command, 'selection', 'stale_mapping_revision')
        again = self.failure(command, 'selection', 'stale_mapping_revision')
        self.assertNotEqual(again.context.phase_progress[0].receipt.posting_id, self.q.pk)

    def test_competing_arbitration_between_phases(self):
        command = self.command()
        original = review._mapping_receipt
        def compete(*args):
            receipt = original(*args)
            arbitration.decide_job_posting_interpretation(actor=self.user, workspace=self.ws,
                posting_id=receipt.posting_id, operation_id=uuid.uuid4(), expected_revision=0,
                mode='select', item_id=self.a.pk, expected_interpretation_revision=1, expected_mapping_revision=0)
            return receipt
        with patch.object(review, '_mapping_receipt', compete):
            self.failure(command, 'selection', 'stale_revision')

    def test_competing_projection_between_phases(self):
        command = self.command()
        original = review._selection_receipt
        def compete(*args):
            receipt = original(*args)
            projection.project_job_posting_descriptors(actor=self.user, workspace=self.ws,
                posting_id=receipt.posting_id, operation_id=uuid.uuid4(), expected_projection_revision=0,
                expected_arbitration_revision=receipt.revision,
                expected_descriptor_digest=command.projection.expected_descriptor_digest)
            return receipt
        with patch.object(review, '_selection_receipt', compete):
            self.failure(command, 'projection', 'stale_projection_revision')
        self.assertEqual(JobPostingDescriptorProjection.objects.count(), 1)

    def test_projection_binds_replayed_decision_not_new_current_revision(self):
        command = self.command(phases=2)
        first = self.run_review(command)
        arbitration.decide_job_posting_interpretation(actor=self.user, workspace=self.ws,
            posting_id=first.posting_id, operation_id=uuid.uuid4(), expected_revision=1, mode='withdraw')
        command = replace(command, projection=review.ProjectionRequest(uuid.uuid4(), 0,
            projection.descriptor_digest(dict.fromkeys(DESCRIPTOR_FIELDS))))
        self.failure(command, 'projection', 'stale_arbitration_revision')

    def test_reader_unmapped_attached_allocated_and_remapped(self):
        state = self.state()
        self.assertIsNone(state.mapping.initial_source_id)
        self.assertIsNone(state.arbitration)
        self.attach(); state = self.state()
        self.assertIsNone(state.allocation)
        self.assertEqual(state.arbitration.state, 'unresolved')
        self.select(item_id=self.b.pk, output_id=self.outputs[1].pk, operation_id=uuid.uuid4())
        allocated = self.run_review(self.command(phases=1), item_id=self.b.pk)
        mappings.correct_posting_source(actor=self.user, workspace=self.ws, item_id=self.b.pk,
            operation_id=uuid.uuid4(), expected_revision=0, mode='associate', target_posting_id=self.q.pk)
        state = self.state(item_id=self.b.pk)
        self.assertEqual(state.allocation.posting_id, allocated.posting_id)
        self.assertEqual(state.mapping.initial_posting_id, allocated.posting_id)
        self.assertEqual(state.mapping.effective_posting_id, self.q.pk)
        self.assertEqual(state.projection.posting_id, self.q.pk)

    def test_reader_projection_drift_and_frozen_snapshot(self):
        result = self.run_review()
        state = self.state()
        self.assertEqual((state.arbitration.state, state.projection.state), ('selected', 'projected'))
        self.assertEqual(state.consistency, 'advisory')
        self.assertFalse(state.changes_detected)
        with self.assertNumQueries(0): repr(state)
        with self.assertRaises(FrozenInstanceError): state.item_id = 9
        with self.assertRaises(TypeError): state.projection.descriptor_snapshot['title'] = 'bad'
        JobPosting.objects.filter(pk=result.posting_id).update(title='drift')
        self.assertTrue(self.state().projection.drift)

    def test_reader_mapping_change_preserves_target_anchor(self):
        result = self.run_review()
        original = review.projection.read_job_posting_projection
        def change(**kwargs):
            value = original(**kwargs); self.remap(); return value
        with patch.object(review.projection, 'read_job_posting_projection', change): state = self.state()
        self.assertTrue(state.changes_detected)
        self.assertEqual(state.projection.posting_id, result.posting_id)
        self.assertEqual(state.final_mapping.effective_posting_id, self.q.pk)
        self.assertEqual(state.projection.observed_mapping_revision, 0)

    def test_reader_arbitration_projection_mismatch(self):
        result = self.run_review()
        original = review.arbitration.read_job_posting_interpretation
        def change(**kwargs):
            value = original(**kwargs)
            arbitration.decide_job_posting_interpretation(actor=self.user, workspace=self.ws,
                posting_id=result.posting_id, operation_id=uuid.uuid4(), expected_revision=1, mode='withdraw')
            return value
        with patch.object(review.arbitration, 'read_job_posting_interpretation', change): state = self.state()
        self.assertTrue(state.changes_detected)
        self.assertEqual(state.arbitration.revision, 1)
        self.assertEqual(state.projection.current_arbitration_revision, 2)

    def test_foreign_scope_command_and_reader(self):
        self.failure(self.command(), 'mapping', 'not_found', workspace=self.ws2)
        with self.assertRaises(APIException) as caught:
            self.state(workspace=self.ws2)
        self.assertEqual(caught.exception.status_code, 404)

    def test_stale_allocation_interpretation_remains_domain_failure(self):
        command = self.command(phases=1)
        command = replace(command, mapping=replace(command.mapping, expected_interpretation_revision=2))
        self.failure(command, 'mapping', 'stale_interpretation_revision')
        self.assertFalse(JobPostingAllocation.objects.exists())

    def test_attach_only_requires_no_selected_interpretation(self):
        self.withdraw()
        self.run_review(self.command('attach_existing', 1))
        self.assertFalse(JobPostingInterpretationDecision.objects.exists())

    def test_later_receipt_failure_preserves_commits_and_replay(self):
        command = self.command()
        for helper, phase, expected_counts in (
                ('_selection_receipt', 'selection', (1, 0)),
                ('_projection_receipt', 'projection', (1, 1))):
            with patch.object(review, helper, side_effect=RuntimeError('detach')), self.assertRaises(review.RetainedPostingReviewPhaseError) as caught:
                self.run_review(command)
            context = caught.exception.context
            self.assertEqual((context.failed_phase, context.failure_stage), (phase, 'receipt'))
            self.assertFalse(context.outcome_may_be_unknown)
            self.assertEqual((JobPostingInterpretationDecision.objects.count(),
                              JobPostingDescriptorProjection.objects.count()), expected_counts)
        self.assertEqual([p.status for p in self.run_review(command).phases], ['replayed'] * 3)

    def test_frozen_error_snapshot_does_not_share_mutable_error_detail(self):
        command = self.command(phases=2)
        bad = replace(command, selection=replace(command.selection, expected_arbitration_revision=1))
        error = self.failure(bad, 'selection', 'stale_revision')
        self.assertIs(type(error.context.domain_error.detail), str)
        error.__cause__.detail.code = 'changed'
        self.assertEqual(error.context.domain_error.codes, 'stale_revision')

    def race(self, calls):
        barrier = Barrier(len(calls))
        def run(call):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try: return call()
                except (review.RetainedPostingReviewPhaseError, OperationalError) as exc: return exc
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=len(calls)) as pool: results = list(pool.map(run, calls))
        for i, result in enumerate(results):
            if isinstance(result, OperationalError) or (isinstance(result, review.RetainedPostingReviewPhaseError)
                    and isinstance(result.__cause__, OperationalError)):
                try: results[i] = calls[i]()
                except review.RetainedPostingReviewPhaseError as exc: results[i] = exc
        return results

    def test_concurrent_duplicate_bundle(self):
        command = self.command()
        results = self.race([lambda: self.run_review(command)] * 2)
        self.assertTrue(all(isinstance(r, review.RetainedPostingReviewResult) for r in results))
        self.assertEqual(JobPostingAllocation.objects.count(), 1)
        self.assertEqual(JobPostingInterpretationDecision.objects.count(), 1)
        self.assertEqual(JobPostingDescriptorProjection.objects.count(), 1)

    def test_concurrent_attach_vs_allocate(self):
        attach, allocate = self.command('attach_existing', 1), self.command(phases=1)
        results = self.race([lambda: self.run_review(attach), lambda: self.run_review(allocate)])
        self.assertEqual(sum(isinstance(r, review.RetainedPostingReviewResult) for r in results), 1)
        self.assertEqual(PostingSource.objects.count(), 1)
        self.assertEqual(JobPosting.objects.count(), 2 + JobPostingAllocation.objects.count())


class WrappedTestCaseRejects(TestCase):
    def test_no_testcase_escape(self):
        with self.assertRaises(review.RetainedPostingReviewTransactionContextInvalid):
            review.review_retained_posting(actor=None, workspace=None, item_id=1, command=None)
