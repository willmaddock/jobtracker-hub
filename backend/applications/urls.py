from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns
from .views import ApplicationViewSet, LegacyApplicationDeletionViewSet

prefix = "workspaces/<int:workspace_id>/applications/"
urlpatterns = [
    path(prefix, ApplicationViewSet.as_view({"get": "list", "post": "create"}), name="application-list"),
    path(prefix + "<int:pk>/documents/", ApplicationViewSet.as_view({"get": "documents", "post": "documents"}), name="application-documents"),
    path(prefix + "<int:pk>/dossier/", ApplicationViewSet.as_view({"get": "dossier"}), name="application-dossier"),
    path(prefix + "<int:pk>/override/", ApplicationViewSet.as_view({"post": "override"}), name="application-override"),
    path(prefix + "bulk-override/", ApplicationViewSet.as_view({"post": "bulk_override"}), name="application-bulk-override"),
    path("applications/<int:pk>/delete/", LegacyApplicationDeletionViewSet.as_view({"post": "delete"}), name="application-delete"),
    path("applications/bulk-delete/", LegacyApplicationDeletionViewSet.as_view({"post": "bulk_delete"}), name="application-bulk-delete"),
]

# Preserve the suffix variants previously supplied by DefaultRouter.
urlpatterns = format_suffix_patterns(urlpatterns)
