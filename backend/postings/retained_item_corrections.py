"""Append-only effective membership. Initial assertions retain historical meaning.

Canonical writes serialize Workspace -> source. No retries or endpoint locks.
Readers capture a revision prefix; concurrent appends cannot rewrite that prefix.
"""
from dataclasses import dataclass

from django.db import router, transaction
from django.db.models import Count, Min, Max, Q
from rest_framework.exceptions import APIException, NotFound

from applications.creation import lock_workspace
from applications.message_relationships import require_eligible_source
from .extraction_contract import InvalidExtraction, operation_uuid
from .models import RetainedPostingItem as Item, RetainedPostingItemAssociation as Association
from .models import RetainedPostingItemCorrection as Correction
from .retained_items import authorize_owner, output_in_workspace, item_in_source, existing_association
from .retained_extractions import identity, scoped_source

MAX_REVISION = 9223372036854775807
METHOD = "explicit_owner"
DECISION_VERSION = 1


class InvalidCorrection(APIException):
    status_code = 400
    default_code = "invalid_posting_item_correction"
    default_detail = "Invalid posting item correction."


class CorrectionConflict(APIException):
    status_code = 409
    default_code = "posting_association_history_invalid"
    default_detail = "Posting association history is invalid."


def conflict(code):
    raise CorrectionConflict("Posting item correction cannot be applied.", code=code)


@dataclass(frozen=True)
class Chain:
    revision: int
    item: Item | None
    decision: object
    source_id: int


@dataclass(frozen=True)
class EffectiveState:
    output: object
    initial_association: Association | None
    effective_item: Item | None
    effective_revision: int | None
    decision_type: str | None
    effective_decision: object | None
    source_eligible: bool


@dataclass(frozen=True)
class CorrectionResult:
    correction: Correction
    replay: bool
    current: EffectiveState


@dataclass(frozen=True)
class CorrectionHistory:
    corrections: tuple
    through_revision: int | None
    next_cursor: tuple | None
    source_eligible: bool


def resolve_chain(initial, *, using=None, through=None):
    """Validate every persisted decision in the captured prefix without loading it.

    Positive unique revisions plus count=max/min=1 prove contiguity. Predicates
    validate older targets too. Privileged coherent history rewrites are not detectable.
    """
    using = using or router.db_for_read(Association)
    initial = Association.objects.using(using).select_related("item", "output__extraction").filter(pk=initial.pk).first()
    if initial is None:
        raise CorrectionConflict()
    source_id = initial.output.extraction.retained_message_id
    if initial.item.retained_message_id != source_id:
        raise CorrectionConflict()
    rows = Correction.objects.using(using).filter(initial_association=initial)
    if through is not None:
        if type(through) is not int or not 0 <= through <= MAX_REVISION:
            raise CorrectionConflict()
        rows = rows.filter(revision__lte=through)
    stats = rows.aggregate(count=Count("pk"), first=Min("revision"), last=Max("revision"))
    revision = stats["last"] if stats["count"] else 0
    if (stats["count"] and (stats["first"] != 1 or stats["count"] != revision)
            or not 0 <= revision <= MAX_REVISION or (through is not None and revision != through)):
        raise CorrectionConflict()
    # Freeze all remaining queries to the aggregate's boundary: a concurrent append
    # is outside this result, not inconsistent history.
    rows = rows.filter(revision__lte=revision)
    valid = (Q(method=METHOD, decision_version=DECISION_VERSION)
             & (Q(mode="withdraw", target_item__isnull=True)
                | Q(mode="associate", target_item__isnull=False, target_item__retained_message_id=source_id)))
    if rows.exclude(valid).exists():
        raise CorrectionConflict()
    if revision == 0:
        return Chain(0, initial.item, initial, source_id)
    latest = rows.select_related("target_item").filter(revision=revision).first()
    if latest is None:
        raise CorrectionConflict()
    return Chain(revision, latest.target_item, latest, source_id)


def state(output, initial, message, chain=None):
    if initial is None:
        return EffectiveState(output, None, None, None, None, None, not message.has_conflict)
    chain = chain or resolve_chain(initial)
    return EffectiveState(output, initial, chain.item, chain.revision,
                          "initial" if chain.revision == 0 else "correction", chain.decision,
                          not message.has_conflict)


