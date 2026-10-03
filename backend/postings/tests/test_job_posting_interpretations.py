"""Posting arbitration witnesses, replay, scope and isolated serialization."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from itertools import combinations
from threading import Barrier, Event
from unittest.mock import patch
import uuid

from django.apps import apps
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError, OperationalError, close_old_connections
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import APIException

from accounts.models import Workspace
from email_sync.models import RetainedMessage
from postings import job_posting_interpretations as service
from postings import retained_interpretations as interpretations, posting_source_corrections as mappings
from postings.models import (JobPostingInterpretationDecision as Decision,
    RetainedPostingInterpretationDecision as Interpretation, PostingSource,
    RetainedPostingExtractionOutput as Output, RetainedPostingItemCorrection,
    PostingSourceCorrection)
from postings.tests.test_retained_interpretations import Fixtures as ItemFixtures
from postings.tests.test_retained_extractions import fields


class Fixtures(ItemFixtures):
    def setUp(self):
        super().setUp()
        self.anchor = self.attach().initial_source
        self.item_decision = self.select().decision
        self.key = uuid.uuid4()

    def choose(self, **changes):
        return service.decide_job_posting_interpretation(**dict(actor=self.user, workspace=self.ws,
            posting_id=self.p.pk, operation_id=self.key, expected_revision=0, mode="select",
            item_id=self.a.pk, expected_interpretation_revision=1, expected_mapping_revision=0) | changes)

    def remove(self, revision=1, **changes):
        return self.choose(**dict(operation_id=uuid.uuid4(), expected_revision=revision, mode="withdraw",
            item_id=None, expected_interpretation_revision=None, expected_mapping_revision=None) | changes)

    def effective(self, **changes):
        return service.read_job_posting_interpretation(**dict(actor=self.user, workspace=self.ws,
            posting_id=self.p.pk) | changes)

    def pages(self, **changes):
        return service.list_job_posting_interpretation_decisions(**dict(actor=self.user, workspace=self.ws,
            posting_id=self.p.pk) | changes)

    def remap(self, **changes):
        return mappings.correct_posting_source(**dict(actor=self.user, workspace=self.ws,
            item_id=self.a.pk, operation_id=uuid.uuid4(), expected_revision=0,
            mode="associate", target_posting_id=self.q.pk) | changes)

    def reaffirm_item(self, **changes):
        return self.select(**dict(operation_id=uuid.uuid4(), expected_revision=1,
            output_id=self.outputs[2].pk) | changes)

    def snapshot(self):
        return tuple((m._meta.label, list(m.objects.order_by("pk").values()))
            for m in apps.get_models() if m._meta.app_label in
            {"postings", "applications", "documents", "email_sync"})

    def row(self, **changes):
        return Decision(**dict(posting=self.p, actor=self.user, operation_id=uuid.uuid4(), revision=1,
            mode="select", selected_interpretation=self.item_decision, initial_source=self.anchor,
            mapping_revision=0) | changes)

    def other_candidate(self):
        self.attach(item_id=self.b.pk)
        self.select(item_id=self.b.pk, operation_id=uuid.uuid4(), output_id=self.outputs[1].pk)
        return dict(item_id=self.b.pk, operation_id=uuid.uuid4(), expected_revision=1)

    def external_candidate(self, **changes):
        message = self.source(self.ws)
        output = self.record(operation_id=uuid.uuid4(), retained_message_id=message.pk,
                             outputs=[fields()]).outputs[0]
        item = self.decide(output).item
        self.attach(item_id=item.pk)
        self.select(item_id=item.pk, operation_id=uuid.uuid4(), output_id=output.pk)
        return message, dict(item_id=item.pk, operation_id=uuid.uuid4(), expected_revision=1) | changes


class ArbitrationTests(Fixtures, TestCase):
    def test_explicit_even_with_multiple_candidates(self):
        for posting in (self.q, self.p):
            state = self.effective(posting_id=posting.pk)
            self.assertEqual((state.revision, state.state), (0, "unresolved"))
            self.assertIsNone(state.source_eligible)
            self.assertFalse(state.can_withdraw)
            self.assertTrue(state.can_append_revision)
        candidate = self.other_candidate()
        self.assertEqual(self.effective().state, "unresolved")
        first = self.choose()
        self.assertEqual(first.current.selected_item.pk, self.a.pk)
        second = self.choose(**candidate)
        self.assertEqual(second.current.selected_item.pk, self.b.pk)
        self.assertEqual(second.current.state, "selected")
        with self.assertRaises(FrozenInstanceError):
            second.current.state = "stale"

    def test_all_stale_reason_combinations_and_old_output(self):
        self.choose()
        names = ("mapping_revision_changed", "interpretation_revision_changed", "membership_revision_changed")
        for size in range(1, 4):
            for indices in combinations(range(3), size):
                with self.subTest(indices=indices), transaction.atomic():
                    if 0 in indices:
                        self.remap()
                    if 1 in indices:
                        self.reaffirm_item()
                    if 2 in indices:
                        self.move()
                    state = self.effective()
                    self.assertEqual(state.stale_reasons, tuple(names[i] for i in indices))
                    self.assertEqual(state.selected_output.pk, self.outputs[0].pk)
                    self.assertIsNone(state.applicable_output)
                    self.assertTrue(state.can_withdraw)
                    self.assertEqual(state.state, "stale")
                    transaction.set_rollback(True)

    def test_membership_return_requires_both_reaffirmations(self):
        self.choose()
        self.move()
        self.move(expected_revision=1, target_item_id=self.a.pk)
        self.error("job_posting_interpretation_not_applicable", lambda: self.choose(
            operation_id=uuid.uuid4(), expected_revision=1), 409)
        self.reaffirm_item(output_id=self.outputs[0].pk, expected_membership_revision=2)
        self.assertEqual(self.effective().stale_reasons,
                         ("interpretation_revision_changed", "membership_revision_changed"))
        result = self.choose(operation_id=uuid.uuid4(), expected_revision=1, expected_interpretation_revision=2)
        self.assertEqual(result.current.state, "selected")
        self.assertEqual(result.current.recorded_membership_revision, 2)

    def test_mapping_away_back_reaffirmation(self):
        self.choose()
        self.remap()
        self.assertEqual(self.effective(posting_id=self.q.pk).state, "unresolved")
        self.remap(expected_revision=1, mode="withdraw", target_posting_id=None)
        self.remap(expected_revision=2, target_posting_id=self.p.pk)
        self.assertEqual(self.effective().stale_reasons, ("mapping_revision_changed",))
        result = self.choose(operation_id=uuid.uuid4(), expected_revision=1, expected_mapping_revision=3)
        self.assertEqual(result.current.state, "selected")

    def test_item_withdrawal_stale_and_new_selection_rejected(self):
        self.choose()
        self.withdraw()
        self.assertEqual(self.effective().stale_reasons, ("interpretation_revision_changed",))
        self.error("stale_interpretation_revision", lambda: self.choose(operation_id=uuid.uuid4(),
            expected_revision=1), 409)
        self.error("job_posting_interpretation_not_applicable", lambda: self.choose(operation_id=uuid.uuid4(),
            expected_revision=1, expected_interpretation_revision=2), 409)
        self.assertEqual(self.remove().current.state, "withdrawn")

    def test_replay_survives_all_changes_and_preserves_attribution(self):
        first = self.choose().decision
        self.remap()
        self.reaffirm_item()
        self.move()
        replay = self.choose()
        self.assertTrue(replay.replay)
        self.assertEqual((replay.decision.pk, replay.decision.created_at, replay.decision.actor_id),
                         (first.pk, first.created_at, self.user.pk))
        self.assertEqual(len(replay.current.stale_reasons), 3)
        self.remove()
        self.assertEqual(self.choose().current.state, "withdrawn")
        self.assertEqual(Decision.objects.count(), 2)

    def test_changed_payload_before_stale_and_owner_transfer(self):
        self.choose()
        self.error("idempotency_key_reused", lambda: self.choose(expected_revision=1), 409)
        self.error("idempotency_key_reused", lambda: self.choose(expected_mapping_revision=1), 409)
        Workspace.objects.filter(pk=self.ws.pk).update(owner=self.other)
        for call in (self.choose, self.effective, self.pages):
            self.error("not_found", call, 404)
        replay = self.choose(actor=self.other)
        self.assertEqual(replay.decision.actor_id, self.user.pk)
        self.assertEqual(self.remove(actor=self.other).decision.actor_id, self.other.pk)

    def test_noops_do_not_reserve_identity(self):
        key = uuid.uuid4()
        self.error("job_posting_interpretation_unchanged", lambda: self.remove(0, operation_id=key), 409)
        self.choose()
        self.error("job_posting_interpretation_unchanged", lambda: self.choose(operation_id=key,
            expected_revision=1), 409)
        self.assertFalse(Decision.objects.filter(operation_id=key).exists())
        state = self.remove(operation_id=key).current
        for name in ("selected_item", "selected_interpretation", "selected_output", "initial_source",
                     "recorded_mapping_revision", "current_mapping_revision", "recorded_interpretation_revision",
                     "current_interpretation_revision", "recorded_membership_revision", "current_membership_revision",
                     "source_eligible", "applicable_output"):
            self.assertIsNone(getattr(state, name))
        self.error("job_posting_interpretation_unchanged", lambda: self.remove(2), 409)

    def test_source_conflict_read_replay_and_withdraw(self):
        self.choose()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        state = self.effective()
        self.assertEqual(state.state, "selected")
        self.assertFalse(state.source_eligible)
        self.assertTrue(state.can_append_revision)
        self.assertFalse(state.can_withdraw)
        self.assertIsNone(state.applicable_output)
        self.assertTrue(self.choose().replay)
        self.assertEqual(len(self.pages().decisions), 1)
        self.error("retained_source_ineligible", self.remove, 409)

    def test_corruption_all_historical_dependencies(self):
        self.choose()
        self.remove()
        cases = [
            (RetainedMessage.objects.filter(pk=self.message.pk), {"content_digest": "bad"}, "retained_source_invalid"),
            (Output.objects.filter(pk=self.outputs[3].pk), {"fields": {"bad": "sibling"}}, "posting_interpretation_evidence_invalid"),
            (Interpretation.objects.filter(pk=self.item_decision.pk), {"revision": 2}, "posting_interpretation_history_invalid"),
            (Decision.objects.filter(revision=1), {"mapping_revision": 8}, "posting_source_history_invalid"),
            (Decision.objects.filter(revision=1), {"revision": 3}, "job_posting_interpretation_history_invalid"),
        ]
        for rows, changes, code in cases:
            with self.subTest(code=code), transaction.atomic():
                rows.update(**changes)
                for call in (self.effective, self.pages, lambda: self.remove(2)):
                    self.error(code, call, 409)
                transaction.set_rollback(True)

    def test_current_lower_history_corruption(self):
        self.choose()
        self.move()
        self.remap()
        for rows, code in ((RetainedPostingItemCorrection.objects.all(), "posting_item_correction_history_invalid"),
                           (PostingSourceCorrection.objects.all(), "posting_source_history_invalid")):
            with transaction.atomic():
                rows.update(revision=3)
                with self.assertRaises(APIException) as caught:
                    self.effective()
                self.assertEqual(caught.exception.status_code, 409)
                transaction.set_rollback(True)

    def test_scope_and_missing_exact_endpoint(self):
        for changes in ({"workspace": self.ws2}, {"posting_id": 999999}, {"item_id": 999999},
                        {"expected_interpretation_revision": 999999}):
            self.error("not_found", lambda: self.choose(**changes), 404)
        self.reaffirm_item()
        self.error("stale_interpretation_revision", self.choose, 409)

    def test_mapping_error_precedence(self):
        self.remap()
        self.error("stale_mapping_revision", self.choose, 409)
        self.error("job_posting_item_not_mapped", lambda: self.choose(expected_mapping_revision=1), 409)
        self.remap(expected_revision=1, mode="withdraw", target_posting_id=None)
        self.error("job_posting_item_not_mapped", lambda: self.choose(expected_mapping_revision=2), 409)

    def test_missing_mapping(self):
        self.select(item_id=self.b.pk, operation_id=uuid.uuid4(), output_id=self.outputs[1].pk)
        self.error("job_posting_mapping_required", lambda: self.choose(item_id=self.b.pk), 409)

    def test_bounded_inputs(self):
        for field, values in {
            "expected_revision": [True, -1, service.MAX_REVISION + 1, "0", None],
            "item_id": [True, 0, -1, service.MAX_REVISION + 1, "1"],
            "expected_interpretation_revision": [True, 0, -1, service.MAX_REVISION + 1],
            "expected_mapping_revision": [True, -1, service.MAX_REVISION + 1],
            "operation_id": [None, "bad", uuid.uuid1()], "mode": [True, "other", None],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.error("invalid_job_posting_interpretation", lambda: self.choose(**{field: value}))
        self.error("invalid_job_posting_interpretation", lambda: self.choose(mode="withdraw"))

    def test_pagination_freezes_posting_prefix(self):
        self.assertEqual(self.pages(cursor=(self.p.pk, 0, 0)).decisions, ())
        self.choose()
        self.remove()
        self.choose(operation_id=uuid.uuid4(), expected_revision=2)
        first = self.pages(limit=1)
        self.remove(3)
        page = self.pages(limit=1, cursor=first.next_cursor)
        last = self.pages(limit=1, cursor=page.next_cursor)
        self.assertEqual([first.decisions[0].revision, page.decisions[0].revision, last.decisions[0].revision], [1, 2, 3])
        self.assertIsNone(last.next_cursor)
        self.assertEqual(last.through_revision, 3)
        self.assertFalse(hasattr(last, "source_eligible"))
        self.assertEqual(self.pages(cursor=(self.p.pk, 0, 0)).decisions, ())
        Decision.objects.filter(revision=1).update(mapping_revision=9)
        self.error("posting_source_history_invalid", lambda: self.pages(cursor=(self.p.pk, 3, 2)), 409)

    def test_invalid_navigation(self):
        for limit in (True, 0, 201, "1"):
            self.error("invalid_job_posting_interpretation", lambda: self.pages(limit=limit))
        for cursor in ((True, 0, 0), (self.q.pk, 0, 0), (self.p.pk, 1, 2), (self.p.pk, 1, 0),
                       (self.p.pk, -1, 0), [self.p.pk, 0, 0], (self.p.pk, 0)):
            self.error("invalid_job_posting_interpretation", lambda: self.pages(cursor=cursor))

    def test_immutability_and_protected_references(self):
        row = self.choose().decision
        for field, value in {"revision": 2, "operation_id": uuid.uuid4(), "mode": "withdraw",
            "selected_interpretation_id": None, "initial_source_id": None, "mapping_revision": 3,
            "actor_id": self.other.pk}.items():
            row.refresh_from_db()
            setattr(row, field, value)
            with self.assertRaises(ValidationError):
                row.save()
        with self.assertRaises(ValidationError):
            self.row(pk=row.pk).save()
        with self.assertRaises(ValidationError):
            row.delete()
        self.remove()
        for obj in (self.p, self.item_decision, self.anchor, self.user):
            with self.assertRaises(ProtectedError):
                type(obj).objects.filter(pk=obj.pk).delete()

    def test_model_guard_rejects_invalid_insertions(self):
        for changes in ({"revision": 2}, {"revision": True}, {"operation_id": uuid.uuid1()},
                        {"mapping_revision": True}, {"actor_id": 999999}, {"decision_version": True},
                        {"posting": self.q}, {"method": "guess"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.row(**changes).save()
        self.choose()
        with self.assertRaises(ValidationError):
            self.row(revision=2).save()

    def test_six_database_constraints(self):
        row = self.choose().decision
        mutations = ({"revision": 0}, {"mode": "bad"}, {"mapping_revision": None},
                     {"method": "guess"}, {"decision_version": 2})
        for changes in mutations:
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                Decision.objects.filter(pk=row.pk).update(**changes)
        for changes in ({"revision": 1}, {"revision": 2, "operation_id": row.operation_id}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Decision.objects.bulk_create([self.row(**changes)])
        self.assertEqual(len(Decision._meta.constraints), 6)

    def test_admin_read_only(self):
        model_admin = admin.site._registry[Decision]
        self.assertIsNone(model_admin.actions)
        for permission in (model_admin.has_add_permission, model_admin.has_change_permission,
                           model_admin.has_delete_permission):
            self.assertFalse(permission(None))
        self.assertEqual(set(model_admin.get_readonly_fields(None)), {f.name for f in Decision._meta.fields})

    def test_only_new_authority_rows_change_and_atomic_rollback(self):
        before = self.snapshot()
        with patch.object(service, "_state", side_effect=RuntimeError("rollback")):
            with self.assertRaises(RuntimeError):
                self.choose()
        self.assertEqual(before, self.snapshot())
        self.choose()
        after = self.snapshot()
        self.assertEqual([(name, rows) for name, rows in before if name != Decision._meta.label],
                         [(name, rows) for name, rows in after if name != Decision._meta.label])

    def test_multisource_replacement_despite_old_sticky_conflict(self):
        other_source, candidate = self.external_candidate()
        first = self.choose().decision
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        self.error("retained_source_ineligible", self.remove, 409)
        result = self.choose(**candidate)
        self.assertEqual(result.current.selected_item.retained_message_id, other_source.pk)
        self.assertTrue(result.current.source_eligible)
        self.assertTrue(self.choose().replay)
        self.assertEqual(self.choose().decision.pk, first.pk)
        self.assertEqual(self.remove(2).current.state, "withdrawn")

    def test_old_and_current_source_corruption_block_replacement(self):
        other_source, candidate = self.external_candidate()
        self.choose()
        for source in (self.message, other_source):
            with self.subTest(source=source.pk), transaction.atomic():
                RetainedMessage.objects.filter(pk=source.pk).update(content_digest="corrupt")
                self.error("retained_source_invalid", lambda: self.choose(**candidate), 409)
                transaction.set_rollback(True)
        self.choose(**candidate)
        RetainedMessage.objects.filter(pk=self.message.pk).update(content_digest="corrupt")
        for call in (self.effective, self.pages, self.choose):
            self.error("retained_source_invalid", call, 409)

    def test_sorted_complete_source_locks_and_reader_gate(self):
        other_source, candidate = self.external_candidate()
        self.choose(**(candidate | {"expected_revision": 0}))
        events = []
        real_gate, real_source = service.lock_workspace, service.scoped_source
        def gate(*args):
            self.assertTrue(connection.in_atomic_block)
            events.append("gate")
            return real_gate(*args)
        def source(workspace, source_id, **kwargs):
            self.assertTrue(connection.in_atomic_block)
            self.assertEqual(kwargs, {"lock": True})
            events.append(source_id)
            return real_source(workspace, source_id, **kwargs)
        with patch.object(service, "lock_workspace", gate), patch.object(service, "scoped_source", source):
            self.choose(operation_id=uuid.uuid4(), expected_revision=1)
            self.assertEqual(events, ["gate"] + sorted([self.message.pk, other_source.pk]))
            for call in (self.effective, self.pages, self.choose):
                events.clear()
                if call == self.choose:
                    # Original UUID was not used in the second selection above.
                    call = lambda: self.choose(operation_id=uuid.uuid4(), expected_revision=2,
                                               item_id=candidate["item_id"])
                call()
                self.assertEqual(events, ["gate"] + sorted([self.message.pk, other_source.pk]))

    def test_discovery_includes_mapping_anchor_even_when_invalid(self):
        other_source, candidate = self.external_candidate()
        self.choose()
        wrong = PostingSource.objects.get(item_id=candidate["item_id"])
        Decision.objects.all().update(initial_source=wrong)
        seen = []
        real = service.scoped_source
        def source(ws, source_id, **kwargs):
            seen.append(source_id)
            return real(ws, source_id, **kwargs)
        with patch.object(service, "scoped_source", source):
            self.error("job_posting_interpretation_history_invalid", self.effective, 409)
        self.assertEqual(seen, sorted([self.message.pk, other_source.pk]))

    def test_historical_membership_remains_visible_after_item_withdrawal(self):
        self.choose()
        self.withdraw()
        self.move()
        self.assertEqual(self.effective().stale_reasons,
                         ("interpretation_revision_changed", "membership_revision_changed"))

    def test_each_lower_change_replay_is_original_not_reselection(self):
        original = self.choose().decision
        for mutate in (self.remap, self.reaffirm_item, self.move):
            with transaction.atomic():
                mutate()
                replay = self.choose()
                self.assertTrue(replay.replay)
                self.assertEqual(replay.decision.pk, original.pk)
                self.assertEqual(replay.decision.selected_interpretation_id, self.item_decision.pk)
                self.assertEqual(replay.decision.mapping_revision, 0)
                self.assertEqual(Decision.objects.count(), 1)
                self.assertEqual(replay.current.state, "stale")
                transaction.set_rollback(True)

    def test_new_interpretation_requires_explicit_posting_reselection(self):
        self.choose()
        new = self.reaffirm_item().decision
        self.assertEqual(self.effective().selected_interpretation.pk, self.item_decision.pk)
        result = self.choose(operation_id=uuid.uuid4(), expected_revision=1, expected_interpretation_revision=2)
        self.assertEqual(result.current.selected_interpretation.pk, new.pk)
        self.assertEqual(result.current.applicable_output.pk, self.outputs[2].pk)

    def test_long_null_blank_retained_fields_unchanged(self):
        value = fields("x" * 4096)
        output = self.record(operation_id=uuid.uuid4(), outputs=[value]).outputs[0]
        self.decide(output, mode="attach_existing", item_id=self.a.pk)
        self.reaffirm_item(output_id=output.pk)
        before = self.snapshot()
        with patch("postings.extraction.extract_postings", side_effect=AssertionError("parser called")):
            result = self.choose(expected_interpretation_revision=2)
            self.effective()
            self.pages()
            self.remove()
        self.assertEqual(result.current.applicable_output.fields, value)
        self.assertNotIn("posting_url", result.current.applicable_output.fields)
        self.assertEqual([(name, rows) for name, rows in before if name != Decision._meta.label],
                         [(name, rows) for name, rows in self.snapshot() if name != Decision._meta.label])

    def test_revision_capacity_advisories_noop_and_replay(self):
        self.choose()
        latest = self.effective().latest_decision
        other = self.other_candidate() | {"expected_revision": service.MAX_REVISION}
        # Stub only the validated posting prefix at its numeric boundary; lower
        # witness validation and all subsequent command ordering remain real.
        with patch.object(service, "resolve_chain", return_value=service.Chain(service.MAX_REVISION, latest)):
            state = self.effective()
            self.assertFalse(state.can_append_revision)
            self.assertFalse(state.can_withdraw)
            self.assertTrue(self.choose().replay)
            self.error("job_posting_interpretation_unchanged", lambda: self.choose(
                operation_id=uuid.uuid4(), expected_revision=service.MAX_REVISION), 409)
            self.error("job_posting_interpretation_revision_exhausted", lambda: self.choose(**other), 409)
            self.error("job_posting_interpretation_revision_exhausted",
                       lambda: self.remove(service.MAX_REVISION), 409)

    def test_foreign_source_and_posting_account_scope(self):
        foreign = self.source(self.ws2)
        from postings.models import RetainedPostingItem
        item = RetainedPostingItem.objects.create(retained_message=foreign)
        self.error("not_found", lambda: self.choose(item_id=item.pk), 404)
        from email_sync.models import EmailAccount
        account = EmailAccount.objects.create(workspace=self.ws2, email="foreign@example.test")
        type(self.p).objects.filter(pk=self.p.pk).update(account=account)
        for call in (self.choose, self.effective, self.pages):
            self.error("not_found", call, 404)

    def test_stale_posting_precedes_ineligible_new_work(self):
        self.choose()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        self.error("stale_revision", lambda: self.choose(operation_id=uuid.uuid4()), 409)

    def test_current_conflict_and_stale_reasons_remain_separate(self):
        self.choose()
        self.move()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        state = self.effective()
        self.assertEqual((state.state, state.stale_reasons), ("stale", ("membership_revision_changed",)))
        self.assertFalse(state.source_eligible)
        self.assertIsNone(state.applicable_output)

    def test_historical_mapping_target_and_item_mismatch_fail_closed(self):
        self.choose()
        for changes in ({"posting_id": self.q.pk}, {"item_id": self.b.pk}):
            with transaction.atomic():
                PostingSource.objects.filter(pk=self.anchor.pk).update(**changes)
                self.error("job_posting_interpretation_history_invalid", self.effective, 409)
                transaction.set_rollback(True)

    def test_all_existing_tables_preserved_across_commands_and_readers(self):
        def snapshot():
            result = {}
            with connection.cursor() as cursor:
                for table in connection.introspection.table_names():
                    if table != Decision._meta.db_table:
                        cursor.execute(f"SELECT * FROM {connection.ops.quote_name(table)} ORDER BY 1")
                        result[table] = cursor.fetchall()
            return result
        before = snapshot()
        with patch("postings.extraction.extract_postings", side_effect=AssertionError("parser")):
            self.choose()
            self.choose()
            self.effective()
            self.pages()
            self.remove()
        self.assertEqual(before, snapshot())

    def test_error_precedence_for_tampered_replay_payload(self):
        self.choose()
        Decision.objects.all().update(mapping_revision=8)
        self.error("idempotency_key_reused", self.choose, 409)
        self.error("posting_source_history_invalid", self.effective, 409)
        Decision.objects.all().update(mapping_revision=0)
        Interpretation.objects.filter(pk=self.item_decision.pk).update(revision=2)
        self.error("not_found", self.choose, 404)
        self.error("posting_interpretation_history_invalid", self.effective, 409)


class ArbitrationConcurrencyTests(Fixtures, TransactionTestCase):
    def race(self, calls):
        barrier = Barrier(len(calls))
        def run(call):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return call()
                except (OperationalError, APIException) as exc:
                    return exc
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            results = list(pool.map(run, calls))
        # SQLite busy failures are explicitly retried by this caller, never service code.
        for i, result in enumerate(results):
            if isinstance(result, OperationalError):
                try:
                    results[i] = calls[i]()
                except APIException as exc:
                    results[i] = exc
        return results

    def test_same_uuid_race(self):
        results = self.race([self.choose, self.choose])
        self.assertEqual(Decision.objects.count(), 1)
        self.assertEqual(sorted(result.replay for result in results), [False, True])

    def test_same_revision_race(self):
        results = self.race([self.choose, lambda: self.choose(operation_id=uuid.uuid4())])
        self.assertEqual(Decision.objects.count(), 1)
        self.assertEqual(sum(isinstance(r, APIException) for r in results), 1)

    def test_changed_uuid_payload_race(self):
        other = self.other_candidate() | {"operation_id": self.key, "expected_revision": 0}
        results = self.race([self.choose, lambda: self.choose(**other)])
        errors = [r for r in results if isinstance(r, APIException)]
        self.assertEqual([e.get_codes() for e in errors], ["idempotency_key_reused"])
        self.assertEqual(Decision.objects.count(), 1)

    def lower_race(self, competitor, reason):
        results = self.race([self.choose, competitor])
        self.assertFalse(isinstance(results[1], APIException))
        if Decision.objects.exists():
            self.assertEqual(self.effective().stale_reasons, (reason,))
        else:
            self.assertIsInstance(results[0], APIException)
            self.assertEqual(self.effective().state, "unresolved")

    def test_mapping_race_with_authority(self):
        self.lower_race(self.remap, "mapping_revision_changed")

    def test_interpretation_race_with_authority(self):
        self.lower_race(self.reaffirm_item, "interpretation_revision_changed")

    def test_membership_race_with_authority(self):
        self.lower_race(self.move, "membership_revision_changed")

    def test_replacements_from_different_sources(self):
        source_a, candidate_a = self.external_candidate()
        source_b, candidate_b = self.external_candidate()
        self.choose()
        results = self.race([lambda: self.choose(**candidate_a), lambda: self.choose(**candidate_b)])
        self.assertEqual(Decision.objects.count(), 2)
        self.assertEqual(sum(isinstance(r, APIException) for r in results), 1)
        self.assertIn(self.effective().selected_item.retained_message_id, {source_a.pk, source_b.pk})

    def coherent_reader(self, history=False):
        self.choose()
        entered, release = Event(), Event()
        real = service.resolve_chain
        def pause(deps, through):
            result = real(deps, through)
            entered.set()
            if not release.wait(timeout=10):
                raise AssertionError("reader release timeout")
            return result
        def read():
            close_old_connections()
            try:
                return self.pages() if history else self.effective()
            finally:
                close_old_connections()
        with patch.object(service, "resolve_chain", pause), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(read)
            try:
                self.assertTrue(entered.wait(timeout=10))
                # The SQLite gate must refuse this competing write while the
                # coherent reader still owns its serialization transaction.
                with self.assertRaises(OperationalError):
                    self.move()
            finally:
                release.set()
            state = future.result(timeout=10)
        if history:
            self.assertEqual(state.through_revision, 1)
        else:
            self.assertEqual(state.state, "selected")
            self.assertEqual(state.current_membership_revision, 0)
        self.move()  # Explicit caller retry after reader transaction completed.
        self.assertEqual(self.effective().state, "stale")

    def test_effective_read_serializes_competing_membership(self):
        self.coherent_reader()

    def test_history_read_serializes_competing_membership(self):
        self.coherent_reader(history=True)
