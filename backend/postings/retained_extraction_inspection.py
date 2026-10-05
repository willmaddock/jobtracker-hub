"""Bounded SELECT-only evidence inspection; no execution or downstream authority.

Pages are advisory, not snapshots. Valid payloads are bounded by the existing
contract; privileged oversized JSON may be decoded before validation rejects it.
"""
from dataclasses import dataclass

from rest_framework.exceptions import APIException

from . import extraction_contract as contract
from . import retained_extractions as extractions
from .models import RetainedPostingExtraction
from .retained_items import authorize_owner

MAX_ID = 9_223_372_036_854_775_807
MAX_LIMIT = 5


class InvalidExtractionEvidenceNavigation(APIException):
    status_code = 400
    default_code = "invalid_extraction_evidence_navigation"
    default_detail = "Invalid extraction evidence navigation."


@dataclass(frozen=True, slots=True)
class RetainedExtractionEvidenceCursor:
    version: int
    workspace_id: int
    retained_message_id: int
    last_extraction_id: int


@dataclass(frozen=True, slots=True)
class RetainedExtractionEvidenceSource:
    workspace_id: int
    retained_message_id: int
    retained_message_portable_id: str
    representation_version: int
    source_eligible: bool


@dataclass(frozen=True, slots=True)
class RetainedExtractionEvidenceOutput:
    output_id: int
    portable_id: str
    position: int
    source: str
    title: str | None
    company: str | None
    location: str | None
    salary: str | None
    employment_type: str | None


@dataclass(frozen=True, slots=True)
class RetainedExtractionEvidenceOperation:
    extraction_id: int
    operation_id: str
    extractor_method: str
    extractor_version: str
    snapshot_version: int
    input_spec_json: str
    extracted_at: str
    recorded_at: str
    output_count: int
    outputs: tuple[RetainedExtractionEvidenceOutput, ...]


@dataclass(frozen=True, slots=True)
class RetainedExtractionEvidencePage:
    source: RetainedExtractionEvidenceSource
    operations: tuple[RetainedExtractionEvidenceOperation, ...]
    has_more: bool
    next_cursor: RetainedExtractionEvidenceCursor | None
    consistency: str = "advisory"


def read_retained_extraction_evidence(*, actor, workspace, retained_message_id,
                                     cursor=None, limit=2) -> RetainedExtractionEvidencePage:
    authorize_owner(actor, workspace)
    extractions.identity(retained_message_id)
    message = extractions.scoped_source(workspace, retained_message_id, lock=False)
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise InvalidExtractionEvidenceNavigation()
    if cursor is not None:
        if (type(cursor) is not RetainedExtractionEvidenceCursor
                or type(cursor.version) is not int or cursor.version != 1
                or any(type(value) is not int or not 0 < value <= MAX_ID for value in (
                    cursor.workspace_id, cursor.retained_message_id, cursor.last_extraction_id))
                or cursor.workspace_id != message.workspace_id
                or cursor.retained_message_id != message.pk):
            raise InvalidExtractionEvidenceNavigation()
    using = message._state.db
    ids = tuple(RetainedPostingExtraction.objects.using(using)
                .filter(retained_message_id=message.pk,
                        pk__gt=cursor.last_extraction_id if cursor else 0)
                .order_by("pk").values_list("pk", flat=True)[:limit + 1])
    operations = []
    for extraction_id in ids[:limit]:
        row, outputs, envelope = extractions.validate_extraction_batch(extraction_id, message, using=using)
        try:
            recorded_at = contract.timestamp(row.recorded_at.isoformat())
        except (contract.InvalidExtraction, AttributeError):
            raise extractions.PostingExtractionEvidenceInvalid() from None
        operations.append(RetainedExtractionEvidenceOperation(
            extraction_id=row.pk, operation_id=envelope["operation_id"],
            extractor_method=envelope["extractor_method"], extractor_version=envelope["extractor_version"],
            snapshot_version=envelope["snapshot_version"],
            input_spec_json=contract.canonical_json(envelope["input_spec"]).decode("utf-8"),
            extracted_at=envelope["extracted_at"], recorded_at=recorded_at, output_count=len(outputs),
            outputs=tuple(RetainedExtractionEvidenceOutput(output_id=output.pk,
                portable_id=str(output.portable_id), position=output.position, **output.fields)
                for output in outputs)))
    has_more = len(ids) > limit
    next_cursor = (RetainedExtractionEvidenceCursor(1, message.workspace_id, message.pk, ids[limit - 1])
                   if has_more else None)
    return RetainedExtractionEvidencePage(
        RetainedExtractionEvidenceSource(message.workspace_id, message.pk, str(message.portable_id),
            message.representation_version, not message.has_conflict),
        tuple(operations), has_more, next_cursor)
