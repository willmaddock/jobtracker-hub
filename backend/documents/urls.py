from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CategoryDeleteView, CategoryListView, CategoryOverrideView, DocumentViewSet

router = DefaultRouter()
router.register(r"documents", DocumentViewSet, basename="document")

urlpatterns = [
    path("categories", CategoryListView.as_view(), name="category-list"),
    path("categories/<str:section>/override", CategoryOverrideView.as_view(), name="category-override"),
    path("categories/<str:section>/delete", CategoryDeleteView.as_view(), name="category-delete"),
] + router.urls
