"""
postings serializers.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md) -- DRF shapes for the "Job
postings" section of the Phase 0 endpoint inventory (GET
/api/job-postings, dismiss/restore/save/apply). The actual apply
eligibility/status-validation rules live in postings/services.py
(ported in Phase 5) and are unchanged here; this module is only the
request/response shape around them.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import JobPosting


class JobPostingSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPosting
        fields = [
            "id", "source", "title", "company", "location", "salary",
            "employment_type", "posting_url", "received_at", "email_subject",
            "sender", "status", "saved", "applied_application", "created_at",
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
