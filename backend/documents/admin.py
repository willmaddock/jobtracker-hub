from django.contrib import admin

from .models import Category, CategoryMembership, Document, DocumentExtraction, DocumentOverride, FolderOverride


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("filename", "doc_type", "application", "workspace", "size", "uploaded_at")
    list_filter = ("workspace", "doc_type")
    search_fields = ("filename", "content_hash")


@admin.register(DocumentOverride)
class DocumentOverrideAdmin(admin.ModelAdmin):
    list_display = ("document", "doc_type_override", "updated_at")
    search_fields = ("document__filename",)


@admin.register(DocumentExtraction)
class DocumentExtractionAdmin(admin.ModelAdmin):
    list_display = ("content_hash", "extractor_version", "workspace", "document", "extracted_at")
    list_filter = ("workspace", "extractor_version")
    search_fields = ("content_hash",)


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
