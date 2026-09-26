"""Read-only canonical review inspection; content stays in retained inspection."""
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from rest_framework.response import Response

from email_sync.retained_views import Inspection, message_summary
from .models import ApplicationMessage, RetainedApplicationReview


def reviews(workspace):
    return RetainedApplicationReview.objects.filter(workspace=workspace,
        retained_message__workspace=workspace, retained_message__mailbox__workspace=workspace,
        originating_observation__workspace=workspace, originating_observation__key__workspace=workspace,
        originating_observation__message_id=F("retained_message_id"),
        originating_observation__mailbox_id=F("retained_message__mailbox_id")
    ).select_related("retained_message", "originating_observation").annotate(candidate_count=Count("candidates"))


def review_summary(row):
    return {"id": row.pk, "portable_id": str(row.portable_id), "workspace_id": row.workspace_id,
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
        relationships = ApplicationMessage.objects.filter(workspace=workspace,
            retained_message=row.retained_message, application__workspace=workspace).order_by("pk")
        return Response({**review_summary(row), "candidates": suggestions,
            "relationships": [{"id": link.pk, "portable_id": str(link.portable_id),
                "application_id": link.application_id, "origin": link.origin,
                "created_at": link.created_at} for link in relationships]})
