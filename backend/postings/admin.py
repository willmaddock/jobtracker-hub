from django.contrib import admin

from .models import (JobPosting, RetainedPostingExtraction, RetainedPostingExtractionOutput,
                     RetainedPostingItem, RetainedPostingItemAssociation, RetainedPostingItemCorrection,
                     PostingSource, PostingSourceCorrection)


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = (
        "title", "company", "source", "status", "saved", "account", "workspace",
        "received_at", "portable_id",
    )
    list_filter = ("status", "saved", "source", "account", "workspace")
    search_fields = ("title", "company", "location", "email_subject", "message_id")
    date_hierarchy = "received_at"
    readonly_fields = ("dedupe_key", "created_at", "portable_id")

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return fields + ("workspace", "account") if obj is not None else fields


@admin.register(RetainedPostingExtraction, RetainedPostingExtractionOutput,
                RetainedPostingItem, RetainedPostingItemAssociation, RetainedPostingItemCorrection,
                PostingSource, PostingSourceCorrection)
class PostingExtractionAdmin(admin.ModelAdmin):
    """Privileged read-only inspection. Default field rendering escapes JSON."""
    actions = None

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
