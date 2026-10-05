"""Explicit whole-output interpretation, independent of posting mapping/projection.

Canonical commands and coherent readers serialize Workspace -> retained source.
History captures a revision prefix. Timestamps never order authority; no retries.
"""
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import router, transaction
from django.db.models import Count, Min, Max
from rest_framework.exceptions import APIException, NotFound

from applications.creation import lock_workspace
from applications.message_relationships import require_eligible_source
from email_sync.models import RetainedMessage
from . import extraction_contract as contract
from .models import RetainedPostingItem as Item
from .models import RetainedPostingExtractionOutput as Output, RetainedPostingItemAssociation as Association
from .models import RetainedPostingInterpretationDecision as Decision
from .retained_extractions import (identity, scoped_source, RetainedSourceInvalid,
    validate_extraction_batch, PostingExtractionEvidenceInvalid)
from .retained_items import authorize_owner
from .retained_item_corrections import resolve_chain as membership_chain, CorrectionConflict

MAX_REVISION = 9223372036854775807
METHOD = "explicit_owner"
DECISION_VERSION = 1


class InvalidPostingInterpretation(APIException):
    status_code = 400
    default_code = "invalid_posting_interpretation"
    default_detail = "Invalid posting interpretation."


class PostingInterpretationConflict(APIException):
    status_code = 409
    default_code = "posting_interpretation_history_invalid"
    default_detail = "Posting interpretation history is invalid."


class PostingInterpretationEvidenceInvalid(APIException):
    status_code = 409
    default_code = "posting_interpretation_evidence_invalid"
    default_detail = "Posting interpretation evidence is invalid."


def conflict(code):
    raise PostingInterpretationConflict("Posting interpretation cannot be applied.", code=code)


