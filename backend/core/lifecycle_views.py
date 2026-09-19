"""Explicit workspace lifecycle routes; retained detail GETs remain inspectable."""
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from core.workspace_scope import WorkspaceScopedMixin
from core.lifecycle import LifecycleContentionMixin, set_trash


class LifecycleView(LifecycleContentionMixin, WorkspaceScopedMixin, APIView):
    def post(self, request, kind, pk, transition, **kwargs):
        if not isinstance(request.data, dict) or set(request.data) != {"expected_revision"}:
            raise ValidationError({"expected_revision": "Supply only the expected lifecycle revision."})
        resource = set_trash(actor=request.user, workspace=self.get_workspace(), kind=kind,
                             pk=pk, trashed=transition == "trash",
                             expected_revision=request.data["expected_revision"])
        if kind == "applications":
            from applications.serializers import ApplicationSerializer
            return Response(ApplicationSerializer(resource).data)
        if kind == "documents":
            from documents.serializers import DocumentSerializer
            return Response(DocumentSerializer(resource).data)
        from documents.category_services import category_data
        return Response(category_data(resource))
