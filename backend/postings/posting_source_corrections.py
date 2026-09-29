"""Append-only effective item-to-posting mapping. Initial assertions retain historical meaning.

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
from .models import RetainedPostingItem as Item, PostingSource, JobPosting
from .models import PostingSourceCorrection as Correction
from .retained_items import authorize_owner
from .retained_extractions import identity
from .posting_sources import scoped_item, scoped_posting, validate_initial, PostingSourceConflict

MAX_REVISION = 9223372036854775807
METHOD = "explicit_owner"
DECISION_VERSION = 1


class InvalidPostingSourceCorrection(APIException):
    status_code = 400
    default_code = "invalid_posting_source_correction"
    default_detail = "Invalid posting source correction."


class PostingSourceCorrectionConflict(APIException):
    status_code = 409
    default_code = "posting_source_history_invalid"
    default_detail = "Posting source history is invalid."


def conflict(code):
    raise PostingSourceCorrectionConflict("Posting source correction cannot be applied.", code=code)


@dataclass(frozen=True)
class Chain:
    revision: int
    posting: JobPosting | None
    decision: object
    workspace_id: int


@dataclass(frozen=True)
class EffectiveState:
    item: Item
    initial_source: PostingSource | None
    effective_posting: JobPosting | None
    effective_revision: int | None
    decision_type: str | None
    effective_decision: object | None
    source_eligible: bool
    can_append_correction: bool


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
    using = using or router.db_for_read(PostingSource)
    initial = PostingSource.objects.using(using).select_related(
        "item__retained_message__mailbox", "posting__account").filter(pk=initial.pk).first()
    if initial is None:
        raise PostingSourceCorrectionConflict()
    message = initial.item.retained_message
    workspace_id = message.workspace_id
    # Alias-aware persisted validation also serves ordinary model insertion.
    # Content admission/current-owner authorization remain service responsibilities.
    if (message.mailbox.workspace_id != workspace_id or message.provider != message.mailbox.provider
            or initial.posting.workspace_id != workspace_id
            or initial.posting.account.workspace_id != workspace_id):
        raise NotFound()
    if initial.method != "explicit_owner" or initial.decision_version != 1:
        raise PostingSourceConflict()
    rows = Correction.objects.using(using).filter(initial_source=initial)
    if through is not None:
        if type(through) is not int or not 0 <= through <= MAX_REVISION:
            raise PostingSourceCorrectionConflict()
        rows = rows.filter(revision__lte=through)
    stats = rows.aggregate(count=Count("pk"), first=Min("revision"), last=Max("revision"))
    revision = stats["last"] if stats["count"] else 0
    if (stats["count"] and (stats["first"] != 1 or stats["count"] != revision)
            or not 0 <= revision <= MAX_REVISION or (through is not None and revision != through)):
        raise PostingSourceCorrectionConflict()
    # Freeze all remaining queries to the aggregate's boundary: a concurrent append
    # is outside this result, not inconsistent history.
    rows = rows.filter(revision__lte=revision)
    valid = (Q(method=METHOD, decision_version=DECISION_VERSION)
             & (Q(mode="withdraw", target_posting__isnull=True)
                | Q(mode="associate", target_posting__isnull=False, target_posting__workspace_id=workspace_id,
                    target_posting__account__workspace_id=workspace_id)))
    if rows.exclude(valid).exists():
        raise PostingSourceCorrectionConflict()
    if revision == 0:
        return Chain(0, initial.posting, initial, workspace_id)
    latest = rows.select_related("target_posting").filter(revision=revision).first()
    if latest is None:
        raise PostingSourceCorrectionConflict()
    return Chain(revision, latest.target_posting, latest, workspace_id)


def state(item, initial, message, chain=None):
    if initial is None:
        return EffectiveState(item, None, None, None, None, None, not message.has_conflict, False)
    chain = chain or resolve_chain(initial)
    return EffectiveState(item, initial, chain.posting, chain.revision,
                          "initial" if chain.revision == 0 else "correction", chain.decision,
                          not message.has_conflict,
                          not message.has_conflict and chain.revision < MAX_REVISION)


def endpoints(workspace, item_id, *, lock=False):
    item, message = scoped_item(workspace, item_id, lock=lock)
    initial = PostingSource.objects.filter(item=item).first()
    if initial is not None:
        validate_initial(workspace, initial)
    return item, initial, message


def correct_posting_source(*, actor, workspace, item_id, operation_id,
                           expected_revision, mode, target_posting_id=None) -> CorrectionResult:
    authorize_owner(actor, workspace)
    identity(item_id)
    try:
        operation_id = operation_uuid(operation_id)
    except InvalidExtraction:
        raise InvalidPostingSourceCorrection() from None
    if (type(expected_revision) is not int or not 0 <= expected_revision <= MAX_REVISION
            or type(mode) is not str or mode not in Correction.Mode.values):
        raise InvalidPostingSourceCorrection()
    if mode == "associate":
        if type(target_posting_id) is not int or not 0 < target_posting_id <= MAX_REVISION:
            raise InvalidPostingSourceCorrection()
    elif target_posting_id is not None:
        raise InvalidPostingSourceCorrection()
    with transaction.atomic():
        lock_workspace(actor, workspace)
        item, initial, message = endpoints(workspace, item_id, lock=True)
        if initial is None:
            conflict("initial_posting_source_required")
        target = scoped_posting(workspace, target_posting_id) if mode == "associate" else None
        prior = Correction.objects.filter(initial_source=initial, operation_id=operation_id).first()
        if prior is not None and (prior.mode != mode or prior.target_posting_id != target_posting_id
                or prior.revision - 1 != expected_revision or prior.method != METHOD
                or prior.decision_version != DECISION_VERSION):
            conflict("idempotency_key_reused")
        chain = resolve_chain(initial, using=router.db_for_write(Correction))
        if prior is not None:
            return CorrectionResult(prior, True, state(item, initial, message, chain))
        if expected_revision != chain.revision:
            conflict("stale_revision")
        require_eligible_source(message)
        if target_posting_id == (chain.posting.pk if chain.posting else None):
            conflict("posting_source_unchanged")
        if chain.revision == MAX_REVISION:
            conflict("posting_source_revision_exhausted")
        row = Correction.objects.create(initial_source=initial, operation_id=operation_id,
            revision=chain.revision + 1, mode=mode, target_posting=target, actor=actor,
            method=METHOD, decision_version=DECISION_VERSION)
        return CorrectionResult(row, False, state(item, initial, message,
            Chain(row.revision, target, row, message.workspace_id)))


def read_effective_posting_source(*, actor, workspace, item_id) -> EffectiveState:
    authorize_owner(actor, workspace)
    identity(item_id)
    item, initial, message = endpoints(workspace, item_id)
    return state(item, initial, message)


def list_posting_source_corrections(*, actor, workspace, item_id, limit=100, cursor=None) -> CorrectionHistory:
    """Cursor: (item ID, initial PostingSource ID, through revision, last revision)."""
    authorize_owner(actor, workspace)
    identity(item_id)
    if type(limit) is not int or not 1 <= limit <= 200:
        raise InvalidPostingSourceCorrection()
    item, initial, message = endpoints(workspace, item_id)
    through, last = None, 0
    if cursor is not None:
        if (type(cursor) is not tuple or len(cursor) != 4
                or any(type(v) is not int or not 0 <= v <= MAX_REVISION for v in cursor)
                or initial is None or cursor[:2] != (item.pk, initial.pk)
                or cursor[3] > cursor[2]):
            raise InvalidPostingSourceCorrection()
        through, last = cursor[2:]
        # An invented future boundary is malformed navigation, not stored corruption.
        if through and not Correction.objects.filter(initial_source=initial, revision=through).exists():
            raise InvalidPostingSourceCorrection()
    if initial is None:
        return CorrectionHistory((), None, None, not message.has_conflict)
    chain = resolve_chain(initial, through=through)
    through = chain.revision
    rows = tuple(Correction.objects.filter(initial_source=initial, revision__gt=last,
                 revision__lte=through).order_by("revision")[:limit + 1])
    page = rows[:limit]
    next_cursor = (item.pk, initial.pk, through, page[-1].revision) if len(rows) > limit else None
    return CorrectionHistory(page, through, next_cursor, not message.has_conflict)
