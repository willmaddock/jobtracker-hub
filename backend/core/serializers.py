"""
core serializers.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md) -- DRF shapes for the
"Cross-cutting views" section of the Phase 0 endpoint inventory
(attention, insights, search, browse, manage/merge/unmerge,
hub/settings). Most of these read plain dicts built by
core/services.py rather than model instances -- see that module's
docstring -- so the serializers here are almost all plain
Serializer subclasses, not ModelSerializer.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import HubSettings


class ApplicationRowSerializer(serializers.Serializer):
    """Shapes one enriched application dict from
    core/services.py's load_applications()/annotate_application() --
    used by both Attention (a filtered/sorted list of these) and
    Browse (nested under each section).
    """

    id = serializers.IntegerField()
    workspace_id = serializers.IntegerField()
    section = serializers.CharField()
    company = serializers.CharField()
    effective_company = serializers.CharField(required=False)
    role_label = serializers.CharField()
    status = serializers.CharField()
    manual_status = serializers.CharField(allow_null=True)
    effective_status = serializers.CharField()
    notes = serializers.CharField(allow_null=True)
    date_applied = serializers.DateField(allow_null=True)
    date_applied_source = serializers.CharField(allow_null=True)
    next_action = serializers.CharField(allow_null=True)
    next_action_date = serializers.DateField(allow_null=True)
    archived = serializers.BooleanField()
    snoozed_until = serializers.DateField(allow_null=True)
    activity_override = serializers.DateField(allow_null=True)
    last_activity = serializers.DateTimeField(allow_null=True)
    days_since_activity = serializers.IntegerField(allow_null=True)
    date_is_manual = serializers.BooleanField()
    activity_is_reset = serializers.BooleanField()
    is_stale = serializers.BooleanField()
    next_action_due = serializers.BooleanField()
    is_snoozed = serializers.BooleanField()


class InsightsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    by_status = serializers.DictField(child=serializers.IntegerField())
    response_rate = serializers.FloatField()
    interview_rate = serializers.FloatField()
    avg_response_days = serializers.IntegerField(allow_null=True)
    lag_sample_size = serializers.IntegerField()


class SearchResultSerializer(serializers.Serializer):
    """One Document hit, with just enough of its owning Application
    to render a result row -- deliberately smaller than
    documents/serializers.py's DocumentSerializer since search never
    needs the full override/duplicate_count payload, only enough to
    link back to the item and show why it matched.
    """

    id = serializers.IntegerField()
    filename = serializers.CharField()
    doc_type = serializers.CharField()
    application_id = serializers.IntegerField()
    company = serializers.CharField()
    role_label = serializers.CharField()
    section = serializers.CharField()


class ManageSerializer(serializers.Serializer):
    duplicate_suggestions = serializers.DictField(child=serializers.ListField(child=serializers.CharField()))
    aliases = serializers.DictField(child=serializers.CharField())
    archived = ApplicationRowSerializer(many=True)
    duplicate_documents = serializers.ListField(child=serializers.DictField())


class MergeSerializer(serializers.Serializer):
    """POST /api/manage/merge body -- `names` (every raw company name
    involved, canonical included) all get aliased to `canonical`,
    same as _app/api.py's merge(): the canonical name itself is
    skipped so it never aliases to itself. `workspace` is validated
    for ownership by the view (core/views.py's _get_owned_workspace),
    the same way CategoryOverrideView/CategoryDeleteView validate it
    outside their own write serializers -- so this only checks shape
    (a plain id), not ownership.
    """

    names = serializers.ListField(child=serializers.CharField(), allow_empty=False)
    canonical = serializers.CharField()
    workspace = serializers.IntegerField()


class UnmergeSerializer(serializers.Serializer):
    alias = serializers.CharField()
    workspace = serializers.IntegerField()


class HubSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = HubSettings
        fields = ["role", "location", "custom_links", "custom_cards", "updated_at"]
        read_only_fields = ["updated_at"]


class HubSettingsWriteSerializer(serializers.Serializer):
    """Partial update: any of these present in the body is merged in
    (see HubSettingsView.post), everything else left as-is -- same
    partial-update shape the original's set_hub_settings(**fields)
    used, just spelled out as a serializer with every field optional
    instead of a **kwargs dict.
    """

    role = serializers.CharField(required=False, allow_blank=True)
    location = serializers.CharField(required=False, allow_blank=True)
    custom_links = serializers.DictField(required=False)
    custom_cards = serializers.DictField(required=False)
