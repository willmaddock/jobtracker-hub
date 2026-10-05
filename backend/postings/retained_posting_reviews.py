"""Owner review coordination with independent default-database phase commits.

No outer transaction, persistence, retries or compensation. Receipts describe
completed historical operations; the composed reader supplies advisory observations.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from enum import StrEnum
import re
from types import MappingProxyType
from uuid import UUID

from django.db import connections
from rest_framework.exceptions import APIException

from . import extraction_contract as contract
from . import job_posting_allocations as allocation
from . import job_posting_interpretations as arbitration
from . import job_posting_projections as projection
from . import posting_sources as sources
from . import posting_source_corrections as mappings
from . import retained_interpretations as interpretations
from .retained_extractions import identity
from .retained_items import authorize_owner

MAX = 9223372036854775807


class MappingAction(StrEnum):
    ATTACH_EXISTING = "attach_existing"
    ALLOCATE_NEW = "allocate_new"


class Phase(StrEnum):
    MAPPING = "mapping"
    SELECTION = "selection"
    PROJECTION = "projection"


class ProgressStatus(StrEnum):
    COMPLETED = "completed"
    REPLAYED = "replayed"
    FAILED_KNOWN = "failed_known"
    FAILED_OUTCOME_UNKNOWN = "failed_outcome_unknown"
    UNATTEMPTED = "unattempted"
    UNREQUESTED = "unrequested"


class InvalidRetainedPostingReview(APIException):
    status_code = 400
    default_code = "invalid_retained_posting_review"
    default_detail = "Invalid retained posting review request."


class RetainedPostingReviewTransactionContextInvalid(APIException):
    status_code = 400
    default_code = "retained_posting_review_transaction_context_invalid"
    default_detail = "Retained posting review requires top-level default-database autocommit."


@dataclass(frozen=True, slots=True)
class MappingRequest:
    action: str
    target_posting_id: int | None = None
    operation_id: UUID | str | None = None
    expected_interpretation_revision: int | None = None


@dataclass(frozen=True, slots=True)
class SelectionRequest:
    operation_id: UUID | str
    expected_arbitration_revision: int
    expected_interpretation_revision: int
    expected_mapping_revision: int


@dataclass(frozen=True, slots=True)
class ProjectionRequest:
    operation_id: UUID | str
    expected_projection_revision: int
    expected_descriptor_digest: str


@dataclass(frozen=True, slots=True)
class RetainedPostingReviewCommand:
    mapping: MappingRequest
    selection: SelectionRequest | None = None
    projection: ProjectionRequest | None = None


def _require(condition):
    if not condition:
        raise InvalidRetainedPostingReview()


def _revision(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX


def _uuid(value):
    try:
        return contract.operation_uuid(value)
    except contract.InvalidExtraction:
        raise InvalidRetainedPostingReview() from None


def _validated(command):
    _require(type(command) is RetainedPostingReviewCommand)
    m, s, p = command.mapping, command.selection, command.projection
    _require(type(m) is MappingRequest)
    _require(type(m.action) in (str, MappingAction) and m.action in MappingAction._value2member_map_)
    ids = []
    if m.action == MappingAction.ATTACH_EXISTING:
        _require(_revision(m.target_posting_id, 1) and m.operation_id is None
                 and m.expected_interpretation_revision is None)
        m = MappingRequest(MappingAction.ATTACH_EXISTING, target_posting_id=m.target_posting_id)
    else:
        _require(m.target_posting_id is None and _revision(m.expected_interpretation_revision, 1))
        op = _uuid(m.operation_id)
        ids.append(op)
        m = MappingRequest(MappingAction.ALLOCATE_NEW, operation_id=op,
                           expected_interpretation_revision=m.expected_interpretation_revision)
    if s is not None:
        _require(type(s) is SelectionRequest)
        _require(_revision(s.expected_arbitration_revision)
                 and _revision(s.expected_interpretation_revision, 1)
                 and _revision(s.expected_mapping_revision))
        op = _uuid(s.operation_id)
        ids.append(op)
        s = SelectionRequest(op, s.expected_arbitration_revision,
                             s.expected_interpretation_revision, s.expected_mapping_revision)
        if m.action == MappingAction.ALLOCATE_NEW:
            _require(m.expected_interpretation_revision == s.expected_interpretation_revision)
    if p is not None:
        _require(type(p) is ProjectionRequest and s is not None)
        _require(_revision(p.expected_projection_revision)
                 and type(p.expected_descriptor_digest) is str
                 and re.fullmatch(r"[0-9a-f]{64}", p.expected_descriptor_digest) is not None)
        op = _uuid(p.operation_id)
        ids.append(op)
        p = ProjectionRequest(op, p.expected_projection_revision, p.expected_descriptor_digest)
    _require(len(ids) == len(set(ids)))
    return RetainedPostingReviewCommand(m, s, p)


def parse_review_command(value):
    """Strict mapping parser; no coercion other than canonical UUID normalization."""
    def construct(cls, data):
        _require(isinstance(data, Mapping))
        _require(set(data) <= {field.name for field in fields(cls)})
        try:
            return cls(**data)
        except TypeError:
            raise InvalidRetainedPostingReview() from None
    _require(isinstance(value, Mapping) and set(value) <= {"mapping", "selection", "projection"}
             and "mapping" in value)
    return _validated(RetainedPostingReviewCommand(
        construct(MappingRequest, value["mapping"]),
        construct(SelectionRequest, value["selection"]) if value.get("selection") is not None else None,
        construct(ProjectionRequest, value["projection"]) if value.get("projection") is not None else None))


def _top_level():
    connection = connections["default"]
    if connection.in_atomic_block or not connection.get_autocommit():
        raise RetainedPostingReviewTransactionContextInvalid()


def _freeze(value):
    if isinstance(value, str):
        return str(value)
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class DomainErrorSnapshot:
    status_code: int
    codes: object
    detail: object


@dataclass(frozen=True, slots=True)
class MappingReceipt:
    action: MappingAction
    item_id: int
    posting_id: int
    posting_portable_id: UUID
    initial_source_id: int
    actor_id: int
    created_at: datetime
    replay: bool
    allocation: allocation.AllocationRecord | None = None


@dataclass(frozen=True, slots=True)
class SelectionReceipt:
    decision_id: int
    revision: int
    posting_id: int
    item_id: int
    selected_interpretation_id: int
    initial_source_id: int
    mapping_revision: int
    operation_id: UUID
    actor_id: int
    created_at: datetime
    replay: bool


@dataclass(frozen=True, slots=True)
class ProjectionReceipt:
    event_id: int
    revision: int
    posting_id: int
    arbitration_decision_id: int
    arbitration_revision: int
    operation_id: UUID
    expected_descriptor_digest: str
    actor_id: int
    created_at: datetime
    replay: bool


@dataclass(frozen=True, slots=True)
class PhaseProgress:
    phase: Phase
    status: ProgressStatus
    receipt: MappingReceipt | SelectionReceipt | ProjectionReceipt | None


@dataclass(frozen=True, slots=True)
class ReviewFailure:
    item_id: int
    requested_mapping_action: MappingAction
    failed_phase: Phase
    failure_stage: str
    phase_progress: tuple[PhaseProgress, ...]
    outcome_may_be_unknown: bool
    domain_error: DomainErrorSnapshot | None


class RetainedPostingReviewPhaseError(Exception):
    def __init__(self, context):
        self.context = context
        super().__init__(f"Retained posting review stopped in {context.failed_phase} ({context.failure_stage}).")


@dataclass(frozen=True, slots=True)
class RetainedPostingReviewResult:
    item_id: int
    requested_mapping_action: MappingAction
    posting_id: int
    posting_portable_id: UUID
    phases: tuple[PhaseProgress, ...]


def _mapping_receipt(result, action):
    if action == MappingAction.ALLOCATE_NEW:
        row = result.allocation
        return MappingReceipt(action, row.item_id, row.posting_id, row.posting_portable_id,
                              row.initial_source_id, row.actor_id, row.created_at, result.replay, row)
    row, posting = result.initial_source, result.posting
    return MappingReceipt(action, row.item_id, posting.pk, posting.portable_id,
                          row.pk, row.actor_id, row.created_at, result.replay)


def _selection_receipt(result, item_id):
    row = result.decision
    return SelectionReceipt(row.pk, row.revision, row.posting_id, item_id,
        row.selected_interpretation_id, row.initial_source_id, row.mapping_revision,
        row.operation_id, row.actor_id, row.created_at, result.replay)


def _projection_receipt(result, selection):
    row = result.event
    return ProjectionReceipt(row.pk, row.revision, row.posting_id, row.arbitration_decision_id,
        selection.revision, row.operation_id, row.expected_descriptor_digest,
        row.actor_id, row.created_at, result.replay)


def review_retained_posting(*, actor, workspace, item_id, command):
    _top_level()
    authorize_owner(actor, workspace)
    identity(item_id)
    command = _validated(command)
    m, s, p = command.mapping, command.selection, command.projection
    progress = [PhaseProgress(phase, ProgressStatus.UNATTEMPTED if requested else ProgressStatus.UNREQUESTED, None)
                for phase, requested in ((Phase.MAPPING, True), (Phase.SELECTION, s is not None),
                                         (Phase.PROJECTION, p is not None))]

    def run(index, call, detach):
        phase = progress[index].phase
        try:
            result = call()
        except Exception as exc:
            known = isinstance(exc, APIException)
            progress[index] = PhaseProgress(phase, ProgressStatus.FAILED_KNOWN if known
                                           else ProgressStatus.FAILED_OUTCOME_UNKNOWN, None)
            domain = DomainErrorSnapshot(exc.status_code, _freeze(exc.get_codes()), _freeze(exc.detail)) if known else None
            raise RetainedPostingReviewPhaseError(ReviewFailure(item_id, m.action, phase, "command",
                tuple(progress), not known, domain)) from exc
        # Successful canonical return means its top-level transaction has exited.
        # Set progress before detachment, which must never issue database queries.
        progress[index] = PhaseProgress(phase, ProgressStatus.REPLAYED if result.replay
                                       else ProgressStatus.COMPLETED, None)
        try:
            receipt = detach(result)
        except Exception as exc:
            domain = (DomainErrorSnapshot(exc.status_code, _freeze(exc.get_codes()), _freeze(exc.detail))
                      if isinstance(exc, APIException) else None)
            raise RetainedPostingReviewPhaseError(ReviewFailure(item_id, m.action, phase, "receipt",
                tuple(progress), False, domain)) from exc
        progress[index] = PhaseProgress(phase, progress[index].status, receipt)
        return receipt

    if m.action == MappingAction.ATTACH_EXISTING:
        call = lambda: sources.attach_posting_source(actor=actor, workspace=workspace,
                                                      item_id=item_id, posting_id=m.target_posting_id)
    else:
        call = lambda: allocation.allocate_job_posting(actor=actor, workspace=workspace, item_id=item_id,
            operation_id=m.operation_id, expected_interpretation_revision=m.expected_interpretation_revision)
    mapped = run(0, call, lambda result: _mapping_receipt(result, m.action))
    if s is not None:
        selected = run(1, lambda: arbitration.decide_job_posting_interpretation(actor=actor,
            workspace=workspace, posting_id=mapped.posting_id, operation_id=s.operation_id,
            expected_revision=s.expected_arbitration_revision, mode="select", item_id=item_id,
            expected_interpretation_revision=s.expected_interpretation_revision,
            expected_mapping_revision=s.expected_mapping_revision), lambda result: _selection_receipt(result, item_id))
        if p is not None:
            run(2, lambda: projection.project_job_posting_descriptors(actor=actor, workspace=workspace,
                posting_id=mapped.posting_id, operation_id=p.operation_id,
                expected_projection_revision=p.expected_projection_revision,
                expected_arbitration_revision=selected.revision,
                expected_descriptor_digest=p.expected_descriptor_digest),
                lambda result: _projection_receipt(result, selected))
    return RetainedPostingReviewResult(item_id, m.action, mapped.posting_id,
                                      mapped.posting_portable_id, tuple(progress))


@dataclass(frozen=True, slots=True)
class ItemInterpretationObservation:
    item_id: int
    revision: int
    state: str
    decision_id: int | None
    selected_output_id: int | None
    recorded_membership_revision: int | None
    current_membership_revision: int | None
    source_eligible: bool


@dataclass(frozen=True, slots=True)
class MappingObservation:
    item_id: int
    initial_source_id: int | None
    initial_posting_id: int | None
    effective_revision: int | None
    effective_posting_id: int | None
    source_eligible: bool


@dataclass(frozen=True, slots=True)
class ArbitrationObservation:
    posting_id: int
    observed_mapping_revision: int
    revision: int
    state: str
    selected_item_id: int | None
    stale_reasons: tuple


@dataclass(frozen=True, slots=True)
class ProjectionObservation:
    posting_id: int
    observed_mapping_revision: int
    revision: int
    state: str
    current_arbitration_revision: int
    descriptor_snapshot: object
    descriptor_digest: str
    drift: bool
    stale_reasons: tuple


@dataclass(frozen=True, slots=True)
class RetainedPostingReviewState:
    item_id: int
    interpretation: ItemInterpretationObservation
    mapping: MappingObservation
    allocation: allocation.AllocationRecord | None
    arbitration: ArbitrationObservation | None
    projection: ProjectionObservation | None
    final_mapping: MappingObservation
    consistency: str
    changes_detected: bool


def _mapping_observation(value):
    initial = value.initial_source
    return MappingObservation(value.item.pk, initial.pk if initial else None,
        initial.posting_id if initial else None, value.effective_revision,
        value.effective_posting.pk if value.effective_posting else None, value.source_eligible)


def read_retained_posting_review_state(*, actor, workspace, item_id):
    _top_level()
    authorize_owner(actor, workspace)
    identity(item_id)
    args = dict(actor=actor, workspace=workspace, item_id=item_id)
    value = interpretations.read_posting_interpretation(**args)
    interpreted = ItemInterpretationObservation(item_id, value.revision, value.state,
        value.latest_decision.pk if value.latest_decision else None,
        value.selected_output.pk if value.selected_output else None,
        value.recorded_membership_revision, value.current_membership_revision, value.source_eligible)
    mapped = _mapping_observation(mappings.read_effective_posting_source(**args))
    allocated = allocation.read_retained_item_allocation(**args).allocation
    selected, projected = None, None
    if mapped.effective_posting_id is not None:
        target = dict(actor=actor, workspace=workspace, posting_id=mapped.effective_posting_id)
        value = arbitration.read_job_posting_interpretation(**target)
        selected = ArbitrationObservation(value.posting.pk, mapped.effective_revision,
            value.revision, value.state, value.selected_item.pk if value.selected_item else None,
            tuple(value.stale_reasons))
        value = projection.read_job_posting_projection(**target)
        projected = ProjectionObservation(value.posting.pk, mapped.effective_revision,
            value.revision, value.state, value.current_arbitration_revision,
            _freeze(value.current_descriptor_snapshot), value.current_descriptor_digest,
            value.descriptor_drift, tuple(value.stale_reasons))
    final = _mapping_observation(mappings.read_effective_posting_source(**args))
    changed = ((mapped.initial_source_id, mapped.effective_revision, mapped.effective_posting_id)
               != (final.initial_source_id, final.effective_revision, final.effective_posting_id)
               or (selected is not None and selected.revision != projected.current_arbitration_revision))
    return RetainedPostingReviewState(item_id, interpreted, mapped, allocated, selected,
                                     projected, final, "advisory", changed)
