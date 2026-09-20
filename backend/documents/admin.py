from django.contrib import admin
from core.lifecycle_admin import LifecycleAdminMixin

from .models import Category, CategoryMembership, Document, DocumentExtraction, DocumentOverride, FolderOverride


@admin.register(Document)
class DocumentAdmin(LifecycleAdminMixin, admin.ModelAdmin):
    list_display = ("filename", "doc_type", "application", "workspace", "size", "uploaded_at")
    list_filter = ("workspace", "doc_type")
    search_fields = ("filename", "content_hash")
    readonly_fields = ("workspace", "application", "file", "trashed_at", "lifecycle_revision",
        "size", "content_hash", "ext", "evidence_event_at", "evidence_event_date",
        "evidence_event_provenance", "verified_legacy_mtime", "original_upload_at")

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if form and not {"filename", "doc_type"} & set(form.changed_data):
            return
        from applications.derivation import derive_application
        derive_application(actor=obj.workspace.owner, workspace=obj.workspace, application_id=obj.application_id)


@admin.register(DocumentOverride)
class DocumentOverrideAdmin(admin.ModelAdmin):
    list_display = ("document", "doc_type_override", "updated_at")
    search_fields = ("document__filename",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DocumentExtraction)
class DocumentExtractionAdmin(admin.ModelAdmin):
    list_display = ("content_hash", "extractor_version", "workspace", "document", "extracted_at")
    list_filter = ("workspace", "extractor_version")
    search_fields = ("content_hash",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# Category mutations require the revision/request authority.
class PreservedReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(FolderOverride, PreservedReadOnlyAdmin)
admin.site.register(Category, PreservedReadOnlyAdmin)
admin.site.register(CategoryMembership, PreservedReadOnlyAdmin)
