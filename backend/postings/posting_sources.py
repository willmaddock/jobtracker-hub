"""Explicit initial mapping only; no allocation, interpretation or effective selection.

Canonical writes serialize Workspace -> retained source. No hidden retries.
Output membership changes do not alter the identity assertion recorded here.
"""
from dataclasses import dataclass

from django.db import transaction
from rest_framework.exceptions import APIException, NotFound

from applications.creation import lock_workspace
from applications.message_relationships import require_eligible_source
from .models import JobPosting, PostingSource, RetainedPostingItem
from .retained_extractions import identity, scoped_source
from .retained_items import authorize_owner

METHOD = "explicit_owner"
DECISION_VERSION = 1
MAX_ID = 9223372036854775807


class PostingSourceConflict(APIException):
    status_code = 409
    default_code = "posting_source_conflict"
    default_detail = "Item already has a different initial posting assertion."


class InvalidPostingSource(APIException):
    status_code = 400
    default_code = "invalid_posting_source"
    default_detail = "Invalid posting source navigation."


@dataclass(frozen=True)
class InitialPostingSourceResult:
    item: RetainedPostingItem
    initial_source: PostingSource | None
    posting: JobPosting | None
    source_eligible: bool
    replay: bool = False


@dataclass(frozen=True)
class InitialPostingSourcePage:
    results: tuple
    next_cursor: tuple | None


def scoped_item(workspace, item_id, *, lock=False):
    item = RetainedPostingItem.objects.filter(pk=item_id, retained_message__workspace=workspace).first()
    if item is None:
        raise NotFound()
    message = scoped_source(workspace, item.retained_message_id, lock=lock)
    return item, message


def scoped_posting(workspace, posting_id):
    posting = JobPosting.objects.filter(pk=posting_id, workspace=workspace,
                                        account__workspace=workspace).first()
    if posting is None:
        raise NotFound()
    return posting


def validate_initial(workspace, row):
    # Resolve persisted endpoints, never cached relation objects. Scope failure
    # precedes replay/policy conflict, including for a previously stored target.
    posting = scoped_posting(workspace, row.posting_id)
    if row.method != METHOD or row.decision_version != DECISION_VERSION:
        raise PostingSourceConflict()
    return posting


def result(item, row, posting, message, *, replay=False):
    return InitialPostingSourceResult(item, row, posting, not message.has_conflict, replay)


def attach_posting_source(*, actor, workspace, item_id, posting_id):
    authorize_owner(actor, workspace)
    identity(item_id)
    identity(posting_id)
    with transaction.atomic():
        lock_workspace(actor, workspace)
        item, message = scoped_item(workspace, item_id, lock=True)
        posting = scoped_posting(workspace, posting_id)
        prior = PostingSource.objects.filter(item=item).first()
        if prior is not None:
            original_posting = validate_initial(workspace, prior)
            if original_posting.pk != posting.pk:
                raise PostingSourceConflict()
            return result(item, prior, original_posting, message, replay=True)
        require_eligible_source(message)
        row = PostingSource.objects.create(item=item, posting=posting, actor=actor,
                                           method=METHOD, decision_version=DECISION_VERSION)
        return result(item, row, posting, message)


def read_initial_posting_source(*, actor, workspace, item_id):
    authorize_owner(actor, workspace)
    identity(item_id)
    item, message = scoped_item(workspace, item_id)
    row = PostingSource.objects.filter(item=item).first()
    posting = validate_initial(workspace, row) if row is not None else None
    return result(item, row, posting, message)


def list_initial_posting_sources(*, actor, workspace, posting_id, limit=100, cursor=None):
    """PK keyset navigation, not a snapshot. Cursor is (posting ID, mapping ID)."""
    authorize_owner(actor, workspace)
    identity(posting_id)
    if type(limit) is not int or not 1 <= limit <= 200:
        raise InvalidPostingSource()
    scoped_posting(workspace, posting_id)
    rows = PostingSource.objects.filter(posting_id=posting_id)
    if cursor is not None:
        if (type(cursor) is not tuple or len(cursor) != 2
                or any(type(v) is not int or not 0 < v <= MAX_ID for v in cursor)
                or cursor[0] != posting_id or not rows.filter(pk=cursor[1]).exists()):
            raise InvalidPostingSource()
        rows = rows.filter(pk__gt=cursor[1])
    rows = tuple(rows.order_by("pk")[:limit + 1])
    page = []
    for row in rows[:limit]:
        item, message = scoped_item(workspace, row.item_id)
        posting = validate_initial(workspace, row)
        page.append(result(item, row, posting, message))
    next_cursor = (posting_id, rows[limit - 1].pk) if len(rows) > limit else None
    return InitialPostingSourcePage(tuple(page), next_cursor)
