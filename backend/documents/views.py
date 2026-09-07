"""documents views.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md) -- DRF surface for the
"Categories & documents" section of the Phase 0 endpoint inventory.
Upload and per-application listing live on ApplicationViewSet instead
(applications/views.py's `documents` action) -- both need an owned
Application in hand first, so scoping them there avoids a second
ownership check.

CATEGORIES, RESHAPED: the original app derived a "category" (a Browse
tab like Credentials or Network) by walking top-level folders on disk
and classifying each one with classify_section() -- and had to handle
more than one physical folder backing the same tab (see _app/api.py's
_folder_key docstring: "Certifications" and "Degree and Transcrips"
both showing under "Credentials"). None of that machinery has an
equivalent here: every Application row (Application, despite the
name, already covers credentials/network/leads/etc -- see
applications/models.py's docstring) carries its own `section` field
directly, chosen at creation time instead of derived from a folder
name. So a category is just "every Application in this workspace
whose section isn't 'applications', grouped by section" -- one row
per section, never split across several folders, because there's no
folder layer left to split across.

Archive state for a category still needs somewhere durable to live,
so it reuses FolderOverride (documents/models.py) with `folder` set
to the section id itself -- the folder-vs-section distinction that
model's docstring describes doesn't apply once folder and section are
literally the same string here, but the table still does exactly the
job its name says: an archived flag keyed by category identity.

There's no `/api/categories/new` here: the original created an empty
folder placeholder ahead of any real file landing in it. That doesn't
map to a DB-only model -- a category now simply exists once an
Application with that section exists, the same way every other
section already works. Creating one is just
`POST /api/applications` with a `section` other than "applications"
(see applications/serializers.py's ApplicationCreateSerializer).
"""
from __future__ import annotations

from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Workspace
from applications.models import Application

from .models import Document, DocumentOverride, FolderOverride
from .serializers import (
    CategoryOverrideWriteSerializer,
    CategorySerializer,
    DocumentOverrideWriteSerializer,
    DocumentRenameSerializer,
    DocumentSerializer,
)
from .services import classify_doc_type, duplicate_counts

RESERVED_CATEGORY_SECTIONS = {"applications"}


class DocumentViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """rename / delete / override for a single Document, all reached
    by its real id (see serializers.py's module docstring on why this
    drops the original's relpath identity). No list route here --
    listing is always scoped to one application, so it lives on
    ApplicationViewSet.documents (applications/views.py) instead of
    needing a redundant workspace-wide list here too.
    """

    serializer_class = DocumentSerializer

    def get_queryset(self):
        return Document.objects.filter(workspace__owner=self.request.user).select_related(
            "override", "application"
        )

    def _serialize(self, document: Document) -> dict:
        counts = duplicate_counts(document.workspace, [document.content_hash])
        return DocumentSerializer(document, context={"duplicate_counts": counts}).data

    @action(detail=True, methods=["post"])
    def rename(self, request, pk=None):
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
    def override(self, request, pk=None):
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

    @action(detail=True, methods=["post"])
    def delete(self, request, pk=None):
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


def _category_rows(workspace) -> list[dict]:
    applications = Application.objects.filter(workspace=workspace).exclude(
        section__in=RESERVED_CATEGORY_SECTIONS
    )
    overrides = {fo.folder: fo for fo in FolderOverride.objects.filter(workspace=workspace)}

    grouped: dict[str, list[int]] = {}
    for app_id, section in applications.values_list("id", "section"):
        grouped.setdefault(section, []).append(app_id)

    rows = []
    for section, app_ids in sorted(grouped.items()):
        doc_count = sum(
            application.documents.count()
            for application in Application.objects.filter(id__in=app_ids)
        )
        rows.append({
            "section": section,
            "item_count": len(app_ids),
            "doc_count": doc_count,
            "archived": bool(overrides.get(section) and overrides[section].archived),
        })
    return rows


class CategoryListView(APIView):
    """GET /api/categories -- every non-reserved section currently in
    use in this workspace, with item/doc counts and archive state.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = _category_rows_for(request)
        serializer = CategorySerializer(rows, many=True)
        return Response(serializer.data)


def _category_rows_for(request):
    # Categories are workspace-scoped like everything else, but this
    # endpoint (unlike applications/postings) has no single-workspace
    # URL segment to key off of -- it aggregates across every
    # workspace the caller owns, one row per (workspace, section)
    # collapsed the same way the frontend already expects a flat
    # category list.
    rows: list[dict] = []
    for workspace in Workspace.objects.filter(owner=request.user):
        rows.extend(_category_rows(workspace))
    return rows


class CategoryOverrideView(APIView):
    """POST /api/categories/{section}/override -- archive/unarchive
    a category. `workspace_id` is required in the body since section
    ids aren't globally unique (two workspaces can both have a
    "leads" category) -- same ownership-scoping requirement every
    other write in this codebase has, just spelled out explicitly
    here instead of coming from a URL segment.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, section):
        workspace_id = request.data.get("workspace")
        workspace = Workspace.objects.filter(owner=request.user, id=workspace_id).first()
        if workspace is None:
            raise ValidationError({"workspace": "Required and must be a workspace you own."})

        serializer = CategoryOverrideWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        archived = serializer.validated_data["archived"]

        has_items = Application.objects.filter(workspace=workspace, section=section).exists()
        if not has_items:
            return Response(
                {"detail": f"No category '{section}' found in this workspace."},
                status=status.HTTP_404_NOT_FOUND,
            )

        FolderOverride.objects.update_or_create(
            workspace=workspace, folder=section,
            defaults={"section": section, "archived": archived},
        )
        return Response({"ok": True, "section": section, "archived": archived})


class CategoryDeleteView(APIView):
    """POST /api/categories/{section}/delete -- permanently deletes
    every Application (and, via FK cascade, every Document) in this
    category. Requires the category to already be archived first,
    same server-side re-check pattern applications/views.py's
    bulk_delete uses for a destructive bulk action.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, section):
        workspace_id = request.data.get("workspace")
        workspace = Workspace.objects.filter(owner=request.user, id=workspace_id).first()
        if workspace is None:
            raise ValidationError({"workspace": "Required and must be a workspace you own."})

        override = FolderOverride.objects.filter(workspace=workspace, folder=section).first()
        if not (override and override.archived):
            return Response(
                {"detail": "Not archived — archive this category before deleting."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        applications = Application.objects.filter(workspace=workspace, section=section)
        deleted_count = applications.count()
        with transaction.atomic():
            applications.delete()
            override.delete()
        return Response({"ok": True, "section": section, "deleted_count": deleted_count})
