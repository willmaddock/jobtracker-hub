"""Whole-output authority, logical witnesses, integrity and isolated concurrency."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError
from threading import Barrier, Event
from unittest.mock import patch
import uuid

from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError, OperationalError, close_old_connections
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import APIException

from accounts.models import User, Workspace
from email_sync.models import RetainedMessage
from postings import retained_interpretations as service, retained_item_corrections as membership
from postings import posting_sources, posting_source_corrections
from postings.models import RetainedPostingInterpretationDecision as Decision
from postings.models import (RetainedPostingItem as Item, RetainedPostingItemAssociation as Association,
    RetainedPostingItemCorrection as Correction, RetainedPostingExtraction as Extraction,
    RetainedPostingExtractionOutput as Output, PostingSource, PostingSourceCorrection)
from postings.tests.test_posting_sources import Fixtures as MappingFixtures
from postings.tests.test_retained_extractions import fields


class Fixtures(MappingFixtures):
    def setUp(self):
        super().setUp()
        self.initial = Association.objects.get(output=self.outputs[0])
        self.second = self.decide(self.outputs[2], mode="attach_existing", item_id=self.a.pk).association
        self.operation = uuid.uuid4()

    def select(self, **changes):
        return service.decide_posting_interpretation(**dict(actor=self.user, workspace=self.ws,
            item_id=self.a.pk, operation_id=self.operation, expected_revision=0, mode="select",
            output_id=self.outputs[0].pk, expected_membership_revision=0) | changes)

    def withdraw(self, revision=1, **changes):
        return self.select(**dict(operation_id=uuid.uuid4(), expected_revision=revision,
            mode="withdraw", output_id=None, expected_membership_revision=None) | changes)

    def current(self, **changes):
        return service.read_posting_interpretation(**dict(actor=self.user, workspace=self.ws,
            item_id=self.a.pk) | changes)

    def history(self, **changes):
        return service.list_posting_interpretation_decisions(**dict(actor=self.user, workspace=self.ws,
            item_id=self.a.pk) | changes)

    def move(self, **changes):
        return membership.correct_posting_item_association(**dict(actor=self.user, workspace=self.ws,
            output_id=self.outputs[0].pk, operation_id=uuid.uuid4(), expected_revision=0,
            mode="associate", target_item_id=self.b.pk) | changes)

    def snapshot(self):
        return tuple(list(model.objects.order_by("pk").values()) for model in
            (Decision, Item, Association, Correction, Extraction, Output, PostingSource, PostingSourceCorrection))

    def model_row(self, **changes):
        return Decision(**dict(item=self.a, actor=self.user, operation_id=uuid.uuid4(), revision=1,
            mode="select", selected_association=self.initial, membership_revision=0) | changes)

    def assert_corrupt(self, code):
        for call in (self.current, self.history, self.select,
                     lambda: self.withdraw(self.current_revision_for_corruption)):
            self.error(code, call, 409)


class InterpretationTests(Fixtures, TestCase):
    def test_unresolved_and_first_whole_output(self):
        state = self.current()
        self.assertEqual((state.revision, state.state), (0, "unresolved"))
        self.assertIsNone(state.latest_decision)
        self.assertIsNone(state.selected_output)
        self.assertIsNone(state.applicable_output)
        self.assertIsNone(state.recorded_membership_revision)
        self.assertIsNone(state.current_membership_revision)
        self.assertTrue(state.can_append_decision)
        self.assertEqual(self.history().through_revision, 0)
        self.assertEqual(self.history().decisions, ())
        result = self.select()
        self.assertFalse(result.replay)
        self.assertEqual((result.decision.revision, result.current.state), (1, "selected"))
        self.assertEqual(result.current.selected_output.pk, self.outputs[0].pk)
        self.assertEqual(result.current.applicable_output.fields, self.outputs[0].fields)
        self.assertEqual(result.decision.selected_association_id, self.initial.pk)
        self.assertEqual((result.current.recorded_membership_revision,
                          result.current.current_membership_revision), (0, 0))
        with self.assertRaises(FrozenInstanceError):
            result.current.state = "withdrawn"

    def test_replace_withdraw_restore_and_timestamp_not_authority(self):
        first = self.select()
        second = self.select(operation_id=uuid.uuid4(), expected_revision=1, output_id=self.outputs[2].pk)
        self.assertEqual(second.current.selected_output.pk, self.outputs[2].pk)
        withdrawn = self.withdraw(2)
        self.assertEqual(withdrawn.current.state, "withdrawn")
        for name in ("selected_output", "applicable_output", "recorded_membership_revision", "current_membership_revision"):
            self.assertIsNone(getattr(withdrawn.current, name))
        restored = self.select(operation_id=uuid.uuid4(), expected_revision=3)
        Decision.objects.filter(pk=first.decision.pk).update(created_at="2099-01-01T00:00:00Z")
        self.assertEqual(self.current().latest_decision.pk, restored.decision.pk)
        self.assertEqual([r.revision for r in self.history().decisions], [1, 2, 3, 4])

    def test_noops_reserve_nothing(self):
        self.error("posting_interpretation_unchanged", lambda: self.withdraw(0), 409)
        self.select()
        key = uuid.uuid4()
        self.error("posting_interpretation_unchanged", lambda: self.select(operation_id=key, expected_revision=1), 409)
        self.assertFalse(Decision.objects.filter(operation_id=key).exists())
        self.withdraw()
        self.error("posting_interpretation_unchanged", lambda: self.withdraw(2, operation_id=key), 409)
        self.assertFalse(Decision.objects.filter(operation_id=key).exists())
        self.assertEqual(self.select(operation_id=key, expected_revision=2).decision.revision, 3)

    def test_move_away_return_stays_stale_and_reaffirm(self):
        first = self.select()
        self.move()
        state = self.current()
        self.assertEqual((state.state, state.current_membership_revision), ("stale", 1))
        self.assertEqual(state.selected_output.pk, self.outputs[0].pk)
        self.assertIsNone(state.applicable_output)
        self.move(expected_revision=1, target_item_id=self.a.pk)
        self.assertEqual(self.current().state, "stale")
        self.assertEqual(Decision.objects.count(), 1)
        replay = self.select()
        self.assertTrue(replay.replay)
        self.assertEqual(replay.decision.pk, first.decision.pk)
        self.assertEqual(replay.current.state, "stale")
        result = self.select(operation_id=uuid.uuid4(), expected_revision=1, expected_membership_revision=2)
        self.assertEqual((result.decision.revision, result.current.state), (2, "selected"))
        self.assertEqual(result.current.recorded_membership_revision, 2)

    def test_replay_old_after_later_decision(self):
        first = self.select()
        self.withdraw()
        replay = self.select(operation_id=str(self.operation))
        self.assertTrue(replay.replay)
        self.assertEqual(replay.decision.pk, first.decision.pk)
        self.assertEqual(replay.decision.created_at, first.decision.created_at)
        self.assertEqual(replay.decision.actor_id, self.user.pk)
        self.assertEqual((replay.current.revision, replay.current.state), (2, "withdrawn"))
        self.assertEqual(Decision.objects.count(), 2)

    def test_changed_payload_precedes_stale_and_corrupt_evidence(self):
        self.select()
        for changes in ({"output_id": self.outputs[2].pk}, {"expected_revision": 1},
                        {"expected_membership_revision": 1},
                        {"mode": "withdraw", "output_id": None, "expected_membership_revision": None}):
            self.error("idempotency_key_reused", lambda: self.select(**changes), 409)
        for name, value in (("METHOD", "future"), ("DECISION_VERSION", 2)):
            with patch.object(service, name, value):
                self.error("idempotency_key_reused", self.select, 409)
        Extraction.objects.filter(pk=self.outputs[0].extraction_id).update(payload_digest="0" * 64)
        self.error("idempotency_key_reused", lambda: self.select(expected_revision=1), 409)
        self.error("posting_interpretation_evidence_invalid", self.select, 409)

    def test_operation_scope_is_item(self):
        self.select()
        other = self.select(item_id=self.b.pk, output_id=self.outputs[1].pk)
        self.assertEqual(other.decision.revision, 1)
        self.assertEqual(Decision.objects.count(), 2)

    def test_interpretation_stale_precedes_eligibility_membership_and_noop(self):
        self.select()
        self.move()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        self.error("stale_revision", lambda: self.select(operation_id=uuid.uuid4()), 409)
        self.error("retained_source_ineligible", lambda: self.select(operation_id=uuid.uuid4(), expected_revision=1), 409)

    def test_membership_errors_and_precedence(self):
        self.error("posting_output_not_member", lambda: self.select(output_id=self.outputs[1].pk), 409)
        self.error("posting_membership_required", lambda: self.select(output_id=self.outputs[3].pk), 409)
        self.move(mode="withdraw", target_item_id=None)
        self.error("stale_membership_revision", self.select, 409)
        self.error("posting_output_not_member", lambda: self.select(expected_membership_revision=1), 409)
        self.move(expected_revision=1)
        self.error("stale_membership_revision", lambda: self.select(expected_membership_revision=1), 409)
        self.error("posting_output_not_member", lambda: self.select(expected_membership_revision=2), 409)

    def test_bounded_input_and_uuid_validation(self):
        for value in (True, False, -1, 2**63, "0", None, 0.0):
            for name in ("expected_revision", "expected_membership_revision"):
                self.error("invalid_posting_interpretation", lambda: self.select(**{name: value}))
        for value in (True, False, 0, -1, 2**63, "1", None):
            self.error("invalid_posting_interpretation", lambda: self.select(output_id=value))
            self.error("not_found", lambda: self.select(item_id=value), 404)
        for value in (None, True, [], "bad", uuid.uuid1(), uuid.UUID(int=0), self.operation.hex, str(self.operation).upper()):
            self.error("invalid_posting_interpretation", lambda: self.select(operation_id=value))
        for change in ({"mode": []}, {"mode": "other"}, {"mode": "withdraw"},
                       {"mode": "withdraw", "output_id": None}):
            self.error("invalid_posting_interpretation", lambda: self.select(**change))

    def test_nonleaking_endpoints(self):
        for ws in (self.ws, self.ws2):
            source = self.source(ws)
            output = self.record(workspace=ws, retained_message_id=source.pk, operation_id=uuid.uuid4()).outputs[0]
            self.error("not_found", lambda: self.select(output_id=output.pk), 404)
        for call in (self.select, self.current, self.history):
            self.error("not_found", lambda: call(workspace=self.ws2), 404)
            self.error("not_found", lambda: call(item_id=999999), 404)
        self.error("not_found", lambda: self.select(output_id=999999), 404)

    def test_owner_transfer_replay_attribution(self):
        first = self.select()
        for actor in (None, AnonymousUser(), User(username="unsaved"), self.other):
            for call in (self.select, self.current, self.history):
                self.error("not_found", lambda: call(actor=actor), 404)
        Workspace.objects.filter(pk=self.ws.pk).update(owner=self.other)
        self.error("not_found", self.current, 404)
        replay = self.select(actor=self.other)
        self.assertTrue(replay.replay)
        self.assertEqual((replay.decision.actor_id, replay.decision.created_at),
                         (self.user.pk, first.decision.created_at))
        self.assertEqual(self.withdraw(actor=self.other).decision.actor_id, self.other.pk)

    def test_sticky_conflict_read_history_replay_only(self):
        self.select()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        state = self.current()
        self.assertEqual(state.state, "selected")
        self.assertFalse(state.source_eligible)
        self.assertFalse(state.can_append_decision)
        self.assertFalse(self.history().source_eligible)
        self.assertTrue(self.select().replay)
        self.error("retained_source_ineligible", lambda: self.select(operation_id=uuid.uuid4(), expected_revision=1), 409)
        self.error("retained_source_ineligible", self.withdraw, 409)

    def test_source_corruption_all_surfaces_even_unresolved(self):
        RetainedMessage.objects.filter(pk=self.message.pk).update(content_digest="0" * 64)
        self.current_revision_for_corruption = 0
        self.assert_corrupt("retained_source_invalid")

    def test_extraction_corruption_matrix_and_historical_withdrawal(self):
        self.select()
        self.withdraw()
        self.current_revision_for_corruption = 2
        extraction = Extraction.objects.get(pk=self.outputs[0].extraction_id)
        mutations = {"payload_digest": "0" * 64, "extractor_method": "future", "extractor_version": "2",
            "snapshot_version": 2, "input_spec": {}, "operation_id": uuid.uuid4(),
            "extracted_at": "2026-09-28T12:00:00Z"}
        for name, value in mutations.items():
            with self.subTest(name=name):
                Extraction.objects.filter(pk=extraction.pk).update(**{name: value})
                self.assert_corrupt("posting_interpretation_evidence_invalid")
                Extraction.objects.filter(pk=extraction.pk).update(**{name: getattr(extraction, name)})

    def test_fields_and_sibling_positions_portable_id_integrity(self):
        self.select()
        self.current_revision_for_corruption = 1
        sibling = self.outputs[3]
        for change in ({"fields": {}}, {"fields": fields("changed")},
                       {"position": 5}, {"portable_id": uuid.uuid1()}):
            with self.subTest(change=change):
                Output.objects.filter(pk=sibling.pk).update(**change)
                self.assert_corrupt("posting_interpretation_evidence_invalid")
                Output.objects.filter(pk=sibling.pk).update(**{name: getattr(sibling, name) for name in change})
        with self.assertRaises(IntegrityError), transaction.atomic():
            Output.objects.filter(pk=sibling.pk).update(position=0)

    def test_selector_validation_even_with_matching_recomputed_digest(self):
        from postings import extraction_contract as contract
        extraction = Extraction.objects.get(pk=self.outputs[0].extraction_id)
        spec = deepcopy(extraction.input_spec)
        spec["selectors"]["sender"]["index"] = 99
        envelope = contract.validate_envelope(extraction.operation_id, extraction.extractor_method,
            extraction.extractor_version, spec, extraction.extracted_at.isoformat(), [o.fields for o in self.outputs])
        digest = contract.replay_digest(envelope, dict(workspace_id=self.ws.pk, retained_message_id=self.message.pk,
            retained_message_portable_id=str(self.message.portable_id), representation_version=1,
            content_digest=self.message.content_digest))
        Extraction.objects.filter(pk=extraction.pk).update(input_spec=spec, payload_digest=digest)
        self.error("posting_interpretation_evidence_invalid", self.select, 409)

    def test_extraction_output_count_bounded(self):
        with patch.object(service.contract, "MAX_OUTPUTS", 3):
            self.error("posting_interpretation_evidence_invalid", self.select, 409)

    def test_false_historical_witness_is_not_stale(self):
        row = self.select().decision
        self.move()
        Decision.objects.filter(pk=row.pk).update(membership_revision=1)
        for call in (self.current, self.history, lambda: self.withdraw()):
            self.error("posting_interpretation_history_invalid", call, 409)

    def test_membership_gap_fails_even_old_replay(self):
        self.move()
        self.move(expected_revision=1, target_item_id=self.a.pk)
        self.select(expected_membership_revision=2)
        Correction.objects.filter(initial_association=self.initial, revision=1).delete()
        for call in (self.current, self.history, lambda: self.select(expected_membership_revision=2)):
            self.error("posting_association_history_invalid", call, 409)

    def test_membership_target_corruption(self):
        self.select()
        correction = self.move().correction
        foreign = Item.objects.create(retained_message=self.source(self.ws))
        Correction.objects.filter(pk=correction.pk).update(target_item=foreign)
        self.error("posting_association_history_invalid", self.current, 409)
        self.error("posting_association_history_invalid", self.select, 409)

    def test_initial_policy_and_membership_policy_corruption(self):
        self.select()
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA ignore_check_constraints = ON")
            try:
                Association.objects.filter(pk=self.initial.pk).update(method="future")
                self.error("posting_association_history_invalid", self.current, 409)
                Association.objects.filter(pk=self.initial.pk).update(method="explicit_owner")
                correction = self.move().correction
                Correction.objects.filter(pk=correction.pk).update(method="future")
                self.error("posting_association_history_invalid", self.current, 409)
            finally:
                cursor.execute("PRAGMA ignore_check_constraints = OFF")

    def test_interpretation_gap(self):
        first = self.select().decision
        self.withdraw()
        Decision.objects.filter(pk=first.pk).delete()
        for call in (self.current, self.history, self.select):
            self.error("posting_interpretation_history_invalid", call, 409)

    def test_interpretation_shape_policy_uuid_corruption(self):
        row = self.select().decision
        self.withdraw()
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA ignore_check_constraints = ON")
            try:
                for change in ({"method": "future"}, {"decision_version": 2}, {"mode": "other"},
                               {"membership_revision": None}, {"selected_association_id": None},
                               {"operation_id": uuid.uuid1()}):
                    with self.subTest(change=change):
                        Decision.objects.filter(pk=row.pk).update(**change)
                        self.error("posting_interpretation_history_invalid", self.current, 409)
                        self.error("posting_interpretation_history_invalid", self.history, 409)
                        self.error("posting_interpretation_history_invalid", lambda: self.withdraw(2), 409)
                        Decision.objects.filter(pk=row.pk).update(**{name: getattr(row, name) for name in change})
            finally:
                cursor.execute("PRAGMA ignore_check_constraints = OFF")

    def test_cross_source_historical_association(self):
        row = self.select().decision
        source = self.source(self.ws)
        output = self.record(retained_message_id=source.pk, operation_id=uuid.uuid4()).outputs[0]
        association = self.decide(output).association
        Decision.objects.filter(pk=row.pk).update(selected_association=association)
        self.error("posting_interpretation_history_invalid", self.current, 409)
        self.error("posting_interpretation_history_invalid", self.history, 409)

    def test_mapping_independence_and_no_winner(self):
        self.select()
        self.select(item_id=self.b.pk, output_id=self.outputs[1].pk)
        before = list(Decision.objects.order_by("pk").values())
        self.assertFalse(PostingSource.objects.exists())
        self.attach()
        self.attach(item_id=self.b.pk)
        for revision, mode, target in ((0, "associate", self.q.pk), (1, "withdraw", None), (2, "associate", self.p.pk)):
            posting_source_corrections.correct_posting_source(actor=self.user, workspace=self.ws, item_id=self.a.pk,
                operation_id=uuid.uuid4(), expected_revision=revision, mode=mode, target_posting_id=target)
            self.assertEqual(list(Decision.objects.order_by("pk").values()), before)
            self.assertEqual(self.current().selected_output.pk, self.outputs[0].pk)
            self.assertEqual(self.current(item_id=self.b.pk).selected_output.pk, self.outputs[1].pk)
        with patch.object(posting_source_corrections, "resolve_chain", side_effect=AssertionError("mapping read")):
            self.current()
            self.history()

    def test_mapping_restoration_does_not_reactivate_stale(self):
        self.select()
        self.attach()
        self.move()
        for revision, mode, target in ((0, "withdraw", None), (1, "associate", self.p.pk)):
            posting_source_corrections.correct_posting_source(actor=self.user, workspace=self.ws, item_id=self.a.pk,
                operation_id=uuid.uuid4(), expected_revision=revision, mode=mode, target_posting_id=target)
        self.assertEqual(self.current().state, "stale")
        self.assertEqual(Decision.objects.count(), 1)

    def test_empty_item_no_synthetic_evidence(self):
        item = Item.objects.create(retained_message=self.message)
        self.record(operation_id=uuid.uuid4(), outputs=[])
        self.assertEqual(self.current(item_id=item.pk).state, "unresolved")
        self.error("posting_output_not_member", lambda: self.select(item_id=item.pk), 409)
        self.assertFalse(Decision.objects.exists())

    def test_long_null_blank_fields_preserved_without_projection(self):
        value = fields("x" * 4096)
        output = self.record(operation_id=uuid.uuid4(), outputs=[value]).outputs[0]
        self.decide(output, mode="attach_existing", item_id=self.a.pk)
        before = self.p.title, self.p.posting_url
        result = self.select(output_id=output.pk)
        self.assertEqual(result.current.applicable_output.fields, value)
        self.assertNotIn("posting_url", result.current.applicable_output.fields)
        self.p.refresh_from_db()
        self.assertEqual((self.p.title, self.p.posting_url), before)

    def test_immutability_and_replacement(self):
        row = self.select().decision
        for field in row._meta.fields:
            clone = Decision.objects.get(pk=row.pk)
            setattr(clone, field.attname, None)
            with self.assertRaises(ValidationError):
                clone.save(update_fields=[field.name])
        replacement = Decision(**{f.attname: getattr(row, f.attname) for f in row._meta.fields})
        with self.assertRaises(ValidationError):
            replacement.save()
        with self.assertRaises(ValidationError):
            row.delete()

    def test_protected_historical_references(self):
        self.select()
        self.withdraw()
        Workspace.objects.filter(owner=self.user).update(owner=self.other)
        for obj in (self.a, self.initial, self.user):
            with self.assertRaises(ProtectedError):
                type(obj).objects.filter(pk=obj.pk).delete()

    def test_model_validation(self):
        for change in ({"revision": True}, {"revision": 0}, {"revision": 2}, {"revision": 2**63},
                       {"membership_revision": True}, {"membership_revision": -1},
                       {"membership_revision": 2**63}, {"membership_revision": 1},
                       {"actor_id": 999999}, {"item_id": 999999}, {"decision_version": True},
                       {"method": "auto"}, {"operation_id": uuid.uuid1()},
                       {"selected_association": Association.objects.get(output=self.outputs[1])}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.model_row(**change).save()
        self.model_row().save()
        with self.assertRaises(ValidationError):
            self.model_row(revision=2).save()

    def test_database_constraints(self):
        first = self.select().decision
        second = self.withdraw().decision
        for change in ({"revision": 0}, {"revision": 1}, {"operation_id": first.operation_id},
                       {"mode": "other"}, {"mode": "select"}, {"membership_revision": 0},
                       {"selected_association": self.initial}, {"method": "auto"}, {"decision_version": 2}):
            with self.subTest(change=change), self.assertRaises(IntegrityError), transaction.atomic():
                Decision.objects.filter(pk=second.pk).update(**change)

    def test_pagination_prefix_and_navigation(self):
        self.select()
        self.withdraw()
        self.select(operation_id=uuid.uuid4(), expected_revision=2)
        page1 = self.history(limit=1)
        self.withdraw(3)
        page2 = self.history(limit=1, cursor=page1.next_cursor)
        page3 = self.history(limit=1, cursor=page2.next_cursor)
        self.assertEqual([p.decisions[0].revision for p in (page1, page2, page3)], [1, 2, 3])
        self.assertEqual(page3.through_revision, 3)
        self.assertIsNone(page3.next_cursor)
        self.assertEqual(self.history().through_revision, 4)
        for limit in (True, 0, 201, "1"):
            self.error("invalid_posting_interpretation", lambda: self.history(limit=limit))
        for cursor in ([], (1,), (True, 1, 0), (self.b.pk, 3, 0), (self.a.pk, 3, 4),
                       (self.a.pk, 99, 0), (self.a.pk, -1, 0), (self.a.pk, 2**63, 0)):
            self.error("invalid_posting_interpretation", lambda: self.history(cursor=cursor))
        self.assertEqual(self.history(cursor=(self.a.pk, 0, 0)).decisions, ())

    def test_history_witness_stays_historical_while_effective_is_live(self):
        self.select()
        self.withdraw()
        page = self.history(limit=1)
        self.move()
        self.assertEqual(page.decisions[0].membership_revision, 0)
        self.assertEqual(self.history(cursor=page.next_cursor).through_revision, 2)
        self.assertEqual(self.current().state, "withdrawn")

    def test_capacity_replay_and_advisory_flag(self):
        self.select()
        with patch.object(service, "MAX_REVISION", 1):
            self.assertTrue(self.select().replay)
            self.assertFalse(self.current().can_append_decision)
            self.error("posting_interpretation_revision_exhausted", self.withdraw, 409)

    def test_failure_after_insert_and_result_rolls_back(self):
        save = Decision.save
        def fail(row, *args, **kwargs):
            save(row, *args, **kwargs)
            raise RuntimeError("after insert")
        before = self.snapshot()
        with patch.object(Decision, "save", fail), self.assertRaises(RuntimeError):
            self.select()
        self.assertEqual(before, self.snapshot())
        before = self.snapshot()
        with patch.object(service, "_state", side_effect=RuntimeError("result")), self.assertRaises(RuntimeError):
            self.select()
        self.assertEqual(before, self.snapshot())

    def test_no_other_table_or_parser_side_effects(self):
        def snapshot():
            with connection.cursor() as cursor:
                result = {}
                for table in connection.introspection.table_names():
                    if table == Decision._meta.db_table:
                        continue
                    cursor.execute(f"SELECT * FROM {connection.ops.quote_name(table)} ORDER BY 1")
                    result[table] = cursor.fetchall()
                return result
        before = snapshot()
        with patch("postings.extraction.extract_postings", side_effect=AssertionError("parser")):
            self.select()
            self.current()
            self.history()
            self.withdraw()
        self.assertEqual(before, snapshot())

    def test_readers_hold_gate_and_transaction_through_membership(self):
        self.select()
        seen = []
        real_gate, real_membership = service.lock_workspace, service._membership
        def gate(*args):
            self.assertTrue(connection.in_atomic_block)
            seen.append("gate")
            return real_gate(*args)
        def membership_read(*args, **kwargs):
            self.assertTrue(connection.in_atomic_block)
            self.assertEqual(seen[0], "gate")
            seen.append("membership")
            return real_membership(*args, **kwargs)
        for reader in (self.current, self.history):
            seen.clear()
            with patch.object(service, "lock_workspace", gate), patch.object(service, "_membership", membership_read):
                reader()
            self.assertIn("membership", seen)

    def test_source_corruption_after_selection_blocks_replay(self):
        self.select()
        RetainedMessage.objects.filter(pk=self.message.pk).update(content_digest="0" * 64)
        self.current_revision_for_corruption = 1
        self.assert_corrupt("retained_source_invalid")

    def test_historical_membership_prefix_does_not_require_current_membership(self):
        self.select()
        self.move(mode="withdraw", target_item_id=None)
        replay = self.select()
        self.assertTrue(replay.replay)
        self.assertEqual(replay.current.state, "stale")
        self.assertEqual(self.history().decisions[0].membership_revision, 0)

    def test_model_rejects_stale_witness_without_changing_history(self):
        self.move()
        self.move(expected_revision=1, target_item_id=self.a.pk)
        with self.assertRaises(ValidationError):
            self.model_row().save()
        self.model_row(membership_revision=2).save()
        self.assertEqual(self.current().state, "selected")

    def test_admin_read_only(self):
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        row = self.select().decision
        base = "/admin/postings/retainedpostinginterpretationdecision/"
        self.assertEqual(self.client.get(base).status_code, 200)
        self.assertEqual(self.client.get(f"{base}{row.pk}/change/").status_code, 200)
        self.assertEqual(self.client.get(base + "add/").status_code, 403)
        for url in (base + "add/", f"{base}{row.pk}/change/", f"{base}{row.pk}/delete/"):
            self.assertEqual(self.client.post(url, {"_save": "Save", "post": "yes"}).status_code, 403)
        model_admin = admin.site._registry[Decision]
        request = type("Request", (), {"user": self.user, "GET": {}})()
        self.assertEqual(model_admin.get_actions(request), {})
        self.assertEqual(set(model_admin.get_readonly_fields(request)), {f.name for f in row._meta.fields})


class InterpretationConcurrencyTests(Fixtures, TransactionTestCase):
    def race(self, variant):
        requests = [{}, {}]
        if variant == "changed":
            requests[1] = {"output_id": self.outputs[2].pk}
        elif variant == "different":
            requests[1] = {"operation_id": uuid.uuid4(), "output_id": self.outputs[2].pk}
        expected = "idempotency_key_reused" if variant == "changed" else "stale_revision"
        barrier = Barrier(2)
        def attempt(changes):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.select(**changes)
            except OperationalError:
                return None
            except APIException as exc:
                self.assertEqual(exc.get_codes(), expected)
                return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(attempt, requests))
        successes, conflicts = [], 0
        # Explicit caller retries after both attempts, never a service retry loop.
        for changes in requests:
            try:
                successes.append(self.select(**changes))
            except APIException as exc:
                self.assertEqual(exc.get_codes(), expected)
                conflicts += 1
        self.assertEqual(conflicts, int(variant != "same"))
        self.assertEqual(len({r.decision.pk for r in successes}), 1)
        self.assertEqual(Decision.objects.count(), 1)

    def test_same_operation(self):
        self.race("same")

    def test_changed_operation_payload(self):
        self.race("changed")

    def test_same_revision_different_operations(self):
        self.race("different")

    def test_membership_and_selection_serial_outcomes(self):
        self.select()
        self.move()
        self.assertEqual(self.current().state, "stale")
        self.error("stale_membership_revision", lambda: self.select(item_id=self.b.pk, operation_id=uuid.uuid4()), 409)
        result = self.select(item_id=self.b.pk, operation_id=uuid.uuid4(), expected_membership_revision=1)
        self.assertEqual(result.current.state, "selected")

    def test_combined_read_blocks_competing_membership_writer(self):
        self.select()
        captured, release = Event(), Event()
        real_resolve = service.resolve_chain
        def paused(*args, **kwargs):
            result = real_resolve(*args, **kwargs)
            captured.set()
            if not release.wait(timeout=10):
                raise AssertionError("reader was not released")
            return result
        def reader():
            close_old_connections()
            try:
                return self.current()
            finally:
                close_old_connections()
        with patch.object(service, "resolve_chain", paused), ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(reader)
            try:
                self.assertTrue(captured.wait(timeout=10))
                # SQLite refuses the competing Workspace gate rather than returning
                # a mixed read. PostgreSQL execution is deliberately not claimed.
                with self.assertRaises(OperationalError):
                    self.move()
            finally:
                release.set()
            state = pending.result(timeout=10)
        self.assertEqual((state.revision, state.state, state.current_membership_revision), (1, "selected", 0))
        self.move()
        self.assertEqual(self.current().state, "stale")

    def test_membership_selection_race_has_only_serial_outcomes(self):
        barrier = Barrier(2)
        def attempt(kind):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.select() if kind == "select" else self.move()
            except OperationalError:
                return None
            except APIException as exc:
                self.assertEqual(exc.get_codes(), "stale_membership_revision")
                return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(attempt, ("select", "move")))
        # Explicitly retry whichever membership operation lost SQLite's gate.
        current = membership.read_effective_posting_item_association(actor=self.user,
            workspace=self.ws, output_id=self.outputs[0].pk)
        if current.effective_revision == 0:
            self.move()
        if Decision.objects.exists():
            replay = self.select()
            self.assertTrue(replay.replay)
            self.assertEqual(replay.current.state, "stale")
        else:
            self.error("stale_membership_revision", self.select, 409)
            self.assertEqual(self.current().state, "unresolved")


class AdvisoryObservationTests(Fixtures, TestCase):
    def observe(self, **changes):
        return service.observe_posting_interpretation(**dict(actor=self.user, workspace=self.ws,
                                                            item_id=self.a.pk) | changes)

    def assert_parity(self):
        current, observed = self.current(), self.observe()
        for name in ('state', 'revision', 'recorded_membership_revision',
                     'current_membership_revision', 'source_eligible'):
            self.assertEqual(getattr(current, name), getattr(observed, name))
        self.assertEqual(observed.selected_output_id,
                         current.selected_output.pk if current.selected_output else None)
        self.assertEqual(observed.applicable_output_id,
                         current.applicable_output.pk if current.applicable_output else None)
        if current.applicable_output:
            from dataclasses import asdict
            self.assertEqual(asdict(observed.evidence), current.applicable_output.fields)
        else:
            self.assertIsNone(observed.evidence)

    def test_state_parity_and_away_back(self):
        self.assert_parity()
        self.select(); self.assert_parity()
        self.move(); self.assert_parity()
        self.move(expected_revision=1, target_item_id=self.a.pk)
        self.assertEqual(self.observe().state, 'stale')
        self.assert_parity()
        self.withdraw(); self.assert_parity()

    def test_gate_lock_preserved_and_observer_unlocked(self):
        with patch.object(service, 'lock_workspace', wraps=service.lock_workspace) as gate, \
             patch.object(service, 'scoped_source', wraps=service.scoped_source) as source:
            self.current()
            gate.assert_called_once()
            self.assertTrue(source.call_args.kwargs['lock'])
        with patch.object(service, 'lock_workspace', side_effect=AssertionError('writer gate')), \
             patch.object(service, 'scoped_source', wraps=service.scoped_source) as source:
            self.observe()
            self.assertFalse(source.call_args.kwargs['lock'])

    def test_select_only_and_detached(self):
        from django.test.utils import CaptureQueriesContext
        self.select()
        with CaptureQueriesContext(connection) as captured:
            first, second = self.observe(), self.observe()
        self.assertTrue(captured.captured_queries)
        self.assertTrue(all(q['sql'].lstrip().upper().startswith('SELECT')
                            for q in captured.captured_queries))
        with self.assertNumQueries(0):
            self.assertEqual(first, second)
            repr(first)
            self.assertEqual(first.evidence.company, 'Acme')
        with self.assertRaises(FrozenInstanceError): first.revision = 99
        with self.assertRaises(FrozenInstanceError): first.evidence.company = 'changed'

    def test_source_conflict_is_advisory(self):
        self.select()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        self.assert_parity()
        self.assertFalse(self.observe().source_eligible)
        self.assertIsNotNone(self.observe().evidence)

    def test_corruption_error_parity(self):
        self.select()
        cases = [(Decision, {'revision': 2}, 'posting_interpretation_history_invalid'),
                 (Extraction, {'payload_digest': '0' * 64}, 'posting_interpretation_evidence_invalid'),
                 (Output, {'fields': {}}, 'posting_interpretation_evidence_invalid'),
                 (RetainedMessage, {'content_digest': '0' * 64}, 'retained_source_invalid')]
        for model, changes, code in cases:
            row = model.objects.first()
            original = {name: getattr(row, name) for name in changes}
            model.objects.filter(pk=row.pk).update(**changes)
            try:
                for reader in (self.current, self.observe):
                    self.error(code, reader, 409)
            finally:
                model.objects.filter(pk=row.pk).update(**original)

    def test_bad_membership_witness_parity(self):
        row = self.select().decision
        self.move()
        Decision.objects.filter(pk=row.pk).update(membership_revision=1)
        for reader in (self.current, self.observe):
            self.error('posting_interpretation_history_invalid', reader, 409)

    def test_owner_and_identity_scope(self):
        for actor in (None, AnonymousUser(), User(username='unsaved'), self.other):
            self.error('not_found', lambda: self.observe(actor=actor), 404)
        self.error('not_found', lambda: self.observe(workspace=self.ws2), 404)
        for item_id in (True, 0, -1, '1', None, 2**63):
            self.error('not_found', lambda: self.observe(item_id=item_id), 404)


    def test_membership_history_gap_error_parity(self):
        self.select()
        self.move()
        self.move(expected_revision=1, target_item_id=self.a.pk)
        Correction.objects.filter(initial_association=self.initial, revision=1).delete()
        for reader in (self.current, self.observe):
            self.error('posting_association_history_invalid', reader, 409)
