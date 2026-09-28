"""Explicit initial decisions only. No automatic continuity or effective selection.

Output identity is the one-shot decision key. Retrying never changes attribution.
All writers take Workspace -> retained source; immutable endpoints need no locks.
"""
from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import APIException, NotFound

from applications.creation import lock_workspace
from applications.message_relationships import require_eligible_source
from .extraction_contract import InvalidExtraction, timestamp
from .models import RetainedPostingExtractionOutput as Output, RetainedPostingItem as Item
from .models import RetainedPostingItemAssociation as Association
from .retained_extractions import authorize, identity, scoped_source

METHOD = "explicit_owner"
DECISION_VERSION = 1


class InvalidItemAssociation(APIException):
    status_code = 400
    default_code = "invalid_posting_item_association"
    default_detail = "Invalid posting item decision."


class ItemAssociationConflict(APIException):
    status_code = 409
    default_code = "posting_item_association_conflict"
    default_detail = "Output already has a different initial decision."


@dataclass(frozen=True)
class AssociationResult:
    output: Output
    association: Association | None
    item: Item | None
    source_eligible: bool
    replay: bool = False


@dataclass(frozen=True)
class ItemResult:
    item: Item
    source_eligible: bool


@dataclass(frozen=True)
class AssociationPage:
    associations: tuple
    next_cursor: tuple | None
    source_eligible: bool


def authorize_owner(actor, workspace):
    # No actorless/system path or synthetic unsaved principal. Ownership is also
    # rechecked by the existing Workspace gate before any canonical write.
    if not isinstance(actor, get_user_model()) or actor._state.adding or actor.pk is None:
        raise NotFound()
    authorize(actor, workspace)


def output_in_workspace(workspace, output_id):
    output = Output.objects.select_related("extraction").filter(
        pk=output_id, extraction__retained_message__workspace=workspace).first()
    if output is None:
        raise NotFound()
    return output


def item_in_source(message, item_id):
    item = Item.objects.filter(pk=item_id, retained_message=message).first()
    if item is None:
        raise NotFound()
    return item


def existing_association(output, message):
    association = Association.objects.select_related("item").filter(output=output).first()
    if association is not None and association.item.retained_message_id != message.pk:
        raise NotFound()
    return association


def result(output, association, message, *, replay=False):
    return AssociationResult(output, association, association.item if association else None,
                             not message.has_conflict, replay)


def associate_posting_output(*, actor, workspace, output_id, mode, item_id=None):
    """Caller explicitly asserts distinct occurrence or continuity; never infer it."""
    authorize_owner(actor, workspace)
    identity(output_id)
    if type(mode) is not str or mode not in Association.Mode.values:
        raise InvalidItemAssociation()
    if mode == Association.Mode.ALLOCATE:
        if item_id is not None:
            raise InvalidItemAssociation()
    else:
        if item_id is None:
            raise InvalidItemAssociation()
        identity(item_id)
    with transaction.atomic():
        lock_workspace(actor, workspace)
        output = output_in_workspace(workspace, output_id)
        message = scoped_source(workspace, output.extraction.retained_message_id, lock=True)
        target = item_in_source(message, item_id) if mode == Association.Mode.ATTACH else None
        prior = existing_association(output, message)
        if prior is not None:
            if (prior.mode != mode or prior.method != METHOD or prior.decision_version != DECISION_VERSION
                    or (target is not None and prior.item_id != target.pk)):
                raise ItemAssociationConflict()
            return result(output, prior, message, replay=True)
        require_eligible_source(message)
        if target is None:
            target = Item.objects.create(retained_message=message)
        association = Association.objects.create(item=target, output=output, actor=actor, mode=mode,
                                                 method=METHOD, decision_version=DECISION_VERSION)
        return result(output, association, message)


def read_posting_output_association(*, actor, workspace, output_id):
    authorize_owner(actor, workspace)
    identity(output_id)
    output = output_in_workspace(workspace, output_id)
    message = scoped_source(workspace, output.extraction.retained_message_id)
    return result(output, existing_association(output, message), message)


def read_posting_item(*, actor, workspace, item_id):
    authorize_owner(actor, workspace)
    identity(item_id)
    item = Item.objects.filter(pk=item_id, retained_message__workspace=workspace).first()
    if item is None:
        raise NotFound()
    message = scoped_source(workspace, item.retained_message_id)
    return ItemResult(item, not message.has_conflict)


def list_posting_item_associations(*, actor, workspace, item_id, limit=100, cursor=None):
    """Bounded chronological history; cursor is (UTC timestamp string, row ID).

    Cursor is scoped/validated against this item. It is navigation, not authority.
    No snapshot guarantee across pages while new assertions are appended.
    """
    read = read_posting_item(actor=actor, workspace=workspace, item_id=item_id)
    if type(limit) is not int or not 1 <= limit <= 200:
        raise InvalidItemAssociation()
    rows = Association.objects.filter(item=read.item).select_related("output__extraction")
    if cursor is not None:
        if type(cursor) is not tuple or len(cursor) != 2:
            raise InvalidItemAssociation()
        try:
            stamp = datetime.fromisoformat(timestamp(cursor[0]))
        except InvalidExtraction:
            raise InvalidItemAssociation() from None
        if type(cursor[1]) is not int or not 0 < cursor[1] <= 9223372036854775807:
            raise InvalidItemAssociation()
        if not rows.filter(pk=cursor[1], created_at=stamp).exists():
            raise InvalidItemAssociation()
        rows = rows.filter(Q(created_at__gt=stamp) | Q(created_at=stamp, pk__gt=cursor[1]))
    page = tuple(rows.order_by("created_at", "pk")[:limit + 1])
    for association in page:
        if association.output.extraction.retained_message_id != read.item.retained_message_id:
            raise NotFound()
    more = len(page) > limit
    page = page[:limit]
    next_cursor = (page[-1].created_at.isoformat(), page[-1].pk) if more else None
    return AssociationPage(page, next_cursor, read.source_eligible)
