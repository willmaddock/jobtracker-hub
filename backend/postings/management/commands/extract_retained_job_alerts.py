"""Bounded operator transport for explicit retained extraction requests."""
import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from rest_framework.exceptions import APIException

from accounts.models import Workspace
from postings import extraction_contract as contract
from postings import retained_extraction_producer as producer
from postings.retained_items import authorize_owner

MAX_FILE_BYTES = 1_048_576
MAX_REQUESTS = 100
MAX_DEPTH = 16
MAX_ID = 9_223_372_036_854_775_807
SAFE_CODES = frozenset({"not_found", "invalid_posting_extraction",
    "idempotency_key_reused", "retained_source_invalid", "retained_source_ineligible",
    "posting_extraction_evidence_invalid"})
ERROR_MESSAGE = "Retained extraction batch failed."


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError


def valid_id(value):
    return type(value) is int and 0 < value <= MAX_ID


def require(condition):
    if not condition:
        raise ValueError


def check_depth(document):
    pending = [(document, 1)]
    while pending:
        value, depth = pending.pop()
        if type(value) in (dict, list):
            require(depth <= MAX_DEPTH)
            children = value.values() if type(value) is dict else value
            pending.extend((child, depth + 1) for child in children
                           if type(child) in (dict, list))


def top_level():
    connection = connections["default"]
    return not connection.in_atomic_block and connection.get_autocommit() is True


class Command(BaseCommand):
    help = "Execute a bounded explicit retained extraction request file."
    output_transaction = False
    requires_system_checks = []
    requires_migrations_checks = False

    def add_arguments(self, parser):
        parser.add_argument("request_file")

    def handle(self, *args, **options):
        report = dict(version=1, actor_id=None, workspace_id=None, status="failed",
                      completed=[], failure=None, unattempted_count=None)
        stage = "transaction_context"
        index = message_id = operation_id = None
        try:
            require(top_level())
            stage = "file"
            with open(options["request_file"], "rb") as request_file:
                raw = request_file.read(MAX_FILE_BYTES + 1)
            require(len(raw) <= MAX_FILE_BYTES and not raw.startswith(b"\xef\xbb\xbf"))
            document = json.loads(raw.decode("utf-8"), object_pairs_hook=object_pairs,
                                  parse_constant=reject_constant)
            stage = "preflight"
            check_depth(document)
            require(type(document) is dict and set(document) ==
                    {"version", "actor_id", "workspace_id", "requests"})
            require(type(document["version"]) is int and document["version"] == 1)
            for key in ("actor_id", "workspace_id"):
                require(valid_id(document[key]))
                report[key] = document[key]
            requests = document["requests"]
            require(type(requests) is list and 1 <= len(requests) <= MAX_REQUESTS)
            report["unattempted_count"] = len(requests)
            detached = []
            seen = set()
            for index, entry in enumerate(requests):
                message_id = operation_id = None
                require(type(entry) is dict and set(entry) ==
                        {"retained_message_id", "operation_id", "input_spec"})
                require(valid_id(entry["retained_message_id"]))
                message_id = entry["retained_message_id"]
                require(type(entry["operation_id"]) is str)
                operation_id = str(contract.operation_uuid(entry["operation_id"]))
                contract.validate_spec(entry["input_spec"])
                input_spec = json.loads(contract.canonical_json(entry["input_spec"]))
                pair = (message_id, operation_id)
                require(pair not in seen)
                seen.add(pair)
                detached.append(dict(retained_message_id=message_id,
                                     operation_id=operation_id, input_spec=input_spec))
            index = message_id = operation_id = None
            stage = "authorization"
            actor = get_user_model().objects.using("default").filter(pk=report["actor_id"]).first()
            workspace = Workspace.objects.using("default").filter(
                pk=report["workspace_id"], owner_id=report["actor_id"]).first()
            require(actor is not None and workspace is not None)
            authorize_owner(actor, workspace)
            for index, entry in enumerate(detached):
                message_id, operation_id = entry["retained_message_id"], entry["operation_id"]
                report["unattempted_count"] = len(detached) - index
                stage = "transaction_context"
                require(top_level())
                stage = "execution"
                report["unattempted_count"] = len(detached) - index - 1
                receipt = producer.produce_retained_job_alert_extraction(
                    actor=actor, workspace=workspace, **entry,
                    extractor_method="job_alert_rules", extractor_version="1")
                # Reporting can fail after commit; execution failures remain uncertain.
                report["completed"].append(dict(index=index, retained_message_id=message_id,
                    operation_id=operation_id, extraction_id=receipt.extraction_id,
                    replay=receipt.replay, output_count=len(receipt.outputs),
                    source_eligible=receipt.source_eligible))
            report["status"] = "completed"
            report["unattempted_count"] = 0
        except Exception as error:
            codes = {"file": "file_error", "preflight": "invalid_request",
                     "authorization": "authorization_error",
                     "transaction_context": "transaction_context_invalid"}
            expected = (stage == "file" and isinstance(error, (OSError, ValueError, UnicodeError, RecursionError))
                        or stage == "preflight" and isinstance(error, (ValueError, RecursionError))
                        or stage == "authorization" and isinstance(error, (ValueError, APIException))
                        or stage == "transaction_context" and isinstance(error, ValueError))
            code = codes[stage] if expected else "execution_error"
            http_status = None
            unknown = not expected
            if stage == "execution" and isinstance(error, APIException):
                try:
                    candidate = error.get_codes()
                    code = candidate if type(candidate) is str and candidate in SAFE_CODES else "domain_error"
                    status = error.status_code
                    http_status = status if type(status) is int and 100 <= status <= 599 else None
                    unknown = False
                except Exception:
                    code, http_status, unknown = "execution_error", None, True
            report["failure"] = dict(stage=stage, index=index, retained_message_id=message_id,
                operation_id=operation_id, code=code, http_status=http_status,
                outcome_may_be_unknown=unknown)
        try:
            self.stdout.write(json.dumps(report, sort_keys=True, separators=(",", ":")))
        except Exception:
            raise CommandError(ERROR_MESSAGE, returncode=1) from None
        if report["status"] == "failed":
            raise CommandError(ERROR_MESSAGE, returncode=1) from None
