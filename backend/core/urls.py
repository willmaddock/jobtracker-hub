from django.urls import path

from .views import (
    AttentionView,
    BrowseView,
    HealthView,
    HubSettingsView,
    InsightsView,
    ManageView,
    MergeView,
    SearchView,
    UnmergeView,
)

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
    path("attention", AttentionView.as_view(), name="attention"),
    path("insights", InsightsView.as_view(), name="insights"),
    path("search", SearchView.as_view(), name="search"),
    path("browse", BrowseView.as_view(), name="browse"),
    path("manage", ManageView.as_view(), name="manage"),
    path("manage/merge", MergeView.as_view(), name="manage-merge"),
    path("manage/unmerge", UnmergeView.as_view(), name="manage-unmerge"),
    path("hub/settings", HubSettingsView.as_view(), name="hub-settings"),
]
