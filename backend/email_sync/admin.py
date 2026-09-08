from django.contrib import admin

from .models import (
    AccountMatch,
    Discovery,
    EmailAccount,
    GmailCredential,
    IMAPCredential,
    JobPostingSender,
    OutlookCredential,
    ThreadIdentifier,
)


@admin.register(EmailAccount)
class EmailAccountAdmin(admin.ModelAdmin):
    list_display = ("email", "account_name", "provider", "status", "workspace", "last_synced_at")
    list_filter = ("provider", "status", "workspace")
    search_fields = ("email", "account_name")


@admin.register(GmailCredential)
class GmailCredentialAdmin(admin.ModelAdmin):
    # access_token/refresh_token are deliberately excluded from
    # list_display and never shown even on the detail page in
    # anything but redacted form -- an admin who needs to debug a
    # connection should be able to see *that* a credential exists and
    # when it expires, never the encrypted token material itself.
    list_display = ("account", "token_expiry", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    exclude = ("access_token", "refresh_token")
    search_fields = ("account__email",)


@admin.register(OutlookCredential)
class OutlookCredentialAdmin(admin.ModelAdmin):
    # Same redaction rationale as GmailCredentialAdmin: never show
    # token material, even encrypted, on the admin detail page.
    list_display = ("account", "token_expiry", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    exclude = ("access_token", "refresh_token")
    search_fields = ("account__email",)


@admin.register(IMAPCredential)
class IMAPCredentialAdmin(admin.ModelAdmin):
    # Same redaction rationale as GmailCredentialAdmin/
    # OutlookCredentialAdmin: never show secret material, even
    # encrypted, on the admin detail page. host/port/username aren't
    # secrets (they're server connection details, not the credential
    # itself) so they're safe to surface, unlike password.
    list_display = ("account", "host", "port", "username", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    exclude = ("password",)
    search_fields = ("account__email", "host", "username")


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
