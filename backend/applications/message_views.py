"""Bounded canonical relationship inspection and explicit attachment."""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from core.lifecycle import LifecycleContentionMixin, require_live
from email_sync.retained_views import Inspection, message_summary
from .message_relationships import attach_message
from .models import Application, ApplicationMessage


def relationship_data(row):
    return {"id": row.pk, "portable_id": str(row.portable_id),
            "workspace_id": row.workspace_id, "application_id": row.application_id,
            "retained_message_id": row.retained_message_id, "origin": row.origin,
            "created_at": row.created_at, "retained_message": message_summary(row.retained_message)}


class ApplicationMessages(LifecycleContentionMixin, Inspection):
    http_method_names = ["get", "post", "head", "options"]

    def get(self, request, workspace_id, pk, format=None):
        workspace = self.get_workspace()
        application = get_object_or_404(Application, pk=pk, workspace=workspace)
        require_live(application)
        return self.page(ApplicationMessage.objects.filter(
            workspace=workspace, application=application, retained_message__workspace=workspace,
            retained_message__mailbox__workspace=workspace).select_related("retained_message"), relationship_data)

    def post(self, request, workspace_id, pk, format=None):
        if not isinstance(request.data, dict) or set(request.data) != {"retained_message_id"}:
            raise ValidationError("Supply only retained_message_id.")
        row, created = attach_message(actor=request.user, workspace=self.get_workspace(),
            application_id=pk, retained_message_id=request.data["retained_message_id"])
        return Response(relationship_data(row), status=201 if created else 200)
