"""Synchronous posting workflows scoped to the owner-authorized route Workspace."""
from __future__ import annotations

from applications.creation import CreationContentionMixin
from core.workspace_scope import WorkspaceScopedMixin
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import JobPosting, PostingApplicationConversion
from .serializers import ApplyJobPostingSerializer, JobPostingSerializer, SaveJobPostingSerializer


class JobPostingViewSet(CreationContentionMixin, WorkspaceScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = JobPostingSerializer

    def get_queryset(self):
        # Unfiltered by status here on purpose -- list() below applies
        # the "new" filter itself. Detail actions (dismiss/restore/
        # save/apply) need to reach a posting regardless of its
        # current status (e.g. restore only makes sense on an already-
        # dismissed one), same as the original's get_job_posting().
        return JobPosting.objects.filter(
            workspace=self.get_workspace()
        ).filter(account__workspace=self.get_workspace()).exclude(
            conversions__in=PostingApplicationConversion.objects.exclude(application_id=None).exclude(
                application__workspace=self.get_workspace())
        ).order_by("-received_at", "-id")

    def list(self, request, *args, **kwargs):
        """Every non-dismissed job posting, newest first -- what the
        Job Postings board renders (see _app/api.py's list_job_postings
        docstring: this list's count, not any Discovery query, is the
        canonical "Job Postings · N").
        """
        queryset = self.get_queryset().filter(status="new")
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None, **kwargs):
        job = self.get_object()
        job.status = "dismissed"
        job.save(update_fields=["status"])
        return Response({"ok": True})

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None, **kwargs):
        job = self.get_object()
        job.status = "new"
        job.save(update_fields=["status"])
        return Response({"ok": True})

    @action(detail=True, methods=["post"])
    def save(self, request, pk=None, **kwargs):
        """Toggles the starred/saved flag and returns the refreshed
        board list, same response shape as dismiss/restore's callers
        expect from the original (_app/api.py save_job_posting).
        """
        job = self.get_object()
        serializer = SaveJobPostingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job.saved = serializer.validated_data["saved"]
        job.save(update_fields=["saved"])
        queryset = self.get_queryset().filter(status="new")
        return Response(JobPostingSerializer(queryset, many=True).data)

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None, **kwargs):
        from applications.creation import request_creation
        # Resolve the route target before allocating an intent; replay reauthorizes.
        job = self.get_object()
        return request_creation(request, self.get_workspace(),
                                ApplyJobPostingSerializer(data=request.data), posting_id=job.pk)
