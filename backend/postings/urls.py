from rest_framework.routers import DefaultRouter

from .views import JobPostingViewSet

router = DefaultRouter()
router.register(r"job-postings", JobPostingViewSet, basename="job-posting")

urlpatterns = router.urls
