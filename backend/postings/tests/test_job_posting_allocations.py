"""One-shot creation, competing authorities, immutable witnesses and writer guards."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier
from unittest.mock import patch
import uuid
from django.apps import apps
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError, OperationalError, close_old_connections
from django.db.models.deletion import ProtectedError
from django.db.models.signals import post_save
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import APIException
from accounts.models import Workspace
from email_sync.models import AccountMailboxBinding, EmailAccount, RetainedMessage
from postings import job_posting_allocations as service, posting_source_corrections as mappings
from postings import job_posting_interpretations as arbitration, job_posting_projections as projection
from postings.models import (JobPosting, JobPostingAllocation as Allocation, PostingSource,
    JobPostingInterpretationDecision, JobPostingDescriptorProjection, RetainedPostingInterpretationDecision,
    RetainedPostingExtractionOutput, DESCRIPTOR_FIELDS)
from postings.tests.test_retained_interpretations import Fixtures as ItemFixtures
from postings.tests.test_retained_extractions import fields


class Fixtures(ItemFixtures):
    def setUp(self):
        super().setUp()
        self.account.provider = self.message.provider
        self.account.save()
        self.binding = AccountMailboxBinding.objects.create(account=self.account, mailbox=self.message.mailbox)
        self.selected = self.select().decision
        self.key = uuid.uuid4()

    def allocate(self, **changes):
        return service.allocate_job_posting(**dict(actor=self.user, workspace=self.ws, item_id=self.a.pk,
            operation_id=self.key, expected_interpretation_revision=1) | changes)

    def lookup(self, **changes):
        return service.read_retained_item_allocation(**dict(actor=self.user, workspace=self.ws, item_id=self.a.pk) | changes)

    def snapshot(self):
        return tuple((m._meta.label, list(m.objects.order_by('pk').values())) for m in apps.get_models()
            if m._meta.app_label in {'postings', 'applications', 'email_sync', 'documents'})

    def remap(self, **changes):
        return mappings.correct_posting_source(**dict(actor=self.user, workspace=self.ws, item_id=self.a.pk,
            operation_id=uuid.uuid4(), expected_revision=0, mode='associate', target_posting_id=self.q.pk) | changes)

    def projected(self, posting_id):
        arbitration.decide_job_posting_interpretation(actor=self.user, workspace=self.ws, posting_id=posting_id,
            operation_id=uuid.uuid4(), expected_revision=0, mode='select', item_id=self.a.pk,
            expected_interpretation_revision=1, expected_mapping_revision=0)
        row = JobPosting.objects.get(pk=posting_id)
        return projection.project_job_posting_descriptors(actor=self.user, workspace=self.ws, posting_id=posting_id,
            operation_id=uuid.uuid4(), expected_projection_revision=0, expected_arbitration_revision=1,
            expected_descriptor_digest=projection.descriptor_digest(projection.descriptor_snapshot(row)))


class AllocationTests(Fixtures, TestCase):
    def test_creation_exact_defaults_and_only_three_rows(self):
        before = dict(self.snapshot())
        result = self.allocate()
        fact = result.allocation
        row = JobPosting.objects.get(pk=fact.posting_id)
        self.assertFalse(result.replay)
        self.assertEqual(row.portable_id.version, 4)
        self.assertEqual((row.workspace_id, row.account_id), (self.ws.pk, self.account.pk))
        self.assertEqual(row.dedupe_key, f'retained-allocation:v1:{self.a.pk}')
        self.assertEqual(row.message_id, self.message.locator_value)
        self.assertEqual([getattr(row, f) for f in (*DESCRIPTOR_FIELDS, 'posting_url', 'email_subject', 'sender', 'received_at')], [None] * 10)
        self.assertEqual((row.status, row.saved), ('new', False))
        self.assertEqual(PostingSource.objects.get(item=self.a).posting_id, row.pk)
        after = dict(self.snapshot())
        for name in before:
            if name not in {'postings.JobPosting', 'postings.PostingSource', 'postings.JobPostingAllocation'}:
                self.assertEqual(before[name], after[name], name)
            else:
                self.assertEqual(len(after[name]), len(before[name]) + 1)
        state = arbitration.read_job_posting_interpretation(actor=self.user, workspace=self.ws, posting_id=row.pk)
        self.assertEqual((state.revision, state.state), (0, 'unresolved'))

    def test_replay_after_current_changes_and_owner_transfer(self):
        first = self.allocate().allocation
        self.withdraw()
        self.remap()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        Workspace.objects.filter(pk=self.ws.pk).update(owner=self.other)
        self.error('not_found', self.allocate, 404)
        before = self.snapshot()
        result = self.allocate(actor=self.other)
        self.assertTrue(result.replay)
        self.assertEqual(result.allocation, first)
        self.assertEqual(before, self.snapshot())

    def test_operation_scope_and_precedence(self):
        self.allocate()
        self.withdraw()
        self.error('idempotency_key_reused', lambda: self.allocate(expected_interpretation_revision=2), 409)
        self.error('job_posting_already_allocated', lambda: self.allocate(operation_id=uuid.uuid4()), 409)
        self.select(item_id=self.b.pk, output_id=self.outputs[1].pk, operation_id=uuid.uuid4())
        result = self.allocate(item_id=self.b.pk)
        self.assertNotEqual(result.allocation.posting_id, Allocation.objects.get(item=self.a).posting_id)
        self.assertEqual(Allocation.objects.filter(operation_id=self.key).count(), 2)

    def test_corruption_precedes_replay_and_changed_payload(self):
        fact = self.allocate().allocation
        JobPosting.objects.filter(pk=fact.posting_id).update(dedupe_key='corrupt')
        for changes in ({}, {'operation_id': uuid.uuid4()}, {'expected_interpretation_revision': 2}):
            self.error('job_posting_allocation_history_invalid', lambda: self.allocate(**changes), 409)

    def test_no_initial_mapping_even_after_corrections(self):
        self.attach()
        self.error('retained_item_initial_mapping_exists', self.allocate, 409)
        self.remap(mode='withdraw', target_posting_id=None)
        self.error('retained_item_initial_mapping_exists', self.allocate, 409)
        self.remap(expected_revision=1)
        self.error('retained_item_initial_mapping_exists', self.allocate, 409)
        self.remap(expected_revision=2, target_posting_id=self.p.pk)
        self.error('retained_item_initial_mapping_exists', self.allocate, 409)

    def test_interpretation_admission(self):
        self.error('stale_interpretation_revision', lambda: self.allocate(expected_interpretation_revision=2), 409)
        self.error('stale_interpretation_revision', lambda: self.allocate(item_id=self.b.pk), 409)
        self.move()
        self.error('posting_interpretation_not_applicable', self.allocate, 409)
        self.withdraw()
        self.error('posting_interpretation_not_applicable', lambda: self.allocate(expected_interpretation_revision=2), 409)

    def test_source_conflict_and_corrupt_sibling(self):
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        self.error('retained_source_ineligible', self.allocate, 409)
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=False)
        RetainedPostingExtractionOutput.objects.filter(pk=self.outputs[1].pk).update(fields=fields('corrupted'))
        self.error('posting_interpretation_evidence_invalid', self.allocate, 409)

    def test_input_and_scope(self):
        for value in (True, 0, -1, 2**63, '1', None):
            self.error('invalid_job_posting_allocation', lambda: self.allocate(expected_interpretation_revision=value))
        self.error('invalid_job_posting_allocation', lambda: self.allocate(operation_id='bad'))
        for changes in ({'item_id': True}, {'workspace': self.ws2}, {'actor': self.other}):
            self.error('not_found', lambda: self.allocate(**changes), 404)

    def test_missing_and_inconsistent_binding(self):
        AccountMailboxBinding.objects.filter(pk=self.binding.pk).delete()
        self.error('job_posting_allocation_account_unavailable', self.allocate, 409)
        AccountMailboxBinding.objects.create(account=self.account, mailbox=self.message.mailbox)
        EmailAccount.objects.filter(pk=self.account.pk).update(provider='outlook')
        self.error('job_posting_allocation_account_unavailable', self.allocate, 409)

    def test_disconnected_and_blocked_accounts(self):
        for status, item, output in [('disconnected', self.a, self.outputs[0]), ('blocked', self.b, self.outputs[1])]:
            if item == self.b:
                self.select(item_id=item.pk, output_id=output.pk, operation_id=uuid.uuid4())
            self.account.status = status
            self.account.save(update_fields=['status'])
            self.assertEqual(self.allocate(item_id=item.pk).allocation.account_id, self.account.pk)

    def test_binding_immutability_and_protection(self):
        self.allocate()
        for row in (self.binding, AccountMailboxBinding(pk=self.binding.pk, account=self.account, mailbox=self.message.mailbox)):
            with self.assertRaises(ValidationError):
                row.save()
        for obj in (self.binding, self.account, self.a, self.selected, PostingSource.objects.get(item=self.a),
                    JobPosting.objects.get(allocation__item=self.a), self.user):
            with self.assertRaises((ProtectedError, ValidationError)), transaction.atomic():
                obj.delete()
        self.account.status = 'disconnected'
        self.account.save(update_fields=['status'])
        self.assertTrue(self.allocate().replay)

    def test_locator_boundaries_copy_exactly(self):
        for index, value in enumerate(('x' * 512, 'é' * 256, '  mixedCase  ')):
            with self.subTest(value=index), transaction.atomic():
                RetainedMessage.objects.filter(pk=self.message.pk).update(locator_value=value)
                result = self.allocate()
                self.assertEqual(JobPosting.objects.get(pk=result.allocation.posting_id).message_id, value)
                transaction.set_rollback(True)

    def test_provider_locators(self):
        for provider in ('outlook', 'imap'):
            source = self.source(self.ws, provider=provider)
            account = EmailAccount.objects.create(workspace=self.ws, email='fixture@example.test', provider=provider)
            AccountMailboxBinding.objects.create(account=account, mailbox=source.mailbox)
            output = self.record(retained_message_id=source.pk, operation_id=uuid.uuid4(), outputs=[fields()]).outputs[0]
            item = self.decide(output).item
            self.select(item_id=item.pk, output_id=output.pk, operation_id=uuid.uuid4())
            self.assertEqual(JobPosting.objects.get(pk=self.allocate(item_id=item.pk).allocation.posting_id).message_id, source.locator_value)

    def test_invalid_persisted_locators_fail_atomically(self):
        for changes in ({'locator_value': ''}, {'locator_value': 'x' * 513}, {'locator_value': '\x00'},
                        {'folder': 'bad'}, {'stability': 'bad'}, {'locator_kind': 'bad'}):
            with self.subTest(changes=changes), transaction.atomic():
                RetainedMessage.objects.filter(pk=self.message.pk).update(**changes)
                self.error('retained_source_invalid', self.allocate, 409)
                transaction.set_rollback(True)
        self.message.locator_value = '\ud800'
        with self.assertRaises(service.RetainedSourceInvalid):
            service._validate_locator(self.message)
        self.message.provider = 'imap'
        self.message.locator_kind = 'imap_uid'
        self.message.folder = 'INBOX'
        self.message.stability = 'uidvalidity:1'
        for value in ('0', '01', '4294967296', '-1'):
            self.message.locator_value = value
            with self.assertRaises(service.RetainedSourceInvalid):
                service._validate_locator(self.message)

    def test_namespace_and_collision_privacy(self):
        key = service.allocation_key(self.a.pk)
        for call in (lambda: self.posting(dedupe_key=key), lambda: self.p.save(update_fields=['dedupe_key'])):
            self.p.dedupe_key = key
            with self.assertRaises(ValidationError) as caught:
                call()
            self.assertEqual(caught.exception.code, 'job_posting_allocation_namespace_reserved')
        JobPosting.objects.filter(pk=self.p.pk).update(dedupe_key=key)
        with self.assertRaises(APIException) as caught:
            self.allocate()
        self.assertEqual(caught.exception.get_codes(), 'job_posting_allocation_key_conflict')
        self.assertNotIn(str(self.p.pk), str(caught.exception.detail))
        self.assertFalse(Allocation.objects.exists())

    def test_key_guard_deferred_stale_empty_and_lifecycle(self):
        posting_id = self.allocate().allocation.posting_id
        for load, kwargs in ((lambda: JobPosting.objects.get(pk=posting_id), {}),
                             (lambda: JobPosting.objects.only('pk').get(pk=posting_id), {}),
                             (lambda: JobPosting.objects.get(pk=posting_id), {'update_fields': ['dedupe_key']})):
            row = load(); row.dedupe_key = 'changed'
            with self.assertRaises(ValidationError) as caught:
                row.save(**kwargs)
            self.assertEqual(caught.exception.code, 'job_posting_allocation_identity_owned')
        row.save(update_fields=[])
        row.saved = True; row.save(update_fields=['saved'])
        row.status = 'dismissed'; row.save(update_fields=['status'])
        row = JobPosting.objects.only('pk', 'status').get(pk=posting_id)
        row.status = 'new'; row.save()
        row = JobPosting.objects.get(pk=posting_id); row.save(update_fields=['dedupe_key'])
        Allocation.objects.filter(posting_id=posting_id).update(operation_id=uuid.UUID(int=0))
        row.dedupe_key = 'still forbidden'
        with self.assertRaises(ValidationError):
            row.save()

    def test_pk_only_forced_save_signals(self):
        posting_id = self.allocate().allocation.posting_id
        signals = []
        def receiver(**kwargs):
            signals.append(kwargs['instance'].pk)
        post_save.connect(receiver, sender=JobPosting)
        try:
            for force in (False, True):
                JobPosting.objects.only('pk').get(pk=posting_id).save(force_update=force)
            self.assertEqual(signals, [posting_id, posting_id])
        finally:
            post_save.disconnect(receiver, sender=JobPosting)

    def test_manual_descriptors_then_projection(self):
        posting_id = self.allocate().allocation.posting_id
        row = JobPosting.objects.get(pk=posting_id); row.title = 'manual'; row.save()
        self.assertNotIn('title', admin.site._registry[JobPosting].get_readonly_fields(None, row))
        self.projected(posting_id)
        row.title = 'stale'
        with self.assertRaises(ValidationError) as caught:
            row.save(update_fields=['title'])
        self.assertEqual(caught.exception.code, 'descriptor_projection_owned')

    def test_remap_preserves_orphan_and_allows_new_target_projection(self):
        original = self.allocate().allocation
        self.remap()
        self.assertEqual(self.allocate().allocation, original)
        self.assertEqual(PostingSource.objects.get(pk=original.initial_source_id).posting_id, original.posting_id)
        row = JobPosting.objects.get(pk=original.posting_id)
        self.assertEqual((row.status, row.title), ('new', None))
        self.assertFalse(JobPostingDescriptorProjection.objects.exists())
        arbitration.decide_job_posting_interpretation(actor=self.user, workspace=self.ws, posting_id=self.q.pk,
            operation_id=uuid.uuid4(), expected_revision=0, mode='select', item_id=self.a.pk,
            expected_interpretation_revision=1, expected_mapping_revision=1)
        projection.project_job_posting_descriptors(actor=self.user, workspace=self.ws, posting_id=self.q.pk,
            operation_id=uuid.uuid4(), expected_projection_revision=0, expected_arbitration_revision=1,
            expected_descriptor_digest=projection.descriptor_digest(projection.descriptor_snapshot(self.q)))

    def test_readers_frozen_absence_scope(self):
        self.assertIsNone(self.lookup().allocation)
        self.assertIsNone(service.read_job_posting_allocation(actor=self.user, workspace=self.ws, posting_id=self.p.pk).allocation)
        fact = self.allocate().allocation
        result = service.read_job_posting_allocation(actor=self.user, workspace=self.ws, posting_id=fact.posting_id)
        self.assertEqual(result.allocation, fact)
        with self.assertRaises(FrozenInstanceError):
            result.allocation.item_id = 9
        self.error('not_found', lambda: self.lookup(workspace=self.ws2), 404)

    def test_provenance_ordinary_writes_and_admin(self):
        fact = self.allocate().allocation
        row = Allocation.objects.get(pk=fact.id)
        values = {f.attname: getattr(row, f.attname) for f in row._meta.fields if f.name != 'created_at'}
        for call in (row.save, row.delete, lambda: Allocation(**values).save(), lambda: Allocation.objects.create(**values)):
            with self.assertRaises(ValidationError):
                call()
        ma = admin.site._registry[Allocation]
        self.assertFalse(ma.has_add_permission(None))
        self.assertFalse(ma.has_change_permission(None, row))
        self.assertFalse(ma.has_delete_permission(None, row))
        self.assertIsNone(ma.actions)

    def test_rollback_at_every_insertion_boundary(self):
        for target, after in (('_insert_posting', True), ('_append_initial_posting_source', False),
                              ('_append_initial_posting_source', True), ('_insert_allocation', False),
                              ('_insert_allocation', True), ('_record', False)):
            original = getattr(service, target)
            def fail(*args, **kwargs):
                if after:
                    original(*args, **kwargs)
                raise RuntimeError('injected')
            before = self.snapshot()
            with patch.object(service, target, fail), self.assertRaises(RuntimeError):
                self.allocate()
            self.assertEqual(before, self.snapshot())

    def test_constraints(self):
        fact = self.allocate().allocation
        row = Allocation.objects.get(pk=fact.id)
        for values in ({'method': 'bad'}, {'allocation_version': 2}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Allocation.objects.filter(pk=row.pk).update(**values)
        for name in ('posting', 'item', 'initial_source'):
            self.assertTrue(Allocation._meta.get_field(name).unique)
        self.assertFalse(Allocation._meta.get_field('operation_id').unique)

    def test_lock_order_and_no_parser(self):
        trace = []
        gate, source = service.lock_workspace, service.scoped_source
        def gate_call(*a, **k): trace.append('workspace'); return gate(*a, **k)
        def source_call(*a, **k): trace.append('source'); return source(*a, **k)
        with patch.object(service, 'lock_workspace', gate_call), patch.object(service, 'scoped_source', source_call), patch('postings.extraction.extract_postings', side_effect=AssertionError('parser')):
            self.allocate()
        self.assertEqual(trace, ['workspace', 'source'])

    def test_corrupt_relationships_fail_both_readers(self):
        fact = self.allocate().allocation
        other_account = EmailAccount.objects.create(workspace=self.ws, email="other@test", provider="gmail")
        cases = [(PostingSource, fact.initial_source_id, {"posting_id": self.q.pk}),
                 (Allocation, fact.id, {"interpretation_decision_id": self.selected.pk}),
                 (AccountMailboxBinding, self.binding.pk, {"account_id": other_account.pk}),
                 (JobPosting, fact.posting_id, {"account_id": other_account.pk})]
        # A withdrawal is a valid event, but cannot become the allocation witness.
        withdrawn = self.withdraw().decision
        cases[1] = (Allocation, fact.id, {"interpretation_decision_id": withdrawn.pk})
        for model, pk, values in cases:
            with self.subTest(model=model.__name__), transaction.atomic():
                model.objects.filter(pk=pk).update(**values)
                self.error("job_posting_allocation_history_invalid", self.lookup, 409)
                self.error("job_posting_allocation_history_invalid", lambda: service.read_job_posting_allocation(
                    actor=self.user, workspace=self.ws, posting_id=fact.posting_id), 409)
                transaction.set_rollback(True)

    def test_uniqueness_enforced_by_database(self):
        first = self.allocate().allocation
        self.select(item_id=self.b.pk, output_id=self.outputs[1].pk, operation_id=uuid.uuid4())
        second = self.allocate(item_id=self.b.pk).allocation
        for field, value in (("posting_id", first.posting_id), ("item_id", first.item_id),
                             ("initial_source_id", first.initial_source_id)):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Allocation.objects.filter(pk=second.id).update(**{field: value})

    def test_binding_wrong_workspace_or_mailbox(self):
        for target, values in ((EmailAccount, {"workspace_id": self.ws2.pk}),
                               (AccountMailboxBinding, {"mailbox_id": self.source(self.ws).mailbox_id})):
            with transaction.atomic():
                target.objects.filter(pk=self.account.pk if target is EmailAccount else self.binding.pk).update(**values)
                self.error("job_posting_allocation_account_unavailable", self.allocate, 409)
                transaction.set_rollback(True)

    def test_disconnect_keeps_allocation_and_binding(self):
        from email_sync.oauth import disconnect_gmail_account
        fact = self.allocate().allocation
        disconnect_gmail_account(self.account)
        self.assertEqual(self.allocate().allocation, fact)
        self.assertTrue(AccountMailboxBinding.objects.filter(pk=self.binding.pk).exists())

    def test_namespace_mutation_on_deferred_instance_and_explicit_empty(self):
        row = JobPosting.objects.only("pk").get(pk=self.p.pk)
        row.dedupe_key = service.allocation_key(self.a.pk)
        row.save(update_fields=[])
        with self.assertRaises(ValidationError) as caught:
            row.save()
        self.assertEqual(caught.exception.code, "job_posting_allocation_namespace_reserved")
        row.saved = True
        row.save(update_fields=["saved"])
        self.p.refresh_from_db()
        self.assertFalse(self.p.dedupe_key.startswith("retained-allocation:v1:"))

    def test_stale_key_cannot_restore_prior_value(self):
        posting_id = self.allocate().allocation.posting_id
        stale = JobPosting.objects.get(pk=posting_id)
        JobPosting.objects.filter(pk=posting_id).update(dedupe_key="maintenance drift")
        with self.assertRaises(ValidationError) as caught:
            stale.save()
        self.assertEqual(caught.exception.code, "job_posting_allocation_identity_owned")

    def test_identity_guards_preserved(self):
        posting_id = self.allocate().allocation.posting_id
        for name, value in (("workspace_id", self.ws2.pk), ("account_id", self.account.pk + 100),
                            ("portable_id", uuid.uuid4())):
            row = JobPosting.objects.only("pk").get(pk=posting_id)
            setattr(row, name, value)
            with self.assertRaises(ValidationError):
                row.save(update_fields=["saved"])

    def test_replay_lock_order(self):
        self.allocate()
        trace = []
        originals = {name: getattr(service, name) for name in ("lock_workspace", "_posting", "scoped_source")}
        def wrapper(name):
            def call(*args, **kwargs):
                trace.append(name)
                return originals[name](*args, **kwargs)
            return call
        with patch.object(service, "lock_workspace", wrapper("lock_workspace")), patch.object(
                service, "_posting", wrapper("_posting")), patch.object(service, "scoped_source", wrapper("scoped_source")):
            self.allocate()
        self.assertEqual(trace, ["lock_workspace", "_posting", "scoped_source"])

    def test_locator_imap_stability_and_folder(self):
        message = self.message
        message.provider = "imap"; message.locator_kind = "imap_uid"; message.locator_value = "4294967295"
        message.folder = "INBOX"; message.stability = "uidvalidity:4294967295"
        service._validate_locator(message)
        for folder, stability in (("", "uidvalidity:1"), ("INBOX", "uidvalidity:0"),
                                  ("INBOX", "uidvalidity:4294967296"), ("INBOX", "v1")):
            message.folder, message.stability = folder, stability
            with self.assertRaises(service.RetainedSourceInvalid):
                service._validate_locator(message)

    def test_foreign_collision_exposes_no_endpoint(self):
        account = EmailAccount.objects.create(workspace=self.ws2, email="other@test")
        row = self.posting(workspace=self.ws2, account=account)
        JobPosting.objects.filter(pk=row.pk).update(dedupe_key=service.allocation_key(self.a.pk))
        with self.assertRaises(APIException) as caught:
            self.allocate()
        self.assertEqual(caught.exception.get_codes(), "job_posting_allocation_key_conflict")
        self.assertEqual(str(caught.exception.detail), "Posting allocation cannot be applied.")


class AllocationConcurrencyTests(Fixtures, TransactionTestCase):
    def race(self, calls):
        barrier = Barrier(len(calls))
        def run(call):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try: return call()
                except OperationalError: return None
                except APIException as exc: return exc
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            results = list(pool.map(run, calls))
        # Explicit caller retry after SQLite contention; no retries in service.
        for n, result in enumerate(results):
            if result is None:
                try: results[n] = calls[n]()
                except APIException as exc: results[n] = exc
        return results

    def test_same_operation(self):
        results = self.race([self.allocate, self.allocate])
        self.assertEqual(Allocation.objects.count(), 1)
        self.assertEqual(sorted(r.replay for r in results), [False, True])

    def test_different_operation(self):
        results = self.race([self.allocate, lambda: self.allocate(operation_id=uuid.uuid4())])
        self.assertEqual(Allocation.objects.count(), 1)
        self.assertEqual([r.get_codes() for r in results if isinstance(r, APIException)], ['job_posting_already_allocated'])

    def test_attach_existing(self):
        results = self.race([self.allocate, self.attach])
        self.assertEqual(PostingSource.objects.filter(item=self.a).count(), 1)
        self.assertEqual(JobPosting.objects.count(), 2 + Allocation.objects.count())
        self.assertEqual(sum(isinstance(r, APIException) for r in results), 1)

    def test_interpretation_change(self):
        results = self.race([self.allocate, self.withdraw])
        self.assertFalse(isinstance(results[1], APIException))
        if Allocation.objects.exists(): self.assertTrue(self.allocate().replay)
        else: self.assertEqual(results[0].get_codes(), 'stale_interpretation_revision')

    def test_ingestion_independent_identity(self):
        from postings.services import ingest_extracted_postings
        def ingest():
            return ingest_extracted_postings(self.account, 'same', 'sender', 'subject', 'body')
        with patch('postings.extraction.extract_postings', return_value=[fields()]):
            results = self.race([self.allocate, ingest])
        self.assertTrue(all(not isinstance(r, APIException) for r in results))
        self.assertEqual(JobPosting.objects.count(), 4)
