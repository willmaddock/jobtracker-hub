from django.contrib import admin
from core.lifecycle_admin import LifecycleAdminMixin

from .models import Application, CompanyAlias, Override, StatusHistory


class OverrideInline(admin.StackedInline):
    model = Override
    can_delete = False


class StatusHistoryInline(admin.TabularInline):
    model = StatusHistory
    extra = 0
    readonly_fields = ("status", "changed_at", "source")
    can_delete = False


@admin.register(Application)
class ApplicationAdmin(LifecycleAdminMixin, admin.ModelAdmin):
    list_display = ("company", "role_label", "section", "status", "workspace")
    list_filter = ("section", "status", "workspace")
    search_fields = ("company", "role_label", "source_relpath")
    inlines = [OverrideInline, StatusHistoryInline]
    readonly_fields = ("portable_id", "workspace", "source_relpath", "category_revision", "trashed_at", "lifecycle_revision")

    def has_add_permission(self, request):
        return False



@admin.register(CompanyAlias)
class CompanyAliasAdmin(admin.ModelAdmin):
    list_display = ("alias", "canonical", "workspace")
    list_filter = ("workspace",)
    search_fields = ("alias", "canonical")
