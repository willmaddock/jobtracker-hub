"""Posting authority; no descriptor projection, allocation, fallback or retries.

Commands and coherent readers serialize Workspace then all discovered sources in
ascending order. Model guards honor their write alias without default-DB helpers.
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
from .models import (JobPosting, PostingSource, RetainedPostingItem as Item,
                     RetainedPostingInterpretationDecision as Interpretation,
                     JobPostingInterpretationDecision as Decision)
from .posting_sources import scoped_posting
from .posting_source_corrections import resolve_chain as mapping_chain
from .retained_interpretations import resolve_chain as interpretation_chain
from .retained_item_corrections import resolve_chain as membership_chain
from .retained_extractions import identity, scoped_source, RetainedSourceInvalid
from .retained_items import authorize_owner

MAX_REVISION = 9223372036854775807
METHOD = "explicit_owner"
DECISION_VERSION = 1


class InvalidJobPostingInterpretation(APIException):
    status_code = 400
    default_code = "invalid_job_posting_interpretation"
    default_detail = "Invalid job posting interpretation."


class JobPostingInterpretationConflict(APIException):
    status_code = 409
    default_code = "job_posting_interpretation_history_invalid"
    default_detail = "Job posting interpretation history is invalid."


def conflict(code):
    raise JobPostingInterpretationConflict("Posting authority cannot be applied.", code=code)


def _revision(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX_REVISION


@dataclass(frozen=True)
class Chain:
    revision: int
    latest: Decision | None


@dataclass(frozen=True)
class EffectiveInterpretation:
    posting: JobPosting
    revision: int
    latest_decision: Decision | None
    selected_item: Item | None
    selected_interpretation: Interpretation | None
    selected_output: object | None
    initial_source: PostingSource | None
    recorded_mapping_revision: int | None
    current_mapping_revision: int | None
    recorded_interpretation_revision: int | None
    current_interpretation_revision: int | None
    recorded_membership_revision: int | None
    current_membership_revision: int | None
    state: str
    stale_reasons: tuple
    source_eligible: bool | None
    applicable_output: object | None
    can_append_revision: bool
    can_withdraw: bool


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


class Dependencies:
    """Per-call caches keyed by identity AND prefix; never persistent caches."""
    def __init__(self, posting, using, messages):
        self.posting, self.using, self.messages = posting, using, messages
        self.mappings, self.interpretations, self.extractions = {}, {}, set()

    def message(self, item):
        message = self.messages.get(item.retained_message_id)
        if message is None or message.workspace_id != self.posting.workspace_id:
            raise NotFound()
        return message

    def mapping(self, initial, through=None):
        key = (initial.pk, through)
        if key not in self.mappings:
            self.mappings[key] = mapping_chain(initial, using=self.using, through=through)
        return self.mappings[key]

    def interpretation(self, item, through=None):
        key = (item.pk, through)
        if key not in self.interpretations:
            self.interpretations[key] = interpretation_chain(item, self.message(item),
                using=self.using, through=through, cache=self.extractions)
        return self.interpretations[key]


def _source_ids(rows, item_id, using):
    ids = set(rows.values_list("selected_interpretation__item__retained_message_id", flat=True))
    ids.update(rows.values_list("initial_source__item__retained_message_id", flat=True))
    if item_id is not None:
        ids.update(Item.objects.using(using).filter(pk=item_id).values_list("retained_message_id", flat=True))
    return sorted(ids - {None})


def _alias_source(source_id, workspace_id, using):
    message = RetainedMessage.objects.using(using).select_related("mailbox").filter(pk=source_id).first()
    if (message is None or message.workspace_id != workspace_id
            or message.mailbox.workspace_id != workspace_id or message.provider != message.mailbox.provider):
        raise NotFound()
    try:
        contract.validate_source_content(message.content, message.representation_version,
                                         message.content_digest, provider=message.provider)
    except contract.InvalidExtraction:
        raise RetainedSourceInvalid() from None
    return message


def _context(posting, using, *, workspace=None, through=None, item_id=None):
    rows = Decision.objects.using(using).filter(posting=posting)
    if through is None:
        through = rows.aggregate(last=Max("revision"))["last"] or 0
    rows = rows.filter(revision__lte=through)
    messages = {}
    for source_id in _source_ids(rows, item_id, using):
        messages[source_id] = (scoped_source(workspace, source_id, lock=True) if workspace is not None
                               else _alias_source(source_id, posting.workspace_id, using))
    return through, Dependencies(posting, using, messages)


def _validate_decision(row, deps):
    try:
        contract.operation_uuid(row.operation_id)
    except contract.InvalidExtraction:
        raise JobPostingInterpretationConflict() from None
    if (row.posting_id != deps.posting.pk or not _revision(row.revision, 1)
            or row.method != METHOD or type(row.decision_version) is not int
            or row.decision_version != DECISION_VERSION):
        raise JobPostingInterpretationConflict()
    if row.mode == "withdraw":
        if any(value is not None for value in (row.selected_interpretation_id, row.initial_source_id,
                                               row.mapping_revision)):
            raise JobPostingInterpretationConflict()
        return
    if (row.mode != "select" or row.selected_interpretation_id is None
            or row.initial_source_id is None or not _revision(row.mapping_revision)):
        raise JobPostingInterpretationConflict()
    selected = Interpretation.objects.using(deps.using).select_related("item").filter(
        pk=row.selected_interpretation_id).first()
    initial = PostingSource.objects.using(deps.using).select_related("item").filter(pk=row.initial_source_id).first()
    if selected is None or initial is None:
        raise JobPostingInterpretationConflict()
    deps.message(selected.item)
    deps.message(initial.item)
    if initial.item_id != selected.item_id:
        raise JobPostingInterpretationConflict()
    mapping = deps.mapping(initial, row.mapping_revision)
    if mapping.posting is None or mapping.posting.pk != deps.posting.pk:
        raise JobPostingInterpretationConflict()
    interpretation = deps.interpretation(selected.item, selected.revision)
    if (interpretation.latest is None or interpretation.latest.pk != selected.pk
            or interpretation.latest.mode != "select"):
        raise JobPostingInterpretationConflict()
    row.selected_interpretation = interpretation.latest
    row.selected_interpretation.item = selected.item
    row.initial_source = initial


def resolve_chain(deps, through):
    rows = Decision.objects.using(deps.using).filter(posting=deps.posting, revision__lte=through)
    stats = rows.aggregate(count=Count("pk"), first=Min("revision"), last=Max("revision"))
    revision = stats["last"] if stats["count"] else 0
    if (not _revision(through) or revision != through
            or (stats["count"] and (stats["first"] != 1 or stats["count"] != revision))):
        raise JobPostingInterpretationConflict()
    latest = None
    for row in rows.order_by("revision").iterator():
        _validate_decision(row, deps)
        latest = row
    return Chain(revision, latest)


def _state(chain, deps):
    latest = chain.latest
    capacity = chain.revision < MAX_REVISION
    if latest is None or latest.mode == "withdraw":
        return EffectiveInterpretation(deps.posting, chain.revision, latest,
            None, None, None, None, None, None, None, None, None, None,
            "unresolved" if latest is None else "withdrawn", (), None, None, capacity, False)
    selected, initial = latest.selected_interpretation, latest.initial_source
    item, association = selected.item, selected.selected_association
    mapping = deps.mapping(initial)
    interpretation = deps.interpretation(item)
    # Always inspect the HISTORICALLY selected output, including after withdrawal
    # or replacement of the item's interpretation with a different output.
    membership = membership_chain(association, using=deps.using)
    reasons = tuple(reason for changed, reason in (
        (mapping.revision != latest.mapping_revision, "mapping_revision_changed"),
        (interpretation.revision != selected.revision, "interpretation_revision_changed"),
        (membership.revision != selected.membership_revision, "membership_revision_changed")) if changed)
    if ((mapping.revision == latest.mapping_revision and
         (mapping.posting is None or mapping.posting.pk != deps.posting.pk))
            or (interpretation.revision == selected.revision and
                (interpretation.latest is None or interpretation.latest.pk != selected.pk))
            or (membership.revision == selected.membership_revision and
                (membership.item is None or membership.item.pk != item.pk))):
        raise JobPostingInterpretationConflict()
    eligible = not deps.message(item).has_conflict
    return EffectiveInterpretation(deps.posting, chain.revision, latest, item, selected,
        association.output, initial, latest.mapping_revision, mapping.revision,
        selected.revision, interpretation.revision, selected.membership_revision, membership.revision,
        "stale" if reasons else "selected", reasons, eligible,
        association.output if eligible and not reasons else None, capacity, eligible and capacity)


def _new_selection(selected, initial, mapping_revision, deps):
    if initial is None:
        conflict("job_posting_mapping_required")
    if initial.item_id != selected.item_id:
        raise JobPostingInterpretationConflict()
    mapping = deps.mapping(initial)
    if mapping.revision != mapping_revision:
        conflict("stale_mapping_revision")
    if mapping.posting is None or mapping.posting.pk != deps.posting.pk:
        conflict("job_posting_item_not_mapped")
    interpretation = deps.interpretation(selected.item)
    if interpretation.revision != selected.revision or interpretation.latest.pk != selected.pk:
        conflict("stale_interpretation_revision")
    current = interpretation.latest
    if current.mode != "select":
        conflict("job_posting_interpretation_not_applicable")
    membership = membership_chain(current.selected_association, using=deps.using)
    if (membership.revision != current.membership_revision or membership.item is None
            or membership.item.pk != selected.item_id):
        conflict("job_posting_interpretation_not_applicable")


def _unchanged(latest, selected_id, initial_id, mapping_revision):
    if selected_id is None:
        return latest is None or latest.mode == "withdraw"
    return (latest is not None and latest.mode == "select"
            and (latest.selected_interpretation_id, latest.initial_source_id, latest.mapping_revision)
            == (selected_id, initial_id, mapping_revision))


def validate_insertion(row, using):
    posting = JobPosting.objects.using(using).select_related("account").filter(pk=row.posting_id).first()
    if (posting is None or posting.account.workspace_id != posting.workspace_id
            or not get_user_model().objects.using(using).filter(pk=row.actor_id).exists()):
        raise JobPostingInterpretationConflict()
    item_id = Interpretation.objects.using(using).filter(pk=row.selected_interpretation_id).values_list(
        "item_id", flat=True).first()
    through, deps = _context(posting, using, item_id=item_id)
    chain = resolve_chain(deps, through)
    _validate_decision(row, deps)
    if row.revision != chain.revision + 1:
        raise JobPostingInterpretationConflict()
    if row.mode == "select":
        _new_selection(row.selected_interpretation, row.initial_source, row.mapping_revision, deps)
    if _unchanged(chain.latest, row.selected_interpretation_id, row.initial_source_id, row.mapping_revision):
        raise JobPostingInterpretationConflict()


def decide_job_posting_interpretation(*, actor, workspace, posting_id, operation_id,
        expected_revision, mode, item_id=None, expected_interpretation_revision=None,
        expected_mapping_revision=None):
    authorize_owner(actor, workspace)
    identity(posting_id)
    try:
        operation_id = contract.operation_uuid(operation_id)
    except contract.InvalidExtraction:
        raise InvalidJobPostingInterpretation() from None
    if not _revision(expected_revision) or type(mode) is not str or mode not in Decision.Mode.values:
        raise InvalidJobPostingInterpretation()
    if mode == "select":
        if (not _revision(item_id, 1) or not _revision(expected_interpretation_revision, 1)
                or not _revision(expected_mapping_revision)):
            raise InvalidJobPostingInterpretation()
    elif any(v is not None for v in (item_id, expected_interpretation_revision, expected_mapping_revision)):
        raise InvalidJobPostingInterpretation()
    using = router.db_for_write(Decision)
    with transaction.atomic():
        lock_workspace(actor, workspace)
        posting = scoped_posting(workspace, posting_id)
        through, deps = _context(posting, using, workspace=workspace, item_id=item_id)
        selected, initial = None, None
        if mode == "select":
            selected = Interpretation.objects.select_related("item").filter(item_id=item_id,
                revision=expected_interpretation_revision, item__retained_message__workspace=workspace).first()
            if selected is None:
                raise NotFound()
            deps.message(selected.item)
            initial = PostingSource.objects.filter(item_id=item_id).first()
        prior = Decision.objects.select_related("selected_interpretation").filter(
            posting=posting, operation_id=operation_id).first()
        if prior is not None:
            old = prior.selected_interpretation
            if (prior.mode != mode or (old.item_id if old else None) != item_id
                    or (old.revision if old else None) != expected_interpretation_revision
                    or prior.mapping_revision != expected_mapping_revision
                    or prior.revision - 1 != expected_revision or prior.method != METHOD
                    or prior.decision_version != DECISION_VERSION):
                conflict("idempotency_key_reused")
        chain = resolve_chain(deps, through)
        if prior is not None:
            return InterpretationResult(prior, True, _state(chain, deps))
        if chain.revision != expected_revision:
            conflict("stale_revision")
        if selected is not None:
            require_eligible_source(deps.message(selected.item))
            _new_selection(selected, initial, expected_mapping_revision, deps)
        elif chain.latest is not None and chain.latest.mode == "select":
            require_eligible_source(deps.message(chain.latest.selected_interpretation.item))
        if _unchanged(chain.latest, selected.pk if selected else None,
                      initial.pk if initial else None, expected_mapping_revision):
            conflict("job_posting_interpretation_unchanged")
        if chain.revision == MAX_REVISION:
            conflict("job_posting_interpretation_revision_exhausted")
        row = Decision.objects.create(posting=posting, operation_id=operation_id,
            revision=chain.revision + 1, mode=mode, selected_interpretation=selected,
            initial_source=initial, mapping_revision=expected_mapping_revision, actor=actor,
            method=METHOD, decision_version=DECISION_VERSION)
        _validate_decision(row, deps)
        return InterpretationResult(row, False, _state(Chain(row.revision, row), deps))


def read_job_posting_interpretation(*, actor, workspace, posting_id):
    authorize_owner(actor, workspace)
    identity(posting_id)
    using = router.db_for_write(Decision)
    with transaction.atomic():
        lock_workspace(actor, workspace)
        posting = scoped_posting(workspace, posting_id)
        through, deps = _context(posting, using, workspace=workspace)
        return _state(resolve_chain(deps, through), deps)


def list_job_posting_interpretation_decisions(*, actor, workspace, posting_id, limit=100, cursor=None):
    authorize_owner(actor, workspace)
    identity(posting_id)
    if type(limit) is not int or not 1 <= limit <= 200:
        raise InvalidJobPostingInterpretation()
    through, last = None, 0
    if cursor is not None:
        if (type(cursor) is not tuple or len(cursor) != 3 or any(not _revision(v) for v in cursor)
                or cursor[0] != posting_id or cursor[2] > cursor[1]):
            raise InvalidJobPostingInterpretation()
        through, last = cursor[1:]
    using = router.db_for_write(Decision)
    with transaction.atomic():
        lock_workspace(actor, workspace)
        posting = scoped_posting(workspace, posting_id)
        if through and not Decision.objects.filter(posting=posting, revision=through).exists():
            raise InvalidJobPostingInterpretation()
        through, deps = _context(posting, using, workspace=workspace, through=through)
        chain = resolve_chain(deps, through)
        rows = tuple(Decision.objects.filter(posting=posting, revision__gt=last,
            revision__lte=chain.revision).order_by("revision")[:limit + 1])
        page = rows[:limit]
        next_cursor = (posting.pk, chain.revision, page[-1].revision) if len(rows) > limit else None
        return InterpretationHistory(page, chain.revision, next_cursor)
