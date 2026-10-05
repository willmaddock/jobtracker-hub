"""Explicit one-shot creation. Workspace -> source -> atomic posting/mapping/fact.

Commands use the default database, matching the existing workspace gate. Historical
validation honors its alias. No parser, provider calls, projection or hidden retries.
"""
from dataclasses import dataclass
from datetime import datetime
import re
from uuid import UUID
from django.contrib.auth import get_user_model
from django.db import models, transaction
from rest_framework.exceptions import APIException, NotFound
from applications.creation import lock_workspace
from applications.message_relationships import require_eligible_source
from email_sync.models import AccountMailboxBinding, RetainedMessage
from . import extraction_contract as contract, retained_interpretations as interpretations
from .models import (JobPosting, JobPostingAllocation as Allocation, PostingSource,
    RetainedPostingItem as Item, RetainedPostingInterpretationDecision as Decision, ALLOCATION_KEY_PREFIX)
from .posting_sources import _append_initial_posting_source
from .retained_extractions import identity, scoped_source, RetainedSourceInvalid
from .retained_items import authorize_owner

METHOD = "explicit_owner"
VERSION = 1
MAX_REVISION = 9223372036854775807


class InvalidJobPostingAllocation(APIException):
    status_code = 400
    default_code = "invalid_job_posting_allocation"
    default_detail = "Invalid posting allocation."


class JobPostingAllocationConflict(APIException):
    status_code = 409
    default_code = "job_posting_allocation_history_invalid"
    default_detail = "Posting allocation history is invalid."


def conflict(code):
    raise JobPostingAllocationConflict("Posting allocation cannot be applied.", code=code)


def allocation_key(item_id):
    return f"{ALLOCATION_KEY_PREFIX}{item_id}"


def _validate_locator(message):
    """Mirror canonical retention namespace rules without changing persisted text."""
    def text(value, limit, nonempty=True):
        if type(value) is not str or (nonempty and not value) or "\x00" in value:
            raise RetainedSourceInvalid()
        try:
            if len(value.encode("utf-8")) > limit:
                raise RetainedSourceInvalid()
        except UnicodeError:
            raise RetainedSourceInvalid() from None
    kinds = {"gmail": "gmail_message_id", "outlook": "graph_immutable_id", "imap": "imap_uid"}
    if message.provider not in kinds or message.locator_kind != kinds[message.provider]:
        raise RetainedSourceInvalid()
    text(message.locator_value, 512)
    text(message.folder, 512, False)
    text(message.stability, 128)
    if message.provider == "imap":
        if (not message.folder or not re.fullmatch(r"[1-9][0-9]{0,9}", message.locator_value)
                or int(message.locator_value) > 4294967295
                or not re.fullmatch(r"uidvalidity:[1-9][0-9]{0,9}", message.stability)
                or int(message.stability.split(":")[1]) > 4294967295):
            raise RetainedSourceInvalid()
    elif message.folder != "" or message.stability != "v1":
        raise RetainedSourceInvalid()


@dataclass(frozen=True)
class AllocationRecord:
    id: int
    posting_id: int
    posting_portable_id: UUID
    item_id: int
    interpretation_decision_id: int
    interpretation_revision: int
    initial_source_id: int
    account_binding_id: int
    account_id: int
    operation_id: UUID
    actor_id: int
    method: str
    allocation_version: int
    created_at: datetime


@dataclass(frozen=True)
class AllocationResult:
    requested_endpoint: str
    requested_id: int
    allocation: AllocationRecord | None
    replay: bool = False


def _binding(message, using, *, binding_id=None, historical=False):
    rows = AccountMailboxBinding.objects.using(using).select_related("account", "mailbox")
    row = rows.filter(pk=binding_id).first() if historical else rows.filter(mailbox_id=message.mailbox_id).first()
    if (row is None or row.mailbox_id != message.mailbox_id
            or row.account.workspace_id != message.workspace_id or row.mailbox.workspace_id != message.workspace_id
            or row.account.provider != message.provider or row.mailbox.provider != message.provider):
        conflict("job_posting_allocation_history_invalid" if historical else "job_posting_allocation_account_unavailable")
    return row


def validate_allocation(row, using):
    """Persisted historical witnesses only; no current applicability requirement."""
    item = Item.objects.using(using).filter(pk=row.item_id).first()
    posting = JobPosting.objects.using(using).select_related("account").filter(pk=row.posting_id).first()
    initial = PostingSource.objects.using(using).filter(pk=row.initial_source_id).first()
    selected = Decision.objects.using(using).filter(pk=row.interpretation_decision_id).first()
    if item is None or posting is None or initial is None or selected is None:
        raise JobPostingAllocationConflict()
    message = RetainedMessage.objects.using(using).select_related("mailbox").filter(pk=item.retained_message_id).first()
    if message is None:
        raise JobPostingAllocationConflict()
    interpretations._validate_source(message)
    _validate_locator(message)
    binding = _binding(message, using, binding_id=row.account_binding_id, historical=True)
    try:
        contract.operation_uuid(row.operation_id)
    except contract.InvalidExtraction:
        raise JobPostingAllocationConflict() from None
    if (row.method != METHOD or type(row.allocation_version) is not int or row.allocation_version != VERSION
            or posting.workspace_id != message.workspace_id or posting.account.workspace_id != message.workspace_id
            or posting.account_id != binding.account_id or posting.dedupe_key != allocation_key(item.pk)
            or initial.item_id != item.pk or initial.posting_id != posting.pk
            or initial.actor_id != row.actor_id or initial.method != METHOD or initial.decision_version != VERSION
            or selected.item_id != item.pk or selected.mode != "select"
            or not get_user_model().objects.using(using).filter(pk=row.actor_id).exists()):
        raise JobPostingAllocationConflict()
    chain = interpretations.resolve_chain(item, message, using=using, through=selected.revision)
    if chain.latest is None or chain.latest.pk != selected.pk:
        raise JobPostingAllocationConflict()
    return posting, selected


