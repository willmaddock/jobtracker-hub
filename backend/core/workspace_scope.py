"""Request-local selected Workspace resolution for normal product endpoints."""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from accounts.models import Workspace


class WorkspaceScopedMixin:
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.get_workspace()
        forbidden = {"workspace", "workspace_id", "owner", "owner_id"}
        supplied = forbidden.intersection(request.query_params)
        if hasattr(request.data, "keys"):
            supplied |= forbidden.intersection(request.data.keys())
        if supplied:
            raise ValidationError({field: "Scope is assigned by the route and authenticated user."
                                   for field in sorted(supplied)})

    def get_workspace(self):
        if not hasattr(self, "_workspace"):
            self._workspace = get_object_or_404(
                Workspace, pk=self.kwargs["workspace_id"], owner=self.request.user)
        return self._workspace


def scoped_duplicate_counts(workspace, content_hashes):
    """Count only documents whose redundant Workspace/parent ownership agrees."""
    from django.db.models import Count
    from documents.models import Document

    hashes = {value for value in content_hashes if value}
    if not hashes:
        return {}
    rows = Document.objects.filter(
        workspace=workspace, application__workspace=workspace, content_hash__in=hashes
    ).values("content_hash").annotate(count=Count("id"))
    return {row["content_hash"]: row["count"] for row in rows}
