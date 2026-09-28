"""Sole completed-extraction recorder and scoped reader; no execution or scheduling.

Producers preserve the operation UUID, completion time and complete envelope across
response loss. New UUIDs on retry mean different observations, not exactly-once work.
Locks: Workspace gate -> source -> operation lookup. No later endpoint locks.
"""
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from rest_framework.exceptions import APIException, NotFound

from accounts.models import Workspace
from applications.creation import lock_workspace
from applications.message_relationships import require_eligible_source
from email_sync.models import RetainedMessage
from . import extraction_contract as contract
from .models import RetainedPostingExtraction, RetainedPostingExtractionOutput


class InvalidPostingExtraction(APIException):
    status_code = 400
    default_code = "invalid_posting_extraction"
    default_detail = "Invalid posting extraction."


class ExtractionKeyReused(APIException):
    status_code = 409
    default_code = "idempotency_key_reused"
    default_detail = "Extraction operation key was already used for different evidence."


class RetainedSourceInvalid(APIException):
    status_code = 409
    default_code = "retained_source_invalid"
    default_detail = "Retained source representation is invalid."


@dataclass(frozen=True)
class ExtractionResult:
    operation: RetainedPostingExtraction
    outputs: tuple
    replay: bool
    source_eligible: bool


def authorize(actor, workspace):
    if not actor.is_authenticated or not Workspace.objects.filter(pk=workspace.pk, owner=actor).exists():
        raise NotFound()


def identity(value):
    if type(value) is not int or not 0 < value <= 9223372036854775807:
        raise NotFound()


def scoped_source(workspace, source_id, *, lock=False):
    rows = RetainedMessage.objects.select_related("mailbox")
    if lock:
        rows = rows.select_for_update(of=("self",))
    message = rows.filter(pk=source_id, workspace=workspace, mailbox__workspace=workspace).first()
    if message is None:
        raise NotFound()
    if message.provider != message.mailbox.provider:
        raise NotFound()
    try:
        contract.validate_source_content(message.content, message.representation_version,
                                         message.content_digest, provider=message.provider)
    except contract.InvalidExtraction:
        raise RetainedSourceInvalid() from None
    return message


def outcome(operation, message, replay):
    return ExtractionResult(operation, tuple(operation.outputs.order_by("position")), replay,
                            not message.has_conflict)


def record_posting_extraction(*, actor, workspace, retained_message_id, operation_id,
                              extractor_method, extractor_version, input_spec, extracted_at, outputs):
    authorize(actor, workspace)
    identity(retained_message_id)
    try:
        envelope = contract.validate_envelope(operation_id, extractor_method, extractor_version,
                                               input_spec, extracted_at, outputs)
    except contract.InvalidExtraction:
        raise InvalidPostingExtraction() from None
    with transaction.atomic():
        lock_workspace(actor, workspace)
        message = scoped_source(workspace, retained_message_id, lock=True)
        try:
            contract.resolve_selectors(envelope["input_spec"], message.content)
            fingerprint = contract.replay_digest(envelope, {
                "workspace_id": message.workspace_id, "retained_message_id": message.pk,
                "retained_message_portable_id": str(message.portable_id),
                "representation_version": message.representation_version,
                "content_digest": message.content_digest,
            })
        except contract.InvalidExtraction:
            raise InvalidPostingExtraction() from None
        prior = RetainedPostingExtraction.objects.filter(
            retained_message=message, operation_id=envelope["operation_id"]).first()
        if prior:
            if prior.payload_digest != fingerprint:
                raise ExtractionKeyReused()
            return outcome(prior, message, True)
        require_eligible_source(message)
        row = RetainedPostingExtraction.objects.create(
            retained_message=message, operation_id=contract.operation_uuid(envelope["operation_id"]),
            extractor_method=envelope["extractor_method"], extractor_version=envelope["extractor_version"],
            snapshot_version=envelope["snapshot_version"], input_spec=envelope["input_spec"],
            payload_digest=fingerprint, extracted_at=datetime.fromisoformat(envelope["extracted_at"]))
        for output in envelope["outputs"]:
            RetainedPostingExtractionOutput.objects.create(extraction=row, **output)
        return outcome(row, message, False)


def read_posting_extraction(*, actor, workspace, extraction_id):
    """Authorized inspection, including conflicted sources; never execute parsing."""
    authorize(actor, workspace)
    identity(extraction_id)
    row = RetainedPostingExtraction.objects.filter(pk=extraction_id,
                                                   retained_message__workspace=workspace).first()
    if row is None:
        raise NotFound()
    message = scoped_source(workspace, row.retained_message_id)
    return outcome(row, message, False)
