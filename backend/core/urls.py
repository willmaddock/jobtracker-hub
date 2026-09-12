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
    path("workspaces/<int:workspace_id>/attention/", AttentionView.as_view(), name="attention"),
    path("workspaces/<int:workspace_id>/insights/", InsightsView.as_view(), name="insights"),
    path("workspaces/<int:workspace_id>/search/", SearchView.as_view(), name="search"),
    path("workspaces/<int:workspace_id>/browse/", BrowseView.as_view(), name="browse"),
    path("workspaces/<int:workspace_id>/manage/", ManageView.as_view(), name="manage"),
    path("workspaces/<int:workspace_id>/manage/merge/", MergeView.as_view(), name="manage-merge"),
    path("workspaces/<int:workspace_id>/manage/unmerge/", UnmergeView.as_view(), name="manage-unmerge"),
    path("workspaces/<int:workspace_id>/hub/settings/", HubSettingsView.as_view(), name="hub-settings"),
]
