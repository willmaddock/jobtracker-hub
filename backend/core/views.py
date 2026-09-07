"""
core views.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md). GET /api/health was ported in
an earlier slice -- see its own docstring below for why it's the only
survivor of the "System / diagnostics" group. This slice adds the
"Cross-cutting views" group from the Phase 0 endpoint inventory:
attention, insights, search, browse, manage (+ merge/unmerge), and
hub/settings.

Two routes from that inventory group are NOT here, on purpose:

- POST /api/open and POST /api/open-url shelled out to the local OS's
  default file/URL opener (`open`/`xdg-open`/`start`) -- there is no
  "the user's OS" on a server process handling requests from an
  arbitrary browser, so there's no hosted equivalent at all, same
  reasoning as /api/diagnostics/reveal-log in the earlier core slice.
- GET /api/file and GET /api/preview-docx served a local path via
  infrastructure/paths.py's traversal guards. The migration plan's
  endpoint inventory flags these as becoming "fetch this object the
  user owns" once Document.file is a real FileField (Phase 4) -- that
  read already exists as Document.file's own storage URL (see
  documents/serializers.py's DocumentSerializer `file` field); there's
  no separate streaming endpoint left to build once the file field
  itself resolves to a real (signed, if the storage backend is
  private) URL.

Every view below is ownership-scoped the same way ApplicationViewSet/
DocumentViewSet already are -- `workspace__owner=request.user` --
except HubSettingsView, which (like documents/views.py's
CategoryOverrideView/CategoryDeleteView) needs a specific workspace id
in the request since HubSettings is a real per-workspace singleton,
not something to aggregate across every workspace a user owns.
"""
from __future__ import annotations

from django.db.models import Q
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Workspace
from applications.models import Application, CompanyAlias
from documents.models import Document, FolderOverride
from documents.serializers import DocumentSerializer
from documents.services import duplicate_counts
from documents.views import RESERVED_CATEGORY_SECTIONS

from .models import HubSettings
from .serializers import (
    ApplicationRowSerializer,
    HubSettingsSerializer,
    HubSettingsWriteSerializer,
    InsightsSerializer,
    ManageSerializer,
    MergeSerializer,
    SearchResultSerializer,
    UnmergeSerializer,
)
from .services import (
    annotate_application,
    compute_metrics,
    find_duplicate_groups,
    load_applications,
    needs_attention,
    suggest_duplicate_companies,
)


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"ok": True})


def _parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes")


def _get_owned_workspace(request, workspace_id) -> Workspace:
    """Shared by every view below that needs one specific workspace
    (rather than aggregating across every workspace the caller owns)
    -- same "required and must be a workspace you own" check
    documents/views.py's CategoryOverrideView/CategoryDeleteView
    already use, pulled out here since HubSettingsView, MergeView, and
    UnmergeView all need it too.
    """
    workspace = Workspace.objects.filter(owner=request.user, id=workspace_id).first()
    if workspace is None:
        raise ValidationError({"workspace": "Required and must be a workspace you own."})
    return workspace


class AttentionView(APIView):
    """GET /api/attention -- stale or next-action-due applications
    across every workspace the caller owns, same needs_attention()
    sort as the original (next-action-due first, then longest idle).
    """

    def get(self, request):
        queryset = Application.objects.filter(workspace__owner=request.user)
        apps = load_applications(queryset)
        attention = needs_attention(apps)
        return Response(ApplicationRowSerializer(attention, many=True).data)


class InsightsView(APIView):
    """GET /api/insights -- response/interview rates and average
    time-to-response, aggregated across every workspace the caller
    owns.
    """

    def get(self, request):
        queryset = Application.objects.filter(workspace__owner=request.user)
        apps = load_applications(queryset)
        return Response(InsightsSerializer(compute_metrics(apps)).data)


class SearchView(APIView):
    """GET /api/search?q=&show_personal= -- matches the original's
    filename/company search (the FTS-vs-LIKE fallback in _app/api.py's
    search() was a SQLite implementation detail; `icontains` on
    Document.filename / Application.company covers the same two match
    paths on a real database). Same personal-section and
    archived-category filtering rules as the original: an archived
    category disappears from search too, not just its own Browse tab.
    """

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        if not q:
            return Response([])
        show_personal = _parse_bool(request.query_params.get("show_personal"))

        documents = (
            Document.objects.filter(workspace__owner=request.user)
            .filter(Q(filename__icontains=q) | Q(application__company__icontains=q))
            .select_related("application")
        )
        if not show_personal:
            documents = documents.exclude(application__section="personal")

        archived_sections = set(
            FolderOverride.objects.filter(workspace__owner=request.user, archived=True).values_list(
                "workspace_id", "folder"
            )
        )

        results = []
        for document in documents:
            application = document.application
            if application.section not in RESERVED_CATEGORY_SECTIONS:
                if (application.workspace_id, application.section) in archived_sections:
                    continue
            results.append({
                "id": document.id,
                "filename": document.filename,
                "doc_type": document.doc_type,
                "application_id": application.id,
                "company": application.company,
                "role_label": application.role_label,
                "section": application.section,
            })
        return Response(SearchResultSerializer(results, many=True).data)


