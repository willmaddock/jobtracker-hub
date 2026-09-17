"""Posting representations use durable conversion facts; creation is protected separately."""
from __future__ import annotations

from rest_framework import serializers
from django.db.models import Q

from .models import JobPosting


class JobPostingSerializer(serializers.ModelSerializer):
    applied_application = serializers.SerializerMethodField()
    conversions = serializers.SerializerMethodField()

    def get_applied_application(self, obj):
        # Temporary read projection; remove when posting UI consumes conversions.
        return obj.conversions.filter(workspace=obj.workspace, application__workspace=obj.workspace).order_by("-pk").values_list("application_id", flat=True).first()

    def get_conversions(self, obj):
        return [{"id": c.pk, "application_id": c.application_id,
                 "portable_id": str(c.application_portable_id),
                 "state": "live" if c.application_id else "removed",
                 "converted_at": c.converted_at}
                for c in obj.conversions.filter(workspace=obj.workspace).filter(
                    Q(application__isnull=True) | Q(application__workspace=obj.workspace))]

    class Meta:
        model = JobPosting
        fields = [
            "id", "source", "title", "company", "location", "salary",
            "employment_type", "posting_url", "received_at", "email_subject",
            "sender", "status", "saved", "applied_application", "conversions", "created_at",
        ]
        read_only_fields = fields


class SaveJobPostingSerializer(serializers.Serializer):
    """POST /api/job-postings/{id}/save body -- toggles the starred
    flag. `saved` defaults to True, matching the original's
    `saved: bool = Body(True, embed=True)`.
    """
    saved = serializers.BooleanField(default=True)


class ApplyJobPostingSerializer(serializers.Serializer):
    """POST /api/job-postings/{id}/apply body. company/role_label
    default to the posting's own company/title when left blank --
    mirrors the original comment that the frontend pre-fills these
    from the posting but leaves them freely editable first.
    """
    company = serializers.CharField(max_length=255, allow_blank=True, required=False, default="")
    role_label = serializers.CharField(max_length=255, allow_blank=True, required=False, default="")
    status = serializers.CharField(max_length=16, allow_blank=True, required=False, default="applied")
    category_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
