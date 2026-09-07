from django.contrib import admin

from .models import HubSettings


@admin.register(HubSettings)
class HubSettingsAdmin(admin.ModelAdmin):
    list_display = ("workspace", "role", "location", "updated_at")
    list_filter = ("workspace",)
    search_fields = ("role", "location")
