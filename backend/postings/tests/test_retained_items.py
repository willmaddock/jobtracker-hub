"""Explicit initial assertions: identity, replay, isolation and no inferred effects."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from unittest.mock import patch
import uuid

from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import APIException

from accounts.models import User, Workspace
from email_sync.models import RetainedMessage
from postings import extraction_contract as contract
from postings.models import RetainedPostingItem as Item, RetainedPostingItemAssociation as Association
from postings.retained_items import (associate_posting_output, read_posting_output_association,
                                    read_posting_item, list_posting_item_associations)
from postings.tests.test_retained_extractions import Fixtures as ExtractionFixtures, fields


class Fixtures(ExtractionFixtures):
    def setUp(self):
        super().setUp()
        self.outputs = self.record(outputs=[fields("A"), fields("B"), fields("C"), fields("D")]).outputs

    def decide(self, output=None, **changes):
        return associate_posting_output(**{"actor": self.user, "workspace": self.ws,
            "output_id": (output or self.outputs[0]).pk, "mode": "allocate_new", **changes})

    def inspect(self, output=None, **changes):
        return read_posting_output_association(**{"actor": self.user, "workspace": self.ws,
            "output_id": (output or self.outputs[0]).pk, **changes})

    def history(self, item, **changes):
        return list_posting_item_associations(**{"actor": self.user, "workspace": self.ws,
                                                 "item_id": item.pk, **changes})

    def snapshot(self):
        return (list(Item.objects.order_by("pk").values()), list(Association.objects.order_by("pk").values()))


class RetainedItemTests(Fixtures, TestCase):
    def test_allocate_and_lost_response_replay(self):
        first = self.decide()
        before = self.snapshot()
        replay = self.decide()
        self.assertFalse(first.replay)
        self.assertTrue(replay.replay)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(first.item.pk, replay.item.pk)
        self.assertEqual(first.item.portable_id, replay.item.portable_id)
        self.assertEqual(first.item.created_at, replay.item.created_at)
        self.assertEqual(first.association.pk, replay.association.pk)
        self.assertEqual(first.association.created_at, replay.association.created_at)
        self.assertEqual(first.association.actor_id, self.user.pk)
        self.assertEqual((Item.objects.count(), Association.objects.count()), (1, 1))

    def test_attachment_replay_and_many_outputs_operations(self):
        item = self.decide().item
        attached = self.decide(self.outputs[1], mode="attach_existing", item_id=item.pk)
        self.assertTrue(self.decide(self.outputs[1], mode="attach_existing", item_id=item.pk).replay)
        later = self.record(operation_id=uuid.uuid4()).outputs[0]
        self.decide(later, mode="attach_existing", item_id=item.pk)
        self.assertEqual(item.associations.count(), 3)
        self.assertEqual(Item.objects.count(), 1)
        self.assertEqual(attached.association.actor_id, self.user.pk)

    def test_different_current_owner_replays_original_actor(self):
        allocated = self.decide()
        attached = self.decide(self.outputs[1], mode="attach_existing", item_id=allocated.item.pk)
        self.error("not_found", lambda: self.decide(actor=self.other), 404)
        Workspace.objects.filter(pk=self.ws.pk).update(owner=self.other)
        # Deliberately retain stale self.ws.owner; helpers must use database ownership.
        for output, mode, target, original in (
            (self.outputs[0], "allocate_new", None, allocated),
            (self.outputs[1], "attach_existing", allocated.item.pk, attached),
        ):
            replay = self.decide(output, actor=self.other, mode=mode, item_id=target)
            self.assertTrue(replay.replay)
            self.assertEqual(replay.association.pk, original.association.pk)
            self.assertEqual(replay.association.actor_id, self.user.pk)
            self.assertEqual(replay.association.created_at, original.association.created_at)
        self.error("not_found", lambda: self.decide(), 404)

    def test_all_changed_mode_target_conflicts(self):
        a = self.decide().item
        b = self.decide(self.outputs[1]).item
        self.decide(self.outputs[2], mode="attach_existing", item_id=a.pk)
        cases = [(self.outputs[0], "attach_existing", a.pk), (self.outputs[0], "attach_existing", b.pk),
                 (self.outputs[2], "allocate_new", None), (self.outputs[2], "attach_existing", b.pk)]
        for output, mode, target in cases:
            self.error("posting_item_association_conflict",
                       lambda: self.decide(output, mode=mode, item_id=target), 409)

    def test_replay_compares_method_and_version(self):
        original = self.decide()
        # Simulate a future supported contract without weakening current DB checks.
        for field, value in (("METHOD", "future_method"), ("DECISION_VERSION", 2)):
            with patch("postings.retained_items." + field, value):
                self.error("posting_item_association_conflict", self.decide, 409)
        self.assertEqual(original.association.actor_id, self.user.pk)

    def test_unresolved_reorder_similarity_disappearance_reappearance(self):
        a = self.decide().item
        b = self.decide(self.outputs[1]).item
        before = self.snapshot()
        reordered = self.record(operation_id=uuid.uuid4(), outputs=[fields("B"), fields("A")]).outputs
        self.record(operation_id=uuid.uuid4(), outputs=[])
        reappeared = self.record(operation_id=uuid.uuid4(), outputs=[fields("A")]).outputs[0]
        for output in (*reordered, reappeared, self.outputs[2]):
            observed = self.inspect(output)
            self.assertIsNone(observed.association)
            self.assertIsNone(observed.item)
        self.assertEqual(before, self.snapshot())
        self.decide(reordered[0], mode="attach_existing", item_id=b.pk)
        self.decide(reordered[1], mode="attach_existing", item_id=a.pk)
        self.assertEqual(Item.objects.count(), 2)

    def test_cross_source_and_workspace(self):
        item = self.decide().item
        same_ws_source = self.source(self.ws)
        same_ws_output = self.record(operation_id=uuid.uuid4(), retained_message_id=same_ws_source.pk).outputs[0]
        foreign_source = self.source(self.ws2)
        foreign_output = self.record(workspace=self.ws2, operation_id=uuid.uuid4(),
                                     retained_message_id=foreign_source.pk).outputs[0]
        self.error("not_found", lambda: self.decide(same_ws_output, mode="attach_existing", item_id=item.pk), 404)
        self.error("not_found", lambda: self.decide(foreign_output), 404)
        self.error("not_found", lambda: self.inspect(foreign_output), 404)
        self.error("not_found", lambda: self.history(item, workspace=self.ws2), 404)
        foreign_item = self.decide(foreign_output, workspace=self.ws2).item
        self.error("not_found", lambda: self.decide(self.outputs[1], mode="attach_existing", item_id=foreign_item.pk), 404)

    def test_authentication_persisted_actor_and_superuser_no_bypass(self):
        self.other.is_superuser = self.other.is_staff = True
        self.other.save()
        deleted = User.objects.create(username="deleted")
        deleted.delete()
        for actor in (None, AnonymousUser(), User(username="unsaved"), deleted, self.other):
            self.error("not_found", lambda: self.decide(actor=actor), 404)
            self.error("not_found", lambda: self.inspect(actor=actor), 404)

    def test_ownership_revalidated_inside_gate(self):
        from postings.retained_items import lock_workspace
        def changed_owner(actor, workspace):
            Workspace.objects.filter(pk=workspace.pk).update(owner=self.other)
            lock_workspace(actor, workspace)
        with patch("postings.retained_items.lock_workspace", changed_owner):
            self.error("not_found", self.decide, 404)

    def test_malformed_ids_and_decision_shapes(self):
        for value in (True, False, None, 0, -1, "1", [], 2**63, 999999):
            self.error("not_found", lambda: self.decide(output_id=value), 404)
        for value in (True, 0, -1, "1", [], 2**63, 999999):
            self.error("not_found", lambda: self.decide(mode="attach_existing", item_id=value), 404)
        for changes in ({"mode": None}, {"mode": []}, {"mode": "auto"}, {"mode": "attach_existing"},
                        {"item_id": 1}, {"item_id": False}):
            self.error("invalid_posting_item_association", lambda: self.decide(**changes))

    def test_sticky_conflict_preserves_replay_and_read_blocks_new_work(self):
        item = self.decide().item
        self.decide(self.outputs[1], mode="attach_existing", item_id=item.pk)
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        self.assertFalse(self.decide().source_eligible)
        self.assertTrue(self.decide(self.outputs[1], mode="attach_existing", item_id=item.pk).replay)
        self.assertFalse(self.inspect().source_eligible)
        self.assertFalse(self.history(item).source_eligible)
        self.assertFalse(read_posting_item(actor=self.user, workspace=self.ws, item_id=item.pk).source_eligible)
        for changes in ({}, {"mode": "attach_existing", "item_id": item.pk}):
            self.error("retained_source_ineligible", lambda: self.decide(self.outputs[2], **changes), 409)
        self.error("posting_item_association_conflict", lambda: self.decide(item_id=item.pk, mode="attach_existing"), 409)

    def test_integrity_failure_blocks_new_and_replay_including_matching_digest(self):
        item = self.decide().item
        original = deepcopy(self.message.content)
        malformed = deepcopy(original)
        malformed["provider_received"]["source"] = "graph_received_datetime"
        cases = [{"representation_version": 2}, {"content_digest": "0" * 64},
                 {"content": malformed, "content_digest": contract.digest(malformed)}]
        for changes in cases:
            RetainedMessage.objects.filter(pk=self.message.pk).update(**changes)
            for call in (self.decide, self.inspect, lambda: self.decide(self.outputs[1]), lambda: self.history(item)):
                self.error("retained_source_invalid", call, 409)
            self.message.refresh_from_db()
            self.assertEqual({k: getattr(self.message, k) for k in changes}, changes)
            RetainedMessage.objects.filter(pk=self.message.pk).update(content=original,
                content_digest=contract.digest(original), representation_version=1)

    def test_corrupt_existing_association_endpoint_fails_closed(self):
        original = self.decide()
        source = self.source(self.ws)
        output = self.record(operation_id=uuid.uuid4(), retained_message_id=source.pk).outputs[0]
        other = self.decide(output)
        Association.objects.filter(pk=original.association.pk).update(item=other.item)
        self.error("not_found", self.decide, 404)
        self.error("not_found", self.inspect, 404)
        self.error("not_found", lambda: self.history(other.item), 404)

    def test_finite_database_checks(self):
        result = self.decide()
        for updates in ({"mode": "auto"}, {"method": "system"}, {"decision_version": 2}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Association.objects.filter(pk=result.association.pk).update(**updates)
        for updates in ({"mode": "auto"}, {"method": "system"}, {"decision_version": True}):
            with self.assertRaises(ValidationError):
                Association.objects.create(item=result.item, output=self.outputs[1], actor=self.user,
                                           **{"mode": "attach_existing", **updates})

    def test_database_output_unique_and_item_uuid_scope(self):
        result = self.decide()
        other = self.decide(self.outputs[1])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Association.objects.filter(pk=other.association.pk).update(output=result.output)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Item.objects.filter(pk=other.item.pk).update(portable_id=result.item.portable_id)
        source = self.source(self.ws)
        # Privileged fixture allocation demonstrates the namespace, not a domain path.
        foreign = Item.objects.create(retained_message=source, portable_id=result.item.portable_id)
        self.assertNotEqual(foreign.pk, result.item.pk)

    def test_model_cross_source_guard_uses_persisted_endpoints(self):
        item = self.decide().item
        source = self.source(self.ws)
        output = self.record(operation_id=uuid.uuid4(), retained_message_id=source.pk).outputs[0]
        item.retained_message_id = source.pk  # A cached fabricated endpoint must not fool validation.
        row = Association(item=item, output=output, actor=self.user, mode="attach_existing")
        for call in (row.save, row.clean):
            with self.assertRaises(ValidationError):
                call()

    def test_every_field_immutable_replacement_routed_reparent_and_delete(self):
        result = self.decide()
        for obj in (result.item, result.association):
            for field in obj._meta.fields:
                clone = type(obj).objects.get(pk=obj.pk)
                setattr(clone, field.attname, None)
                with self.assertRaises(ValidationError):
                    clone.save(update_fields=[field.name])
            replacement = type(obj)(**{f.attname: getattr(obj, f.attname) for f in obj._meta.fields})
            with patch("postings.models.router.db_for_write", return_value="default") as routed:
                with self.assertRaises(ValidationError):
                    replacement.save()
                routed.assert_called_once()
            with self.assertRaises(ValidationError):
                obj.delete()

    def test_protected_source_item_output_actor(self):
        result = self.decide()
        # Transfer only in fixture so actor protection is independently visible.
        Workspace.objects.filter(owner=self.user).update(owner=self.other)
        for obj in (self.message, result.item, result.output, self.user):
            with self.assertRaises(ProtectedError):
                type(obj).objects.filter(pk=obj.pk).delete()

    def test_failures_after_item_and_during_association_leave_no_orphan(self):
        real = Association.save
        def insert_then_fail(obj, *args, **kwargs):
            real(obj, *args, **kwargs)
            raise RuntimeError("after insert")
        for failure in (RuntimeError("before association"), insert_then_fail):
            before = self.snapshot()
            with patch.object(Association, "save", side_effect=failure) if isinstance(failure, Exception) else patch.object(Association, "save", failure):
                with self.assertRaises(RuntimeError):
                    self.decide()
            self.assertEqual(before, self.snapshot())

    def test_bounded_stable_history_and_cursor_validation(self):
        item = self.decide().item
        for output in self.outputs[1:]:
            self.decide(output, mode="attach_existing", item_id=item.pk)
        first = item.associations.order_by("pk").first()
        # Equal timestamps exercise the required deterministic ID tie-breaker.
        item.associations.update(created_at=first.created_at)
        page1 = self.history(item, limit=2)
        page2 = self.history(item, limit=2, cursor=page1.next_cursor)
        ids = [a.pk for a in page1.associations + page2.associations]
        self.assertEqual(ids, list(item.associations.order_by("pk").values_list("pk", flat=True)))
        self.assertIsNone(page2.next_cursor)
        for limit in (True, 0, -1, 201, "2"):
            self.error("invalid_posting_item_association", lambda: self.history(item, limit=limit))
        for cursor in ([], ("bad", 1), (first.created_at.isoformat(), True), (first.created_at.isoformat(), 99999)):
            self.error("invalid_posting_item_association", lambda: self.history(item, cursor=cursor))

    def test_reader_no_parser_no_unrelated_writes(self):
        def snapshot():
            tables = set(connection.introspection.table_names()) - {Item._meta.db_table, Association._meta.db_table}
            with connection.cursor() as cursor:
                result = {}
                for table in tables:
                    cursor.execute(f"SELECT * FROM {connection.ops.quote_name(table)} ORDER BY 1")
                    result[table] = cursor.fetchall()
                return result
        before = snapshot()
        with patch("postings.extraction.extract_postings", side_effect=AssertionError("parser executed")):
            result = self.decide()
            self.inspect()
            self.history(result.item)
            read_posting_item(actor=self.user, workspace=self.ws, item_id=result.item.pk)
        self.assertEqual(before, snapshot())

    def test_admin_read_only(self):
        self.user.is_superuser = self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        result = self.decide()
        for obj in (result.item, result.association):
            base = f"/admin/postings/{obj._meta.model_name}/"
            self.assertEqual(self.client.get(base).status_code, 200)
            self.assertEqual(self.client.get(f"{base}{obj.pk}/change/").status_code, 200)
            self.assertEqual(self.client.get(base + "add/").status_code, 403)
            for url in (base + "add/", f"{base}{obj.pk}/change/", f"{base}{obj.pk}/delete/"):
                self.assertEqual(self.client.post(url, {"_save": "Save", "post": "yes"}).status_code, 403)
            model_admin = admin.site._registry[type(obj)]
            request = type("Request", (), {"user": self.user, "GET": {}})()
            self.assertEqual(model_admin.get_actions(request), {})
            self.assertEqual(set(model_admin.get_readonly_fields(request)), {f.name for f in obj._meta.fields})


class RetainedItemConcurrencyTests(Fixtures, TransactionTestCase):
    def race(self, modes):
        a = self.decide(self.outputs[1]).item
        b = self.decide(self.outputs[2]).item
        choices = {"allocate": {"mode": "allocate_new"},
                   "a": {"mode": "attach_existing", "item_id": a.pk},
                   "b": {"mode": "attach_existing", "item_id": b.pk}}
        barrier = Barrier(2)
        def attempt(mode):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.decide(**choices[mode])
            except OperationalError:
                return None
            except APIException as exc:
                self.assertEqual(exc.get_codes(), "posting_item_association_conflict")
                return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(attempt, modes))
        successes, conflicts = [], 0
        for mode in modes:
            try:
                successes.append(self.decide(**choices[mode]))
            except APIException as exc:
                self.assertEqual(exc.get_codes(), "posting_item_association_conflict")
                conflicts += 1
        self.assertEqual(conflicts, int(modes[0] != modes[1]))
        self.assertEqual(len({r.association.pk for r in successes}), 1)
        winner = Association.objects.get(output=self.outputs[0])
        self.assertEqual(Item.objects.count(), 2 + int(winner.mode == "allocate_new"))
        self.assertEqual(Association.objects.count(), 3)
        self.assertFalse(Item.objects.filter(associations__isnull=True).exists())

    def test_allocate_allocate(self):
        self.race(("allocate", "allocate"))

    def test_allocate_attach(self):
        self.race(("allocate", "a"))

    def test_attach_same(self):
        self.race(("a", "a"))

    def test_attach_different(self):
        self.race(("a", "b"))
