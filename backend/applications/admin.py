from django.contrib import admin

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
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("company", "role_label", "section", "status", "workspace")
    list_filter = ("section", "status", "workspace")
    search_fields = ("company", "role_label", "source_relpath")
    inlines = [OverrideInline, StatusHistoryInline]


@admin.register(CompanyAlias)
class CompanyAliasAdmin(admin.ModelAdmin):
    list_display = ("alias", "canonical", "workspace")
    list_filter = ("workspace",)
    search_fields = ("alias", "canonical")
