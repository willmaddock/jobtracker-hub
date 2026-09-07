from django.contrib import admin

from .models import JobPosting


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = (
        "title", "company", "source", "status", "saved", "account", "workspace",
        "applied_application", "received_at",
    )
    list_filter = ("status", "saved", "source", "account", "workspace")
    search_fields = ("title", "company", "location", "email_subject", "message_id")
    date_hierarchy = "received_at"
    readonly_fields = ("dedupe_key", "created_at")
    autocomplete_fields = ("applied_application",)
