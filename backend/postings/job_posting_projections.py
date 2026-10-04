"""Explicit six-column materialization; immutable witnesses, no allocation or retries.

Ordinary event writes are blocked. Only _append_and_materialize deliberately uses
base insertion, under the command's Workspace -> posting -> sorted source locks.
"""
from dataclasses import dataclass
import re
from types import MappingProxyType

from django.contrib.auth import get_user_model
from django.db import models, router, transaction
from django.db.models import Count, Min, Max, Q
from rest_framework.exceptions import APIException, NotFound

from applications.creation import lock_workspace
from applications.message_relationships import require_eligible_source
from . import extraction_contract as contract, job_posting_interpretations as arbitration
from .models import (DESCRIPTOR_FIELDS, JobPosting, JobPostingDescriptorProjection as Projection,
                     JobPostingInterpretationDecision as Decision)
from .retained_extractions import identity, scoped_source
from .retained_items import authorize_owner

MAX_REVISION = 9223372036854775807
METHOD = "explicit_owner"
PROJECTION_VERSION = 1
CAPACITIES = dict(zip(DESCRIPTOR_FIELDS, (64, 255, 255, 255, 255, 64)))


class InvalidJobPostingProjection(APIException):
    status_code = 400
    default_code = "invalid_job_posting_projection"
    default_detail = "Invalid descriptor projection request."


class JobPostingProjectionConflict(APIException):
    status_code = 409
    default_code = "job_posting_projection_history_invalid"
    default_detail = "Descriptor projection history is invalid."


def conflict(code):
    raise JobPostingProjectionConflict("Descriptor projection cannot be applied.", code=code)


