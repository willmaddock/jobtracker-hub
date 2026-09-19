from django.urls import path
from core.lifecycle_views import LifecycleView
from rest_framework.urlpatterns import format_suffix_patterns
from .views import DocumentViewSet, LegacyDocumentDeletionViewSet
from .category_views import CategoryView, CategoryApplicationsView, ApplicationCategoryView

prefix = "workspaces/<int:workspace_id>/"
document_patterns = [
    path(prefix + "documents/<int:pk>/", DocumentViewSet.as_view({"get": "retrieve"}), name="document-detail"),
    path(prefix + "documents/<int:pk>/rename/", DocumentViewSet.as_view({"post": "rename"}), name="document-rename"),
    path(prefix + "documents/<int:pk>/override/", DocumentViewSet.as_view({"post": "override"}), name="document-override"),
    path("documents/<int:pk>/delete/", LegacyDocumentDeletionViewSet.as_view({"post": "delete"}), name="document-delete"),
]

# Only Document routes came from DefaultRouter; section adapters did not.
urlpatterns = format_suffix_patterns(document_patterns) + [
    path(prefix + "categories/", CategoryView.as_view(), name="category-list"),
    path(prefix + "categories/<int:pk>/", CategoryView.as_view(), name="category-detail"),
    path(prefix + "categories/<int:pk>/applications/", CategoryApplicationsView.as_view(), name="category-applications"),
    path(prefix + "applications/<int:pk>/category/", ApplicationCategoryView.as_view(), name="application-category"),
]

# Lifecycle routes use only desired state and the expected lifecycle revision.
for kind in ['documents', 'categories']:
    for transition in ("trash", "restore"):
        urlpatterns.append(path(
            f"workspaces/<int:workspace_id>/{kind}/<int:pk>/{transition}/",
            LifecycleView.as_view(), {"kind": kind, "transition": transition},
            name=f"{kind[:-1] if kind != 'categories' else 'category'}-{transition}"))
