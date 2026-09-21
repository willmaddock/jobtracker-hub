"""Canonical explicit attachment. No provider, legacy or derivation effects.

One atomic transaction; deterministic locks: Workspace gate, Application, retained
message, then resolve/create the immutable pair. Competing writers take the same
Workspace gate first. No mailbox/key writes or locks are needed here. SQLite lock
refusal is exposed to callers, never hidden by a retry loop.
"""
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException, NotFound, ValidationError

from core.lifecycle import require_live
from email_sync.models import RetainedMessage
from .creation import lock_workspace
from .models import Application, ApplicationMessage


class SourceIneligible(APIException):
    status_code = 409
    default_code = "retained_source_ineligible"
    default_detail = "Retained source identity must be resolved and unconflicted."


def attach_message(*, actor, workspace, application_id, retained_message_id):
    if not actor.is_authenticated:
        raise NotFound()
    for value in (application_id, retained_message_id):
        if type(value) is not int or not 0 < value <= 9223372036854775807:
            raise ValidationError("A positive canonical integer identity is required.")
    with transaction.atomic():
        lock_workspace(actor, workspace)
        application = get_object_or_404(Application.objects.select_for_update(),
                                       pk=application_id, workspace=workspace)
        require_live(application)
        message = get_object_or_404(RetainedMessage.objects.select_for_update(of=("self",)),
            pk=retained_message_id, workspace=workspace, mailbox__workspace=workspace)
        # Canonical rows are allocated only by retention.py with a complete strong
        # namespace. Observations are not accepted or promoted by this service.
        if message.has_conflict:
            raise SourceIneligible()
        row, created = ApplicationMessage.objects.get_or_create(
            application=application, retained_message=message,
            defaults={"workspace": workspace, "origin": ApplicationMessage.Origin.MANUAL})
        if row.workspace_id != workspace.pk:
            raise NotFound()
        return row, created
