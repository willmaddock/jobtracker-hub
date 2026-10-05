"""Completed recording acceptance. Isolated retained fixtures, no producer adoption."""
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

from accounts.models import User, Workspace
from email_sync.models import RetainedMessage
from email_sync.retention import establish_mailbox, retain_observation
from email_sync.tests.test_retention import fixture
from postings import extraction_contract as contract
from postings.models import RetainedPostingExtraction as Extraction, RetainedPostingExtractionOutput as Output
from postings.retained_extractions import record_posting_extraction, read_posting_extraction
from rest_framework.exceptions import APIException


def spec():
    return {"version": 1, "representation_version": 1,
            "selectors": {"sender": {"role": "from", "index": 0},
                          "subject": "content.subject", "body": "content.text.value"},
            "transform": {"method": "retained_text_arguments", "version": "1"}}


def fields(title="Engineer"):
    return {"source": "linkedin", "title": title, "company": "Acme", "location": None,
            "salary": "", "employment_type": None}


class Fixtures:
    def setUp(self):
        self.user = User.objects.create_user(username="record-owner")
        self.other = User.objects.create_user(username="record-other")
        self.ws = Workspace.objects.create(owner=self.user, name="Records")
        self.ws2 = Workspace.objects.create(owner=self.user, name="Other workspace")
        self.message = self.source(self.ws)
        self.kw = dict(actor=self.user, workspace=self.ws, retained_message_id=self.message.pk,
                       operation_id=uuid.uuid4(), extractor_method=contract.EXTRACTOR_METHOD,
                       extractor_version=contract.EXTRACTOR_VERSION, input_spec=spec(),
                       extracted_at="2026-09-27T12:34:56Z", outputs=[fields()])

    def source(self, workspace, *, change=None, provider="gmail"):
        mailbox = establish_mailbox(actor=workspace.owner, workspace=workspace, provider=provider,
                                    evidence={"method": "test", "reference": "isolated"})
        data = fixture(mailbox)
        data["source"]["provider"] = provider
        if provider == "outlook":
            data["source"]["kind"] = "graph_immutable_id"
        elif provider == "imap":
            data["source"].update(kind="imap_uid", value="1", folder="INBOX", stability="uidvalidity:1")
        data["content"]["addresses"]["from"].append({"name": "Other", "address": "other@example.test"})
        if change:
            change(data["content"])
        result = retain_observation(actor=workspace.owner, workspace=workspace, key=str(uuid.uuid4()), observation=data)
        return RetainedMessage.objects.get(pk=result.message_id)

    def record(self, **changes):
        return record_posting_extraction(**{**deepcopy(self.kw), **changes})

    def read(self, row, **changes):
        return read_posting_extraction(**{ "actor": self.user, "workspace": self.ws,
                                          "extraction_id": row.pk, **changes})

    def error(self, code, call, status=400):
        before = self.snapshot()
        with self.assertRaises(APIException) as caught:
            call()
        self.assertEqual(caught.exception.status_code, status)
        self.assertEqual(caught.exception.get_codes(), code)
        self.assertEqual(before, self.snapshot())

    def snapshot(self):
        return (list(Extraction.objects.order_by("pk").values()), list(Output.objects.order_by("pk").values()))


