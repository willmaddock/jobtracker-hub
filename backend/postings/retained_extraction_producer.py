"""Explicit synchronous retained-text extraction, ending at completed evidence.

Workspace -> source locks stay held through parsing and nested recording. Replay
uses validated historical outputs, never current parser behavior or a new clock.
Contention is exposed; rolled-back execution may run again on explicit retry.
"""
from dataclasses import dataclass
import json

from django.db import transaction
from django.utils import timezone

from applications.creation import lock_workspace
from applications.message_relationships import require_eligible_source
from . import extraction_contract as contract
from .extraction import extract_postings
from .models import RetainedPostingExtraction
from .retained_items import authorize_owner
from .retained_extractions import (ExtractionKeyReused, InvalidPostingExtraction,
    identity, scoped_source, record_posting_extraction, validate_extraction_batch)


@dataclass(frozen=True)
class RetainedExtractionOutputReceipt:
    output_id: int
    portable_id: str
    position: int
    source: str
    title: str | None
    company: str | None
    location: str | None
    salary: str | None
    employment_type: str | None


@dataclass(frozen=True)
class RetainedJobAlertExtractionReceipt:
    workspace_id: int
    retained_message_id: int
    retained_message_portable_id: str
    extraction_id: int
    operation_id: str
    extractor_method: str
    extractor_version: str
    snapshot_version: int
    input_spec_json: str
    payload_digest: str
    completed_at: str
    recorded_at: str
    outputs: tuple[RetainedExtractionOutputReceipt, ...]
    replay: bool
    source_eligible: bool


def receipt(result, message):
    row = result.operation
    return RetainedJobAlertExtractionReceipt(
        workspace_id=message.workspace_id, retained_message_id=message.pk,
        retained_message_portable_id=str(message.portable_id), extraction_id=row.pk,
        operation_id=str(row.operation_id), extractor_method=row.extractor_method,
        extractor_version=row.extractor_version, snapshot_version=row.snapshot_version,
        input_spec_json=contract.canonical_json(row.input_spec).decode('utf-8'),
        payload_digest=row.payload_digest,
        completed_at=contract.timestamp(row.extracted_at.isoformat()),
        recorded_at=contract.timestamp(row.recorded_at.isoformat()),
        outputs=tuple(RetainedExtractionOutputReceipt(output_id=o.pk,
            portable_id=str(o.portable_id), position=o.position, **o.fields) for o in result.outputs),
        replay=result.replay, source_eligible=result.source_eligible)


def produce_retained_job_alert_extraction(*, actor, workspace, retained_message_id,
    operation_id, input_spec, extractor_method='job_alert_rules',
    extractor_version='1') -> RetainedJobAlertExtractionReceipt:
    """New work executes v1 once per successful transaction; replay never parses.

    Within a caller-owned transaction, the receipt remains subject to its commit.
    No downstream identity or eligibility permission is conferred by this receipt.
    """
    authorize_owner(actor, workspace)
    identity(retained_message_id)
    try:
        operation_id = contract.operation_uuid(operation_id)
        contract.require(type(extractor_method) is str and type(extractor_version) is str)
        contract.require((extractor_method, extractor_version) ==
                         (contract.EXTRACTOR_METHOD, contract.EXTRACTOR_VERSION))
        contract.validate_spec(input_spec)
        input_spec = json.loads(contract.canonical_json(input_spec))
    except contract.InvalidExtraction:
        raise InvalidPostingExtraction() from None
    with transaction.atomic():
        lock_workspace(actor, workspace)
        message = scoped_source(workspace, retained_message_id, lock=True)
        prior = RetainedPostingExtraction.objects.filter(
            retained_message=message, operation_id=operation_id).first()
        if prior is not None:
            _, _, historical = validate_extraction_batch(prior.pk, message, using=prior._state.db)
        try:
            arguments = contract.resolve_selectors(input_spec, message.content)
        except contract.InvalidExtraction:
            raise InvalidPostingExtraction() from None
        if prior is not None:
            if (historical['input_spec'] != input_spec or
                historical['extractor_method'] != extractor_method or
                historical['extractor_version'] != extractor_version):
                raise ExtractionKeyReused()
            outputs = [o['fields'] for o in historical['outputs']]
            completed_at = historical['extracted_at']
        else:
            require_eligible_source(message)
            outputs = extract_postings(*arguments)
            completed_at = timezone.now().isoformat()
        result = record_posting_extraction(actor=actor, workspace=workspace,
            retained_message_id=retained_message_id, operation_id=operation_id,
            extractor_method=extractor_method, extractor_version=extractor_version,
            input_spec=input_spec, extracted_at=completed_at, outputs=outputs)
        return receipt(result, message)
