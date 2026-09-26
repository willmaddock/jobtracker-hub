"""Canonical initial snapshot writer; no relationship or review decision effects.

Lock order: Workspace gate → RetainedMessage → review. No Application row locks.
Gmail calls inside its existing message transaction after retention. Database
uniqueness is the final guard; SQLite lock refusal requires caller replay.
"""
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound, ValidationError

from email_sync.models import RetainedMessage, RetainedObservation
from .creation import lock_workspace
from .models import Application, RetainedApplicationReview, RetainedApplicationReviewCandidate


def ensure_application_review(*, actor, workspace, retained_message_id, observation_id,
                              classification, candidate_ids):
    if not actor.is_authenticated:
        raise NotFound()
    if not isinstance(candidate_ids, (list, tuple)):
        raise ValidationError("Supply candidate Application IDs.")
    for value in (retained_message_id, observation_id, *candidate_ids):
        if type(value) is not int or not 0 < value <= 9223372036854775807:
            raise ValidationError("A positive canonical integer identity is required.")
    ids = set(candidate_ids)
    counts = {"match": len(ids) == 1, "ambiguous": len(ids) > 1, "application": not ids}
    if classification not in counts or not counts[classification]:
        raise ValidationError("Classification must describe the supplied candidate set.")
    with transaction.atomic():
        lock_workspace(actor, workspace)
        message = get_object_or_404(RetainedMessage.objects.select_for_update(of=("self",)),
            pk=retained_message_id, workspace=workspace, mailbox__workspace=workspace)
        observation = get_object_or_404(RetainedObservation, pk=observation_id,
            workspace=workspace, key__workspace=workspace, message=message, mailbox=message.mailbox)
        candidates = list(Application.objects.filter(workspace=workspace, pk__in=ids).order_by("portable_id"))
        if len(candidates) != len(ids):
            raise NotFound()
        review = RetainedApplicationReview.objects.select_for_update().filter(retained_message=message).first()
        if review:
            if review.workspace_id != workspace.pk:
                raise NotFound()
            return review, False
        # Initial automatic effects remain paused for uncertain evidence. Existing
        # reviews above stay inspectable and replayable, without a new snapshot.
        if message.has_conflict or observation.state != "retained" or observation.key.has_conflict:
            raise ValidationError("Initial review requires an unconflicted canonical observation.")
        review, created = RetainedApplicationReview.objects.get_or_create(
            retained_message=message,
            defaults={"workspace": workspace, "originating_observation": observation,
                      "initial_classification": classification})
        if review.workspace_id != workspace.pk:
            raise NotFound()
        if created:
            for application in candidates:
                RetainedApplicationReviewCandidate.objects.create(review=review, application=application,
                    application_portable_id=application.portable_id)
        return review, created


def scoped_reviews(workspace):
    """Validate immutable review/source/provenance references for reads and attach."""
    return RetainedApplicationReview.objects.filter(workspace=workspace,
        retained_message__workspace=workspace, retained_message__mailbox__workspace=workspace,
        originating_observation__workspace=workspace, originating_observation__key__workspace=workspace,
        originating_observation__message_id=F("retained_message_id"),
        originating_observation__mailbox_id=F("retained_message__mailbox_id"))


def attach_review(*, actor, workspace, review_id, application_id):
    """Resolve immutable provenance, then delegate all creation/locking authority.

    No outer transaction or source/review locks: supported writers cannot reparent
    or delete reviews. attach_message reauthorizes ownership and checks mutable
    target/source eligibility inside its Workspace → Application → source transaction.
    """
    from .message_relationships import attach_message

    if not actor.is_authenticated or workspace.owner_id != actor.pk:
        raise NotFound()
    if type(review_id) is not int or not 0 < review_id <= 9223372036854775807:
        raise ValidationError("A positive canonical integer identity is required.")
    review = get_object_or_404(scoped_reviews(workspace), pk=review_id)
    return attach_message(actor=actor, workspace=workspace, application_id=application_id,
                          retained_message_id=review.retained_message_id)
