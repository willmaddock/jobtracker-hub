"""documents serializers.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md) -- DRF shapes for the
"Categories & documents" section of the Phase 0 endpoint inventory.

Documents are identified by their real Document.id in every write
serializer here, not by the old app's `relpath` string -- same
numeric-id-over-string-key choice applications/views.py already made
for Application (see its OverrideWriteSerializer module note), and
one that happens to simplify rename for free: `doc_type_override` in
DocumentOverride is a straight FK to Document now, so renaming a file
no longer needs the old relpath-rekey step db.py's rename endpoint
used to do (see documents/views.py's rename() docstring).
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Document, DocumentOverride


class DocumentOverrideSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentOverride
        fields = ["doc_type_override", "updated_at"]
        read_only_fields = fields


class DocumentSerializer(serializers.ModelSerializer):
    override = DocumentOverrideSerializer(read_only=True)
    effective_doc_type = serializers.SerializerMethodField()
    duplicate_count = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id", "application", "file", "filename", "doc_type", "effective_doc_type",
            "ext", "content_hash", "size", "uploaded_at", "override", "duplicate_count",
        ]
        read_only_fields = fields

    def get_effective_doc_type(self, obj) -> str:
        override = getattr(obj, "override", None)
        if override is not None and override.doc_type_override:
            return override.doc_type_override
        return obj.doc_type

    def get_duplicate_count(self, obj) -> int:
        # Populated by the view via a `_duplicate_counts` dict passed
        # in context -- see views.py's _serialize_documents -- rather
        # than a per-row query here, so listing N documents costs one
        # extra query total instead of N.
        counts = self.context.get("duplicate_counts", {})
        return max(0, counts.get(obj.content_hash, 1) - 1) if obj.content_hash else 0


class DocumentUploadSerializer(serializers.Serializer):
    """POST /api/applications/{id}/documents body -- one or more
    files. doc_type is always auto-classified from the filename here
    (classify_doc_type, ported unchanged in documents/services.py);
    a wrong guess is fixed afterwards via the override endpoint, same
    division of labor the original app used.
    """

    files = serializers.ListField(
        child=serializers.FileField(), allow_empty=False, max_length=20
    )


class DocumentRenameSerializer(serializers.Serializer):
    new_filename = serializers.CharField()

    def validate_new_filename(self, value: str) -> str:
        value = value.strip()
        if not value or "/" in value or "\\" in value:
            raise serializers.ValidationError("Invalid filename.")
        return value


class DocumentOverrideWriteSerializer(serializers.Serializer):
    # None/blank clears the correction, same as the original's
    # DocumentOverrideRequest.doc_type_override.
    doc_type_override = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class CategorySerializer(serializers.Serializer):
    """Not model-backed -- a category is a live grouping of
    Applications by `section`, computed in the view (see views.py's
    module docstring on why there's no more physical-folder layer to
    read this from). This just shapes that computed dict for output.
    """

    section = serializers.CharField()
    item_count = serializers.IntegerField()
    doc_count = serializers.IntegerField()
    archived = serializers.BooleanField()


class CategoryOverrideWriteSerializer(serializers.Serializer):
    archived = serializers.BooleanField()
