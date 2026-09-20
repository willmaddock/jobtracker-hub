"""Document workflows. Native categories live in category_views/category_services."""
from __future__ import annotations

from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.workspace_scope import WorkspaceScopedMixin, scoped_duplicate_counts

from .models import Document, DocumentOverride
from applications.derivation import derive_application
from core.lifecycle import locked_resource
from .serializers import (
    DocumentOverrideWriteSerializer,
    DocumentRenameSerializer,
    DocumentSerializer,
)
from .services import classify_doc_type
from core.lifecycle import LifecycleContentionMixin, require_live, workspace_mutation

class DocumentViewSet(LifecycleContentionMixin, WorkspaceScopedMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Metadata / rename / override for a single Document, all reached
    by its real id (see serializers.py's module docstring on why this
    drops the original's relpath identity). No list route here --
    listing is always scoped to one application, so it lives on
    ApplicationViewSet.documents (applications/views.py) instead of
    needing a redundant workspace-wide list here too.
    """

    serializer_class = DocumentSerializer

    def get_queryset(self):
        return Document.objects.filter(workspace=self.get_workspace(), application__workspace=self.get_workspace()).select_related(
            "override", "application"
        )

    def _serialize(self, document: Document) -> dict:
        counts = scoped_duplicate_counts(document.workspace, [document.content_hash])
        return DocumentSerializer(document, context={"duplicate_counts": counts}).data

    @action(detail=True, methods=["post"])
    @workspace_mutation
    def rename(self, request, pk=None, **kwargs):
        """Renames the file in place. doc_type is recomputed from the
        new filename via the same classify_doc_type rules used at
        upload time -- a rename is usually exactly how you'd fix a
        file the classifier couldn't read on its own. Unlike the
        original, no relpath-rekey step is needed for any existing
        doc-type override: DocumentOverride is a straight FK to this
        Document row, so it just carries over automatically.
        """
        document = locked_resource(self.get_workspace(), "documents", pk)
        require_live(document)
        serializer = DocumentRenameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_filename = serializer.validated_data["new_filename"]
        if new_filename == document.filename:
            return Response({"ok": True, "id": document.id, "unchanged": True})

        document.filename = new_filename
        document.ext = "." + new_filename.rsplit(".", 1)[-1].lower() if "." in new_filename else ""
        document.doc_type = classify_doc_type(new_filename)
        document.save(update_fields=["filename", "ext", "doc_type"])
        document._state.fields_cache.pop("override", None)
        derive_application(actor=request.user, workspace=self.get_workspace(), application_id=document.application_id)
        return Response(self._serialize(document))

    @action(detail=True, methods=["post"])
    @workspace_mutation
    def override(self, request, pk=None, **kwargs):
        """Manual doc-type correction for a file the filename-based
        classifier can't disambiguate on its own. Never touches the
        stored file itself.
        """
        document = locked_resource(self.get_workspace(), "documents", pk)
        require_live(document)
        serializer = DocumentOverrideWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        value = serializer.validated_data.get("doc_type_override") or None
        existing = getattr(document, "override", None)
        if (existing.doc_type_override if existing else None) == value:
            return Response(self._serialize(document))
        if value:
            DocumentOverride.objects.update_or_create(
                document=document, defaults={"doc_type_override": value}
            )
        else:
            DocumentOverride.objects.filter(document=document).delete()
        document._state.fields_cache.pop("override", None)
        derive_application(actor=request.user, workspace=self.get_workspace(), application_id=document.application_id)
        return Response(self._serialize(document))


class LegacyDocumentDeletionViewSet(viewsets.GenericViewSet):
    """Retired; never delete a retained row or storage object."""
    def delete(self, request, **kwargs):
        return Response({"code": "endpoint_retired", "detail": "Use workspace-scoped Trash."}, status=410)
