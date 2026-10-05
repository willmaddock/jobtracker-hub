"""Operator transport acceptance using isolated evidence and independent commits."""
from copy import deepcopy
from contextlib import ExitStack
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TransactionTestCase
from rest_framework.exceptions import APIException, NotFound

from postings import retained_extraction_producer as producer
from postings.management.commands import extract_retained_job_alerts as adapter
from postings.models import RetainedPostingExtraction as Extraction
from postings.models import RetainedPostingExtractionOutput as Output
from postings.tests.test_extraction import linkedin_body
from postings.tests.test_retained_extractions import Fixtures, fields, spec


class BatchCommandTests(Fixtures, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "requests.json"
        self.document = dict(version=1, actor_id=self.user.pk, workspace_id=self.ws.pk,
                             requests=[self.entry()])

    def entry(self, message=None, operation=None):
        return dict(retained_message_id=(message or self.message).pk,
                    operation_id=str(operation or uuid.uuid4()), input_spec=spec())

    def write(self, document=None):
        self.path.write_text(json.dumps(document or self.document), encoding="utf-8")

    def invoke(self, *, failed=False, write=True):
        if write:
            self.write()
        stdout = StringIO()
        stderr = StringIO()
        if failed:
            with self.assertRaises(CommandError) as caught:
                call_command("extract_retained_job_alerts", str(self.path), stdout=stdout, stderr=stderr)
            self.assertEqual(str(caught.exception), adapter.ERROR_MESSAGE)
            self.assertEqual(caught.exception.returncode, 1)
        else:
            call_command("extract_retained_job_alerts", str(self.path), stdout=stdout, stderr=stderr)
        text = stdout.getvalue()
        report = json.loads(text)
        self.assertEqual(text, json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(set(report), {"version", "actor_id", "workspace_id", "status",
                                      "completed", "failure", "unattempted_count"})
        if failed:
            self.assertEqual(set(report["failure"]), {"stage", "index", "retained_message_id",
                "operation_id", "code", "http_status", "outcome_may_be_unknown"})
        return report

    def reject(self, *, write=True, stage="preflight"):
        with patch.object(producer, "produce_retained_job_alert_extraction") as call:
            result = self.invoke(failed=True, write=write)
            call.assert_not_called()
        self.assertEqual(result["failure"]["stage"], stage)
        self.assertEqual(result["completed"], [])
        return result

    def test_file_errors(self):
        for raw in (b"\xef\xbb\xbf{}", b"\xff", b"{", b'{"version":1,"version":1}',
                    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}',
                    b"x" * (adapter.MAX_FILE_BYTES + 1)):
            with self.subTest(raw=raw[:20]):
                self.path.write_bytes(raw)
                self.reject(write=False, stage="file")
        self.path.unlink()
        self.reject(write=False, stage="file")
        with patch("builtins.open", side_effect=OSError("secret path")):
            self.reject(write=False, stage="file")

    def test_envelope_validation(self):
        documents = [[], None, {}, {**self.document, "extra": 1}]
        documents += [{k: v for k, v in self.document.items() if k != missing}
                      for missing in self.document]
        for key, values in (("version", [True, 2, "1"]),
                            ("actor_id", [True, 0, -1, 2**63, "1"]),
                            ("workspace_id", [True, 0, -1, 2**63, None]),
                            ("requests", [{}, [], [self.entry() for _ in range(101)]])):
            documents.extend({**self.document, key: value} for value in values)
        for document in documents:
            with self.subTest(document=document):
                self.path.write_text(json.dumps(document), encoding="utf-8")
                self.reject(write=False)
        nested = 0
        for _ in range(17):
            nested = [nested]
        self.path.write_text(json.dumps(nested), encoding="utf-8")
        self.reject(write=False)
        self.path.write_bytes(b"[" * 2000 + b"]" * 2000)
        with patch.object(producer, "produce_retained_job_alert_extraction") as call:
            report = self.invoke(failed=True, write=False)
            call.assert_not_called()
        self.assertIn(report["failure"]["stage"], {"file", "preflight"})

    def test_entry_validation_and_later_preflight(self):
        entry = self.entry()
        invalid = [None, [], {**entry, "outputs": []}]
        invalid += [{k: v for k, v in entry.items() if k != missing} for missing in entry]
        for key, values in (("retained_message_id", [True, 0, -1, 2**63, "1"]),
                            ("operation_id", [None, "bad", str(uuid.uuid1()),
                                              str(uuid.uuid4()).upper()]),
                            ("input_spec", [{}, {**spec(), "extra": "x" * 2049}])):
            invalid.extend({**entry, key: value} for value in values)
        for bad in invalid:
            with self.subTest(entry=bad):
                self.document["requests"] = [self.entry(), bad]
                result = self.reject()
                self.assertEqual(result["unattempted_count"], 2)
                self.assertEqual(result["failure"]["index"], 1)

    def test_duplicate_pairs_rejected(self):
        for changed in (False, True):
            entry = self.entry()
            duplicate = deepcopy(entry)
            if changed:
                duplicate["input_spec"]["selectors"]["sender"]["index"] = 1
            self.document["requests"] = [entry, duplicate]
            self.reject()

    def test_source_scoped_operations_and_order(self):
        other = self.source(self.ws)
        operation = uuid.uuid4()
        self.document["requests"] = [self.entry(other, operation), self.entry(self.message, operation),
                                     self.entry(other)]
        real = producer.produce_retained_job_alert_extraction
        with patch.object(producer, "produce_retained_job_alert_extraction", wraps=real) as call:
            report = self.invoke()
        self.assertEqual([c.kwargs["retained_message_id"] for c in call.call_args_list],
                         [other.pk, self.message.pk, other.pk])
        self.assertEqual([x["index"] for x in report["completed"]], [0, 1, 2])
        self.assertEqual(Extraction.objects.count(), 3)
        for call_args in call.call_args_list:
            self.assertEqual(call_args.kwargs["extractor_method"], "job_alert_rules")
            self.assertEqual(call_args.kwargs["extractor_version"], "1")

    def test_authorization_uniform(self):
        failures = []
        for actor, workspace in ((2**63 - 1, self.ws.pk), (self.user.pk, 2**63 - 1),
                                 (self.other.pk, self.ws.pk)):
            self.document.update(actor_id=actor, workspace_id=workspace)
            failures.append(self.reject(stage="authorization")["failure"])
        self.assertEqual(failures, [failures[0]] * 3)
        self.assertEqual(failures[0]["code"], "authorization_error")

    def test_inactive_owner_allowed(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.invoke()["status"], "completed")

    def test_real_linkedin_fixture(self):
        def change(content):
            content["addresses"]["from"][0]["address"] = "jobalerts-noreply@linkedin.com"
            content["subject"] = "Software Engineer at Haystack"
            content["text"]["value"] = linkedin_body()
        source = self.source(self.ws, change=change)
        self.document["requests"] = [self.entry(source)]
        report = self.invoke()
        self.assertEqual(report["completed"][0]["output_count"], 6)
        self.assertEqual(Output.objects.count(), 6)

    def test_duplicate_outputs_preserved(self):
        with patch.object(producer, "extract_postings", return_value=[fields(), fields()]):
            report = self.invoke()
        self.assertEqual(report["completed"][0]["output_count"], 2)
        self.assertEqual(list(Output.objects.values_list("position", flat=True)), [0, 1])
        self.assertEqual(list(Output.objects.values_list("fields", flat=True)), [fields(), fields()])

    def test_zero_output_and_replay_without_parser_or_clock(self):
        with patch.object(producer, "extract_postings", return_value=[]):
            first = self.invoke()
        before = self.snapshot()
        with patch.object(producer, "extract_postings", side_effect=AssertionError("parser")), \
             patch.object(producer.timezone, "now", side_effect=AssertionError("clock")):
            second = self.invoke()
        self.assertEqual(first["completed"][0]["output_count"], 0)
        expected = {**first["completed"][0], "replay": True}
        self.assertEqual(second["completed"], [expected])
        self.assertEqual(before, self.snapshot())

    def test_changed_intent_conflicts(self):
        self.invoke()
        before = self.snapshot()
        self.document["requests"][0]["input_spec"]["selectors"]["sender"]["index"] = 1
        report = self.invoke(failed=True)
        self.assertEqual(report["failure"]["code"], "idempotency_key_reused")
        self.assertEqual(report["failure"]["http_status"], 409)
        self.assertEqual(before, self.snapshot())

    def test_first_and_middle_failure_independent_commits(self):
        for fail_index in (0, 1):
            with self.subTest(index=fail_index):
                self.document["requests"] = [self.entry(), self.entry(), self.entry()]
                real = producer.produce_retained_job_alert_extraction
                calls = []
                count = Extraction.objects.count()
                def execute(**kwargs):
                    self.assertFalse(connection.in_atomic_block)
                    self.assertTrue(connection.get_autocommit())
                    self.assertEqual(Extraction.objects.count(), count + len(calls))
                    if len(calls) == fail_index:
                        raise NotFound("secret")
                    calls.append(kwargs)
                    return real(**kwargs)
                with patch.object(producer, "produce_retained_job_alert_extraction", side_effect=execute) as call:
                    report = self.invoke(failed=True)
                self.assertEqual(call.call_count, fail_index + 1)
                self.assertEqual(len(report["completed"]), fail_index)
                self.assertEqual(report["failure"]["index"], fail_index)
                self.assertEqual(report["failure"]["stage"], "execution")
                self.assertEqual(report["unattempted_count"], 2 - fail_index)
                self.assertEqual(Extraction.objects.count(), count + fail_index)

    def test_explicit_retry_progresses(self):
        self.document["requests"] = [self.entry(), self.entry(), self.entry()]
        real = producer.produce_retained_job_alert_extraction
        calls = 0
        def execute(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise NotFound()
            return real(**kwargs)
        with patch.object(producer, "produce_retained_job_alert_extraction",
                          side_effect=execute) as call:
            first = self.invoke(failed=True)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(len(first["completed"]), 1)
        second = self.invoke()
        self.assertEqual([x["replay"] for x in second["completed"]], [True, False, False])
        self.assertEqual(Extraction.objects.count(), 3)

    def test_outer_atomic_rejected(self):
        with transaction.atomic():
            result = self.reject(stage="transaction_context")
        self.assertIsNone(result["actor_id"])
        self.assertIsNone(result["unattempted_count"])

    def test_manual_autocommit_off_rejected(self):
        connection.set_autocommit(False)
        try:
            self.reject(stage="transaction_context")
        finally:
            connection.rollback()
            connection.set_autocommit(True)

    def test_first_entry_context_recheck_counts_current_entry(self):
        self.document["requests"] = [self.entry(), self.entry()]
        with patch.object(adapter, "top_level", side_effect=[True, False]), \
             patch.object(producer, "produce_retained_job_alert_extraction") as call:
            report = self.invoke(failed=True)
        call.assert_not_called()
        self.assertEqual(report["completed"], [])
        self.assertEqual(report["failure"]["index"], 0)
        self.assertEqual(report["failure"]["stage"], "transaction_context")
        self.assertEqual(report["unattempted_count"], 2)
        self.assertEqual(Extraction.objects.count(), 0)

    def test_later_context_recheck_counts_current_and_later_entries(self):
        self.document["requests"] = [self.entry(), self.entry(), self.entry()]
        with patch.object(adapter, "top_level", side_effect=[True, True, False]), \
             patch.object(producer, "produce_retained_job_alert_extraction",
                          wraps=producer.produce_retained_job_alert_extraction) as call:
            report = self.invoke(failed=True)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.kwargs["operation_id"], self.document["requests"][0]["operation_id"])
        self.assertEqual([entry["index"] for entry in report["completed"]], [0])
        self.assertEqual(report["failure"]["index"], 1)
        self.assertEqual(report["failure"]["stage"], "transaction_context")
        self.assertEqual(report["unattempted_count"], 2)
        self.assertEqual(Extraction.objects.count(), 1)

    def test_safe_error_classification_and_content_free_output(self):
        errors = [NotFound("BODY SUBJECT SENDER PASSWORD"), APIException("secret", code="unknown"),
                  APIException({"secret": "password"}), RuntimeError("raw secret traceback")]
        for error, code in zip(errors, ["not_found", "domain_error", "domain_error", "execution_error"]):
            with self.subTest(code=code), patch.object(producer, "produce_retained_job_alert_extraction",
                                                     side_effect=error):
                report = self.invoke(failed=True)
            self.assertEqual(report["failure"]["code"], code)
            self.assertEqual(report["failure"]["outcome_may_be_unknown"], code == "execution_error")
            self.assertNotIn("secret", json.dumps(report))
            self.assertNotIn("password", json.dumps(report))
        self.assertEqual(report["failure"]["http_status"], None)

    def test_summary_failure_after_commit_unknown(self):
        real = producer.produce_retained_job_alert_extraction
        def execute(**kwargs):
            real(**kwargs)
            return SimpleNamespace()
        with patch.object(producer, "produce_retained_job_alert_extraction", side_effect=execute):
            report = self.invoke(failed=True)
        self.assertTrue(report["failure"]["outcome_may_be_unknown"])
        self.assertEqual(Extraction.objects.count(), 1)
        self.assertEqual(report["completed"], [])

    def test_output_failure_preserves_commit(self):
        class BrokenOutput(StringIO):
            def write(self, text):
                raise OSError("secret stream")
        self.write()
        with self.assertRaisesMessage(CommandError, adapter.ERROR_MESSAGE):
            call_command("extract_retained_job_alerts", str(self.path), stdout=BrokenOutput())
        self.assertEqual(Extraction.objects.count(), 1)

    def test_cli_failure_and_argparse(self):
        self.write()
        stdout, stderr = StringIO(), StringIO()
        command = adapter.Command(stdout=stdout, stderr=stderr, no_color=True)
        with patch.object(producer, "produce_retained_job_alert_extraction", side_effect=NotFound()), \
             patch("django.core.management.base.connections.close_all"), \
             self.assertRaises(SystemExit) as caught:
            command.run_from_argv(["manage.py", "extract_retained_job_alerts", str(self.path)])
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(stderr.getvalue(), "CommandError: Retained extraction batch failed.\n")
        self.assertEqual(json.loads(stdout.getvalue())["status"], "failed")
        with patch("sys.stderr", new=StringIO()), self.assertRaises(SystemExit) as caught:
            adapter.Command().run_from_argv(["manage.py", "extract_retained_job_alerts"])
        self.assertEqual(caught.exception.code, 2)

    def test_only_extraction_tables_change(self):
        excluded = {Extraction._meta.db_table, Output._meta.db_table}
        def snapshot():
            with connection.cursor() as cursor:
                tables = connection.introspection.table_names(cursor)
                result = {}
                for table in tables:
                    if table not in excluded:
                        cursor.execute("SELECT * FROM " + connection.ops.quote_name(table))
                        result[table] = sorted(cursor.fetchall(), key=repr)
                return result
        before = snapshot()
        report = self.invoke()
        self.assertEqual(before, snapshot())
        self.assertEqual(set(report["completed"][0]), {"index", "retained_message_id", "operation_id",
            "extraction_id", "replay", "output_count", "source_eligible"})
        self.assertEqual(Extraction.objects.count(), 1)

    def test_bounded_read_and_symlink_path(self):
        self.write()
        from unittest.mock import mock_open
        file = mock_open(read_data=self.path.read_bytes())
        with patch("builtins.open", file):
            self.invoke(write=False)
        file().read.assert_called_once_with(adapter.MAX_FILE_BYTES + 1)
        link = Path(self.directory.name) / "link.json"
        link.symlink_to(self.path)
        stdout = StringIO()
        call_command("extract_retained_job_alerts", str(link), stdout=stdout)
        self.assertTrue(json.loads(stdout.getvalue())["completed"][0]["replay"])

    def test_container_depth_boundary(self):
        for depth in (16, 17):
            value = 0
            for _ in range(depth):
                value = [value]
            if depth == 16:
                adapter.check_depth(value)
            else:
                with self.assertRaises(ValueError):
                    adapter.check_depth(value)

    def test_maximum_request_count(self):
        self.document["requests"] = [self.entry() for _ in range(100)]
        with patch.object(producer, "produce_retained_job_alert_extraction") as call:
            call.return_value = SimpleNamespace(extraction_id=1, replay=False, outputs=(), source_eligible=True)
            report = self.invoke()
        self.assertEqual(call.call_count, 100)
        self.assertEqual(len(report["completed"]), 100)

    def test_all_recognized_domain_codes(self):
        for code in adapter.SAFE_CODES:
            error = APIException("sensitive content", code=code)
            error.status_code = 409
            with self.subTest(code=code), patch.object(producer, "produce_retained_job_alert_extraction",
                                                     side_effect=error):
                report = self.invoke(failed=True)
            self.assertEqual(report["failure"]["code"], code)
            self.assertEqual(report["failure"]["http_status"], 409)
            self.assertFalse(report["failure"]["outcome_may_be_unknown"])

    def test_unexpected_authorization_and_error_reporting_failure(self):
        with patch.object(adapter, "authorize_owner", side_effect=RuntimeError("secret")):
            report = self.invoke(failed=True)
        self.assertEqual(report["failure"]["code"], "execution_error")
        self.assertTrue(report["failure"]["outcome_may_be_unknown"])
        error = APIException("secret")
        with patch.object(error, "get_codes", side_effect=RuntimeError("secret")), \
             patch.object(producer, "produce_retained_job_alert_extraction", side_effect=error):
            report = self.invoke(failed=True)
        self.assertEqual(report["failure"]["code"], "execution_error")
        self.assertTrue(report["failure"]["outcome_may_be_unknown"])

    def test_forbidden_authority_calls_absent(self):
        targets = ["email_sync.sync_service.sync_account",
            "postings.services.ingest_extracted_postings", "postings.extraction.compute_dedupe_key",
            "postings.retained_items.associate_posting_output",
            "postings.retained_item_corrections.correct_posting_item_association",
            "postings.posting_sources.attach_posting_source",
            "postings.posting_source_corrections.correct_posting_source",
            "postings.retained_interpretations.decide_posting_interpretation",
            "postings.job_posting_allocations.allocate_job_posting",
            "postings.job_posting_interpretations.decide_job_posting_interpretation",
            "postings.job_posting_projections.project_job_posting_descriptors",
            "postings.retained_posting_reviews.review_retained_posting",
            "postings.retained_posting_candidates.discover_retained_posting_candidates",
            "applications.creation.create_attempt", "applications.retained_reviews.set_review_dismissal"]
        with ExitStack() as stack:
            calls = [stack.enter_context(patch(target, side_effect=AssertionError(target))) for target in targets]
            self.invoke()
            for call in calls:
                call.assert_not_called()

    def test_spec_detached_at_adapter_boundary(self):
        self.write()
        original = deepcopy(self.document["requests"][0]["input_spec"])
        canonical_json = adapter.contract.canonical_json
        parsed_spec = None

        def capture(value):
            nonlocal parsed_spec
            # validate_spec and detachment both reach this actual parsed object.
            if parsed_spec is None and value == original:
                parsed_spec = value
            return canonical_json(value)

        def assert_separate(detached, parsed):
            if type(parsed) is dict:
                self.assertIsNot(detached, parsed)
                for key in parsed:
                    assert_separate(detached[key], parsed[key])
            elif type(parsed) is list:
                self.assertIsNot(detached, parsed)
                for detached_child, parsed_child in zip(detached, parsed):
                    assert_separate(detached_child, parsed_child)

        def verify(**kwargs):
            self.assertIsNotNone(parsed_spec)
            detached = kwargs["input_spec"]
            self.assertEqual(detached, original)
            assert_separate(detached, parsed_spec)
            parsed_spec["selectors"]["sender"]["index"] = 1
            parsed_spec["selectors"]["subject"] = "mutated"
            parsed_spec["transform"]["version"] = "mutated"
            self.assertEqual(detached, original)
            return SimpleNamespace(extraction_id=1, replay=False, outputs=(), source_eligible=True)

        with patch.object(adapter.contract, "canonical_json", side_effect=capture), \
             patch.object(producer, "produce_retained_job_alert_extraction", side_effect=verify) as call:
            self.invoke(write=False)
        call.assert_called_once()
        self.assertEqual(call.call_args.kwargs["input_spec"], original)
        self.assertNotEqual(parsed_spec, original)