class RecordingTests(Fixtures, TestCase):
    def test_exact_recorder_replay_validates_all_persisted_siblings(self):
        self.kw["outputs"] = [fields("A"), fields("B")]
        result = self.record()
        sibling = result.outputs[1]
        for change in ({"fields": fields("Tampered")}, {"position": 9},
                       {"portable_id": uuid.uuid1()}):
            with self.subTest(change=change):
                Output.objects.filter(pk=sibling.pk).update(**change)
                self.error("posting_extraction_evidence_invalid", self.record, 409)
                Output.objects.filter(pk=sibling.pk).update(
                    **{name: getattr(sibling, name) for name in change})
        Extraction.objects.filter(pk=result.operation.pk).update(snapshot_version=2)
        self.error("posting_extraction_evidence_invalid", self.record, 409)

    def test_unknown_receipt_provenance_with_matching_digest_rejects(self):
        for label in ("not_a_retention_source", ""):
            content = deepcopy(self.message.content)
            content["provider_received"]["source"] = label
            self.assert_receipt_invalid(content)

    def assert_receipt_invalid(self, content, source=None):
        source = source or self.message
        RetainedMessage.objects.filter(pk=source.pk).update(content=content, content_digest=contract.digest(content))
        before_source = RetainedMessage.objects.values().get(pk=source.pk)
        self.error("retained_source_invalid", lambda: self.record(retained_message_id=source.pk), 409)
        self.assertEqual(before_source, RetainedMessage.objects.values().get(pk=source.pk))
        self.assertEqual(Extraction.objects.count(), 0)
        self.assertEqual(Output.objects.count(), 0)

    def test_provider_receipt_mismatch_with_matching_digest_rejects(self):
        provenance = {"gmail": "gmail_internal_date", "outlook": "graph_received_datetime",
                      "imap": "imap_internaldate"}
        for provider, expected in provenance.items():
            source = self.source(self.ws, provider=provider)
            for label in provenance.values():
                if label == expected:
                    continue
                for precision in ("instant", "unknown"):
                    content = deepcopy(source.content)
                    receipt = {"precision": precision, "source": label, "value": None}
                    if precision == "instant":
                        receipt.update(value="2026-09-27T12:00:00+00:00", source_utc_offset_seconds=0)
                    content["provider_received"] = receipt
                    self.assert_receipt_invalid(content, source)

    def test_valid_provider_receipts_preserve_replay_and_conflict_behavior(self):
        provenance = {"gmail": "gmail_internal_date", "outlook": "graph_received_datetime",
                      "imap": "imap_internaldate"}
        for provider, label in provenance.items():
            # These combinations are accepted by the actual canonical writer,
            # including known provenance with unknown precision.
            receipts = [{"precision": "instant", "value": "2026-09-27T12:00:00Z", "source": label},
                        {"precision": "date", "value": "2026-09-27", "source": label},
                        {"precision": "uncertain", "value": "uncertain receipt", "source": label},
                        {"precision": "unknown", "value": None, "source": label},
                        {"precision": "unknown", "value": None, "source": "unknown"}]
            for receipt in receipts:
                source = self.source(self.ws, provider=provider,
                                     change=lambda c: c.update(provider_received=receipt))
                first = self.record(retained_message_id=source.pk)
                before = self.snapshot()
                second = self.record(retained_message_id=source.pk)
                self.assertTrue(second.replay)
                self.assertEqual(first.operation.pk, second.operation.pk)
                self.assertEqual(first.operation.recorded_at, second.operation.recorded_at)
                self.assertEqual(first.outputs[0].portable_id, second.outputs[0].portable_id)
                self.assertEqual(before, self.snapshot())
                RetainedMessage.objects.filter(pk=source.pk).update(has_conflict=True)
                self.assertFalse(self.record(retained_message_id=source.pk).source_eligible)
                self.assertFalse(self.read(first.operation).source_eligible)
                self.error("retained_source_ineligible", lambda: self.record(
                    retained_message_id=source.pk, operation_id=uuid.uuid4()), 409)

    def test_adjacent_receipt_precision_semantics_with_matching_digest(self):
        cases = [{"precision": "uncertain", "value": "", "source": "gmail_internal_date"},
                 {"precision": "unknown", "value": "unexpected", "source": "gmail_internal_date"},
                 {"precision": "instant", "value": "2026-09-27T12:00:00+00:00",
                  "source": "unknown", "source_utc_offset_seconds": 0},
                 {"precision": "date", "value": "2026-09-27", "source": "unknown"},
                 {"precision": "uncertain", "value": "some date", "source": "unknown"}]
        for receipt in cases:
            content = deepcopy(self.message.content)
            content["provider_received"] = receipt
            self.assert_receipt_invalid(content)

    def test_zero_one_many_and_identical_outputs(self):
        for n in (0, 1, 3):
            with self.subTest(n=n):
                result = self.record(operation_id=uuid.uuid4(), outputs=[fields()] * n)
                self.assertFalse(result.replay)
                self.assertTrue(result.source_eligible)
                self.assertEqual([o.position for o in result.outputs], list(range(n)))
                self.assertEqual(len({o.portable_id for o in result.outputs}), n)
                self.assertTrue(all(o.portable_id.version == 4 for o in result.outputs))

    def test_response_loss_exact_replay_keeps_all_evidence(self):
        first = self.record()
        before = self.snapshot()
        second = self.record()
        self.assertTrue(second.replay)
        self.assertEqual(first.operation.pk, second.operation.pk)
        self.assertEqual(first.operation.recorded_at, second.operation.recorded_at)
        self.assertEqual(before, self.snapshot())
        self.assertEqual([(o.pk, o.portable_id) for o in first.outputs],
                         [(o.pk, o.portable_id) for o in second.outputs])

    def test_json_key_order_and_equivalent_instant_replay(self):
        first = self.record()
        second = self.record(input_spec=dict(reversed(list(spec().items()))),
                             outputs=[dict(reversed(list(fields().items())))],
                             extracted_at="2026-09-27T06:34:56.000000-06:00")
        self.assertTrue(second.replay)
        self.assertEqual(first.operation.pk, second.operation.pk)

    def test_changed_valid_payload_conflicts(self):
        self.kw["outputs"] = [fields("A"), fields("B")]
        self.record()
        changed = spec()
        changed["selectors"]["sender"]["index"] = 1
        for update in ({"input_spec": changed}, {"extracted_at": "2026-09-27T12:34:57Z"},
                       {"outputs": [fields("B"), fields("A")]}, {"outputs": [fields("C")]}):
            with self.subTest(update=update):
                self.error("idempotency_key_reused", lambda: self.record(**update), 409)

    def test_unsupported_producer_contract_is_validation_not_conflict(self):
        self.record()
        for update in ({"extractor_method": "python.function"}, {"extractor_version": "2"},
                       {"extractor_version": 1}, {"extractor_method": []}):
            self.error("invalid_posting_extraction", lambda: self.record(**update))

    def test_distinct_operations_and_source_scoped_uuid(self):
        a = self.record()
        b = self.record(operation_id=uuid.uuid4())
        source = self.source(self.ws)
        c = self.record(retained_message_id=source.pk)
        self.assertEqual(len({a.operation.pk, b.operation.pk, c.operation.pk}), 3)
        self.assertEqual(len({a.outputs[0].portable_id, b.outputs[0].portable_id, c.outputs[0].portable_id}), 3)

    def test_uuid_validation(self):
        for value in (None, True, 1, [], "bad", uuid.uuid1(), uuid.UUID(int=0), self.kw["operation_id"].hex):
            self.error("invalid_posting_extraction", lambda: self.record(operation_id=value))
        self.assertFalse(self.record(operation_id=str(self.kw["operation_id"])).replay)
        self.assertTrue(self.record().replay)

    def test_unauthorized_and_foreign_scope(self):
        foreign = self.source(self.ws2)
        for changes in ({"actor": self.other}, {"actor": AnonymousUser()},
                        {"workspace": self.ws2}, {"retained_message_id": foreign.pk}):
            self.error("not_found", lambda: self.record(**changes), 404)
        row = self.record().operation
        self.error("not_found", lambda: self.read(row, actor=self.other), 404)
        self.error("not_found", lambda: self.read(row, workspace=self.ws2), 404)

    def test_malformed_source_and_reader_ids(self):
        for value in (True, False, 0, -1, "1", None, 2**63):
            self.error("not_found", lambda: self.record(retained_message_id=value), 404)
            self.error("not_found", lambda: read_posting_extraction(actor=self.user, workspace=self.ws,
                                                                    extraction_id=value), 404)

    def test_corrupt_mailbox_workspace_or_provider_fails_closed(self):
        foreign = self.source(self.ws2)
        original = self.message.mailbox_id
        RetainedMessage.objects.filter(pk=self.message.pk).update(mailbox_id=foreign.mailbox_id)
        self.error("not_found", self.record, 404)
        RetainedMessage.objects.filter(pk=self.message.pk).update(mailbox_id=original, provider="outlook")
        self.error("not_found", self.record, 404)

    def test_source_conflict_new_work_vs_old_replay_and_inspection(self):
        first = self.record()
        RetainedMessage.objects.filter(pk=self.message.pk).update(has_conflict=True)
        self.error("retained_source_ineligible", lambda: self.record(operation_id=uuid.uuid4()), 409)
        replay = self.record()
        self.assertTrue(replay.replay)
        self.assertFalse(replay.source_eligible)
        self.assertFalse(self.read(first.operation).source_eligible)

    def test_source_integrity_digest_and_representation_checks(self):
        original = deepcopy(self.message.content)
        cases = [{"representation_version": 2}, {"content_digest": "0" * 64},
                 {"content": []}, {"content": {**original, "version": True}},
                 {"content": {**original, "text": {"value": [], "completeness": "complete", "reason": ""}}},
                 {"content": {**original, "addresses": {"from": ["bad"]}}}]
        for changes in cases:
            with self.subTest(changes=changes):
                if "content" in changes:
                    changes["content_digest"] = contract.digest(changes["content"])
                RetainedMessage.objects.filter(pk=self.message.pk).update(**changes)
                self.error("retained_source_invalid", self.record, 409)
                RetainedMessage.objects.filter(pk=self.message.pk).update(content=original,
                    representation_version=1, content_digest=contract.digest(original))

    def test_missing_selected_sender_and_forbidden_null_selector(self):
        for selector in ({"role": "sender", "index": 0}, {"role": "from", "index": 99}, None):
            value = spec()
            value["selectors"]["sender"] = selector
            self.error("invalid_posting_extraction", lambda: self.record(input_spec=value))

    def test_allowed_null_sender_and_exact_arguments(self):
        source = self.source(self.ws, change=lambda c: c.update(addresses={}))
        value = spec()
        value["selectors"]["sender"] = None
        self.record(retained_message_id=source.pk, input_spec=value, outputs=[])
        self.assertEqual(contract.resolve_selectors(value, source.content),
                         (None, source.content["subject"], source.content["text"]["value"]))
        args = contract.resolve_selectors(spec(), self.message.content)
        self.assertEqual(args[0], "recruiter@example.test")
        self.assertNotIn("Recruiter", args[0])

    def test_complete_partial_unavailable_and_truncated_retention(self):
        bodies = [{"value": "x", "completeness": "complete"},
                  {"value": "x", "completeness": "partial", "reason": "missing_part"},
                  {"value": None, "completeness": "unavailable"},
                  {"value": "x" * (129 * 1024), "completeness": "complete"}]
        for body in bodies:
            source = self.source(self.ws, change=lambda c: c.update(text=body))
            before = deepcopy(source.content)
            result = self.record(retained_message_id=source.pk, outputs=[])
            self.assertEqual(result.outputs, ())
            source.refresh_from_db()
            self.assertEqual(source.content, before)

    def test_invalid_timestamps(self):
        values = [None, "2026-09-27", "2026-09-27T12:34:56", "2026-02-30T12:34:56Z",
                  "0000-01-01T00:00:00Z", "0001-01-01T00:00:00+01:00", "2026-09-27T12:34:60Z",
                  "2026-09-27T12:34:56.1234567Z", "2026-09-27T12:34:56+00:60",
                  "2026-09-27T12:34:56+24:00", "2026-09-27 12:34:56Z"]
        for value in values:
            self.error("invalid_posting_extraction", lambda: self.record(extracted_at=value))

    def test_input_spec_strict_shape_and_types(self):
        changes = [lambda s: s.update(extra=1), lambda s: s.pop("version"),
                   lambda s: s.update(version=True), lambda s: s.update(representation_version=2),
                   lambda s: s["selectors"].update(extra=1),
                   lambda s: s["selectors"]["sender"].update(role="to"),
                   lambda s: s["selectors"]["sender"].update(index=True),
                   lambda s: s["selectors"]["sender"].update(index=-1),
                   lambda s: s["selectors"]["sender"].update(index=100),
                   lambda s: s["transform"].update(method="x" * 2049),
                   lambda s: s["transform"].update(version="2")]
        for change in changes:
            value = spec()
            change(value)
            self.error("invalid_posting_extraction", lambda: self.record(input_spec=value))

    def test_output_strict_fields_types_and_strings(self):
        values = [{}, {**fields(), "url": "https://example.test"}, {**fields(), "title": []},
                  {**fields(), "title": True}, {**fields(), "title": float("nan")},
                  {**fields(), "source": None}, {**fields(), "source": "unknown"},
                  {**fields(), "title": "secret\x00"}, {**fields(), "title": "\ud800"}]
        for value in values:
            self.error("invalid_posting_extraction", lambda: self.record(outputs=[value]))
        for value in (None, {}, (fields(),)):
            self.error("invalid_posting_extraction", lambda: self.record(outputs=value))

    def test_null_blank_and_multibyte_field_bounds(self):
        good = {**fields(), "title": "é" * 2048, "company": None, "location": ""}
        row = self.record(outputs=[good])
        self.assertEqual(row.outputs[0].fields, good)
        self.error("invalid_posting_extraction", lambda: self.record(outputs=[{**good, "title": "é" * 2049}]))

    def test_count_boundary(self):
        result = self.record(outputs=[fields()] * 1000)
        self.assertEqual(len(result.outputs), 1000)
        self.error("invalid_posting_extraction", lambda: self.record(outputs=[fields()] * 1001))

    def test_aggregate_payload_exact_boundary_and_overflow(self):
        outputs = [fields("") for _ in range(600)]
        envelope = contract.validate_envelope(self.kw["operation_id"], "job_alert_rules", "1", spec(),
                                                self.kw["extracted_at"], outputs)
        source = {"workspace_id": self.ws.pk, "retained_message_id": self.message.pk,
                  "retained_message_portable_id": str(self.message.portable_id),
                  "representation_version": 1, "content_digest": self.message.content_digest}
        current = len(contract.canonical_json({"digest_version": 1, "source": source, **envelope}))
        remaining = contract.MAX_PAYLOAD_BYTES - current
        for output in outputs:
            size = min(4096, remaining)
            output["title"] = "x" * size
            remaining -= size
        self.assertEqual(remaining, 0)
        self.record(outputs=outputs)
        outputs[-1]["company"] += "x"
        self.error("invalid_posting_extraction", lambda: self.record(outputs=outputs))

    def test_every_field_is_immutable_including_replacement_instances(self):
        result = self.record()
        for obj in (result.operation, result.outputs[0]):
            for field in obj._meta.fields:
                clone = type(obj).objects.get(pk=obj.pk)
                setattr(clone, field.attname, None)
                # Guard precedes field validation, even for PK/reparenting changes.
                with self.subTest(model=type(obj).__name__, field=field.name):
                    with self.assertRaises(ValidationError):
                        clone.save(update_fields=[field.name])
            replacement = type(obj)(**{f.attname: getattr(obj, f.attname) for f in obj._meta.fields})
            with self.assertRaises(ValidationError):
                replacement.save()
            with patch("postings.models.router.db_for_write", return_value="default") as routed:
                with self.assertRaises(ValidationError):
                    replacement.save()
                routed.assert_called_once()
            with self.assertRaises(ValidationError):
                obj.delete()
        result.operation.retained_message = self.source(self.ws)
        with self.assertRaises(ValidationError):
            result.operation.save()
        result.outputs[0].extraction = self.record(operation_id=uuid.uuid4()).operation
        with self.assertRaises(ValidationError):
            result.outputs[0].save()

    def test_parent_protection_and_zero_output_delete(self):
        result = self.record()
        with self.assertRaises(ProtectedError):
            RetainedMessage.objects.filter(pk=self.message.pk).delete()
        with self.assertRaises(ProtectedError):
            Extraction.objects.filter(pk=result.operation.pk).delete()
        zero = self.record(operation_id=uuid.uuid4(), outputs=[])
        with self.assertRaises(ValidationError):
            zero.operation.delete()

    def test_database_unique_constraints(self):
        result = self.record(outputs=[fields("A"), fields("B")])
        for updates in ({"portable_id": result.outputs[0].portable_id}, {"position": 0}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Output.objects.filter(pk=result.outputs[1].pk).update(**updates)
        other = self.record(operation_id=uuid.uuid4())
        with self.assertRaises(IntegrityError), transaction.atomic():
            Extraction.objects.filter(pk=other.operation.pk).update(operation_id=result.operation.operation_id)

    def test_failure_after_operation_or_partial_outputs_rolls_back(self):
        real = Output.save
        for fail_at in (1, 2):
            count = 0
            def fail(instance, *args, **kwargs):
                nonlocal count
                count += 1
                if count == fail_at:
                    raise RuntimeError("injected")
                return real(instance, *args, **kwargs)
            before = self.snapshot()
            with patch.object(Output, "save", fail), self.assertRaises(RuntimeError):
                self.record(outputs=[fields("A"), fields("B")])
            self.assertEqual(before, self.snapshot())

    def test_reader_order_no_parser_and_negative_scope(self):
        def database_snapshot():
            tables = [t for t in connection.introspection.table_names()
                      if t not in {Extraction._meta.db_table, Output._meta.db_table}]
            with connection.cursor() as cursor:
                result = {}
                for table in tables:
                    cursor.execute(f"SELECT * FROM {connection.ops.quote_name(table)} ORDER BY 1")
                    result[table] = cursor.fetchall()
                return result
        before = database_snapshot()
        with patch("postings.extraction.extract_postings", side_effect=AssertionError("must not execute")):
            result = self.record(outputs=[fields("B"), fields("A")])
            read = self.read(result.operation)
        self.assertEqual([o.fields["title"] for o in read.outputs], ["B", "A"])
        self.assertEqual(before, database_snapshot())

    def test_admin_read_only_and_escaped_json(self):
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        result = self.record(outputs=[fields("<script>alert(1)</script>")])
        for obj in (result.operation, result.outputs[0]):
            name = obj._meta.model_name
            base = f"/admin/postings/{name}/"
            self.assertEqual(self.client.get(base).status_code, 200)
            detail = self.client.get(f"{base}{obj.pk}/change/")
            self.assertEqual(detail.status_code, 200)
            self.assertNotContains(detail, "<script>alert(1)</script>")
            self.assertEqual(self.client.get(base + "add/").status_code, 403)
            for url in (base + "add/", f"{base}{obj.pk}/change/", f"{base}{obj.pk}/delete/"):
                self.assertEqual(self.client.post(url, {"position": 4, "_save": "Save", "post": "yes"}).status_code, 403)
            request = type("Request", (), {"user": self.user, "GET": {}})()
            self.assertEqual(admin.site._registry[type(obj)].get_actions(request), {})


class RecordingConcurrencyTests(Fixtures, TransactionTestCase):
    def race(self, different):
        barrier = Barrier(2)
        def attempt(n):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.record(outputs=[fields(str(n) if different else "same")])
            except OperationalError:
                return None
            except APIException as exc:
                self.assertEqual(exc.get_codes(), "idempotency_key_reused")
                return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(attempt, range(2)))
        successes, conflicts = [], 0
        for n in range(2):
            try:
                successes.append(self.record(outputs=[fields(str(n) if different else "same")]))
            except APIException as exc:
                self.assertEqual(exc.get_codes(), "idempotency_key_reused")
                conflicts += 1
        self.assertEqual(Extraction.objects.count(), 1)
        self.assertEqual(Output.objects.count(), 1)
        self.assertEqual(conflicts, int(different))
        self.assertEqual(len({r.operation.pk for r in successes}), 1)

    def test_same_operation_converges_after_explicit_retry(self):
        self.race(False)

    def test_different_payload_race_one_winner(self):
        self.race(True)
