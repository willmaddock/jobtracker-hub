from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User, Workspace

admin.site.register(User, UserAdmin)


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    list_filter = ("owner",)
    search_fields = ("name", "owner__username", "owner__email")
