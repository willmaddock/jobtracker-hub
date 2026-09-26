"""Immutable review snapshots, mutable disposition, and attachment admission.

Snapshot creation takes Workspace → RetainedMessage → review, without Application
locks. Disposition takes only the Workspace gate. Attachment holds that gate
through admission and delegates Workspace → Application → source to attach_message.
SQLite lock refusal requires caller replay; no automatic retries.
"""
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException, NotFound, ValidationError

from email_sync.models import RetainedMessage, RetainedObservation
from .creation import lock_workspace
from .models import (Application, ApplicationMessage, RetainedApplicationReview,
                     RetainedApplicationReviewCandidate, RetainedApplicationReviewDisposition)


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


class ReviewDispositionConflict(APIException):
    status_code = 409
    default_code = "review_dismissed"
    default_detail = "Restore this review before attaching a new Application."


def disposition_data(disposition):
    return {"state": "dismissed" if disposition and disposition.dismissed_at else "active",
            "revision": disposition.revision if disposition else 0,
            "dismissed_at": disposition.dismissed_at if disposition else None}


def validate_review_actor(actor, workspace, review_id):
    if not actor.is_authenticated or workspace.owner_id != actor.pk:
        raise NotFound()
    if type(review_id) is not int or not 0 < review_id <= 9223372036854775807:
        raise ValidationError("A positive canonical integer identity is required.")


def set_review_dismissal(*, actor, workspace, review_id, dismissed, expected_revision):
    """One desired-state writer; Workspace serializes even absent sidecars."""
    validate_review_actor(actor, workspace, review_id)
    if type(dismissed) is not bool:
        raise ValidationError("A boolean desired dismissal state is required.")
    if type(expected_revision) is not int or not 0 <= expected_revision <= 9223372036854775807:
        raise ValidationError({"expected_revision": "A nonnegative canonical integer is required."})
    with transaction.atomic():
        lock_workspace(actor, workspace)
        review = get_object_or_404(scoped_reviews(workspace), pk=review_id)
        disposition = RetainedApplicationReviewDisposition.objects.filter(review=review).first()
        current = disposition_data(disposition)
        if expected_revision != current["revision"]:
            raise ReviewDispositionConflict("Review disposition revision changed. Refetch current state.",
                                           code="stale_revision")
        if dismissed != (current["state"] == "dismissed"):
            if disposition is None:
                disposition = RetainedApplicationReviewDisposition(review=review)
            disposition.dismissed_at = timezone.now() if dismissed else None
            disposition.revision += 1
            disposition.save()
        return {"id": review.pk, "workspace_id": workspace.pk,
                "disposition": disposition_data(disposition)}


def attach_review(*, actor, workspace, review_id, application_id):
    """Hold Workspace through disposition admission and canonical pair delegation.

    No review/source row locks precede Application locks. attach_message retains
    sole creation authority and its Workspace → Application → source lock order.
    """
    from .message_relationships import attach_message

    validate_review_actor(actor, workspace, review_id)
    if type(application_id) is not int or not 0 < application_id <= 9223372036854775807:
        raise ValidationError("A positive canonical integer identity is required.")
    with transaction.atomic():
        lock_workspace(actor, workspace)
        review = get_object_or_404(scoped_reviews(workspace), pk=review_id)
        disposition = RetainedApplicationReviewDisposition.objects.filter(review=review).first()
        application = get_object_or_404(Application, pk=application_id, workspace=workspace)
        pair = ApplicationMessage.objects.filter(application=application,
                                                 retained_message_id=review.retained_message_id).first()
        if pair is not None and pair.workspace_id != workspace.pk:
            raise NotFound()
        if disposition and disposition.dismissed_at and pair is None:
            raise ReviewDispositionConflict()
        return attach_message(actor=actor, workspace=workspace, application_id=application_id,
                              retained_message_id=review.retained_message_id)