def endpoints(workspace, output_id, *, lock=False):
    output = output_in_workspace(workspace, output_id)
    message = scoped_source(workspace, output.extraction.retained_message_id, lock=lock)
    initial = existing_association(output, message)
    return output, initial, message


def correct_posting_item_association(*, actor, workspace, output_id, operation_id,
                                     expected_revision, mode, target_item_id=None):
    authorize_owner(actor, workspace)
    identity(output_id)
    try:
        operation_id = operation_uuid(operation_id)
    except InvalidExtraction:
        raise InvalidCorrection() from None
    if (type(expected_revision) is not int or not 0 <= expected_revision <= MAX_REVISION
            or type(mode) is not str or mode not in Correction.Mode.values):
        raise InvalidCorrection()
    if mode == "associate":
        if type(target_item_id) is not int or not 0 < target_item_id <= MAX_REVISION:
            raise InvalidCorrection()
    elif target_item_id is not None:
        raise InvalidCorrection()
    with transaction.atomic():
        lock_workspace(actor, workspace)
        output, initial, message = endpoints(workspace, output_id, lock=True)
        if initial is None:
            conflict("initial_association_required")
        target = item_in_source(message, target_item_id) if mode == "associate" else None
        prior = Correction.objects.filter(initial_association=initial, operation_id=operation_id).first()
        if prior is not None and (prior.mode != mode or prior.target_item_id != target_item_id
                or prior.revision - 1 != expected_revision or prior.method != METHOD
                or prior.decision_version != DECISION_VERSION):
            conflict("idempotency_key_reused")
        chain = resolve_chain(initial, using=router.db_for_write(Correction))
        if prior is not None:
            return CorrectionResult(prior, True, state(output, initial, message, chain))
        if expected_revision != chain.revision:
            conflict("stale_revision")
        require_eligible_source(message)
        if target_item_id == (chain.item.pk if chain.item else None):
            conflict("posting_association_unchanged")
        if chain.revision == MAX_REVISION:
            conflict("posting_correction_revision_exhausted")
        row = Correction.objects.create(initial_association=initial, operation_id=operation_id,
            revision=chain.revision + 1, mode=mode, target_item=target, actor=actor,
            method=METHOD, decision_version=DECISION_VERSION)
        return CorrectionResult(row, False, state(output, initial, message,
            Chain(row.revision, target, row, message.pk)))


def read_effective_posting_item_association(*, actor, workspace, output_id):
    authorize_owner(actor, workspace)
    identity(output_id)
    output, initial, message = endpoints(workspace, output_id)
    return state(output, initial, message)


def list_posting_item_corrections(*, actor, workspace, output_id, limit=100, cursor=None):
    """Cursor: (output ID, initial association ID, through revision, last revision)."""
    authorize_owner(actor, workspace)
    identity(output_id)
    if type(limit) is not int or not 1 <= limit <= 200:
        raise InvalidCorrection()
    output, initial, message = endpoints(workspace, output_id)
    through, last = None, 0
    if cursor is not None:
        if (type(cursor) is not tuple or len(cursor) != 4
                or any(type(v) is not int or not 0 <= v <= MAX_REVISION for v in cursor)
                or initial is None or cursor[:2] != (output.pk, initial.pk)
                or cursor[3] > cursor[2]):
            raise InvalidCorrection()
        through, last = cursor[2:]
        # An invented future boundary is malformed navigation, not stored corruption.
        if through and not Correction.objects.filter(initial_association=initial, revision=through).exists():
            raise InvalidCorrection()
    if initial is None:
        return CorrectionHistory((), None, None, not message.has_conflict)
    chain = resolve_chain(initial, through=through)
    through = chain.revision
    rows = tuple(Correction.objects.filter(initial_association=initial, revision__gt=last,
                 revision__lte=through).order_by("revision")[:limit + 1])
    page = rows[:limit]
    next_cursor = (output.pk, initial.pk, through, page[-1].revision) if len(rows) > limit else None
    return CorrectionHistory(page, through, next_cursor, not message.has_conflict)
