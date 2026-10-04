"""Projection, competing writers, provenance, scope and isolated concurrency."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from itertools import combinations
from threading import Barrier
from unittest.mock import patch
import uuid

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError, OperationalError, close_old_connections
from django.db.models.deletion import ProtectedError
from django.db.models.signals import post_save
from django.test import TestCase, TransactionTestCase, RequestFactory
from django.urls import reverse
from rest_framework.exceptions import APIException
from rest_framework.test import APIClient

from accounts.models import Workspace
from email_sync.models import RetainedMessage
from postings import job_posting_projections as service
from postings import job_posting_interpretations as arbitration
from postings.models import JobPosting, JobPostingDescriptorProjection as Projection, DESCRIPTOR_FIELDS
from postings.tests.test_job_posting_interpretations import Fixtures as ArbitrationFixtures
from postings.tests.test_retained_extractions import fields


class Fixtures(ArbitrationFixtures):
    def setUp(self):
        super().setUp()
        self.authority = self.choose().decision
        self.projection_key = uuid.uuid4()
        self.initial_digest = service.descriptor_digest(service.descriptor_snapshot(self.p))

    def project(self, **changes):
        return service.project_job_posting_descriptors(**dict(actor=self.user, workspace=self.ws,
            posting_id=self.p.pk, operation_id=self.projection_key, expected_projection_revision=0,
            expected_arbitration_revision=1, expected_descriptor_digest=self.initial_digest) | changes)

    def projection(self, **changes):
        return service.read_job_posting_projection(**dict(actor=self.user, workspace=self.ws,
                                                        posting_id=self.p.pk) | changes)

    def events(self, **changes):
        return service.list_job_posting_projection_events(**dict(actor=self.user, workspace=self.ws,
                                                                 posting_id=self.p.pk) | changes)

    def fresh_project(self, **changes):
        state = self.projection()
        return self.project(**dict(operation_id=uuid.uuid4(), expected_projection_revision=state.revision,
            expected_arbitration_revision=state.current_arbitration_revision,
            expected_descriptor_digest=state.current_descriptor_digest) | changes)

    def new_values(self, values):
        output = self.record(operation_id=uuid.uuid4(), outputs=[values]).outputs[0]
        self.decide(output, mode="attach_existing", item_id=self.a.pk)
        item_revision = self.current().revision
        self.select(operation_id=uuid.uuid4(), expected_revision=item_revision, output_id=output.pk)
        arb_revision = self.effective().revision
        return self.choose(operation_id=uuid.uuid4(), expected_revision=arb_revision,
                           expected_interpretation_revision=item_revision + 1).decision

    def drift(self, **values):
        JobPosting.objects.filter(pk=self.p.pk).update(**(values or {"title": "privileged drift"}))


class ProjectionTests(Fixtures, TestCase):
    def test_first_projection_exact_and_preserves_every_other_column(self):
        before = JobPosting.objects.filter(pk=self.p.pk).values().get()
        result = self.project()
        after = JobPosting.objects.filter(pk=self.p.pk).values().get()
        self.assertEqual(result.event.snapshot, self.outputs[0].fields)
        self.assertEqual({k: after[k] for k in DESCRIPTOR_FIELDS}, result.event.snapshot)
        self.assertEqual({k: v for k, v in before.items() if k not in DESCRIPTOR_FIELDS},
                         {k: v for k, v in after.items() if k not in DESCRIPTOR_FIELDS})
        self.assertEqual((result.event.revision, result.current.state, result.replay), (1, "projected", False))
        self.assertEqual(result.event.arbitration_decision_id, self.authority.pk)
        self.assertEqual(result.event.expected_descriptor_digest, self.initial_digest)

    def test_first_equal_value_projection_meaningful(self):
        self.drift(**self.outputs[0].fields)
        result = self.fresh_project()
        self.assertEqual(result.event.revision, 1)
        self.assertEqual(result.current.state, "projected")

    def test_unprojected_reader_and_frozen_snapshots(self):
        state = self.projection()
        self.assertEqual((state.state, state.revision, state.source_eligible), ("unprojected", 0, None))
        self.assertTrue(state.can_project)
        with self.assertRaises(FrozenInstanceError):
            state.state = "stale"
        with self.assertRaises(TypeError):
            state.current_descriptor_snapshot["title"] = "bad"
        projected = self.project().current
        with self.assertRaises(TypeError):
            projected.projected_snapshot["title"] = "bad"
        self.assertFalse(projected.can_project)

    def test_null_blank_unicode_whitespace_case(self):
        value = fields("  Éngineer e\u0301\t\n") | {"company": " ACME ", "location": "", "salary": None,
                                                 "employment_type": "MiXeD "}
        self.new_values(value)
        self.assertEqual(dict(self.fresh_project().current.projected_snapshot), value)

    def test_digest_exact_envelope_and_broad_current_source(self):
        import hashlib
        import json
        self.drift(source="Custom Source", title=None, salary="")
        state = self.projection()
        encoded = json.dumps({"descriptor_digest_version": 1, "fields": dict(state.current_descriptor_snapshot)},
                             sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.assertEqual(state.current_descriptor_digest, hashlib.sha256(encoded).hexdigest())
        self.fresh_project()

    def test_capacity_boundaries_and_atomic_overflow(self):
        for name, maximum in service.CAPACITIES.items():
            if name == "source":
                continue
            with self.subTest(field=name), transaction.atomic():
                self.new_values(fields() | {name: "é" * maximum})
                self.fresh_project()
                before = self.snapshot()
                self.new_values(fields() | {name: "é" * (maximum + 1)})
                key = uuid.uuid4()
                state = self.projection()
                self.assertFalse(state.can_project)
                with self.assertRaises(APIException) as caught:
                    self.fresh_project(operation_id=key, expected_descriptor_digest="0" * 64)
                self.assertEqual(caught.exception.status_code, 409)
                self.assertEqual(caught.exception.get_codes()["fields"][0]["field"], "projection_capacity_exceeded")
                self.assertEqual(str(caught.exception.detail["fields"][0]["field"]), name)
                self.assertFalse(Projection.objects.filter(operation_id=key).exists())
                self.assertEqual(Projection.objects.count(), 1)
                self.assertEqual(self.projection().current_descriptor_snapshot[name], "é" * maximum)
                self.assertTrue(before)
                transaction.set_rollback(True)

    def test_capacity_error_fixed_field_order_no_values(self):
        self.new_values(fields() | {"salary": "s" * 256, "title": "t" * 256, "employment_type": "e" * 65})
        with self.assertRaises(APIException) as caught:
            self.fresh_project()
        self.assertEqual([str(v["field"]) for v in caught.exception.detail["fields"]],
                         ["title", "salary", "employment_type"])
        self.assertNotIn("tttt", str(caught.exception.detail))
        self.assertFalse(Projection.objects.exists())

    def test_source_contract_rejects_unknown_and_oversized(self):
        for source in ("unknown", "x" * 65, None):
            with self.assertRaises(APIException):
                self.record(operation_id=uuid.uuid4(), outputs=[fields() | {"source": source}])
        self.assertFalse(Projection.objects.exists())

    def test_noop_url_only_no_reservation_and_new_authority_equal_values(self):
        self.project()
        self.drift(posting_url="https://example.test/new")
        self.assertFalse(self.projection().descriptor_drift)
        key = uuid.uuid4()
        self.error("job_posting_projection_unchanged", lambda: self.fresh_project(operation_id=key), 409)
        self.assertFalse(Projection.objects.filter(operation_id=key).exists())
        self.new_values(dict(self.outputs[0].fields))
        state = self.projection()
        self.assertEqual(state.stale_reasons, ("arbitration_revision_changed", "arbitration_not_applicable"))
        result = self.fresh_project(operation_id=key)
        self.assertEqual(result.event.revision, 2)
        self.assertEqual(result.current.posting.posting_url, "https://example.test/new")

    def test_valid_different_item_replacement_only_revision_reason(self):
        self.project()
        self.choose(**self.other_candidate())
        self.assertEqual(self.projection().stale_reasons, ("arbitration_revision_changed",))
        self.fresh_project()

    def test_drift_repair_digest_and_dedupe(self):
        self.project()
        self.drift(title="changed", salary="changed")
        state = self.projection()
        self.assertEqual(state.stale_reasons, ("descriptor_drift",))
        self.error("stale_descriptor_digest", lambda: self.fresh_project(expected_descriptor_digest="0" * 64), 409)
        result = self.fresh_project()
        self.assertEqual(result.current.state, "projected")
        self.assertEqual(result.current.posting.dedupe_key, self.p.dedupe_key)
        self.assertEqual(result.event.snapshot, self.outputs[0].fields)

    def test_aba_current_equality_only(self):
        self.project()
        digest = self.projection().current_descriptor_digest
        self.drift()
        self.drift(**self.outputs[0].fields)
        self.assertEqual(self.projection().current_descriptor_digest, digest)
        self.assertFalse(self.projection().descriptor_drift)
        self.error("job_posting_projection_unchanged", self.fresh_project, 409)

    def test_replay_never_rewrites_after_drift_later_projection_and_arbitration(self):
        first = self.project().event
        self.drift()
        replay = self.project()
        self.assertTrue(replay.replay)
        self.assertTrue(replay.current.descriptor_drift)
        self.fresh_project()
        self.remove()
        self.drift(title="leave this")
        replay = self.project()
        self.assertEqual((replay.event.pk, replay.event.actor_id, replay.event.created_at),
                         (first.pk, first.actor_id, first.created_at))
        self.assertEqual(replay.current.current_descriptor_snapshot["title"], "leave this")
        self.assertEqual(Projection.objects.count(), 2)

    def test_changed_payload_precedes_stale(self):
        self.project()
        for changes in ({"expected_projection_revision": 1}, {"expected_descriptor_digest": "0" * 64}):
            self.error("idempotency_key_reused", lambda: self.project(**changes), 409)
        self.remove()
        self.error("idempotency_key_reused", lambda: self.project(expected_arbitration_revision=2), 409)

    def test_stale_projection_then_arbitration_then_applicability(self):
        self.project()
        self.remove()
        self.error("stale_projection_revision", lambda: self.project(operation_id=uuid.uuid4()), 409)
        self.error("stale_arbitration_revision", lambda: self.project(operation_id=uuid.uuid4(),
                   expected_projection_revision=1), 409)
        self.error("job_posting_projection_not_applicable", self.fresh_project, 409)
        self.assertEqual(self.projection().stale_reasons,
                         ("arbitration_revision_changed", "arbitration_not_applicable"))

    def test_each_lower_staleness_and_recorded_current_separation(self):
        for mutate, reason in ((self.remap, "mapping_revision_changed"),
                               (self.reaffirm_item, "interpretation_revision_changed"),
                               (self.move, "membership_revision_changed")):
            with self.subTest(reason=reason), transaction.atomic():
                self.project()
                mutate()
                state = self.projection()
                self.assertEqual(state.stale_reasons, ("arbitration_not_applicable",))
                self.assertEqual(state.recorded_authority_stale_reasons, (reason,))
                self.assertEqual(state.current_arbitration_stale_reasons, (reason,))
                self.error("job_posting_projection_not_applicable", self.fresh_project, 409)
                self.assertTrue(self.project().replay)
                transaction.set_rollback(True)

    def test_all_projection_stale_reason_combinations(self):
        for count in range(1, 4):
            for flags in combinations(range(3), count):
                with self.subTest(flags=flags), transaction.atomic():
                    self.project()
                    if 0 in flags:
                        self.choose(**self.other_candidate())
                    if 1 in flags:
                        self.move()
                    if 2 in flags:
                        self.drift()
                    names = ("arbitration_revision_changed", "arbitration_not_applicable", "descriptor_drift")
                    self.assertEqual(self.projection().stale_reasons, tuple(names[i] for i in flags))
                    transaction.set_rollback(True)

    def test_sticky_conflict_is_eligibility_not_staleness(self):
        self.project()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        state = self.projection()
        self.assertEqual((state.state, state.stale_reasons, state.source_eligible), ("projected", (), False))
        self.assertIsNone(state.applicable_snapshot)
        self.assertTrue(self.project().replay)
        self.error("retained_source_ineligible", self.fresh_project, 409)

    def test_old_conflict_allows_new_eligible_source_but_corruption_blocks(self):
        source, candidate = self.external_candidate()
        self.project()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        self.choose(**candidate)
        self.fresh_project()
        self.assertTrue(self.projection().source_eligible)
        RetainedMessage.objects.filter(pk=self.message.pk).update(content_digest="corrupt")
        for call in (self.projection, self.events, self.project):
            self.error("retained_source_invalid", call, 409)

    def test_input_validation(self):
        for changes in ({"operation_id": str(uuid.uuid4()).upper()}, {"operation_id": uuid.uuid1()},
                        {"expected_projection_revision": True}, {"expected_projection_revision": -1},
                        {"expected_projection_revision": 2**63}, {"expected_arbitration_revision": False},
                        {"expected_arbitration_revision": 0}, {"expected_descriptor_digest": "A" * 64},
                        {"expected_descriptor_digest": None}):
            self.error("invalid_job_posting_projection", lambda: self.project(**changes))
        self.error("not_found", lambda: self.project(expected_arbitration_revision=99), 404)

    def test_owner_scope_and_transfer_replay_actor(self):
        first = self.project().event
        for changes in ({"actor": self.other}, {"workspace": self.ws2}, {"posting_id": self.q.pk}):
            self.error("not_found", lambda: self.project(**changes), 404)
        Workspace.objects.filter(pk=self.ws.pk).update(owner=self.other)
        self.error("not_found", self.project, 404)
        self.ws.refresh_from_db()
        replay = self.project(actor=self.other)
        self.assertEqual(replay.event.actor_id, first.actor_id)
        self.drift()
        state = self.projection(actor=self.other)
        event = self.project(actor=self.other, operation_id=uuid.uuid4(), expected_projection_revision=1,
                             expected_descriptor_digest=state.current_descriptor_digest).event
        self.assertEqual(event.actor_id, self.other.pk)

    def test_projection_rows_reject_create_update_replace_delete(self):
        first = self.project().event
        data = {f.attname: getattr(first, f.attname) for f in Projection._meta.fields if f.name not in {"id", "created_at"}}
        for call in (lambda: Projection.objects.create(**data), first.save, first.delete,
                     lambda: Projection(pk=first.pk, **data).save()):
            with self.assertRaises(ValidationError):
                call()
        for obj in (self.p, self.authority, self.user):
            with self.assertRaises(ProtectedError):
                type(obj).objects.filter(pk=obj.pk).delete()

    def test_five_constraints(self):
        row = self.project().event
        for changes in ({"revision": 0}, {"method": "bad"}, {"projection_version": 2}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Projection.objects.filter(pk=row.pk).update(**changes)
        data = {f.attname: getattr(row, f.attname) for f in Projection._meta.fields if f.name not in {"id", "created_at"}}
        for changes in ({"operation_id": uuid.uuid4()}, {"revision": 2}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Projection.objects.bulk_create([Projection(**(data | changes))])
        self.assertEqual(len(Projection._meta.constraints), 5)

    def test_tampered_history_and_snapshot_fail_closed(self):
        row = self.project().event
        for changes in ({"snapshot": fields("wrong")}, {"snapshot": {}},
                        {"expected_descriptor_digest": "bad"}, {"revision": 2},
                        {"operation_id": uuid.uuid1()}):
            with self.subTest(changes=changes), transaction.atomic():
                Projection.objects.filter(pk=row.pk).update(**changes)
                self.error("job_posting_projection_history_invalid", self.projection, 409)
                self.error("job_posting_projection_history_invalid", self.events, 409)
                transaction.set_rollback(True)

    def test_corrupt_history_does_not_release_ownership(self):
        self.project()
        Projection.objects.update(snapshot={})
        self.p.title = "write"
        with self.assertRaises(ValidationError) as caught:
            self.p.save(update_fields=["title"])
        self.assertEqual(caught.exception.code, "descriptor_projection_owned")

    def test_history_prefix_pagination_later_exclusion(self):
        self.project()
        self.drift()
        self.fresh_project()
        self.drift(title="again")
        self.fresh_project()
        first = self.events(limit=1)
        self.drift(title="later")
        self.fresh_project()
        second = self.events(limit=1, cursor=first.next_cursor)
        third = self.events(limit=1, cursor=second.next_cursor)
        self.assertEqual([p.events[0].revision for p in (first, second, third)], [1, 2, 3])
        self.assertIsNone(third.next_cursor)
        self.assertFalse(hasattr(first, "source_eligible"))
        self.assertEqual(self.events(cursor=(self.p.pk, 0, 0)).events, ())
        Projection.objects.filter(revision=1).update(snapshot={})
        self.error("job_posting_projection_history_invalid", lambda: self.events(cursor=(self.p.pk, 3, 2)), 409)

    def test_history_excludes_later_arbitration_dependencies(self):
        self.project()
        source, candidate = self.external_candidate()
        self.choose(**candidate)
        RetainedMessage.objects.filter(pk=source.pk).update(content_digest="bad")
        self.assertEqual(self.events().through_revision, 1)
        self.error("retained_source_invalid", self.projection, 409)

    def test_invalid_history_navigation(self):
        for limit in (True, 0, 201, "1"):
            self.error("invalid_job_posting_projection", lambda: self.events(limit=limit))
        for cursor in ((True, 0, 0), (self.q.pk, 0, 0), (self.p.pk, 1, 2),
                       (self.p.pk, 1, 0), [self.p.pk, 0, 0]):
            self.error("invalid_job_posting_projection", lambda: self.events(cursor=cursor))

    def test_sorted_sources_after_workspace_and_posting(self):
        source, candidate = self.external_candidate()
        self.project()
        self.choose(**candidate)
        trace = []
        real_gate, real_posting, real_source = service.lock_workspace, service._posting, service.scoped_source
        def gate(*args):
            trace.append("workspace")
            return real_gate(*args)
        def posting(*args):
            trace.append("posting")
            return real_posting(*args)
        def retained(*args, **kwargs):
            trace.append(args[1])
            return real_source(*args, **kwargs)
        with patch.object(service, "lock_workspace", gate), patch.object(service, "_posting", posting), patch.object(service, "scoped_source", retained):
            self.project(operation_id=uuid.uuid4(), expected_projection_revision=1, expected_arbitration_revision=2,
                         expected_descriptor_digest=self.projection().current_descriptor_digest)
        expected = ["workspace", "posting"] + sorted([self.message.pk, source.pk])
        self.assertEqual(trace, expected * 2)

    def test_rollback_after_append_materialization_or_result_failure(self):
        for target in ("_materialize", "_state"):
            with self.subTest(target=target):
                before = self.snapshot()
                with patch.object(service, target, side_effect=RuntimeError("rollback")):
                    with self.assertRaises(RuntimeError):
                        self.project()
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.project().event.revision, 1)

    def test_no_other_tables_change_or_parser_called(self):
        before = dict(self.snapshot())
        with patch("postings.extraction.extract_postings", side_effect=AssertionError("parser")):
            self.project()
            self.project()
            self.projection()
            self.events()
        after = dict(self.snapshot())
        for name in before:
            if name not in {JobPosting._meta.label, Projection._meta.label}:
                self.assertEqual(before[name], after[name], name)

    def test_revision_exhaustion_after_noop_and_replay(self):
        latest = self.project().event
        with patch.object(service, "resolve_chain", return_value=service.Chain(service.MAX_REVISION, latest)):
            self.assertFalse(self.projection().can_append_revision)
            self.assertTrue(self.project().replay)
            self.error("job_posting_projection_unchanged", self.fresh_project, 409)
            self.drift()
            self.error("job_posting_projection_revision_exhausted", self.fresh_project, 409)

    def test_ordinary_saves_and_stale_instances(self):
        self.p.title = "unprojected edit"
        self.p.save(update_fields=["title"])
        self.initial_digest = service.descriptor_digest(service.descriptor_snapshot(self.p))
        stale = JobPosting.objects.get(pk=self.p.pk)
        self.project()
        for update_fields in (None, ["title"]):
            with self.assertRaises(ValidationError) as caught:
                stale.save(update_fields=update_fields)
            self.assertEqual(caught.exception.code, "descriptor_projection_owned")
        stale.status = "dismissed"
        stale.save(update_fields=["status"])
        stale.saved = True
        stale.save(update_fields=["saved"])
        stale.save(update_fields=[])
        current = JobPosting.objects.get(pk=self.p.pk)
        current.posting_url = "https://example.test/edit"
        current.save()
        self.assertEqual((current.status, current.saved), ("dismissed", True))
        self.assertEqual(service.descriptor_snapshot(current), self.outputs[0].fields)

    def test_pk_only_deferred_save_is_not_an_explicit_empty_save(self):
        saved = []
        def receiver(sender, instance, **kwargs):
            saved.append(instance.pk)
        post_save.connect(receiver, sender=JobPosting)
        try:
            for force_update in (False, True):
                with self.subTest(force_update=force_update):
                    row = JobPosting.objects.only("pk").get(pk=self.p.pk)
                    self.assertEqual(set(row.__dict__) - {"_state"}, {row._meta.pk.attname})
                    saved.clear()
                    row.save(force_update=force_update)
                    self.assertEqual(saved, [row.pk])
        finally:
            post_save.disconnect(receiver, sender=JobPosting)

    def test_pk_only_deferred_explicit_empty_save_remains_noop(self):
        saved = []
        def receiver(sender, instance, **kwargs):
            saved.append(instance.pk)
        post_save.connect(receiver, sender=JobPosting)
        try:
            row = JobPosting.objects.only("pk").get(pk=self.p.pk)
            before = service.descriptor_snapshot(self.p)
            row.title = "must not be saved"
            row.save(update_fields=[])
            self.assertEqual(saved, [])
            self.p.refresh_from_db()
            self.assertEqual(service.descriptor_snapshot(self.p), before)
        finally:
            post_save.disconnect(receiver, sender=JobPosting)

    def test_pk_only_deferred_save_preserves_projection_ownership(self):
        stale = JobPosting.objects.only("pk").get(pk=self.p.pk)
        stale.title = "stale descriptor"
        self.project()
        current = JobPosting.objects.only("pk").get(pk=self.p.pk)
        current.save(force_update=True)
        with self.assertRaises(ValidationError) as caught:
            stale.save()
        self.assertEqual(caught.exception.code, "descriptor_projection_owned")
        self.p.refresh_from_db()
        self.assertEqual(service.descriptor_snapshot(self.p), self.outputs[0].fields)

    def test_deferred_fields_respect_actual_write_set(self):
        stale = JobPosting.objects.only("pk", "status").get(pk=self.p.pk)
        self.project()
        stale.status = "dismissed"
        stale.save()
        self.assertEqual(self.projection().current_descriptor_snapshot, self.outputs[0].fields)
        stale.title = "explicit deferred edit"
        with self.assertRaises(ValidationError):
            stale.save()

    def test_ownership_persists_after_withdrawal_and_drift(self):
        self.project()
        self.remove()
        self.drift()
        self.p.title = "ordinary"
        with self.assertRaises(ValidationError):
            self.p.save(update_fields=["title"])

    def test_admin_readonly_and_stale_form(self):
        from postings.admin import JobPostingAdminForm
        model_admin = admin.site._registry[JobPosting]
        self.assertFalse(set(DESCRIPTOR_FIELDS) & set(model_admin.get_readonly_fields(None, self.p)))
        self.project()
        self.assertTrue(set(DESCRIPTOR_FIELDS) <= set(model_admin.get_readonly_fields(None, self.p)))
        self.assertNotIn("posting_url", model_admin.get_readonly_fields(None, self.p))
        form = JobPostingAdminForm(data={"title": "stale"}, instance=self.p)
        self.assertFalse(form.is_valid())
        self.assertIn("projection-owned", str(form.non_field_errors()))
        provenance = admin.site._registry[Projection]
        self.assertIsNone(provenance.actions)
        for permission in (provenance.has_add_permission, provenance.has_change_permission, provenance.has_delete_permission):
            self.assertFalse(permission(None))

    def test_admin_post_rejects_excluded_descriptor_keys_and_allows_url(self):
        self.other.is_staff = self.other.is_superuser = True
        self.other.save()
        self.client.force_login(self.other)
        url = reverse("admin:postings_jobposting_change", args=[self.p.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.project()
        data = dict(message_id="transitional", status="new", posting_url="https://example.test/admin", title="stale", _save="Save")
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "projection-owned")
        del data["title"]
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.projection().posting.posting_url, data["posting_url"])

    def test_api_lifecycle_and_conversion_use_materialized_descriptors(self):
        from applications.models import Application
        self.new_values(fields("Projected role") | {"company": "Projected employer"})
        self.fresh_project()
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get(reverse("job-posting-list", args=[self.ws.pk]))
        item = next(row for row in response.data if row["id"] == self.p.pk)
        self.assertEqual(item["title"], "Projected role")
        self.assertEqual(item["posting_url"], self.p.posting_url)
        for action, data in (("dismiss", {}), ("restore", {}), ("save", {"saved": True})):
            self.assertEqual(client.post(reverse("job-posting-" + action, args=[self.ws.pk, self.p.pk]),
                                         data, format="json").status_code, 200)
        response = client.post(reverse("job-posting-apply", args=[self.ws.pk, self.p.pk]), {},
                               format="json", HTTP_IDEMPOTENCY_KEY=uuid.uuid4().hex)
        self.assertEqual(response.status_code, 201, response.data)
        app = Application.objects.get()
        self.assertEqual((app.company, app.role_label), ("Projected employer", "Projected role"))
        self.assertFalse(self.projection().descriptor_drift)

    def test_materialization_mismatch_rolls_back_event_and_columns(self):
        before = self.snapshot()
        real_refresh = JobPosting.refresh_from_db
        def refresh(row, *args, **kwargs):
            real_refresh(row, *args, **kwargs)
            row.title = "simulate incomplete materialization"
        with patch.object(JobPosting, "refresh_from_db", refresh):
            self.error("job_posting_projection_history_invalid", self.project, 409)
        self.assertEqual(before, self.snapshot())

    def test_history_foreign_arbitration_anchor_rejected(self):
        event = self.project().event
        from postings.models import JobPostingInterpretationDecision
        # Privileged corruption: move the referenced arbitration anchor itself.
        JobPostingInterpretationDecision.objects.filter(pk=self.authority.pk).update(posting=self.q)
        self.error("job_posting_projection_history_invalid", self.events, 409)
        self.assertTrue(Projection.objects.filter(pk=event.pk).exists())

    def test_replay_after_all_three_stale_reasons_does_not_repair(self):
        self.project()
        self.choose(**self.other_candidate())
        self.move()
        self.drift()
        result = self.project()
        self.assertTrue(result.replay)
        self.assertEqual(len(result.current.stale_reasons), 3)
        self.assertEqual(result.current.current_descriptor_snapshot["title"], "privileged drift")

    def test_url_absence_not_fabricated(self):
        self.drift(posting_url=None)
        self.project()
        self.assertIsNone(self.projection().posting.posting_url)

    def test_ordinary_identity_guard_preserved(self):
        self.project()
        self.p.workspace = self.ws2
        with self.assertRaises(ValidationError):
            self.p.save(update_fields=["saved"])

    def test_noncanonical_source_snapshot_corruption_rejected(self):
        self.project()
        Projection.objects.update(snapshot=fields() | {"source": "other"})
        self.error("job_posting_projection_history_invalid", self.projection, 409)



class ProjectionConcurrencyTests(Fixtures, TransactionTestCase):
    def race(self, calls):
        barrier = Barrier(len(calls))
        def run(call):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return call()
                except (OperationalError, APIException, ValidationError) as exc:
                    return exc
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            results = list(pool.map(run, calls))
        # Explicit test caller retry after SQLite busy; no service retries.
        for i, result in enumerate(results):
            if isinstance(result, OperationalError):
                try:
                    results[i] = calls[i]()
                except (APIException, ValidationError) as exc:
                    results[i] = exc
        return results

    def test_same_operation_race(self):
        result = self.race([self.project, self.project])
        self.assertEqual(Projection.objects.count(), 1)
        self.assertEqual(sorted(row.replay for row in result), [False, True])

    def test_same_expected_revision_race(self):
        results = self.race([self.project, lambda: self.project(operation_id=uuid.uuid4())])
        self.assertEqual(Projection.objects.count(), 1)
        self.assertEqual([r.get_codes() for r in results if isinstance(r, APIException)], ["stale_projection_revision"])

    def test_changed_payload_race(self):
        results = self.race([self.project, lambda: self.project(expected_projection_revision=1)])
        self.assertEqual(Projection.objects.count(), 1)
        self.assertEqual(sum(isinstance(r, APIException) for r in results), 1)
        self.error("idempotency_key_reused", lambda: self.project(expected_projection_revision=1), 409)

    def test_projection_vs_arbitration(self):
        results = self.race([self.project, self.remove])
        self.assertFalse(isinstance(results[1], Exception))
        if Projection.objects.exists():
            self.assertEqual(self.projection().state, "stale")
        else:
            self.assertEqual(results[0].get_codes(), "stale_arbitration_revision")

    def test_projection_vs_ordinary_save(self):
        def save():
            row = JobPosting.objects.get(pk=self.p.pk)
            row.title = "ordinary"
            row.save(update_fields=["title"])
        results = self.race([self.project, save])
        if Projection.objects.exists():
            self.assertEqual(self.projection().state, "projected")
            self.assertIsInstance(results[1], ValidationError)
        else:
            self.assertEqual(results[0].get_codes(), "stale_descriptor_digest")

    def ingestion(self):
        from postings.services import ingest_extracted_postings
        return ingest_extracted_postings(self.account, "new", "sender", "subject", "body",
                                         posting_urls=[self.p.posting_url])

    def race_ingestion(self, repair=False):
        from postings.extraction import compute_dedupe_key
        JobPosting.objects.filter(pk=self.p.pk).update(dedupe_key=compute_dedupe_key(
            str(self.account.pk), "new", self.p.posting_url, "Incoming", "Company"))
        if repair:
            self.project()
            self.drift()
        state = self.projection()
        command = lambda: self.project(operation_id=uuid.uuid4(), expected_projection_revision=state.revision,
                                        expected_descriptor_digest=state.current_descriptor_digest)
        with patch("postings.extraction.extract_postings", return_value=[fields("Incoming")]):
            results = self.race([command, self.ingestion])
        self.assertFalse(isinstance(results[1], Exception))
        self.assertEqual(JobPosting.objects.count(), 2)
        if not isinstance(results[0], Exception):
            self.assertEqual(self.projection().state, "projected")
        else:
            self.assertEqual(results[0].get_codes(), "stale_descriptor_digest")

    def test_first_projection_vs_ingestion(self):
        self.race_ingestion()

    def test_repair_vs_ingestion(self):
        self.race_ingestion(repair=True)

    def test_two_ingestions_same_dedupe(self):
        with patch("postings.extraction.extract_postings", return_value=[fields("Incoming")]):
            results = self.race([self.ingestion, self.ingestion])
        self.assertTrue(all(not isinstance(result, Exception) for result in results))
        self.assertEqual(results[0][0].pk, results[1][0].pk)
        self.assertEqual(JobPosting.objects.count(), 3)

    def test_reader_holds_gate_through_fresh_state(self):
        from threading import Event
        self.project()
        entered, release = Event(), Event()
        original = service._state
        def pause(*args):
            result = original(*args)
            entered.set()
            if not release.wait(timeout=10):
                raise AssertionError("reader timeout")
            return result
        def reader():
            close_old_connections()
            try:
                return self.projection()
            finally:
                close_old_connections()
        with patch.object(service, "_state", pause), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(reader)
            try:
                self.assertTrue(entered.wait(timeout=10))
                with self.assertRaises(OperationalError):
                    self.remove()
            finally:
                release.set()
            self.assertEqual(future.result(timeout=10).state, "projected")
        self.remove()
        self.assertEqual(self.projection().state, "stale")
