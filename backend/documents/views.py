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
from .serializers import (
    DocumentOverrideWriteSerializer,
    DocumentRenameSerializer,
    DocumentSerializer,
)
from .services import classify_doc_type

class DocumentViewSet(WorkspaceScopedMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
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
    def rename(self, request, pk=None, **kwargs):
        """Renames the file in place. doc_type is recomputed from the
        new filename via the same classify_doc_type rules used at
        upload time -- a rename is usually exactly how you'd fix a
        file the classifier couldn't read on its own. Unlike the
        original, no relpath-rekey step is needed for any existing
        doc-type override: DocumentOverride is a straight FK to this
        Document row, so it just carries over automatically.
        """
        document = self.get_object()
        serializer = DocumentRenameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_filename = serializer.validated_data["new_filename"]
        if new_filename == document.filename:
            return Response({"ok": True, "id": document.id, "unchanged": True})

        document.filename = new_filename
        document.ext = "." + new_filename.rsplit(".", 1)[-1].lower() if "." in new_filename else ""
        document.doc_type = classify_doc_type(new_filename)
        document.save(update_fields=["filename", "ext", "doc_type"])
        return Response(self._serialize(document))

    @action(detail=True, methods=["post"])
    def override(self, request, pk=None, **kwargs):
        """Manual doc-type correction for a file the filename-based
        classifier can't disambiguate on its own. Never touches the
        stored file itself.
        """
        document = self.get_object()
        serializer = DocumentOverrideWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        value = serializer.validated_data.get("doc_type_override") or None
        if value:
            DocumentOverride.objects.update_or_create(
                document=document, defaults={"doc_type_override": value}
            )
        else:
            DocumentOverride.objects.filter(document=document).delete()
        return Response(self._serialize(document))


class LegacyDocumentDeletionViewSet(viewsets.GenericViewSet):
    """Preserves the existing deletion endpoint independently of scoped actions."""

    serializer_class = DocumentSerializer
    def get_queryset(self):
        return Document.objects.filter(workspace__owner=self.request.user).select_related(
            "override", "application")

    @action(detail=True, methods=["post"])
    def delete(self, request, pk=None, **kwargs):
        """Deletes both the storage object and the Document row --
        the original moved the file to the OS Trash (recoverable);
        there's no equivalent "trash" tier for object storage here,
        so this is a real delete, same as Application/JobPosting
        delete elsewhere in this API.
        """
        document = self.get_object()
        document_id = document.id
        document.file.delete(save=False)
        document.delete()
        return Response({"ok": True, "id": document_id})
