from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User, Workspace

admin.site.register(User, UserAdmin)


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    list_filter = ("owner",)
    search_fields = ("name", "owner__username", "owner__email")


from .models import MfaDevice  # noqa: E402


@admin.register(MfaDevice)
class MfaDeviceAdmin(admin.ModelAdmin):
    """Operator view for resetting MFA. Secrets and codes are never displayed or editable.

    Deleting a row is the reset: the user must enrol again at next sign-in.
    """
    list_display = ("user", "confirmed_at", "failed_attempts", "locked_at", "created_at")
    list_filter = ("locked_at",)
    search_fields = ("user__username", "user__email")
    exclude = ("secret_encrypted", "last_used_step")
    readonly_fields = ("user", "confirmed_at", "failed_attempts", "locked_at", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
