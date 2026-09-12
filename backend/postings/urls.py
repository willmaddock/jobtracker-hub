from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns
from .views import JobPostingViewSet

prefix = "workspaces/<int:workspace_id>/job-postings/"
urlpatterns = [
    path(prefix, JobPostingViewSet.as_view({"get": "list"}), name="job-posting-list"),
] + [
    path(prefix + "<int:pk>/" + action + "/", JobPostingViewSet.as_view({"post": action}), name="job-posting-" + action)
    for action in ("dismiss", "restore", "save", "apply")
]

# Preserve the suffix variants previously supplied by DefaultRouter.
urlpatterns = format_suffix_patterns(urlpatterns)