def _record(row, using):
    posting, selected = validate_allocation(row, using)
    return AllocationRecord(row.pk, posting.pk, posting.portable_id, row.item_id, selected.pk,
        selected.revision, row.initial_source_id, row.account_binding_id, posting.account_id,
        row.operation_id, row.actor_id, row.method, row.allocation_version, row.created_at)


def _item(workspace, item_id):
    item = Item.objects.filter(pk=item_id, retained_message__workspace=workspace).first()
    if item is None:
        raise NotFound()
    return item


def _posting(workspace, posting_id):
    row = JobPosting.objects.select_for_update(of=("self",)).filter(
        pk=posting_id, workspace=workspace, account__workspace=workspace).first()
    if row is None:
        raise NotFound()
    return row


def _insert_posting(workspace, item, message, binding, using):
    posting = JobPosting(workspace=workspace, account_id=binding.account_id,
        dedupe_key=allocation_key(item.pk), message_id=message.locator_value)
    models.Model.save(posting, using=using, force_insert=True)
    return posting


def _insert_allocation(row, using):
    validate_allocation(row, using)
    models.Model.save(row, using=using, force_insert=True)


def allocate_job_posting(*, actor, workspace, item_id, operation_id, expected_interpretation_revision):
    authorize_owner(actor, workspace)
    identity(item_id)
    try:
        operation_id = contract.operation_uuid(operation_id)
    except contract.InvalidExtraction:
        raise InvalidJobPostingAllocation() from None
    if type(expected_interpretation_revision) is not int or not 1 <= expected_interpretation_revision <= MAX_REVISION:
        raise InvalidJobPostingAllocation()
    using = "default"
    with transaction.atomic(using=using):
        lock_workspace(actor, workspace)
        item = _item(workspace, item_id)
        prior = Allocation.objects.filter(item=item).first()
        if prior is not None:
            _posting(workspace, prior.posting_id)
        message = scoped_source(workspace, item.retained_message_id, lock=True)
        if prior is not None:
            recorded = _record(prior, using)
            if recorded.operation_id != operation_id:
                conflict("job_posting_already_allocated")
            if recorded.interpretation_revision != expected_interpretation_revision:
                conflict("idempotency_key_reused")
            return AllocationResult("item", item.pk, recorded, True)
        if PostingSource.objects.filter(item=item).exists():
            conflict("retained_item_initial_mapping_exists")
        chain = interpretations.resolve_chain(item, message, using=using)
        if chain.revision != expected_interpretation_revision:
            conflict("stale_interpretation_revision")
        current = interpretations._state(item, message, chain, using)
        if current.state != "selected" or current.applicable_output is None:
            conflict("posting_interpretation_not_applicable")
        require_eligible_source(message)
        _validate_locator(message)
        binding = _binding(message, using)
        if JobPosting.objects.filter(dedupe_key=allocation_key(item.pk)).exists():
            conflict("job_posting_allocation_key_conflict")
        posting = _insert_posting(workspace, item, message, binding, using)
        initial = _append_initial_posting_source(item=item, posting=posting, actor=actor, using=using)
        row = Allocation(posting=posting, item=item, interpretation_decision=chain.latest,
            initial_source=initial, account_binding=binding, operation_id=operation_id, actor=actor,
            method=METHOD, allocation_version=VERSION)
        _insert_allocation(row, using)
        return AllocationResult("item", item.pk, _record(Allocation.objects.get(pk=row.pk), using))


def read_job_posting_allocation(*, actor, workspace, posting_id):
    authorize_owner(actor, workspace)
    identity(posting_id)
    with transaction.atomic():
        lock_workspace(actor, workspace)
        _posting(workspace, posting_id)
        row = Allocation.objects.filter(posting_id=posting_id).first()
        if row is None:
            return AllocationResult("posting", posting_id, None)
        item = _item(workspace, row.item_id)
        scoped_source(workspace, item.retained_message_id, lock=True)
        return AllocationResult("posting", posting_id, _record(row, "default"))


def read_retained_item_allocation(*, actor, workspace, item_id):
    authorize_owner(actor, workspace)
    identity(item_id)
    with transaction.atomic():
        lock_workspace(actor, workspace)
        item = _item(workspace, item_id)
        row = Allocation.objects.filter(item=item).first()
        if row is not None:
            _posting(workspace, row.posting_id)
        scoped_source(workspace, item.retained_message_id, lock=True)
        return AllocationResult("item", item_id, _record(row, "default") if row else None)