def _revision(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX_REVISION


@dataclass(frozen=True)
class Chain:
    revision: int
    latest: Decision | None


@dataclass(frozen=True)
class EffectiveInterpretation:
    item: Item
    revision: int
    latest_decision: Decision | None
    state: str
    selected_output: Output | None
    recorded_membership_revision: int | None
    current_membership_revision: int | None
    applicable_output: Output | None
    source_eligible: bool
    can_append_decision: bool


@dataclass(frozen=True)
class InterpretationResult:
    decision: Decision
    replay: bool
    current: EffectiveInterpretation


@dataclass(frozen=True)
class InterpretationHistory:
    decisions: tuple
    through_revision: int
    next_cursor: tuple | None
    source_eligible: bool


def _validate_source(message):
    if (message.workspace_id != message.mailbox.workspace_id
            or message.provider != message.mailbox.provider):
        raise NotFound()
    try:
        contract.validate_source_content(message.content, message.representation_version,
                                         message.content_digest, provider=message.provider)
    except contract.InvalidExtraction:
        raise RetainedSourceInvalid() from None


def _validate_extraction(extraction_id, message, using, cache):
    """Keep interpretation caching/errors around the shared batch authority."""
    if extraction_id in cache:
        return
    _validate_source(message)
    try:
        validate_extraction_batch(extraction_id, message, using=using)
    except PostingExtractionEvidenceInvalid:
        raise PostingInterpretationEvidenceInvalid() from None
    cache.add(extraction_id)


def _membership(association, using, through=None):
    if (association.method != "explicit_owner" or association.decision_version != 1
            or association.mode not in Association.Mode.values):
        raise CorrectionConflict()
    return membership_chain(association, using=using, through=through)


def _validate_decision(row, item, message, using, cache):
    try:
        contract.operation_uuid(row.operation_id)
    except contract.InvalidExtraction:
        raise PostingInterpretationConflict() from None
    if (row.item_id != item.pk or not _revision(row.revision, 1)
            or row.method != METHOD or row.decision_version != DECISION_VERSION):
        raise PostingInterpretationConflict()
    if row.mode == "withdraw":
        if row.selected_association_id is not None or row.membership_revision is not None:
            raise PostingInterpretationConflict()
        return
    if (row.mode != "select" or row.selected_association_id is None
            or not _revision(row.membership_revision)):
        raise PostingInterpretationConflict()
    association = Association.objects.using(using).select_related("output__extraction").filter(
        pk=row.selected_association_id).first()
    if association is None or association.output.extraction.retained_message_id != message.pk:
        raise PostingInterpretationConflict()
    witness = _membership(association, using, through=row.membership_revision)
    if witness.item is None or witness.item.pk != item.pk:
        raise PostingInterpretationConflict()
    _validate_extraction(association.output.extraction_id, message, using, cache)
    # Populate only after persisted validation, never trust caller relation caches.
    row.selected_association = association


def resolve_chain(item, message, *, using, through=None, cache=None):
    cache = set() if cache is None else cache
    rows = Decision.objects.using(using).filter(item=item)
    if through is not None:
        if not _revision(through):
            raise PostingInterpretationConflict()
        rows = rows.filter(revision__lte=through)
    stats = rows.aggregate(count=Count("pk"), first=Min("revision"), last=Max("revision"))
    revision = stats["last"] if stats["count"] else 0
    if (not _revision(revision) or (through is not None and revision != through)
            or (stats["count"] and (stats["first"] != 1 or stats["count"] != revision))):
        raise PostingInterpretationConflict()
    latest = None
    for row in rows.filter(revision__lte=revision).order_by("revision").iterator():
        _validate_decision(row, item, message, using, cache)
        latest = row
    return Chain(revision, latest)


def _state(item, message, chain, using):
    latest = chain.latest
    state, output, recorded, current, applicable = "unresolved", None, None, None, None
    if latest is not None:
        state = "withdrawn"
        if latest.mode == "select":
            association = latest.selected_association
            output, recorded = association.output, latest.membership_revision
            membership = _membership(association, using)
            current = membership.revision
            state = "stale"
            if current == recorded:
                if membership.item is None or membership.item.pk != item.pk:
                    raise PostingInterpretationConflict()
                state, applicable = "selected", output
    return EffectiveInterpretation(item, chain.revision, latest, state, output, recorded, current,
        applicable, not message.has_conflict, not message.has_conflict and chain.revision < MAX_REVISION)


def _endpoints(workspace, item_id, *, lock=True):
    item = Item.objects.filter(pk=item_id, retained_message__workspace=workspace).first()
    if item is None:
        raise NotFound()
    return item, scoped_source(workspace, item.retained_message_id, lock=lock)


def _unchanged(latest, association_id, witness):
    if association_id is None:
        return latest is None or latest.mode == "withdraw"
    return (latest is not None and latest.mode == "select"
            and latest.selected_association_id == association_id and latest.membership_revision == witness)


def validate_insertion(row, using):
    """Alias-aware ordinary model guard; canonical authorization lives in commands."""
    item = Item.objects.using(using).filter(pk=row.item_id).first()
    if item is None or not get_user_model().objects.using(using).filter(pk=row.actor_id).exists():
        raise PostingInterpretationConflict()
    message = RetainedMessage.objects.using(using).select_related("mailbox").get(pk=item.retained_message_id)
    _validate_source(message)
    cache = set()
    chain = resolve_chain(item, message, using=using, cache=cache)
    _validate_decision(row, item, message, using, cache)
    if row.revision != chain.revision + 1 or type(row.decision_version) is not int:
        raise PostingInterpretationConflict()
    if row.mode == "select":
        current = _membership(row.selected_association, using)
        if current.revision != row.membership_revision or current.item is None or current.item.pk != item.pk:
            raise PostingInterpretationConflict()
    if _unchanged(chain.latest, row.selected_association_id, row.membership_revision):
        raise PostingInterpretationConflict()


def decide_posting_interpretation(*, actor, workspace, item_id, operation_id,
                                  expected_revision, mode, output_id=None,
                                  expected_membership_revision=None):
    authorize_owner(actor, workspace)
    identity(item_id)
    try:
        operation_id = contract.operation_uuid(operation_id)
    except contract.InvalidExtraction:
        raise InvalidPostingInterpretation() from None
    if not _revision(expected_revision) or type(mode) is not str or mode not in Decision.Mode.values:
        raise InvalidPostingInterpretation()
    if mode == "select":
        if not _revision(output_id, 1) or not _revision(expected_membership_revision):
            raise InvalidPostingInterpretation()
    elif output_id is not None or expected_membership_revision is not None:
        raise InvalidPostingInterpretation()
    using = router.db_for_write(Decision)
    with transaction.atomic():
        lock_workspace(actor, workspace)
        item, message = _endpoints(workspace, item_id)
        output, association = None, None
        if mode == "select":
            output = Output.objects.select_related("extraction").filter(
                pk=output_id, extraction__retained_message=message).first()
            if output is None:
                raise NotFound()
            association = Association.objects.filter(output=output).first()
        prior = Decision.objects.select_related("selected_association").filter(
            item=item, operation_id=operation_id).first()
        if prior is not None:
            prior_output = prior.selected_association.output_id if prior.selected_association_id else None
            if (prior.mode != mode or prior_output != output_id or prior.revision - 1 != expected_revision
                    or prior.membership_revision != expected_membership_revision
                    or prior.method != METHOD or prior.decision_version != DECISION_VERSION):
                conflict("idempotency_key_reused")
        cache = set()
        chain = resolve_chain(item, message, using=using, cache=cache)
        if output is not None:
            _validate_extraction(output.extraction_id, message, using, cache)
        if prior is not None:
            return InterpretationResult(prior, True, _state(item, message, chain, using))
        if expected_revision != chain.revision:
            conflict("stale_revision")
        require_eligible_source(message)
        if mode == "select":
            if association is None:
                conflict("posting_membership_required")
            current = _membership(association, using)
            if current.revision != expected_membership_revision:
                conflict("stale_membership_revision")
            if current.item is None or current.item.pk != item.pk:
                conflict("posting_output_not_member")
        if _unchanged(chain.latest, association.pk if association else None, expected_membership_revision):
            conflict("posting_interpretation_unchanged")
        if chain.revision == MAX_REVISION:
            conflict("posting_interpretation_revision_exhausted")
        row = Decision.objects.create(item=item, operation_id=operation_id, revision=chain.revision + 1,
            mode=mode, selected_association=association, membership_revision=expected_membership_revision,
            actor=actor, method=METHOD, decision_version=DECISION_VERSION)
        return InterpretationResult(row, False, _state(item, message, Chain(row.revision, row), using))


def read_posting_interpretation(*, actor, workspace, item_id):
    authorize_owner(actor, workspace)
    identity(item_id)
    using = router.db_for_write(Decision)
    with transaction.atomic():
        lock_workspace(actor, workspace)
        item, message = _endpoints(workspace, item_id)
        return _state(item, message, resolve_chain(item, message, using=using), using)


def list_posting_interpretation_decisions(*, actor, workspace, item_id, limit=100, cursor=None):
    """Cursor (item, through revision, last revision); applicability is not frozen."""
    authorize_owner(actor, workspace)
    identity(item_id)
    if type(limit) is not int or not 1 <= limit <= 200:
        raise InvalidPostingInterpretation()
    through, last = None, 0
    if cursor is not None:
        if (type(cursor) is not tuple or len(cursor) != 3 or any(not _revision(v) for v in cursor)
                or cursor[0] != item_id or cursor[2] > cursor[1]):
            raise InvalidPostingInterpretation()
        through, last = cursor[1:]
    using = router.db_for_write(Decision)
    with transaction.atomic():
        lock_workspace(actor, workspace)
        item, message = _endpoints(workspace, item_id)
        if through and not Decision.objects.filter(item=item, revision=through).exists():
            raise InvalidPostingInterpretation()
        chain = resolve_chain(item, message, using=using, through=through)
        rows = tuple(Decision.objects.filter(item=item, revision__gt=last, revision__lte=chain.revision)
                     .order_by("revision")[:limit + 1])
        page = rows[:limit]
        next_cursor = (item.pk, chain.revision, page[-1].revision) if len(rows) > limit else None
        return InterpretationHistory(page, chain.revision, next_cursor, not message.has_conflict)


@dataclass(frozen=True, slots=True)
class RetainedEvidence:
    source: str
    title: str | None
    company: str | None
    location: str | None
    salary: str | None
    employment_type: str | None


@dataclass(frozen=True, slots=True)
class InterpretationObservation:
    workspace_id: int
    item_id: int
    state: str
    revision: int
    latest_decision_id: int | None
    selected_association_id: int | None
    selected_output_id: int | None
    recorded_membership_revision: int | None
    current_membership_revision: int | None
    applicable_output_id: int | None
    evidence: RetainedEvidence | None
    source_eligible: bool
    consistency: str = "advisory"


def observe_posting_interpretation(*, actor, workspace, item_id):
    """Non-serialized SELECT-only observation; no future command admission.

    Captured history prefixes are validated by the same resolvers as the locked
    reader. Membership/source facts can come from different concurrent instants.
    """
    authorize_owner(actor, workspace)
    identity(item_id)
    using = router.db_for_write(Decision)
    item, message = _endpoints(workspace, item_id, lock=False)
    value = _state(item, message, resolve_chain(item, message, using=using), using)
    latest, output = value.latest_decision, value.applicable_output
    return InterpretationObservation(
        workspace.pk, item.pk, value.state, value.revision,
        latest.pk if latest else None,
        latest.selected_association_id if latest else None,
        value.selected_output.pk if value.selected_output else None,
        value.recorded_membership_revision, value.current_membership_revision,
        output.pk if output else None,
        RetainedEvidence(**output.fields) if output else None,
        value.source_eligible)
