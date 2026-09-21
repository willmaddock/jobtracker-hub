from django.urls import path
from core.lifecycle_views import LifecycleView
from rest_framework.urlpatterns import format_suffix_patterns
from .views import ApplicationViewSet, LegacyApplicationDeletionViewSet
from .message_views import ApplicationMessages

prefix = "workspaces/<int:workspace_id>/applications/"
urlpatterns = [
    path(prefix + "<int:pk>/messages/", ApplicationMessages.as_view(), name="application-messages"),
    path(prefix + "<int:pk>/derive/", ApplicationViewSet.as_view({"post": "derive"}), name="application-derive"),
    path(prefix + "<int:pk>/", ApplicationViewSet.as_view({"get": "retrieve"}), name="application-detail"),
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

# Lifecycle routes use only desired state and the expected lifecycle revision.
for kind in ['applications']:
    for transition in ("trash", "restore"):
        urlpatterns.append(path(
            f"workspaces/<int:workspace_id>/{kind}/<int:pk>/{transition}/",
            LifecycleView.as_view(), {"kind": kind, "transition": transition},
            name=f"{kind[:-1] if kind != 'categories' else 'category'}-{transition}"))
