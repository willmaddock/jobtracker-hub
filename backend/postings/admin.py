from django.contrib import admin

from .models import JobPosting


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = (
        "title", "company", "source", "status", "saved", "account", "workspace",
        "received_at",
    )
    list_filter = ("status", "saved", "source", "account", "workspace")
    search_fields = ("title", "company", "location", "email_subject", "message_id")
    date_hierarchy = "received_at"
    readonly_fields = ("dedupe_key", "created_at")

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return fields + ("workspace", "account") if obj is not None else fields