class BrowseView(APIView):
    """GET /api/browse?show_personal=&show_archived=&q= -- every
    application, grouped by section, with its documents nested.
    Archived state is checked at both the application level
    (Override.archived, via annotate_application) and the category
    level (FolderOverride, same as CategoryOverrideView) -- archiving
    a category hides everything in it from Browse without touching
    each application's own archived flag, same relationship the
    original's folder_overrides check had to item_overrides.archived.

    Returns a plain `{section: [item, ...]}` dict rather than a
    Serializer-shaped list, same as the original endpoint -- the
    section keys are dynamic (whatever sections exist for this user),
    which doesn't fit a fixed-field Serializer the way Attention/
    Insights/Search's regular list-of-rows shapes do.
    """

    def get(self, request):
        show_personal = _parse_bool(request.query_params.get("show_personal"))
        show_archived = _parse_bool(request.query_params.get("show_archived"))
        q = request.query_params.get("q", "").strip()
        ql = q.lower()

        applications = (
            Application.objects.filter(workspace__owner=request.user)
            .select_related("override")
            .prefetch_related("documents", "documents__override")
            .order_by("company", "role_label")
        )
        if not show_personal:
            applications = applications.exclude(section="personal")

        folder_overrides = {
            (fo.workspace_id, fo.folder): fo
            for fo in FolderOverride.objects.filter(workspace__owner=request.user)
        }

        out: dict[str, list[dict]] = {}
        for application in applications:
            row = annotate_application(application)
            if row["archived"] and not show_archived:
                continue
            if application.section not in RESERVED_CATEGORY_SECTIONS:
                folder_override = folder_overrides.get((application.workspace_id, application.section))
                if folder_override and folder_override.archived and not show_archived:
                    continue

            if not application.role_label or application.role_label == "(root)":
                label = application.company
            else:
                label = f"{application.company} — {application.role_label}"

            documents = list(application.documents.all())
            if ql and ql not in label.lower():
                if not any(ql in d.filename.lower() for d in documents):
                    continue

            counts = duplicate_counts(application.workspace, [d.content_hash for d in documents])
            row["label"] = label
            row["documents"] = DocumentSerializer(
                sorted(documents, key=lambda d: d.filename),
                many=True,
                context={"duplicate_counts": counts},
            ).data
            out.setdefault(application.section, []).append(row)
        return Response(out)


class ManageView(APIView):
    """GET /api/manage -- merge suggestions (companies not already
    aliased to the same canonical name), current aliases, archived
    applications, and duplicate-document groups, all aggregated across
    every workspace the caller owns.
    """

    def get(self, request):
        app_queryset = Application.objects.filter(workspace__owner=request.user)
        apps = load_applications(app_queryset)

        aliases = dict(
            CompanyAlias.objects.filter(workspace__owner=request.user).values_list("alias", "canonical")
        )
        suggestions = suggest_duplicate_companies(apps)
        unresolved = {
            key: names for key, names in suggestions.items()
            if len({aliases.get(name, name) for name in names}) > 1
        }
        archived = [a for a in apps if a["archived"]]

        doc_queryset = Document.objects.filter(workspace__owner=request.user)
        duplicate_documents = find_duplicate_groups(doc_queryset)

        data = {
            "duplicate_suggestions": unresolved,
            "aliases": aliases,
            "archived": archived,
            "duplicate_documents": duplicate_documents,
        }
        return Response(ManageSerializer(data).data)


class MergeView(APIView):
    """POST /api/manage/merge -- alias every name in `names` (except
    `canonical` itself) to `canonical`, within one workspace.
    """

    def post(self, request):
        serializer = MergeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workspace = _get_owned_workspace(request, serializer.validated_data["workspace"])
        canonical = serializer.validated_data["canonical"]
        for name in serializer.validated_data["names"]:
            if name != canonical:
                CompanyAlias.objects.update_or_create(
                    workspace=workspace, alias=name, defaults={"canonical": canonical}
                )
        return Response({"ok": True})


class UnmergeView(APIView):
    """POST /api/manage/unmerge -- removes one alias, within one
    workspace. Removing an alias that doesn't exist is a no-op, same
    as the original's plain DELETE ... WHERE alias = ?.
    """

    def post(self, request):
        serializer = UnmergeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workspace = _get_owned_workspace(request, serializer.validated_data["workspace"])
        CompanyAlias.objects.filter(workspace=workspace, alias=serializer.validated_data["alias"]).delete()
        return Response({"ok": True})


class HubSettingsView(APIView):
    """GET/POST /api/hub/settings?workspace= -- per-workspace role/
    location context plus user-authored dashboard customization.
    Created lazily on first read/write (get_or_create), same as the
    original's `hub_settings WHERE id = 1` singleton-with-defaults
    behavior, just keyed by workspace instead of being a single global
    row.
    """

    def get(self, request):
        workspace = _get_owned_workspace(request, request.query_params.get("workspace"))
        settings, _ = HubSettings.objects.get_or_create(workspace=workspace)
        return Response(HubSettingsSerializer(settings).data)

    def post(self, request):
        workspace = _get_owned_workspace(request, request.data.get("workspace"))
        serializer = HubSettingsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings, _ = HubSettings.objects.get_or_create(workspace=workspace)
        for field, value in serializer.validated_data.items():
            setattr(settings, field, value)
        settings.save()
        return Response(HubSettingsSerializer(settings).data)
