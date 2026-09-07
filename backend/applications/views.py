"""applications views.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md) -- DRF viewset for the
"applications" section of the Phase 0 endpoint inventory. Every
action is scoped to workspace__owner=request.user, same pattern as
postings/views.py's JobPostingViewSet.

create() still doesn't create a folder or accept file uploads inline
(see postings/views.py's apply() for the same deliberate
simplification) -- uploading now happens as a separate step through
the `documents` action below, same two-step flow the original's
"create, then drag files onto the new application" UI already used
even though its /api/applications/new endpoint *could* take files
inline. A 409 on create still means the same thing it used to: this
exact company/role_label combination already exists in this
workspace (applications/models.py's unique_application_identity_per_workspace
constraint), just via an IntegrityError catch instead of a
FileExistsError one.

The `documents` action (list + upload) lands in this slice too -- see
its own docstring below.

`dossier` (this slice) ports _app/api.py's application_dossier
endpoint on top of applications/dossier.assemble_dossier() and
documents/extraction.py -- see those modules' docstrings for the
content-extraction pipeline itself. What's ported here is the
endpoint-level policy assemble_dossier() deliberately leaves to its
caller: auto-filling an empty date_applied from strong
("confirmation") evidence, and computing the Timeline's "Current
status" line from StatusHistory. Same as the original, this endpoint
writes at most one thing -- the date_applied auto-fill -- and never
touches a date_applied that already has a value, regardless of
evidence tier.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .dossier import assemble_dossier
from .models import Application, Override, StatusHistory
from .serializers import (
    ApplicationCreateSerializer,
    ApplicationSerializer,
    BulkDeleteSerializer,
    BulkOverrideWriteSerializer,
    OverrideWriteSerializer,
)
from .services import (
    compute_bulk_override_fields,
    compute_override_fields,
    resolve_effective_status,
)

# email_sync imports the other direction already (AccountMatch ->
# Application FK) -- see email_sync/models.py's module docstring, so
# this is a one-way dependency here too, not a cycle.
from email_sync.models import AccountMatch

# The `documents` action below (list + upload, deferred from the
# slice2 recommendation) needs these -- documents/views.py imports
# Application the same direction, so this is a one-way dependency,
# not a cycle.
from documents.models import Document
from documents.serializers import DocumentSerializer, DocumentUploadSerializer
from documents.services import classify_doc_type, duplicate_counts, sha256_of

_VALID_STATUSES = [choice[0] for choice in Application.STATUS_CHOICES]


class ApplicationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    def get_queryset(self):
        return (
            Application.objects.filter(workspace__owner=self.request.user)
            .select_related("override")
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return ApplicationCreateSerializer
        return ApplicationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        status_value = data.pop("status", "").strip()
        if status_value and status_value not in _VALID_STATUSES:
            raise ValidationError(
                {"status": f"Unknown status '{status_value}'. Must be one of {_VALID_STATUSES}."}
            )
        try:
            with transaction.atomic():
                application = Application.objects.create(
                    workspace=data["workspace"],
                    section=data.get("section", "applications"),
                    company=data["company"],
                    role_label=data.get("role_label", ""),
                    # No folder/Document to derive a real relpath from
                    # yet -- see this module's docstring.
                    source_relpath="",
                )
                if status_value:
                    Override.objects.create(application=application, manual_status=status_value)
                    StatusHistory.objects.create(
                        application=application, status=status_value,
                        changed_at=timezone.now(), source="manual_create",
                    )
        except IntegrityError:
            raise ValidationError(
                {"company": "An application with this company and role already exists."},
                code="conflict",
            )
        application = self.get_queryset().get(id=application.id)
        return Response(ApplicationSerializer(application).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"])
    def documents(self, request, pk=None):
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
            documents = application.documents.select_related("override").order_by(
                "doc_type", "filename"
            )
            counts = duplicate_counts(
                application.workspace, [d.content_hash for d in documents]
            )
            serializer = DocumentSerializer(
                documents, many=True, context={"duplicate_counts": counts}
            )
            return Response(serializer.data)

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
            )
            created.append(document)

        counts = duplicate_counts(
            application.workspace, [d.content_hash for d in created]
        )
        serializer = DocumentSerializer(created, many=True, context={"duplicate_counts": counts})
        return Response({"ok": True, "documents": serializer.data}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def dossier(self, request, pk=None):
        """GET /api/applications/{id}/dossier -- see this module's
        docstring and applications/dossier.assemble_dossier() for the
        extraction/tiebreak rules.

        date_applied auto-fill, split by evidence tier
        (assemble_dossier's detected_date_evidence_tier):
          - date_applied already has a value (typed, or auto-filled
            earlier): NEVER touched here, regardless of tier. A value
            already on record only ever changes via an explicit
            accept through the override action.
          - date_applied is unset AND the evidence is "confirmation"
            (a direct record of submission, from an
            application_confirmation document): auto-filled here,
            once, silently -- see date_applied_auto_filled in the
            response, which the frontend uses to know it needs to
            refresh the applications list.
          - date_applied is unset AND the evidence is only "posting"
            (weaker -- names when the position was *listed*, not
            applied to): left unset and still surfaced as a
            suggestion for the user to accept or dismiss.

        `timeline_events` passes straight through from
        assemble_dossier() -- doc-derived, nothing to compute here.
        `current_status` / `current_status_date` /
        `current_status_date_known` cover the Timeline's last line:
        `current_status` is the same manual-status-or-auto-status
        value ApplicationSerializer.get_effective_status computes; the
        date comes from the most recent StatusHistory row recording a
        transition TO that status, so current_status_date_known is
        False (and current_status_date is None) for any status that
        predates the first StatusHistory row for it, rather than
        guessing. `account_matches` is connected-account matches for
        this application's timeline -- empty for everyone until an
        account is actually connected and synced (Phase 9); cheap
        no-op reads either way, not worth gating behind a feature
        flag.
        """
        application = self.get_object()
        documents = application.documents.select_related("override")
        result = assemble_dossier(documents)

        override = getattr(application, "override", None)
        result["date_applied_auto_filled"] = False
        if (
            (override is None or not override.date_applied)
            and result.get("detected_date_evidence_tier") == "confirmation"
            and result.get("detected_date_applied")
        ):
            Override.objects.update_or_create(
                application=application,
                defaults={
                    "date_applied": result["detected_date_applied"],
                    "date_applied_source": "confirmation",
                },
            )
            result["date_applied_auto_filled"] = True

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
            AccountMatch.objects.filter(application=application)
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
    def override(self, request, pk=None):
        """Uses the numeric Application.id in the URL -- no item_key
        round-trip to worry about, since Application.id has been the
        real identity since Phase 3 (see core/exceptions.py's
        docstring on what that made unnecessary to port).
        """
        application = self.get_object()
        serializer = OverrideWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        reset_status = values.pop("reset_status", False)
        fields_set = set(values.keys())
        fields = compute_override_fields(fields_set, values, reset_status)
        if fields:
            Override.objects.update_or_create(application=application, defaults=fields)
        if "manual_status" in fields:
            effective_status = resolve_effective_status(fields, application.status)
            StatusHistory.objects.create(
                application=application, status=effective_status,
                changed_at=timezone.now(), source="manual",
            )
        return Response({"ok": True, "id": application.id})

    @action(detail=False, methods=["post"], url_path="bulk-override")
    def bulk_override(self, request):
        """Apply the same override fields to many applications at
        once -- powers Needs Attention's multi-select bulk actions.
        Ids the caller doesn't own are silently skipped (excluded by
        get_queryset()'s ownership filter) rather than erroring the
        whole batch, matching the original's "id not found -> skip"
        behavior for a nonexistent id.
        """
        serializer = BulkOverrideWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        item_ids = data.pop("item_ids")
        reset_status = data.pop("reset_status", False)
        fields_set = set(data.keys())
        fields = compute_bulk_override_fields(fields_set, data, reset_status)
        updated = 0
        for application in self.get_queryset().filter(id__in=item_ids):
            if fields:
                Override.objects.update_or_create(application=application, defaults=fields)
            if "manual_status" in fields:
                effective_status = resolve_effective_status(fields, application.status)
                StatusHistory.objects.create(
                    application=application, status=effective_status,
                    changed_at=timezone.now(), source="manual",
                )
            updated += 1
        return Response({"ok": True, "count": updated})

    @action(detail=True, methods=["post"])
    def delete(self, request, pk=None):
        """Permanently removes one application. Works whether it's
        archived or not -- same as the original, single delete has no
        archived precondition (only bulk-delete below re-verifies
        that). FK cascades (Override, StatusHistory) and SET_NULL
        (JobPosting.applied_application) handle the cleanup that used
        to be several manual DELETE statements plus a document-override
        ghost cleanup loop -- there's no document_overrides table or
        disk folder left to leave a ghost row in anymore.
        """
        application = self.get_object()
        application_id = application.id
        application.delete()
        return Response({"ok": True, "id": application_id})

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        """Re-verifies server-side that every id is actually archived
        before touching it, same as the original -- the frontend only
        offers this from the Archived list, but that's a UI-level
        guarantee, not a security one, for a destructive bulk action.
        Never aborts the whole batch on one bad id.
        """
        serializer = BulkDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item_ids = serializer.validated_data["item_ids"]
        queryset = self.get_queryset().filter(id__in=item_ids)
        by_id = {application.id: application for application in queryset}
        deleted: list[int] = []
        failed: list[dict] = []
        for app_id in item_ids:
            application = by_id.get(app_id)
            if application is None:
                failed.append({"id": app_id, "error": "Application not found."})
                continue
            override = getattr(application, "override", None)
            if not (override and override.archived):
                failed.append({"id": app_id, "error": "Not archived — archive it before deleting."})
                continue
            application.delete()
            deleted.append(app_id)
        return Response({"ok": len(failed) == 0, "deleted": deleted, "failed": failed})
