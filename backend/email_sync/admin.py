from django.contrib import admin

from .models import AccountMatch, Discovery, EmailAccount, JobPostingSender, ThreadIdentifier


@admin.register(EmailAccount)
class EmailAccountAdmin(admin.ModelAdmin):
    list_display = ("email", "account_name", "provider", "status", "workspace", "last_synced_at")
    list_filter = ("provider", "status", "workspace")
    search_fields = ("email", "account_name")


@admin.register(AccountMatch)
class AccountMatchAdmin(admin.ModelAdmin):
    list_display = ("subject", "account", "application", "received_at")
    list_filter = ("account",)
    search_fields = ("subject", "message_id")


@admin.register(Discovery)
class DiscoveryAdmin(admin.ModelAdmin):
    list_display = ("subject", "sender", "status", "kind", "match_kind", "account")
    list_filter = ("status", "kind", "match_kind", "account")
    search_fields = ("subject", "sender", "guessed_company")


@admin.register(JobPostingSender)
class JobPostingSenderAdmin(admin.ModelAdmin):
    list_display = ("sender", "workspace", "added_at")
    list_filter = ("workspace",)
    search_fields = ("sender",)


@admin.register(ThreadIdentifier)
class ThreadIdentifierAdmin(admin.ModelAdmin):
    list_display = ("application", "message_id")
    search_fields = ("message_id",)
