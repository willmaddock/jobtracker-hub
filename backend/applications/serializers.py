"""applications serializers.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md) -- DRF shapes for the
"applications" section of the Phase 0 endpoint inventory, minus the
two document-heavy routes (GET .../documents, GET .../dossier) and the
upload route (POST .../documents) -- those move together into the
Documents slice, since they need Document/DocumentOverride wiring
this module has no reason to duplicate.

The actual field-diffing rules for override/bulk-override live in
applications/services.py (ported unchanged in Phase 5, written
specifically to take a plain fields_set/values pair from whatever
framework sits on top of it) -- these serializers exist only to turn
request bodies into that fields_set/values shape, not to reimplement
any of the override logic themselves.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Application, Override


class OverrideSerializer(serializers.ModelSerializer):
    class Meta:
        model = Override
        fields = [
            "manual_status", "notes", "date_applied", "date_applied_source",
            "next_action", "next_action_date", "archived", "snoozed_until",
            "activity_override",
        ]
        read_only_fields = fields


class ApplicationSerializer(serializers.ModelSerializer):
    override = OverrideSerializer(read_only=True)
    effective_status = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = [
            "id", "workspace", "section", "company", "role_label", "source_relpath",
            "status", "effective_status", "last_activity", "first_activity",
            "created_at", "override",
        ]
        read_only_fields = fields

    def get_effective_status(self, obj) -> str:
        override = getattr(obj, "override", None)
        if override is not None and override.manual_status:
            return override.manual_status
        return obj.status


class ApplicationCreateSerializer(serializers.ModelSerializer):
    """POST /api/applications body. `status`, if given, is written as
    an Override.manual_status once the Application exists -- it's not
    a real Application field, same as the original's Form(...)
    `status` parameter (see _app/api.py's create_application).

    `section` defaults to "applications" (a real job application) but
    accepts any of Application.SECTION_CHOICES -- this is also how a
    category now comes into being (see documents/views.py's module
    docstring): there's no separate "create category" call anymore,
    just an item created with a non-default section.
    """

    status = serializers.CharField(required=False, allow_blank=True, default="")

    class Meta:
        model = Application
        fields = ["company", "role_label", "status", "section"]
        extra_kwargs = {
            "role_label": {"required": False, "allow_blank": True, "default": ""},
            "section": {"required": False, "default": "applications"},
        }

class OverrideWriteSerializer(serializers.Serializer):
    """POST /api/applications/{id}/override body. Every field left
    deliberately without a `default=` (reset_status is the one
    exception) so a field the caller didn't send is simply absent from
    validated_data -- that absence is exactly the `fields_set`
    semantics compute_override_fields() (applications/services.py)
    needs to tell "not sent" apart from "sent as null/blank".
    """

    manual_status = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    reset_status = serializers.BooleanField(required=False, default=False)
    notes = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    date_applied = serializers.DateField(required=False, allow_null=True)
    date_applied_source = serializers.ChoiceField(
        choices=Override.DATE_APPLIED_SOURCE_CHOICES, required=False, allow_null=True,
    )
    next_action = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    next_action_date = serializers.DateField(required=False, allow_null=True)
    archived = serializers.BooleanField(required=False, allow_null=True)
    snoozed_until = serializers.DateField(required=False, allow_null=True)
    activity_override = serializers.DateField(required=False, allow_null=True)


class BulkOverrideWriteSerializer(serializers.Serializer):
    """POST /api/applications/bulk-override body -- deliberately a
    smaller field set than OverrideWriteSerializer above, mirroring
    compute_bulk_override_fields()'s own smaller set (no notes,
    date_applied, or date_applied_source for a bulk action).
    """

    item_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False, max_length=1000)
    manual_status = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    reset_status = serializers.BooleanField(required=False, default=False)
    archived = serializers.BooleanField(required=False, allow_null=True)
    snoozed_until = serializers.DateField(required=False, allow_null=True)
    next_action = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    next_action_date = serializers.DateField(required=False, allow_null=True)
    activity_override = serializers.DateField(required=False, allow_null=True)


class BulkDeleteSerializer(serializers.Serializer):
    item_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
