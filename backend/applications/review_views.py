"""Canonical review inspection and explicit attachment to existing Applications."""
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from core.lifecycle import LifecycleContentionMixin
from .message_views import relationship_data
from .retained_reviews import attach_review, scoped_reviews

from email_sync.retained_views import Inspection, message_summary
from .models import ApplicationMessage


def reviews(workspace):
    return scoped_reviews(workspace).select_related(
        "retained_message", "originating_observation").annotate(
            candidate_count=Count("candidates", distinct=True),
            relationship_count=Count("retained_message__application_relationships", distinct=True,
                filter=Q(retained_message__application_relationships__workspace=workspace,
                         retained_message__application_relationships__application__workspace=workspace)))


def attachment_data(count):
    return {"attachment_status": "attached" if count else "unattached", "relationship_count": count}


def review_relationships(workspace, message_id):
    return ApplicationMessage.objects.filter(workspace=workspace,
        retained_message_id=message_id, retained_message__workspace=workspace,
        retained_message__mailbox__workspace=workspace, application__workspace=workspace)


def review_summary(row):
    return {**attachment_data(row.relationship_count), "id": row.pk, "portable_id": str(row.portable_id), "workspace_id": row.workspace_id,
            "retained_message": message_summary(row.retained_message),
            "subject": row.retained_message.content.get("subject"),
            "initial_classification": row.initial_classification, "candidate_count": row.candidate_count,
            "snapshot_version": row.snapshot_version, "created_at": row.created_at,
            "originating_observation_id": row.originating_observation_id,
            "observed_at": row.originating_observation.observed_at}


class RetainedApplicationReviewList(Inspection):
    def get(self, request, workspace_id, format=None):
        return self.page(reviews(self.get_workspace()), review_summary)


class RetainedApplicationReviewDetail(Inspection):
    def get(self, request, workspace_id, pk, format=None):
        workspace = self.get_workspace()
        row = get_object_or_404(reviews(workspace), pk=pk)
        candidates = row.candidates.filter(Q(application__isnull=True) | Q(
            application__workspace=workspace, application__portable_id=F("application_portable_id")
        )).select_related("application").order_by("application_portable_id")
        suggestions = []
        for candidate in candidates:
            app = candidate.application
            availability = "removed" if app is None else "trashed" if app.is_trashed else "live"
            suggestions.append({"id": candidate.pk, "application_id": candidate.application_id,
                "application_portable_id": str(candidate.application_portable_id),
                "created_at": candidate.created_at, "availability": availability,
                "attachable": availability == "live" and not row.retained_message.has_conflict,
                "current_application": None if app is None else {
                    "company": app.company, "role_label": app.role_label, "section": app.section,
                    "trashed_at": app.trashed_at, "lifecycle_revision": app.lifecycle_revision}})
        relationships = review_relationships(workspace, row.retained_message_id).select_related("application").order_by("pk")
        return Response({**review_summary(row), "candidates": suggestions,
            "relationships": [{"id": link.pk, "portable_id": str(link.portable_id),
                "application_id": link.application_id, "origin": link.origin,
                "created_at": link.created_at,
                "availability": "trashed" if link.application.is_trashed else "live"} for link in relationships]})


class RetainedApplicationReviewAttach(LifecycleContentionMixin, Inspection):
    http_method_names = ["post", "options"]

    def post(self, request, workspace_id, pk, format=None):
        if not isinstance(request.data, dict) or set(request.data) != {"application_id"}:
            raise ValidationError("Supply only application_id.")
        workspace = self.get_workspace()
        row, created = attach_review(actor=request.user, workspace=workspace,
                                     review_id=pk, application_id=request.data["application_id"])
        # A fresh derived read after commit; no stored state or response-time writes.
        count = review_relationships(workspace, row.retained_message_id).count()
        return Response({**relationship_data(row), **attachment_data(count)},
                        status=201 if created else 200)
