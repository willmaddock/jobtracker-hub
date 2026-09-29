"""Initial mapping authority: persisted replay, isolation and no derived effects."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import fields
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
from rest_framework.test import APIClient

from accounts.models import User, Workspace
from email_sync.models import EmailAccount, RetainedMessage, MailboxLineage
from postings import posting_sources as service, extraction_contract as contract
from postings.models import JobPosting, PostingSource, RetainedPostingItem as Item
from postings.retained_item_corrections import correct_posting_item_association
from postings.tests.test_retained_items import Fixtures as ItemFixtures


class Fixtures(ItemFixtures):
    def setUp(self):
        super().setUp()
        self.a = self.decide().item
        self.b = self.decide(self.outputs[1]).item
        self.account = EmailAccount.objects.create(workspace=self.ws, email="different@example.test")
        self.p = self.posting()
        self.q = self.posting()

    def posting(self, **changes):
        return JobPosting.objects.create(**dict(workspace=self.ws, account=self.account,
            message_id="transitional", dedupe_key=uuid.uuid4().hex, title="Engineer", company="Acme",
            location="Remote", salary="100", employment_type="Full time", posting_url="https://example.test/job") | changes)

    def attach(self, **changes):
        return service.attach_posting_source(**dict(actor=self.user, workspace=self.ws,
            item_id=self.a.pk, posting_id=self.p.pk) | changes)

    def read(self, **changes):
        return service.read_initial_posting_source(**dict(actor=self.user, workspace=self.ws,
            item_id=self.a.pk) | changes)

    def listing(self, **changes):
        return service.list_initial_posting_sources(**dict(actor=self.user, workspace=self.ws,
            posting_id=self.p.pk) | changes)

    def correction(self, **changes):
        return correct_posting_item_association(**dict(actor=self.user, workspace=self.ws,
            output_id=self.outputs[0].pk, operation_id=uuid.uuid4(), expected_revision=0,
            mode="associate", target_item_id=self.b.pk) | changes)

    def snapshot(self):
        return list(PostingSource.objects.order_by("pk").values())

    def model_row(self, **changes):
        return PostingSource(**dict(item=self.a, posting=self.p, actor=self.user) | changes)


class PostingSourceTests(Fixtures, TestCase):
    def test_attach_replay_and_changed_target(self):
        first = self.attach()
        before = self.snapshot()
        again = self.attach()
        self.assertFalse(first.replay)
        self.assertTrue(again.replay)
        self.assertEqual(first.initial_source.pk, again.initial_source.pk)
        self.assertEqual(first.initial_source.actor_id, self.user.pk)
        self.assertEqual(first.initial_source.created_at, again.initial_source.created_at)
        self.assertEqual(before, self.snapshot())
        self.error("posting_source_conflict", lambda: self.attach(posting_id=self.q.pk), 409)
        self.assertEqual(before, self.snapshot())

    def test_many_items_same_posting(self):
        self.attach()
        self.attach(item_id=self.b.pk)
        self.assertEqual(PostingSource.objects.filter(posting=self.p).count(), 2)

    def test_read_optional_initial_only(self):
        empty = self.read()
        self.assertIsNone(empty.initial_source)
        self.assertIsNone(empty.posting)
        row = self.attach().initial_source
        self.assertEqual(self.read().initial_source.pk, row.pk)
        self.assertEqual({f.name for f in fields(self.read())},
            {"item", "initial_source", "posting", "source_eligible", "replay"})

    def test_owner_and_later_owner_attribution(self):
        first = self.attach()
        self.other.is_staff = self.other.is_superuser = True
        self.other.save()
        for actor in (None, AnonymousUser(), User(username="unsaved"), self.other):
            for call in (lambda: self.attach(actor=actor), lambda: self.read(actor=actor), lambda: self.listing(actor=actor)):
                self.error("not_found", call, 404)
        Workspace.objects.filter(pk=self.ws.pk).update(owner=self.other)
        replay = self.attach(actor=self.other)
        self.assertTrue(replay.replay)
        self.assertEqual(replay.initial_source.actor_id, self.user.pk)
        self.assertEqual(replay.initial_source.created_at, first.initial_source.created_at)
        new = self.attach(actor=self.other, item_id=self.b.pk)
        self.assertEqual(new.initial_source.actor_id, self.other.pk)
        self.error("not_found", self.read, 404)

    def test_gate_rechecks_ownership(self):
        original = service.lock_workspace
        def transfer(actor, workspace):
            Workspace.objects.filter(pk=workspace.pk).update(owner=self.other)
            return original(actor, workspace)
        with patch.object(service, "lock_workspace", transfer):
            self.error("not_found", self.attach, 404)
        self.assertEqual(self.snapshot(), [])

    def test_ids_and_cross_workspace(self):
        account = EmailAccount.objects.create(workspace=self.ws2, email="other@example.test")
        foreign = self.posting(workspace=self.ws2, account=account)
        for value in (True, False, 0, -1, 2**63, "1", None, 999999):
            self.error("not_found", lambda: self.attach(item_id=value), 404)
            self.error("not_found", lambda: self.attach(posting_id=value), 404)
        self.error("not_found", lambda: self.attach(posting_id=foreign.pk), 404)
        self.error("not_found", lambda: self.attach(workspace=self.ws2), 404)
        self.error("not_found", lambda: self.read(workspace=self.ws2), 404)
        self.error("not_found", lambda: self.listing(workspace=self.ws2), 404)

    def test_posting_account_inconsistency_blocks_new_read_replay(self):
        self.attach()
        EmailAccount.objects.filter(pk=self.account.pk).update(workspace=self.ws2)
        for call in (self.attach, self.read, self.listing, lambda: self.attach(item_id=self.b.pk)):
            self.error("not_found", call, 404)

    def test_stored_foreign_target_fails_before_changed_target_conflict(self):
        self.attach()
        other_account = EmailAccount.objects.create(workspace=self.ws2, email="foreign@example.test")
        foreign = self.posting(workspace=self.ws2, account=other_account)
        PostingSource.objects.update(posting=foreign)
        self.error("not_found", self.read, 404)
        self.error("not_found", self.attach, 404)
        self.error("not_found", lambda: self.attach(posting_id=self.q.pk), 404)

    def test_stored_foreign_item_fails_list(self):
        self.attach()
        other_source = self.source(self.ws2)
        other_item = Item.objects.create(retained_message=other_source)
        PostingSource.objects.update(item=other_item)
        self.error("not_found", self.listing, 404)

    def test_source_integrity_all_surfaces(self):
        self.attach()
        content = deepcopy(self.message.content)
        bad = deepcopy(content)
        bad["provider_received"]["source"] = "imap_internaldate"
        for changes in ({"representation_version": 2}, {"content_digest": "0" * 64},
                        {"content": bad, "content_digest": contract.digest(bad)}):
            RetainedMessage.objects.filter(pk=self.message.pk).update(**changes)
            for call in (self.attach, self.read, self.listing, lambda: self.attach(item_id=self.b.pk),
                         lambda: self.attach(posting_id=self.q.pk)):
                self.error("retained_source_invalid", call, 409)
            RetainedMessage.objects.filter(pk=self.message.pk).update(content=content,
                content_digest=contract.digest(content), representation_version=1)

    def test_replay_policy_is_part_of_assertion_identity(self):
        self.attach()
        for name, value in (("METHOD", "future"), ("DECISION_VERSION", 2)):
            with patch.object(service, name, value):
                for call in (self.attach, self.read, self.listing):
                    self.error("posting_source_conflict", call, 409)
        self.assertEqual(PostingSource.objects.count(), 1)

    def test_sticky_conflict_replay_and_conflict_before_admission(self):
        self.attach()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        self.assertFalse(self.attach().source_eligible)
        self.assertFalse(self.read().source_eligible)
        self.assertFalse(self.listing().results[0].source_eligible)
        self.error("posting_source_conflict", lambda: self.attach(posting_id=self.q.pk), 409)
        self.error("retained_source_ineligible", lambda: self.attach(item_id=self.b.pk), 409)
        self.assertEqual(PostingSource.objects.count(), 1)

    def test_multiple_outputs_and_zero_outputs_are_not_admission(self):
        self.decide(self.outputs[2], mode="attach_existing", item_id=self.a.pk)
        self.attach()
        self.assertEqual(self.a.associations.count(), 2)
        self.correction()
        self.correction(output_id=self.outputs[2].pk, mode="withdraw", target_item_id=None)
        self.assertTrue(self.attach().replay)
        self.assertFalse(PostingSource.objects.filter(item=self.b).exists())
        # A distinct initially allocated item becomes unsupported before attachment.
        c = self.decide(self.outputs[3]).item
        self.correction(output_id=self.outputs[3].pk, mode="withdraw", target_item_id=None)
        self.assertEqual(self.attach(item_id=c.pk).item.pk, c.pk)

    def test_membership_remap_and_withdraw_do_not_mutate_mapping(self):
        self.attach()
        before = self.snapshot()
        self.correction()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(PostingSource.objects.filter(item=self.b).exists())
        self.correction(expected_revision=1, mode="withdraw", target_item_id=None)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.read().posting.pk, self.p.pk)
        self.assertTrue(Item.objects.filter(pk=self.a.pk).exists())

    def test_posting_states_and_real_conversion_preserve_mapping(self):
        client = APIClient()
        client.force_authenticate(self.user)
        base = f"/api/workspaces/{self.ws.pk}/job-postings/{self.p.pk}/"
        self.p.status = "dismissed"
        self.p.saved = True
        self.p.save()
        self.attach()
        before = self.snapshot()
        for action, payload in (("restore", {}), ("save", {"saved": False}), ("dismiss", {})):
            response = client.post(base + action + "/", payload, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(self.snapshot(), before)
        response = client.post(base + "apply/", {"company": "Acme", "role_label": "Engineer"},
                               format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(self.p.conversions.exists())
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.attach().replay)
        self.attach(item_id=self.b.pk)  # new attachment to an already converted posting

    def test_protected_deletion_and_account_cascade(self):
        self.attach()
        for obj in (self.a, self.p, self.user, self.account, self.ws):
            with self.assertRaises(ProtectedError):
                type(obj).objects.filter(pk=obj.pk).delete()
        self.assertEqual(PostingSource.objects.count(), 1)
        self.assertTrue(JobPosting.objects.filter(pk=self.p.pk).exists())
        self.assertTrue(EmailAccount.objects.filter(pk=self.account.pk).exists())
        # Actor protection remains attributable to PostingSource after ownership transfer.
        Workspace.objects.filter(owner=self.user).update(owner=self.other)
        with self.assertRaises(ProtectedError) as caught:
            User.objects.filter(pk=self.user.pk).delete()
        self.assertIn(self.read(actor=self.other).initial_source, caught.exception.protected_objects)

    def test_disconnect_all_providers_preserves_mapping(self):
        from email_sync.oauth import disconnect_gmail_account
        from email_sync.outlook_oauth import disconnect_outlook_account
        from email_sync.imap_auth import disconnect_imap_account
        self.attach()
        before = self.snapshot()
        with patch("email_sync.oauth.revoke_gmail_token") as network:
            for disconnect in (disconnect_gmail_account, disconnect_outlook_account, disconnect_imap_account):
                disconnect(self.account)
                self.assertTrue(EmailAccount.objects.filter(pk=self.account.pk).exists())
                self.assertEqual(self.snapshot(), before)
                self.assertTrue(self.attach().replay)
            network.assert_not_called()  # no live credentials in this fixture

    def test_ordinary_model_policy_and_persisted_actor(self):
        for changes in ({"method": "automatic"}, {"decision_version": True}, {"decision_version": 2},
                        {"actor": None}, {"actor_id": 999999, "actor": None}):
            row = self.model_row(**changes)
            with self.assertRaises(ValidationError):
                row.save()
        missing = self.model_row()
        missing.actor_id = 999999
        with self.assertRaises(ValidationError):
            missing.save()
        # Service, not model save, owns current-owner authorization.
        row = self.model_row(actor=self.other)
        row.save()
        self.assertEqual(row.actor_id, self.other.pk)

    def test_model_persisted_endpoints_not_cached_objects(self):
        other_account = EmailAccount.objects.create(workspace=self.ws2, email="other@example.test")
        foreign = self.posting(workspace=self.ws2, account=other_account)
        foreign.workspace_id = self.ws.pk
        foreign.account_id = self.account.pk
        row = self.model_row(posting=foreign)
        for call in (row.save, row.clean):
            with self.assertRaises(ValidationError):
                call()
        foreign_source = self.source(self.ws2)
        foreign_item = Item.objects.create(retained_message=foreign_source)
        foreign_item.retained_message_id = self.message.pk
        with self.assertRaises(ValidationError):
            self.model_row(item=foreign_item).save()
        EmailAccount.objects.filter(pk=self.account.pk).update(workspace=self.ws2)
        with self.assertRaises(ValidationError):
            self.model_row().save()

    def test_model_source_mailbox_consistency(self):
        mailbox = self.message.mailbox
        for changes in ({"workspace": self.ws2}, {"provider": "imap"}):
            MailboxLineage.objects.filter(pk=mailbox.pk).update(**changes)
            with self.assertRaises(ValidationError):
                self.model_row().save()
            self.error("not_found", self.attach, 404)
            MailboxLineage.objects.filter(pk=mailbox.pk).update(workspace=self.ws, provider="gmail")

    def test_mutation_reparent_replacement_delete(self):
        row = self.attach().initial_source
        for field in row._meta.fields:
            changed = PostingSource.objects.get(pk=row.pk)
            setattr(changed, field.attname, None)
            with self.assertRaises(ValidationError):
                changed.save(update_fields=[field.name])
        for changes in ({"item": self.b}, {"posting": self.q}, {"actor": self.other}):
            changed = PostingSource.objects.get(pk=row.pk)
            for name, value in changes.items():
                setattr(changed, name, value)
            with self.assertRaises(ValidationError):
                changed.save()
        replacement = PostingSource(**{f.attname: getattr(row, f.attname) for f in row._meta.fields})
        with patch("postings.models.router.db_for_write", return_value="default") as routed:
            with self.assertRaises(ValidationError):
                replacement.save()
            routed.assert_called_once()
        with self.assertRaises(ValidationError):
            row.delete()

    def test_database_uniqueness_and_policy(self):
        self.attach()
        other = self.attach(item_id=self.b.pk).initial_source
        for changes in ({"item": self.a}, {"method": "auto"}, {"decision_version": 2}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                PostingSource.objects.filter(pk=other.pk).update(**changes)

    def test_pagination_and_limits(self):
        self.attach()
        self.attach(item_id=self.b.pk)
        one = self.listing(limit=1)
        c = self.decide(self.outputs[2]).item
        self.attach(item_id=c.pk)
        two = self.listing(limit=2, cursor=one.next_cursor)
        self.assertEqual([r.item.pk for r in two.results], [self.b.pk, c.pk])
        self.assertIsNone(two.next_cursor)
        foreign = self.attach(item_id=self.decide(self.outputs[3]).item.pk, posting_id=self.q.pk).initial_source
        for limit in (True, 0, -1, 201, "1"):
            self.error("invalid_posting_source", lambda: self.listing(limit=limit))
        for cursor in ([], (1,), (True, 1), (self.q.pk, one.results[0].initial_source.pk),
                       (self.p.pk, foreign.pk), (self.p.pk, 999999), (self.p.pk, 0), (self.p.pk, 2**63)):
            self.error("invalid_posting_source", lambda: self.listing(cursor=cursor))
        self.assertEqual([r.initial_source.pk for r in self.listing().results],
                         list(PostingSource.objects.filter(posting=self.p).order_by("pk").values_list("pk", flat=True)))

    def test_rollback_after_insert(self):
        original = PostingSource.save
        def fail(row, *args, **kwargs):
            original(row, *args, **kwargs)
            raise RuntimeError("after insert")
        with patch.object(PostingSource, "save", fail), self.assertRaises(RuntimeError):
            self.attach()
        self.assertEqual(self.snapshot(), [])

    def test_no_unrelated_writes_parser_ingestion_or_descriptor_changes(self):
        def tables():
            with connection.cursor() as cursor:
                values = {}
                for table in connection.introspection.table_names():
                    if table != PostingSource._meta.db_table:
                        cursor.execute(f"SELECT * FROM {connection.ops.quote_name(table)} ORDER BY 1")
                        values[table] = cursor.fetchall()
                return values
        before = tables()
        with patch("postings.extraction.extract_postings", side_effect=AssertionError("parser")), \
             patch("postings.services.ingest_extracted_postings", side_effect=AssertionError("ingestion")):
            self.attach()
            self.attach()
            snapshot = self.snapshot()
            self.read()
            self.listing()
            self.assertEqual(snapshot, self.snapshot())
        self.assertEqual(before, tables())

    def test_admin_read_only(self):
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        row = self.attach().initial_source
        base = "/admin/postings/postingsource/"
        self.assertEqual(self.client.get(base).status_code, 200)
        self.assertEqual(self.client.get(f"{base}{row.pk}/change/").status_code, 200)
        self.assertEqual(self.client.get(base + "add/").status_code, 403)
        for url in (base + "add/", f"{base}{row.pk}/change/", f"{base}{row.pk}/delete/"):
            self.assertEqual(self.client.post(url, {"_save": "Save", "post": "yes"}).status_code, 403)
        model_admin = admin.site._registry[PostingSource]
        request = type("Request", (), {"user": self.user, "GET": {}})()
        self.assertEqual(model_admin.get_actions(request), {})
        self.assertEqual(set(model_admin.get_readonly_fields(request)), {f.name for f in row._meta.fields})


class PostingSourceConcurrencyTests(Fixtures, TransactionTestCase):
    def race(self, variant):
        requests = [{}, {}]
        if variant == "changed":
            requests[1] = {"posting_id": self.q.pk}
        elif variant == "items":
            requests[1] = {"item_id": self.b.pk}
        barrier = Barrier(2)
        def attempt(changes):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.attach(**changes)
            except OperationalError:
                return None
            except APIException as exc:
                self.assertEqual(variant, "changed")
                self.assertEqual(exc.get_codes(), "posting_source_conflict")
                return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(attempt, requests))
        successes, conflicts = [], 0
        for changes in requests:
            try:
                successes.append(self.attach(**changes))
            except APIException as exc:
                self.assertEqual(exc.get_codes(), "posting_source_conflict")
                conflicts += 1
        self.assertEqual(conflicts, int(variant == "changed"))
        self.assertEqual(PostingSource.objects.count(), 2 if variant == "items" else 1)
        self.assertEqual(len({r.initial_source.pk for r in successes}), 2 if variant == "items" else 1)

    def test_same_item_same_posting(self):
        self.race("same")

    def test_same_item_different_posting(self):
        self.race("changed")

    def test_different_items_same_posting(self):
        self.race("items")