def _revision(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX_REVISION


def _digest_valid(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def descriptor_snapshot(posting):
    return {name: getattr(posting, name) for name in DESCRIPTOR_FIELDS}


def descriptor_digest(fields):
    # Current columns are deliberately not validated as retained extraction output.
    return contract.digest({"descriptor_digest_version": 1, "fields": dict(fields)})


def _capacity_errors(snapshot):
    return tuple((name, limit) for name, limit in CAPACITIES.items()
                 if snapshot[name] is not None and len(snapshot[name]) > limit)


def _check_capacity(snapshot):
    errors = _capacity_errors(snapshot)
    if errors:
        raise JobPostingProjectionConflict(
            {"fields": [{"field": name, "limit": limit} for name, limit in errors]},
            code="projection_capacity_exceeded")


@dataclass(frozen=True)
class Chain:
    revision: int
    latest: Projection | None


@dataclass(frozen=True)
class EffectiveProjection:
    posting: JobPosting
    revision: int
    latest_event: Projection | None
    recorded_arbitration_decision: Decision | None
    projected_snapshot: object | None
    current_descriptor_snapshot: object
    current_descriptor_digest: str
    descriptor_drift: bool
    current_arbitration_revision: int
    current_arbitration_state: str
    current_arbitration_stale_reasons: tuple
    recorded_authority_stale_reasons: tuple
    source_eligible: bool | None
    state: str
    stale_reasons: tuple
    applicable_snapshot: object | None
    can_append_revision: bool
    can_project: bool


@dataclass(frozen=True)
class ProjectionResult:
    event: Projection
    replay: bool
    current: EffectiveProjection


@dataclass(frozen=True)
class ProjectionHistory:
    events: tuple
    through_revision: int
    next_cursor: tuple | None


def _posting(workspace, posting_id, using):
    posting = JobPosting.objects.using(using).select_for_update(of=("self",)).filter(
        pk=posting_id, workspace=workspace, account__workspace=workspace).first()
    if posting is None:
        raise NotFound()
    return posting


def _context(posting, using, *, workspace=None, through=None, current=True, extra=None):
    rows = Projection.objects.using(using).filter(posting=posting)
    if through is None:
        through = rows.aggregate(last=Max("revision"))["last"] or 0
    rows = rows.filter(revision__lte=through)
    endpoints = list(rows.values_list("arbitration_decision__posting_id", "arbitration_decision__revision"))
    if extra is not None:
        endpoints.append((extra.posting_id, extra.revision))
    current_revision = (Decision.objects.using(using).filter(posting=posting).aggregate(
        last=Max("revision"))["last"] or 0) if current else 0
    if current:
        endpoints.append((posting.pk, current_revision))
    # Include even corrupt foreign anchors during discovery; validation grants no
    # authority from these joins. All referenced arbitration PREFIXES are needed.
    prefixes = {}
    for anchor, revision in endpoints:
        if anchor is not None and revision is not None:
            prefixes[anchor] = max(prefixes.get(anchor, 0), revision)
    query = Q(pk__in=[])
    for anchor, revision in prefixes.items():
        query |= Q(posting_id=anchor, revision__lte=revision)
    decisions = Decision.objects.using(using).filter(query)
    messages = {}
    for source_id in arbitration._source_ids(decisions, None, using):
        messages[source_id] = (scoped_source(workspace, source_id, lock=True) if workspace is not None
                               else arbitration._alias_source(source_id, posting.workspace_id, using))
    return through, current_revision, arbitration.Dependencies(posting, using, messages)


def _validate_event(row, deps, cache):
    try:
        contract.operation_uuid(row.operation_id)
        contract.validate_fields(row.snapshot)
    except contract.InvalidExtraction:
        raise JobPostingProjectionConflict() from None
    if (row.posting_id != deps.posting.pk or not _revision(row.revision, 1)
            or row.method != METHOD or type(row.projection_version) is not int
            or row.projection_version != PROJECTION_VERSION or not _digest_valid(row.expected_descriptor_digest)
            or _capacity_errors(row.snapshot)
            or not get_user_model().objects.using(deps.using).filter(pk=row.actor_id).exists()):
        raise JobPostingProjectionConflict()
    decision = Decision.objects.using(deps.using).filter(pk=row.arbitration_decision_id).first()
    if decision is None or decision.posting_id != deps.posting.pk or not _revision(decision.revision, 1):
        raise JobPostingProjectionConflict()
    if decision.revision not in cache:
        cache[decision.revision] = arbitration.resolve_chain(deps, decision.revision)
    selected = cache[decision.revision].latest
    if selected is None or selected.pk != decision.pk or selected.mode != "select":
        raise JobPostingProjectionConflict()
    if row.snapshot != selected.selected_interpretation.selected_association.output.fields:
        raise JobPostingProjectionConflict()
    row.arbitration_decision = selected


def resolve_chain(deps, through):
    rows = Projection.objects.using(deps.using).filter(posting=deps.posting, revision__lte=through)
    stats = rows.aggregate(count=Count("pk"), first=Min("revision"), last=Max("revision"))
    revision = stats["last"] if stats["count"] else 0
    if (not _revision(through) or revision != through
            or (stats["count"] and (stats["first"] != 1 or stats["count"] != revision))):
        raise JobPostingProjectionConflict()
    latest, cache = None, {}
    for row in rows.order_by("revision").iterator():
        _validate_event(row, deps, cache)
        latest = row
    return Chain(revision, latest)


def validate_event(row, using):
    """Alias-only historical validation, never a public insertion permission."""
    posting = JobPosting.objects.using(using).filter(pk=row.posting_id,
        account__workspace_id=models.F("workspace_id")).first()
    if posting is None:
        raise JobPostingProjectionConflict()
    decision = Decision.objects.using(using).filter(pk=row.arbitration_decision_id).first()
    through, _, deps = _context(posting, using, current=False, extra=decision)
    resolve_chain(deps, through)
    _validate_event(row, deps, {})


def _unchanged(latest, decision, snapshot, current):
    return (latest is not None and latest.arbitration_decision_id == decision.pk
            and latest.snapshot == snapshot and current == snapshot)


def _state(chain, deps, arbitration_revision):
    current_authority = arbitration._state(arbitration.resolve_chain(deps, arbitration_revision), deps)
    latest = chain.latest
    current = descriptor_snapshot(deps.posting)
    projected = MappingProxyType(dict(latest.snapshot)) if latest else None
    drift = latest is not None and current != latest.snapshot
    recorded = (arbitration._state(arbitration.Chain(latest.arbitration_decision.revision,
                latest.arbitration_decision), deps) if latest else None)
    reasons = tuple(reason for changed, reason in (
        (latest is not None and arbitration_revision != latest.arbitration_decision.revision,
         "arbitration_revision_changed"),
        (latest is not None and (bool(recorded.stale_reasons)
         or current_authority.state != "selected"), "arbitration_not_applicable"),
        (drift, "descriptor_drift")) if changed)
    eligible = recorded.source_eligible if recorded else None
    capacity = chain.revision < MAX_REVISION
    output = current_authority.applicable_output
    can_project = bool(capacity and output is not None and not _capacity_errors(output.fields)
        and not _unchanged(latest, current_authority.latest_decision, output.fields, current))
    return EffectiveProjection(deps.posting, chain.revision, latest,
        latest.arbitration_decision if latest else None, projected, MappingProxyType(current),
        descriptor_digest(current), drift, arbitration_revision, current_authority.state,
        current_authority.stale_reasons, recorded.stale_reasons if recorded else (), eligible,
        "unprojected" if latest is None else "stale" if reasons else "projected", reasons,
        projected if latest and not reasons and eligible else None, capacity, can_project)


def _materialize(posting, snapshot, using):
    if JobPosting.objects.using(using).filter(pk=posting.pk, workspace_id=posting.workspace_id).update(**snapshot) != 1:
        raise JobPostingProjectionConflict()
    posting.refresh_from_db(using=using)
    if descriptor_snapshot(posting) != snapshot:
        raise JobPostingProjectionConflict()


def _append_and_materialize(row, deps):
    _validate_event(row, deps, {})
    # Ordinary save() is intentionally never enabled, even temporarily.
    models.Model.save(row, using=deps.using, force_insert=True)
    _materialize(deps.posting, row.snapshot, deps.using)


def project_job_posting_descriptors(*, actor, workspace, posting_id, operation_id,
        expected_projection_revision, expected_arbitration_revision, expected_descriptor_digest):
    authorize_owner(actor, workspace)
    identity(posting_id)
    try:
        operation_id = contract.operation_uuid(operation_id)
    except contract.InvalidExtraction:
        raise InvalidJobPostingProjection() from None
    if (not _revision(expected_projection_revision) or not _revision(expected_arbitration_revision, 1)
            or not _digest_valid(expected_descriptor_digest)):
        raise InvalidJobPostingProjection()
    using = router.db_for_write(Projection)
    with transaction.atomic(using=using):
        lock_workspace(actor, workspace)
        posting = _posting(workspace, posting_id, using)
        through, arb_revision, deps = _context(posting, using, workspace=workspace)
        requested = Decision.objects.using(using).filter(posting=posting,
            revision=expected_arbitration_revision).first()
        if requested is None:
            raise NotFound()
        prior = Projection.objects.using(using).filter(posting=posting, operation_id=operation_id).first()
        if prior is not None and (prior.arbitration_decision_id != requested.pk
                or prior.revision - 1 != expected_projection_revision
                or prior.expected_descriptor_digest != expected_descriptor_digest
                or prior.method != METHOD or prior.projection_version != PROJECTION_VERSION):
            conflict("idempotency_key_reused")
        chain = resolve_chain(deps, through)
        authority_chain = arbitration.resolve_chain(deps, arb_revision)
        if prior is not None:
            return ProjectionResult(prior, True, _state(chain, deps, arb_revision))
        if chain.revision != expected_projection_revision:
            conflict("stale_projection_revision")
        if arb_revision != expected_arbitration_revision:
            conflict("stale_arbitration_revision")
        authority = arbitration._state(authority_chain, deps)
        if authority.state != "selected" or authority.latest_decision.pk != requested.pk:
            conflict("job_posting_projection_not_applicable")
        require_eligible_source(deps.message(authority.selected_item))
        if authority.applicable_output is None:
            conflict("job_posting_projection_not_applicable")
        snapshot = dict(authority.applicable_output.fields)
        contract.validate_fields(snapshot)
        _check_capacity(snapshot)
        current = descriptor_snapshot(posting)
        if descriptor_digest(current) != expected_descriptor_digest:
            conflict("stale_descriptor_digest")
        if _unchanged(chain.latest, requested, snapshot, current):
            conflict("job_posting_projection_unchanged")
        if chain.revision == MAX_REVISION:
            conflict("job_posting_projection_revision_exhausted")
        row = Projection(posting=posting, operation_id=operation_id, revision=chain.revision + 1,
            arbitration_decision=requested, snapshot=snapshot, expected_descriptor_digest=expected_descriptor_digest,
            actor=actor, method=METHOD, projection_version=PROJECTION_VERSION)
        _append_and_materialize(row, deps)
        return ProjectionResult(row, False, _state(Chain(row.revision, row), deps, arb_revision))


def read_job_posting_projection(*, actor, workspace, posting_id):
    authorize_owner(actor, workspace)
    identity(posting_id)
    using = router.db_for_write(Projection)
    with transaction.atomic(using=using):
        lock_workspace(actor, workspace)
        posting = _posting(workspace, posting_id, using)
        through, arb_revision, deps = _context(posting, using, workspace=workspace)
        return _state(resolve_chain(deps, through), deps, arb_revision)


def list_job_posting_projection_events(*, actor, workspace, posting_id, limit=100, cursor=None):
    authorize_owner(actor, workspace)
    identity(posting_id)
    if type(limit) is not int or not 1 <= limit <= 200:
        raise InvalidJobPostingProjection()
    through, last = None, 0
    if cursor is not None:
        if (type(cursor) is not tuple or len(cursor) != 3 or any(not _revision(v) for v in cursor)
                or cursor[0] != posting_id or cursor[2] > cursor[1]):
            raise InvalidJobPostingProjection()
        through, last = cursor[1:]
    using = router.db_for_write(Projection)
    with transaction.atomic(using=using):
        lock_workspace(actor, workspace)
        posting = _posting(workspace, posting_id, using)
        if through and not Projection.objects.using(using).filter(posting=posting, revision=through).exists():
            raise InvalidJobPostingProjection()
        through, _, deps = _context(posting, using, workspace=workspace, through=through, current=False)
        chain = resolve_chain(deps, through)
        rows = tuple(Projection.objects.using(using).filter(posting=posting, revision__gt=last,
            revision__lte=chain.revision).order_by("revision")[:limit + 1])
        page = rows[:limit]
        cursor = (posting.pk, chain.revision, page[-1].revision) if len(rows) > limit else None
        return ProjectionHistory(page, chain.revision, cursor)
