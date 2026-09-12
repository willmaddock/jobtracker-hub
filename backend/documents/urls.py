from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns
from .views import (CategoryDeleteView, CategoryListView, CategoryOverrideView,
                    DocumentViewSet, LegacyDocumentDeletionViewSet)

prefix = "workspaces/<int:workspace_id>/"
document_patterns = [
    path(prefix + "documents/<int:pk>/", DocumentViewSet.as_view({"get": "retrieve"}), name="document-detail"),
    path(prefix + "documents/<int:pk>/rename/", DocumentViewSet.as_view({"post": "rename"}), name="document-rename"),
    path(prefix + "documents/<int:pk>/override/", DocumentViewSet.as_view({"post": "override"}), name="document-override"),
    path("documents/<int:pk>/delete/", LegacyDocumentDeletionViewSet.as_view({"post": "delete"}), name="document-delete"),
]

# Only Document routes came from DefaultRouter; section adapters did not.
urlpatterns = format_suffix_patterns(document_patterns) + [
    path(prefix + "categories/", CategoryListView.as_view(), name="category-list"),
    path(prefix + "categories/<str:section>/override/", CategoryOverrideView.as_view(), name="category-override"),
    path("categories/<str:section>/delete", CategoryDeleteView.as_view(), name="category-delete"),
]
