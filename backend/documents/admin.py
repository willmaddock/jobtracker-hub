from django.contrib import admin

from .models import DocumentExtraction, DocumentOverride, FolderOverride


@admin.register(DocumentOverride)
class DocumentOverrideAdmin(admin.ModelAdmin):
    list_display = ("relpath", "doc_type_override", "workspace", "updated_at")
    list_filter = ("workspace",)
    search_fields = ("relpath",)


@admin.register(DocumentExtraction)
class DocumentExtractionAdmin(admin.ModelAdmin):
    list_display = ("content_hash", "extractor_version", "workspace", "extracted_at")
    list_filter = ("workspace", "extractor_version")
    search_fields = ("content_hash",)


@admin.register(FolderOverride)
class FolderOverrideAdmin(admin.ModelAdmin):
    list_display = ("folder", "section", "archived", "workspace")
    list_filter = ("archived", "section", "workspace")
    search_fields = ("folder",)
