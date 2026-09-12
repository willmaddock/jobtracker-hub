"""Synchronous posting workflows scoped to the owner-authorized route Workspace."""
from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from core.workspace_scope import WorkspaceScopedMixin
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from applications.models import Application, Override, StatusHistory

from .models import JobPosting
from .serializers import ApplyJobPostingSerializer, JobPostingSerializer, SaveJobPostingSerializer
from .services import build_apply_response, ensure_postable, validate_apply_status

_VALID_APPLY_STATUSES = [choice[0] for choice in Application.STATUS_CHOICES]


class JobPostingViewSet(WorkspaceScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = JobPostingSerializer

    def get_queryset(self):
        # Unfiltered by status here on purpose -- list() below applies
        # the "new" filter itself. Detail actions (dismiss/restore/
        # save/apply) need to reach a posting regardless of its
        # current status (e.g. restore only makes sense on an already-
        # dismissed one), same as the original's get_job_posting().
        return JobPosting.objects.filter(
            workspace=self.get_workspace()
        ).filter(account__workspace=self.get_workspace()).filter(
            Q(applied_application__isnull=True) | Q(applied_application__workspace=self.get_workspace())
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
        """Turns a job posting into a real tracked Application.

        Simpler than the original's version: no application folder to
        create on disk and no email-evidence PDF to save alongside it
        (that whole surface was the Phase 4 folder->storage rewrite,
        and doesn't have a Document to attach yet without the actual
        source email bytes -- Phase 9's sync work is what will give
        this a real message to save as a Document). What's unchanged:
        the eligibility/status-validation rules themselves, still
        owned entirely by postings/services.py.
        """
        job = self.get_object()
        serializer = ApplyJobPostingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        status_value = data["status"].strip()
        validate_apply_status(status_value, _VALID_APPLY_STATUSES)
        ensure_postable(job, job.id)

        company = data["company"].strip() or (job.company or "").strip()
        role_label = data["role_label"].strip() or (job.title or "").strip()
        if not company:
            raise ValidationError({"company": "This field is required."})

        with transaction.atomic():
            application = Application.objects.create(
                workspace=job.workspace,
                section="applications",
                company=company,
                role_label=role_label,
                # No folder/Document backs this Application yet -- see
                # the docstring above. applications/models.py's unique
                # constraint (workspace, section, company, role_label,
                # source_relpath) means applying to two different
                # postings for the exact same company+role in the same
                # workspace will collide on this empty string; a real
                # Document-backed source_relpath in a later phase
                # removes that edge case.
                source_relpath="",
            )
            if status_value:
                Override.objects.update_or_create(
                    application=application, defaults={"manual_status": status_value},
                )
                StatusHistory.objects.create(
                    application=application,
                    status=status_value,
                    changed_at=timezone.now(),
                    source="job_posting_apply",
                )
            job.applied_application = application
            job.save(update_fields=["applied_application"])

        return Response(build_apply_response(application), status=status.HTTP_201_CREATED)
