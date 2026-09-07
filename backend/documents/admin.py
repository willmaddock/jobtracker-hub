from django.contrib import admin

from .models import Document, DocumentExtraction, DocumentOverride, FolderOverride


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


@admin.register(FolderOverride)
class FolderOverrideAdmin(admin.ModelAdmin):
    list_display = ("folder", "section", "archived", "workspace")
    list_filter = ("archived", "section", "workspace")
    search_fields = ("folder",)
