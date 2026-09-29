"""Revision authority, historical replay and fail-closed correction chains."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from threading import Barrier
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
from postings import extraction_contract as contract
from postings import posting_source_corrections as service
from postings.models import PostingSourceCorrection as Correction, PostingSource, JobPosting
from postings.models import RetainedPostingItem as Item
from postings.tests.test_posting_sources import Fixtures as SourceFixtures
from email_sync.models import EmailAccount
from rest_framework.test import APIClient


class Fixtures(SourceFixtures):
    def setUp(self):
        super().setUp()
        self.initial = self.attach().initial_source
        self.r = self.posting()
        self.operation = uuid.uuid4()

    def correct(self, **changes):
        return service.correct_posting_source(**dict(actor=self.user, workspace=self.ws,
            item_id=self.a.pk, operation_id=self.operation, expected_revision=0,
            mode="associate", target_posting_id=self.q.pk) | changes)

    def effective(self, **changes):
        return service.read_effective_posting_source(**dict(actor=self.user, workspace=self.ws,
                                                          item_id=self.a.pk) | changes)

    def history(self, **changes):
        return service.list_posting_source_corrections(**dict(actor=self.user, workspace=self.ws,
                                                            item_id=self.a.pk) | changes)

    def snapshot(self):
        return (super().snapshot(), list(Correction.objects.order_by("pk").values()))

    def sequence(self):
        first = self.correct()
        second = self.correct(operation_id=uuid.uuid4(), expected_revision=1, mode="withdraw", target_posting_id=None)
        third = self.correct(operation_id=uuid.uuid4(), expected_revision=2, target_posting_id=self.p.pk)
        return first, second, third

    def model_row(self, **changes):
        return Correction(**dict(initial_source=self.initial, actor=self.user,
            operation_id=uuid.uuid4(), revision=1, mode="associate", target_posting=self.q) | changes)

    def foreign_posting(self):
        account = EmailAccount.objects.create(workspace=self.ws2, email="foreign@example.test")
        return self.posting(workspace=self.ws2, account=account)


class CorrectionTests(Fixtures, TestCase):
    def test_initial_zero_and_unresolved_null(self):
        current = self.effective()
        self.assertEqual((current.effective_revision, current.effective_posting.pk, current.decision_type), (0, self.p.pk, "initial"))
        unresolved = self.effective(item_id=self.b.pk)
        self.assertIsNone(unresolved.effective_revision)
        self.assertIsNone(unresolved.effective_posting)
        self.assertIsNone(self.history(item_id=self.b.pk).through_revision)
        self.error("initial_posting_source_required", lambda: self.correct(item_id=self.b.pk), 409)
        self.assertEqual(self.history().through_revision, 0)
        self.assertEqual(self.history().corrections, ())

    def test_remap_and_initial_replay_stays_historical(self):
        before_item = list(Item.objects.values())
        before_initial = list(PostingSource.objects.values())
        result = self.correct()
        self.assertEqual(result.correction.revision, 1)
        self.assertEqual(result.current.effective_posting.pk, self.q.pk)
        historical = self.attach()
        self.assertTrue(historical.replay)
        self.assertEqual(historical.posting.pk, self.p.pk)
        self.assertEqual(self.effective().effective_posting.pk, self.q.pk)
        self.assertEqual(list(Item.objects.values()), before_item)
        self.assertEqual(list(PostingSource.objects.values()), before_initial)
        self.assertTrue(Item.objects.filter(pk=self.a.pk).exists())

    def test_first_withdraw_and_restore(self):
        result = self.correct(mode="withdraw", target_posting_id=None)
        self.assertEqual(result.current.effective_revision, 1)
        self.assertIsNone(result.current.effective_posting)
        restore = self.correct(expected_revision=1, operation_id=uuid.uuid4(), target_posting_id=self.p.pk)
        self.assertEqual((restore.current.effective_revision, restore.current.effective_posting.pk), (2, self.p.pk))

    def test_multiple_corrections_and_timestamp_ignored(self):
        first, second, third = self.sequence()
        Correction.objects.filter(pk=first.correction.pk).update(created_at="2099-01-01T00:00:00Z")
        self.assertEqual(self.effective().effective_decision.pk, third.correction.pk)
        self.assertEqual([r.revision for r in self.history().corrections], [1, 2, 3])
        self.assertIsNone(second.correction.target_posting_id)

    def test_exact_replay_and_old_replay_after_later_corrections(self):
        first = self.correct()
        snapshot = self.snapshot()
        replay = self.correct(operation_id=str(self.operation))
        self.assertTrue(replay.replay)
        self.assertEqual(snapshot, self.snapshot())
        self.correct(expected_revision=1, operation_id=uuid.uuid4(), mode="withdraw", target_posting_id=None)
        replay = self.correct()
        self.assertEqual(replay.correction.pk, first.correction.pk)
        self.assertEqual(replay.correction.created_at, first.correction.created_at)
        self.assertEqual(replay.correction.actor_id, self.user.pk)
        self.assertEqual(replay.correction.target_posting_id, self.q.pk)
        self.assertEqual(replay.current.effective_revision, 2)
        self.assertIsNone(replay.current.effective_posting)

    def test_changed_payload_precedes_stale(self):
        self.correct()
        for changes in ({"mode": "withdraw", "target_posting_id": None}, {"target_posting_id": self.r.pk},
                        {"expected_revision": 1}):
            self.error("idempotency_key_reused", lambda: self.correct(**changes), 409)
        for field, value in (("METHOD", "future"), ("DECISION_VERSION", 2)):
            with patch.object(service, field, value):
                self.error("idempotency_key_reused", self.correct, 409)

    def test_same_uuid_independent_other_chain(self):
        self.correct()
        self.attach(item_id=self.b.pk, posting_id=self.q.pk)
        other = self.correct(item_id=self.b.pk, target_posting_id=self.p.pk)
        self.assertEqual(other.correction.revision, 1)
        self.assertEqual(Correction.objects.count(), 2)

    def test_independent_chains_can_select_same_target(self):
        self.attach(item_id=self.b.pk)
        self.correct()
        other = self.correct(item_id=self.b.pk)
        self.assertEqual(other.current.effective_posting.pk, self.q.pk)
        self.assertEqual(Correction.objects.count(), 2)

    def test_stale_before_noop(self):
        self.correct()
        self.error("stale_revision", lambda: self.correct(operation_id=uuid.uuid4()), 409)

    def test_noops_not_persisted_or_reserved(self):
        self.error("posting_source_unchanged", lambda: self.correct(target_posting_id=self.p.pk), 409)
        self.assertFalse(Correction.objects.filter(operation_id=self.operation).exists())
        self.correct(mode="withdraw", target_posting_id=None)
        other = uuid.uuid4()
        self.error("posting_source_unchanged", lambda: self.correct(operation_id=other,
            expected_revision=1, mode="withdraw", target_posting_id=None), 409)
        self.assertFalse(Correction.objects.filter(operation_id=other).exists())
        self.assertTrue(self.correct(mode="withdraw", target_posting_id=None).replay)
        restored = self.correct(operation_id=other, expected_revision=1, target_posting_id=self.p.pk)
        self.assertEqual(restored.correction.revision, 2)

    def test_uuid_validation(self):
        for value in (None, True, [], "bad", uuid.uuid1(), uuid.UUID(int=0), self.operation.hex, str(self.operation).upper()):
            self.error("invalid_posting_source_correction", lambda: self.correct(operation_id=value))
        self.assertEqual(self.correct(operation_id=str(self.operation)).correction.operation_id, self.operation)

    def test_revision_and_shape_validation_before_replay(self):
        self.correct()
        for value in (True, False, -1, 2**63, "0", None):
            self.error("invalid_posting_source_correction", lambda: self.correct(expected_revision=value))
        for changes in ({"mode": []}, {"mode": "restore"}, {"target_posting_id": None},
                        {"target_posting_id": True}, {"target_posting_id": "1"}, {"mode": "withdraw"}):
            self.error("invalid_posting_source_correction", lambda: self.correct(**changes))

    def test_cross_source_target_and_nonleaking_endpoints(self):
        foreign = self.foreign_posting()
        self.error("not_found", lambda: self.correct(target_posting_id=foreign.pk), 404)
        self.error("not_found", lambda: self.correct(target_posting_id=999999), 404)
        self.error("not_found", lambda: self.correct(workspace=self.ws2), 404)
        self.error("not_found", lambda: self.effective(workspace=self.ws2), 404)
        self.error("not_found", lambda: self.history(workspace=self.ws2), 404)

    def test_owner_authorization_and_transfer(self):
        first = self.correct()
        self.other.is_staff = self.other.is_superuser = True
        self.other.save()
        for actor in (None, AnonymousUser(), User(username="unsaved"), self.other):
            for call in (lambda: self.correct(actor=actor), lambda: self.effective(actor=actor),
                         lambda: self.history(actor=actor)):
                self.error("not_found", call, 404)
        Workspace.objects.filter(pk=self.ws.pk).update(owner=self.other)
        replay = self.correct(actor=self.other)
        self.assertEqual(replay.correction.actor_id, self.user.pk)
        self.assertEqual(replay.correction.created_at, first.correction.created_at)
        self.assertTrue(replay.replay)
        next_result = self.correct(actor=self.other, expected_revision=1, operation_id=uuid.uuid4(), target_posting_id=self.r.pk)
        self.assertEqual(next_result.correction.actor_id, self.other.pk)
        self.error("not_found", self.effective, 404)

    def test_ownership_gate_rechecks(self):
        original = service.lock_workspace
        def transfer(actor, workspace):
            Workspace.objects.filter(pk=workspace.pk).update(owner=self.other)
            original(actor, workspace)
        with patch.object(service, "lock_workspace", transfer):
            self.error("not_found", self.correct, 404)

    def test_source_integrity_blocks_replay_and_reads(self):
        self.correct()
        content = deepcopy(self.message.content)
        bad = deepcopy(content)
        bad["provider_received"]["source"] = "imap_internaldate"
        for changes in ({"representation_version": 2}, {"content_digest": "0" * 64},
                        {"content": bad, "content_digest": contract.digest(bad)}):
            RetainedMessage.objects.filter(pk=self.message.pk).update(**changes)
            for call in (self.correct, self.effective, self.history, lambda: self.correct(operation_id=uuid.uuid4(), expected_revision=1)):
                self.error("retained_source_invalid", call, 409)
            RetainedMessage.objects.filter(pk=self.message.pk).update(content=content,
                content_digest=contract.digest(content), representation_version=1)

    def test_sticky_conflict_replay_read_and_new_work(self):
        self.correct()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        self.assertFalse(self.correct().current.source_eligible)
        self.assertFalse(self.effective().source_eligible)
        self.assertFalse(self.history().source_eligible)
        self.error("stale_revision", lambda: self.correct(operation_id=uuid.uuid4()), 409)
        for changes in ({"mode": "withdraw", "target_posting_id": None}, {"target_posting_id": self.q.pk}, {"target_posting_id": self.r.pk}):
            self.error("retained_source_ineligible", lambda: self.correct(operation_id=uuid.uuid4(), expected_revision=1, **changes), 409)

    def test_revision_capacity_and_replay_precedence(self):
        first = self.correct()
        real = service.resolve_chain
        def boundary(*args, **kwargs):
            return replace(real(*args, **kwargs), revision=service.MAX_REVISION)
        # Reaching 2**63-1 naturally is infeasible; exercise boundary arithmetic with
        # a validated state seam. This is not evidence of a stored gigantic chain.
        with patch.object(service, "resolve_chain", boundary):
            self.assertTrue(self.correct().replay)
            self.assertFalse(self.effective().can_append_correction)
            self.error("posting_source_revision_exhausted", lambda: self.correct(
                operation_id=uuid.uuid4(), expected_revision=service.MAX_REVISION, target_posting_id=self.r.pk), 409)
        self.assertEqual(Correction.objects.count(), 1)

    def test_model_sequence_shape_uuid_and_persisted_target(self):
        for changes in ({"revision": 0}, {"revision": 2}, {"revision": True}, {"operation_id": uuid.uuid1()},
                        {"mode": "withdraw"}, {"method": "auto"}, {"decision_version": True}):
            with self.assertRaises(ValidationError):
                self.model_row(**changes).save()
        self.correct()
        for revision in (1, 3):
            with self.assertRaises(ValidationError):
                self.model_row(revision=revision, target_posting=self.r).save()
        other = self.foreign_posting()
        other.workspace_id = self.ws.pk
        other.account = self.account
        row = self.model_row(revision=2, target_posting=other)
        for call in (row.save, row.clean):
            with self.assertRaises(ValidationError):
                call()

    def test_immutability_replacement_reparent_delete(self):
        row = self.correct().correction
        for field in row._meta.fields:
            clone = Correction.objects.get(pk=row.pk)
            setattr(clone, field.attname, None)
            with self.assertRaises(ValidationError):
                clone.save(update_fields=[field.name])
        replacement = Correction(**{f.attname: getattr(row, f.attname) for f in row._meta.fields})
        with patch("postings.models.router.db_for_write", return_value="default") as routed:
            with self.assertRaises(ValidationError):
                replacement.save()
            routed.assert_called_once()
        with self.assertRaises(ValidationError):
            row.delete()

    def test_foreign_key_protection(self):
        self.sequence()
        Workspace.objects.filter(owner=self.user).update(owner=self.other)
        for obj in (self.initial, self.p, self.q, self.a, self.account, self.user):
            with self.assertRaises(ProtectedError):
                type(obj).objects.filter(pk=obj.pk).delete()

    def test_database_constraints(self):
        first, second, third = self.sequence()
        cases = [{"revision": 0}, {"revision": 1}, {"operation_id": first.correction.operation_id},
                 {"mode": "other"}, {"mode": "associate", "target_posting": None},
                 {"mode": "withdraw", "target_posting": self.q}, {"method": "auto"}, {"decision_version": 2}]
        for changes in cases:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Correction.objects.filter(pk=third.correction.pk).update(**changes)

    def test_chain_gap_fails_even_old_replay(self):
        first, second, third = self.sequence()
        Correction.objects.filter(pk=second.correction.pk).delete()
        for call in (self.effective, self.history, self.correct):
            self.error("posting_source_history_invalid", call, 409)

    def test_old_cross_source_target_detected_not_only_latest(self):
        first, second, third = self.sequence()
        other = self.foreign_posting()
        Correction.objects.filter(pk=first.correction.pk).update(target_posting=other)
        self.error("posting_source_history_invalid", self.effective, 409)
        self.error("posting_source_history_invalid", self.history, 409)
        self.error("posting_source_history_invalid", lambda: self.correct(operation_id=uuid.uuid4(),
            expected_revision=3, target_posting_id=self.q.pk), 409)

    def test_history_capture_boundary_and_cursor_validation(self):
        self.sequence()
        page1 = self.history(limit=1)
        self.correct(operation_id=uuid.uuid4(), expected_revision=3, target_posting_id=self.r.pk)
        page2 = self.history(limit=1, cursor=page1.next_cursor)
        page3 = self.history(limit=1, cursor=page2.next_cursor)
        self.assertEqual([p.corrections[0].revision for p in (page1, page2, page3)], [1, 2, 3])
        self.assertEqual(page3.through_revision, 3)
        self.assertIsNone(page3.next_cursor)
        self.assertEqual(self.history().through_revision, 4)
        for limit in (True, 0, 201, "1"):
            self.error("invalid_posting_source_correction", lambda: self.history(limit=limit))
        for cursor in ([], (1,), (True, 1, 1, 0), (self.b.pk, self.initial.pk, 3, 1),
                       (self.a.pk, self.initial.pk, 3, 4),
                       (self.a.pk, self.initial.pk, 99, 0)):
            self.error("invalid_posting_source_correction", lambda: self.history(cursor=cursor))
        zero = self.history(cursor=(self.a.pk, self.initial.pk, 0, 0))
        self.assertEqual(zero.corrections, ())
        self.assertEqual(zero.through_revision, 0)

    def test_append_between_reader_queries_keeps_captured_boundary(self):
        self.correct()
        from django.db.models.query import QuerySet
        real = QuerySet.aggregate
        appended = False
        def aggregate(rows, *args, **kwargs):
            nonlocal appended
            answer = real(rows, *args, **kwargs)
            if rows.model is Correction and not appended:
                appended = True
                self.correct(operation_id=uuid.uuid4(), expected_revision=1, target_posting_id=self.r.pk)
            return answer
        with patch.object(QuerySet, "aggregate", aggregate):
            current = self.effective()
        self.assertEqual(current.effective_revision, 1)
        self.assertEqual(current.effective_posting.pk, self.q.pk)
        self.assertEqual(self.effective().effective_revision, 2)

    def test_failure_after_insert_rolls_back(self):
        save = Correction.save
        def fail(row, *args, **kwargs):
            save(row, *args, **kwargs)
            raise RuntimeError("injected after insert")
        before = self.snapshot()
        with patch.object(Correction, "save", fail), self.assertRaises(RuntimeError):
            self.correct()
        self.assertEqual(before, self.snapshot())

    def test_no_parser_or_unrelated_writes_and_reads_pure(self):
        def snapshot():
            with connection.cursor() as cursor:
                values = {}
                for table in connection.introspection.table_names():
                    if table == Correction._meta.db_table:
                        continue
                    cursor.execute(f"SELECT * FROM {connection.ops.quote_name(table)} ORDER BY 1")
                    values[table] = cursor.fetchall()
                return values
        before = snapshot()
        with patch("postings.extraction.extract_postings", side_effect=AssertionError("parser")):
            self.correct()
            after_write = self.snapshot()
            self.effective()
            self.history()
            self.assertEqual(after_write, self.snapshot())
        self.assertEqual(before, snapshot())

    def test_admin_read_only(self):
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        row = self.correct().correction
        base = "/admin/postings/postingsourcecorrection/"
        self.assertEqual(self.client.get(base).status_code, 200)
        self.assertEqual(self.client.get(f"{base}{row.pk}/change/").status_code, 200)
        self.assertEqual(self.client.get(base + "add/").status_code, 403)
        for url in (base + "add/", f"{base}{row.pk}/change/", f"{base}{row.pk}/delete/"):
            self.assertEqual(self.client.post(url, {"_save": "Save", "post": "yes"}).status_code, 403)
        model_admin = admin.site._registry[Correction]
        request = type("Request", (), {"user": self.user, "GET": {}})()
        self.assertEqual(model_admin.get_actions(request), {})
        self.assertEqual(set(model_admin.get_readonly_fields(request)), {f.name for f in row._meta.fields})

    def test_eligibility_and_result_shape(self):
        from dataclasses import fields, FrozenInstanceError
        current = self.effective()
        self.assertTrue(current.can_append_correction)
        self.assertEqual(current.effective_decision.pk, self.initial.pk)
        self.assertEqual({f.name for f in fields(current)}, {
            "item", "initial_source", "effective_posting", "effective_revision", "decision_type",
            "effective_decision", "source_eligible", "can_append_correction"})
        self.assertFalse(self.effective(item_id=self.b.pk).can_append_correction)
        with self.assertRaises(FrozenInstanceError):
            current.effective_revision = 10
        withdrawn = self.correct(mode="withdraw", target_posting_id=None).current
        self.assertEqual(withdrawn.decision_type, "correction")
        self.assertTrue(withdrawn.can_append_correction)
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        self.assertFalse(self.effective().can_append_correction)

    def test_target_account_scope_and_different_account_allowed(self):
        account = EmailAccount.objects.create(workspace=self.ws, email="third@example.test")
        target = self.posting(account=account)
        self.assertEqual(self.correct(target_posting_id=target.pk).current.effective_posting.pk, target.pk)
        self.correct(operation_id=uuid.uuid4(), expected_revision=1, mode="withdraw", target_posting_id=None)
        EmailAccount.objects.filter(pk=account.pk).update(workspace=self.ws2)
        self.error("not_found", lambda: self.correct(target_posting_id=target.pk), 404)
        for call in (self.effective, self.history,
                     lambda: self.correct(operation_id=uuid.uuid4(), expected_revision=2)):
            self.error("posting_source_history_invalid", call, 409)

    def test_initial_scope_policy_and_source_mailbox_validation(self):
        for field, value in (("METHOD", "future"), ("DECISION_VERSION", 2)):
            with patch("postings.posting_sources." + field, value):
                for call in (self.effective, self.history, self.correct):
                    self.error("posting_source_conflict", call, 409)
        original = self.initial.posting_id
        PostingSource.objects.filter(pk=self.initial.pk).update(posting=self.foreign_posting())
        for call in (self.effective, self.history, self.correct):
            self.error("not_found", call, 404)
        PostingSource.objects.filter(pk=self.initial.pk).update(posting_id=original)
        RetainedMessage.objects.filter(pk=self.message.pk).update(provider="imap")
        for call in (self.effective, self.history, self.correct):
            self.error("not_found", call, 404)

    def test_item_and_target_bounds(self):
        for value in (True, False, 0, -1, 2**63, "1", None, 999999):
            for call in (lambda: self.correct(item_id=value), lambda: self.effective(item_id=value),
                         lambda: self.history(item_id=value)):
                self.error("not_found", call, 404)
        for value in (False, 0, -1, 2**63):
            self.error("invalid_posting_source_correction", lambda: self.correct(target_posting_id=value))

    def test_membership_independence_with_zero_outputs(self):
        self.correct()
        before = self.snapshot()
        self.correction(mode="withdraw", target_item_id=None)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.effective().effective_posting.pk, self.q.pk)
        next_result = self.correct(operation_id=uuid.uuid4(), expected_revision=1, target_posting_id=self.r.pk)
        self.assertEqual(next_result.current.effective_posting.pk, self.r.pk)
        before = self.snapshot()
        self.correction(expected_revision=1, target_item_id=self.b.pk)
        self.assertEqual(before, self.snapshot())
        self.assertIsNone(self.effective(item_id=self.b.pk).initial_source)

    def test_lifecycle_targets_and_old_posting_untouched(self):
        client = APIClient()
        client.force_authenticate(self.user)
        base = f"/api/workspaces/{self.ws.pk}/job-postings/{self.q.pk}/"
        for action, payload in (("dismiss", {}), ("save", {"saved": True})):
            self.assertEqual(client.post(base + action + "/", payload, format="json").status_code, 200)
        response = client.post(base + "apply/", {"company": "Acme", "role_label": "Engineer"},
                               format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(self.q.conversions.exists())
        before = list(JobPosting.objects.order_by("pk").values())
        result = self.correct()
        self.assertEqual(result.current.effective_posting.pk, self.q.pk)
        self.assertEqual(before, list(JobPosting.objects.order_by("pk").values()))
        self.assertEqual(client.post(base + "restore/", {}, format="json").status_code, 200)
        self.assertEqual(self.effective().effective_revision, 1)
        self.assertTrue(self.correct().replay)

    def test_model_persisted_actor_anchor_noop_and_alias(self):
        for changes in ({"actor_id": 999999, "actor": None}, {"initial_source": None},
                        {"target_posting": self.p}, {"revision": 2**63}):
            # Supply either FK object or FK ID, never let object assignment mask the ID.
            if "actor_id" in changes:
                changes.pop("actor")
                row = self.model_row()
                row.actor_id = changes["actor_id"]
            else:
                row = self.model_row(**changes)
            with self.assertRaises(ValidationError):
                row.save()
        from django.db.models.query import QuerySet
        real_exists, real_first, real_aggregate = QuerySet.exists, QuerySet.first, QuerySet.aggregate
        seen = []
        def checked(real):
            def call(rows, *args, **kwargs):
                seen.append(rows._db)
                self.assertEqual(rows._db, "default")
                return real(rows, *args, **kwargs)
            return call
        with patch.object(QuerySet, "exists", checked(real_exists)), \
             patch.object(QuerySet, "first", checked(real_first)), \
             patch.object(QuerySet, "aggregate", checked(real_aggregate)), \
             patch("postings.models.router.db_for_read", side_effect=AssertionError("read routing")):
            self.model_row().save(using="default")
        self.assertTrue(seen)

    def test_corrupt_policy_and_shape_fail_closed(self):
        if connection.vendor != "sqlite":
            self.skipTest("SQLite CHECK bypass fixture")
        first, second, third = self.sequence()
        # Simulate privileged maintenance bypassing CHECK constraints, as on SQLite.
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA ignore_check_constraints = ON")
        try:
            for changes in ({"method": "auto"}, {"decision_version": 2},
                            {"mode": "withdraw"}, {"mode": "unknown"}):
                Correction.objects.filter(pk=first.correction.pk).update(**changes)
                for call in (self.effective, self.history,
                             lambda: self.correct(operation_id=uuid.uuid4(), expected_revision=3)):
                    self.error("posting_source_history_invalid", call, 409)
                Correction.objects.filter(pk=first.correction.pk).update(
                    method="explicit_owner", decision_version=1, mode="associate")
        finally:
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA ignore_check_constraints = OFF")



class CorrectionConcurrencyTests(Fixtures, TransactionTestCase):
    def race(self, variant):
        requests = [{}, {}]
        if variant == "changed":
            requests[1] = {"target_posting_id": self.r.pk}
        elif variant == "different":
            requests[1] = {"operation_id": uuid.uuid4(), "target_posting_id": self.r.pk}
        elif variant == "withdraw":
            requests[1] = {"operation_id": uuid.uuid4(), "mode": "withdraw", "target_posting_id": None}
        expected_error = "idempotency_key_reused" if variant == "changed" else "stale_revision"
        barrier = Barrier(2)
        def attempt(changes):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.correct(**changes)
            except OperationalError:
                return None
            except APIException as exc:
                self.assertEqual(exc.get_codes(), expected_error)
                return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(attempt, requests))
        successes, conflicts = [], 0
        for changes in requests:
            try:
                successes.append(self.correct(**changes))
            except APIException as exc:
                self.assertEqual(exc.get_codes(), expected_error)
                conflicts += 1
        self.assertEqual(conflicts, int(variant != "same"))
        self.assertEqual(len({r.correction.pk for r in successes}), 1)
        self.assertEqual(Correction.objects.count(), 1)
        self.assertEqual(self.effective().effective_revision, 1)

    def test_same_operation(self):
        self.race("same")

    def test_changed_same_operation(self):
        self.race("changed")

    def test_different_operations(self):
        self.race("different")

    def test_associate_withdraw(self):
        self.race("withdraw")
