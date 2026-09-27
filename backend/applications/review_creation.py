"""Review-specific creation context. Allocation and intent completion stay in creation.

All mutation helpers execute inside creation's Workspace-gated transaction. No
Application allocator, challenge writer, disposition writer or relationship writer
lives here. Protected result references do not implement future purge policy.
"""
from copy import deepcopy

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException, NotFound, ValidationError

from core.lifecycle import lifecycle_data
from .models import (ApplicationMessage, RetainedApplicationReviewCandidate,
                     RetainedApplicationReviewDisposition, RetainedReviewCreationResult)
from .retained_reviews import scoped_reviews, disposition_data, ReviewDispositionConflict
from .serializers import ApplicationSerializer


class CreationResultIntegrityError(APIException):
    status_code = 500
    default_code = "creation_result_inconsistent"
    default_detail = "The completed creation result is inconsistent. No new effect was performed."


def get_review(workspace, review_id):
    if type(review_id) is not int or not 0 < review_id <= 9223372036854775807:
        raise ValidationError("A positive canonical review identity is required.")
    return get_object_or_404(scoped_reviews(workspace).select_related("retained_message"), pk=review_id)


def current_disposition(review):
    return disposition_data(RetainedApplicationReviewDisposition.objects.filter(review=review).first())


def admit(review, candidate_id):
    from .message_relationships import require_eligible_source
    if current_disposition(review)["state"] == "dismissed":
        raise ReviewDispositionConflict("Restore this review before creating an Application.")
    require_eligible_source(review.retained_message)
    candidate = None
    if candidate_id is not None:
        candidate = get_object_or_404(RetainedApplicationReviewCandidate.objects.select_related("application"),
                                      pk=candidate_id, review=review)
        if candidate.application_id and (candidate.application.workspace_id != review.workspace_id
                or candidate.application.portable_id != candidate.application_portable_id):
            raise NotFound()
    return candidate


def validate_link(link, review):
    if (link.workspace_id != review.workspace_id or link.application.workspace_id != review.workspace_id
            or link.retained_message_id != review.retained_message_id
            or link.retained_message.workspace_id != review.workspace_id
            or link.retained_message.mailbox.workspace_id != review.workspace_id):
        raise NotFound()


def validate_result(row, review):
    from .creation import review_digest
    validate_link(row.application_message, review)
    intent = row.request_intent
    if row.review_id != review.pk or intent.workspace_id != review.workspace_id:
        raise NotFound()
    if row.candidate_id and row.candidate.review_id != review.pk:
        raise NotFound()
    if not isinstance(row.input_snapshot, dict):
        raise CreationResultIntegrityError()
    if (not intent.completed or intent.kind != "review_create"
            or intent.application_id != row.application_message.application_id
            or intent.result_portable_id != row.application_message.application.portable_id
            or row.snapshot_version != 1 or row.input_snapshot.get("candidate_id") != row.candidate_id
            or intent.digest != review_digest(review.workspace_id, review.pk, row.input_snapshot)):
        raise CreationResultIntegrityError()


def results_for(review):
    return RetainedReviewCreationResult.objects.filter(review=review).select_related(
        "request_intent", "candidate", "application_message__application",
        "application_message__retained_message__mailbox")


def application_context(app):
    return {"id": app.pk, "portable_id": str(app.portable_id),
            "company": app.company, "role_label": app.role_label, **lifecycle_data(app)}


def repeat_context(review):
    prior = []
    for row in results_for(review).order_by("pk"):
        validate_result(row, review)
        prior.append({"id": row.pk, "application_message_id": row.application_message_id,
                      "application": application_context(row.application_message.application)})
    links = []
    for link in ApplicationMessage.objects.filter(retained_message_id=review.retained_message_id).select_related(
            "application", "retained_message__mailbox").order_by("pk"):
        validate_link(link, review)
        links.append({"id": link.pk, "portable_id": str(link.portable_id),
                      "application": application_context(link.application)})
    return {"prior_creation_results": prior, "source_relationships": links}


def finish(*, actor, workspace, review, candidate, intent, app, supplied):
    from .message_relationships import attach_message
    link, created = attach_message(actor=actor, workspace=workspace, application_id=app.pk,
                                   retained_message_id=review.retained_message_id)
    if not created:
        raise CreationResultIntegrityError()
    return RetainedReviewCreationResult.objects.create(review=review, request_intent=intent,
        candidate=candidate, application_message=link, input_snapshot=deepcopy(supplied))


def result_data(row, review):
    from .message_views import relationship_data
    validate_result(row, review)
    return {"id": row.pk, "review_id": review.pk, "workspace_id": review.workspace_id,
            "candidate_id": row.candidate_id, "created_at": row.created_at,
            "snapshot_version": row.snapshot_version, "input_snapshot": deepcopy(row.input_snapshot),
            "application": ApplicationSerializer(row.application_message.application).data,
            "application_message": relationship_data(row.application_message),
            "disposition": current_disposition(review)}


def replay(intent, review):
    row = results_for(review).filter(request_intent=intent).first()
    if row is None:
        raise CreationResultIntegrityError()
    return result_data(row, review)


def result_page(review, cursor):
    if not cursor.isascii() or not cursor.isdigit() or len(cursor) > 19 or int(cursor) > 9223372036854775807:
        raise ValidationError("Invalid creation results cursor.")
    rows = list(results_for(review).filter(pk__gt=int(cursor)).order_by("pk")[:51])
    return {"results": [result_data(row, review) for row in rows[:50]],
            "next_after": rows[49].pk if len(rows) > 50 else None}
