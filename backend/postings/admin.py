from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError
from django.db import router, transaction
from django.contrib.admin.utils import unquote
from django.contrib.admin.exceptions import DisallowedModelAdminToField

from .models import (JobPosting, RetainedPostingExtraction, RetainedPostingExtractionOutput,
                     RetainedPostingItem, RetainedPostingItemAssociation, RetainedPostingItemCorrection,
                     PostingSource, PostingSourceCorrection, RetainedPostingInterpretationDecision,
                JobPostingInterpretationDecision, JobPostingDescriptorProjection)

from .models import DESCRIPTOR_FIELDS, _lock_descriptor_workspace


class JobPostingAdminForm(forms.ModelForm):
    class Meta:
        model = JobPosting
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        using = self.instance._state.db or router.db_for_write(JobPosting)
        if (self.instance.pk and JobPostingDescriptorProjection.objects.using(using).filter(
                posting_id=self.instance.pk).exists()
                and any(self.add_prefix(name) in self.data for name in DESCRIPTOR_FIELDS)):
            raise ValidationError("Descriptors became projection-owned. Reload this posting before saving.",
                                  code="descriptor_projection_owned")
        return cleaned


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    form = JobPostingAdminForm
    list_display = (
        "title", "company", "source", "status", "saved", "account", "workspace",
        "received_at", "portable_id",
    )
    list_filter = ("status", "saved", "source", "account", "workspace")
    search_fields = ("title", "company", "location", "email_subject", "message_id")
    date_hierarchy = "received_at"
    readonly_fields = ("dedupe_key", "created_at", "portable_id")

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj is not None:
            fields += ("workspace", "account")
            if obj.descriptor_projections.exists():
                fields += DESCRIPTOR_FIELDS
        return fields

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST" or object_id is None:
            return super().changeform_view(request, object_id, form_url, extra_context)
        using = router.db_for_write(JobPosting)
        to_field = request.POST.get("_to_field", request.GET.get("_to_field"))
        if to_field and not self.to_field_allowed(request, to_field):
            raise DisallowedModelAdminToField("The requested field cannot be referenced.")
        with transaction.atomic(using=using):
            obj = self.get_object(request, unquote(object_id), to_field)
            if obj is not None and self.has_change_permission(request, obj):
                _lock_descriptor_workspace(obj.workspace_id, using)
                JobPosting.objects.using(using).select_for_update(of=("self",)).get(pk=obj.pk)
            return super().changeform_view(request, object_id, form_url, extra_context)


@admin.register(RetainedPostingExtraction, RetainedPostingExtractionOutput,
                RetainedPostingItem, RetainedPostingItemAssociation, RetainedPostingItemCorrection,
                PostingSource, PostingSourceCorrection, RetainedPostingInterpretationDecision,
                JobPostingInterpretationDecision, JobPostingDescriptorProjection)
class PostingExtractionAdmin(admin.ModelAdmin):
    """Privileged read-only inspection. Default field rendering escapes JSON."""
    actions = None

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
