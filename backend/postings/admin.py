from django.contrib import admin

from .models import JobPosting


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = (
        "title", "company", "source", "status", "saved", "workspace", "received_at",
    )
    list_filter = ("status", "saved", "source", "workspace")
    search_fields = ("title", "company", "location", "email_subject")
