"""Workspace-scoped Application workflows; evidence writes explicitly derive."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from .dossier import assemble_dossier
from .derivation import apply_overrides, derive_application, effective_date
from .models import Application
from .serializers import (
    ApplicationCreateSerializer,
    ApplicationSerializer,
    BulkOverrideWriteSerializer,
    OverrideWriteSerializer,
)
from .services import (
    compute_bulk_override_fields,
    compute_override_fields,
)

# email_sync imports the other direction already (AccountMatch ->
# Application FK) -- see email_sync/models.py's module docstring, so
# this is a one-way dependency here too, not a cycle.
from email_sync.models import AccountMatch

# The `documents` action below (list + upload, deferred from the
# slice2 recommendation) needs these -- documents/views.py imports
# Application the same direction, so this is a one-way dependency,
# not a cycle.
from documents.models import Document, DocumentExtraction
from documents.serializers import DocumentSerializer, DocumentUploadSerializer
from applications.creation import CreationContentionMixin
from core.workspace_scope import WorkspaceScopedMixin, scoped_duplicate_counts

from documents.services import classify_doc_type, sha256_of
from core.lifecycle import LifecycleContentionMixin, require_live, workspace_mutation

_VALID_STATUSES = [choice[0] for choice in Application.STATUS_CHOICES]


class ApplicationViewSet(CreationContentionMixin, LifecycleContentionMixin, WorkspaceScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    def get_queryset(self):
        queryset = Application.objects.filter(workspace=self.get_workspace())
        if self.action == "list" and self.request.query_params.get("show_trashed", "").lower() not in {"true", "1"}:
            queryset = queryset.live()
        return (
            queryset
            .select_related("override", "category_membership__category")
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return ApplicationCreateSerializer
        return ApplicationSerializer

    def create(self, request, *args, **kwargs):
        from .creation import request_creation
        return request_creation(request, self.get_workspace(), self.get_serializer(data=request.data))

    @action(detail=True, methods=["get", "post"])
    @workspace_mutation
    def documents(self, request, pk=None, **kwargs):
        """GET lists this application's documents; POST uploads one
        or more new ones. Same URL for both, matching the original's
        single `/api/applications/{item_id}/documents` route for
        list+upload.

        Upload writes straight to S3-compatible storage (Phase 4)
        instead of the original's Applications/<Company>/<Role>/
        folder on disk -- classify_doc_type still runs against the
        filename the same way build_index.py's indexer did, so a new
        upload is classified immediately instead of waiting for a
        rebuild. content_hash is real SHA-256 of the uploaded bytes
        (documents/services.py's sha256_of), used only for the
        informational duplicate_count badge -- uploads are never
        deduped or rejected on a hash match, same as the original.
        """
        application = self.get_object()
        if request.method == "GET":
            documents = application.documents.filter(workspace=self.get_workspace())
            if request.query_params.get("show_trashed", "").lower() not in {"1", "true"}:
                documents = documents.live()
            documents = documents.select_related("override", "application").order_by(
                "doc_type", "filename"
            )
            counts = scoped_duplicate_counts(
                application.workspace, [d.content_hash for d in documents]
            )
            serializer = DocumentSerializer(
                documents, many=True, context={"duplicate_counts": counts}
            )
            return Response(serializer.data)

        application = Application.objects.select_for_update().get(pk=application.pk, workspace=self.get_workspace())
        require_live(application)
        serializer = DocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created = []
        for uploaded_file in serializer.validated_data["files"]:
            content_hash = sha256_of(uploaded_file)
            ext = (
                "." + uploaded_file.name.rsplit(".", 1)[-1].lower()
                if "." in uploaded_file.name else ""
            )
            document = Document.objects.create(
                workspace=application.workspace,
                application=application,
                file=uploaded_file,
                filename=uploaded_file.name,
                doc_type=classify_doc_type(uploaded_file.name),
                ext=ext,
                content_hash=content_hash,
                size=uploaded_file.size,
                original_upload_at=timezone.now(),
            )
            created.append(document)

        derive_application(actor=request.user, workspace=self.get_workspace(), application_id=application.pk)
        counts = scoped_duplicate_counts(
            application.workspace, [d.content_hash for d in created]
        )
        serializer = DocumentSerializer(created, many=True, context={"duplicate_counts": counts})
        return Response({"ok": True, "documents": serializer.data}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def dossier(self, request, pk=None, **kwargs):
        """Read cached evidence only; POST derive prepares missing extraction."""
        application = self.get_object()
        require_live(application)
        documents = application.documents.live().filter(workspace=self.get_workspace()).select_related("override")
        # Reject inconsistent historical cache provenance before projecting it.
        caches = DocumentExtraction.objects.filter(
            workspace=self.get_workspace(),
            content_hash__in=[document.content_hash for document in documents if document.content_hash],
            document__isnull=False,
        )
        if caches.exclude(document__workspace=self.get_workspace()).exists() or caches.exclude(
            document__application__workspace=self.get_workspace()
        ).exists():
            raise NotFound()
        result = assemble_dossier(documents)

        override = getattr(application, "override", None)
        result["date_applied_auto_filled"] = False
        result["effective_date_applied"] = effective_date(application)
        result["automatic_date_applied"] = application.automatic_date_applied
        result["date_candidate"] = application.date_candidate
        result["derivation_state"] = application.derivation_state

        current_status = (override.manual_status if override and override.manual_status
                           else application.status)
        status_change = (
            application.status_history.filter(status=current_status).order_by("-id").first()
        )
        result["current_status"] = current_status
        result["current_status_date"] = (
            status_change.changed_at.date().isoformat() if status_change else None
        )
        result["current_status_date_known"] = status_change is not None

        matches = (
            AccountMatch.objects.filter(application=application, account__workspace=self.get_workspace())
            .select_related("account")
            .order_by("-received_at")
        )
        result["account_matches"] = [
            {
                "id": m.id,
                "account_id": m.account_id,
                "message_id": m.message_id,
                "subject": m.subject,
                "received_at": m.received_at,
                "account_email": m.account.email,
                "account_provider": m.account.provider,
            }
            for m in matches
        ]
        return Response(result)

    @action(detail=True, methods=["post"])
    @workspace_mutation
    def derive(self, request, pk=None, **kwargs):
        # Explicit reconciliation prepares retained evidence without inventing
        # historical transitions at the time of a repair request.
        application = self.get_object()
        require_live(application)
        application = derive_application(actor=request.user, workspace=self.get_workspace(), application_id=application.pk, record_history=False)
        return Response(ApplicationSerializer(application).data)

    @action(detail=True, methods=["post"])
    @workspace_mutation
    def override(self, request, pk=None, **kwargs):
        """Uses the numeric Application.id in the URL -- no item_key
        round-trip to worry about, since Application.id has been the
        real identity since Phase 3 (see core/exceptions.py's
        docstring on what that made unnecessary to port).
        """
        application = self.get_object()
        require_live(application)
        serializer = OverrideWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        reset_status = values.pop("reset_status", False)
        fields_set = set(values.keys())
        fields = compute_override_fields(fields_set, values, reset_status)
        apply_overrides(actor=request.user, workspace=self.get_workspace(), application_id=application.pk, fields=fields)
        return Response({"ok": True, "id": application.id})

    @action(detail=False, methods=["post"], url_path="bulk-override")
    @workspace_mutation
    def bulk_override(self, request, **kwargs):
        """Validate all selected-Workspace targets before atomically applying overrides."""
        serializer = BulkOverrideWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        item_ids = data.pop("item_ids")
        reset_status = data.pop("reset_status", False)
        fields_set = set(data.keys())
        fields = compute_bulk_override_fields(fields_set, data, reset_status)
        with transaction.atomic():
            targets = list(Application.objects.filter(
                workspace=self.get_workspace(), id__in=item_ids).order_by("pk").select_for_update())
            if {app.pk for app in targets} != set(item_ids):
                raise NotFound()
            for application in targets:
                require_live(application)
            for application in targets:
                apply_overrides(actor=request.user, workspace=self.get_workspace(), application_id=application.pk, fields=fields)
        return Response({"ok": True, "count": len(targets)})


class LegacyApplicationDeletionViewSet(viewsets.GenericViewSet):
    """Retired: callers must use workspace-scoped revision-protected Trash."""
    def delete(self, request, **kwargs):
        return Response({"code": "endpoint_retired", "detail": "Use workspace-scoped Trash."}, status=410)

    def bulk_delete(self, request, **kwargs):
        return self.delete(request, **kwargs)
