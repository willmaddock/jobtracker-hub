"""Canonical reversible lifecycle authority. No storage writes; direct evidence changes explicitly derive.

All lifecycle/ordinary product mutations acquire the existing workspace gate,
then category (when needed), Application, Document. This also serializes category
assignment and parent/child transitions. SQLite takes the write gate before reads.
"""
from functools import wraps

from django.db import OperationalError, connection, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.response import Response


class LifecycleConflict(APIException):
    status_code = 409
    default_code = "resource_trashed"
    default_detail = "Restore this resource before ordinary mutation."


def require_live(resource):
    if resource.effective_trashed:
        raise LifecycleConflict()


def lifecycle_data(resource):
    return {"is_trashed": resource.is_trashed, "trashed_at": resource.trashed_at.isoformat() if resource.trashed_at else None,
            "effective_trashed": resource.effective_trashed,
            "lifecycle_revision": resource.lifecycle_revision}


def workspace_mutation(method):
    """Keep eligibility checks and the ordinary write under the lifecycle gate."""
    @wraps(method)
    def guarded(self, request, *args, **kwargs):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return method(self, request, *args, **kwargs)
        from applications.creation import lock_workspace
        with transaction.atomic():
            lock_workspace(request.user, self.get_workspace())
            return method(self, request, *args, **kwargs)
    return guarded


class LifecycleContentionMixin:
    def handle_exception(self, exc):
        if isinstance(exc, OperationalError) and connection.vendor == "sqlite" and "locked" in str(exc).lower():
            return Response({"code": "lifecycle_busy", "detail": "Database busy. Refetch state before retrying."}, status=503)
        return super().handle_exception(exc)


def locked_resource(workspace, kind, pk):
    from applications.models import Application
    from documents.models import Category, Document
    model = {"applications": Application, "documents": Document, "categories": Category}[kind]
    queryset = model.objects.filter(workspace=workspace)
    if kind == "documents":
        queryset = queryset.filter(application__workspace=workspace)
        parent_id = queryset.filter(pk=pk).values_list("application_id", flat=True).first()
        if parent_id is None:
            raise NotFound()
        parent = Application.objects.select_for_update().get(pk=parent_id, workspace=workspace)
    resource = queryset.select_for_update().filter(pk=pk).first()
    if resource is None:
        raise NotFound()
    if kind == "documents":
        resource.application = parent
    return resource


def set_trash(*, actor, workspace, kind, pk, trashed, expected_revision):
    from applications.creation import lock_workspace
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValidationError({"expected_revision": "A nonnegative integer is required."})
    with transaction.atomic():
        lock_workspace(actor, workspace)
        resource = locked_resource(workspace, kind, pk)
        if resource.lifecycle_revision != expected_revision:
            raise LifecycleConflict("Lifecycle revision changed. Refetch current state.", code="stale_revision")
        if not trashed and kind == "documents" and resource.application.is_trashed:
            raise LifecycleConflict("Restore the parent Application first.", code="parent_trashed")
        if resource.is_trashed != trashed:
            resource.trashed_at = timezone.now() if trashed else None
            resource.lifecycle_revision += 1
            resource.save(update_fields=["trashed_at", "lifecycle_revision"])
            from applications.derivation import derive_application
            if kind == "documents":
                if resource.application.is_trashed:
                    parent = resource.application
                    parent.derivation_state = "needs_reconciliation"
                    parent.save(update_fields=["derivation_state"])
                else:
                    derive_application(actor=actor, workspace=workspace, application_id=resource.application_id)
            elif kind == "applications" and not trashed and resource.derivation_state == "needs_reconciliation":
                resource = derive_application(actor=actor, workspace=workspace, application_id=resource.pk)
        return resource
