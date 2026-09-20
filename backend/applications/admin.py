from django.contrib import admin
from core.lifecycle_admin import LifecycleAdminMixin

from .models import Application, CompanyAlias, Override, StatusHistory


class OverrideInline(admin.StackedInline):
    model = Override
    can_delete = False
    readonly_fields = ("date_applied_mode",)


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
    readonly_fields = ("portable_id", "workspace", "source_relpath", "category_revision", "trashed_at", "lifecycle_revision",
        "status", "last_activity", "first_activity", "first_activity_date", "last_activity_date",
        "activity_provenance", "automatic_date_applied", "date_candidate", "derivation_version",
        "derivation_fingerprint", "derived_at", "derivation_state")

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        from applications.derivation import effective_status
        # Gate before reading; lifecycle mixin rechecks retained state as well.
        from applications.creation import lock_workspace
        lock_workspace(obj.workspace.owner, obj.workspace)
        current = Application.objects.select_for_update().get(pk=obj.pk)
        obj._previous_effective_status = effective_status(current)
        obj._derivation_needed = bool(form and "section" in form.changed_data)
        # Read-only form fields can still be stale on the model instance.
        for field in self.readonly_fields:
            setattr(obj, field, getattr(current, field))
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        if formset.model is Override:
            for child in formset.forms:
                if {"manual_status", "date_applied"} & set(child.changed_data):
                    form.instance._derivation_needed = True
                if child.has_changed() and "date_applied" in child.changed_data:
                    child.instance.date_applied_mode = "manual" if child.instance.date_applied else "suppressed"
        super().save_formset(request, form, formset, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if not form.instance._derivation_needed:
            return
        from applications.derivation import _derive_locked
        application = Application.objects.get(pk=form.instance.pk)
        _derive_locked(application, previous=form.instance._previous_effective_status, source="manual")



@admin.register(CompanyAlias)
class CompanyAliasAdmin(admin.ModelAdmin):
    list_display = ("alias", "canonical", "workspace")
    list_filter = ("workspace",)
    search_fields = ("alias", "canonical")
