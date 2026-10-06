from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns
from .views import JobPostingViewSet
from .retained_extraction_views import RetainedExtractionEvidenceView

prefix = "workspaces/<int:workspace_id>/job-postings/"
urlpatterns = [
    path(prefix, JobPostingViewSet.as_view({"get": "list"}), name="job-posting-list"),
] + [
    path(prefix + "<int:pk>/" + action + "/", JobPostingViewSet.as_view({"post": action}), name="job-posting-" + action)
    for action in ("dismiss", "restore", "save", "apply")
]

# Preserve the suffix variants previously supplied by DefaultRouter.
urlpatterns = format_suffix_patterns(urlpatterns)

urlpatterns += [
    path("workspaces/<int:workspace_id>/retained-messages/<int:retained_message_id>/posting-extractions/",
         RetainedExtractionEvidenceView.as_view(), name="retained-posting-extraction-list"),
]
