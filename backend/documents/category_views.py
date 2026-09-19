"""Native numeric-ID category APIs; section mutation/deletion routes are retired."""
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from applications.creation import CreationContentionMixin
from applications.serializers import ApplicationSerializer
from applications.models import Application
from core.workspace_scope import WorkspaceScopedMixin
from core.lifecycle import require_live
from .models import Category, CATEGORY_SECTIONS, validate_category_name
from .category_services import assign_category, category_data, mutate_category, ordered_categories


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError({"detail": "Unknown fields are not accepted."})
        return super().to_internal_value(data)


class CategoryCreateInput(StrictInput):
    name = serializers.CharField(max_length=255, trim_whitespace=False, validators=[validate_category_name])
    section = serializers.ChoiceField(choices=CATEGORY_SECTIONS, default="misc")
    challenge = serializers.CharField(required=False, max_length=64, trim_whitespace=False)

    def validate_challenge(self, value):
        if not value.isascii():
            raise serializers.ValidationError("Expected an opaque challenge token.")
        return value


class CategoryUpdateInput(CategoryCreateInput):
    name = serializers.CharField(required=False, max_length=255, trim_whitespace=False, validators=[validate_category_name])
    section = serializers.ChoiceField(required=False, choices=CATEGORY_SECTIONS)
    archived = serializers.BooleanField(required=False)
    expected_revision = serializers.IntegerField(min_value=0)


class MembershipInput(StrictInput):
    category_id = serializers.IntegerField(min_value=1, allow_null=True)
    expected_revision = serializers.IntegerField(min_value=0)


class CategoryView(CreationContentionMixin, WorkspaceScopedMixin, APIView):
    action = "category"

    def get(self, request, pk=None, **kwargs):
        queryset = Category.objects.filter(workspace=self.get_workspace())
        if pk is not None:
            category = queryset.filter(pk=pk).first()
            if category is None:
                raise NotFound()
            return Response(category_data(category))
        if request.query_params.get("show_trashed", "").lower() not in {"1", "true"}:
            queryset = queryset.live()
        if request.query_params.get("show_archived", "").lower() not in {"1", "true"}:
            queryset = queryset.filter(archived=False)
        return Response([category_data(c) for c in ordered_categories(queryset)])

    def post(self, request, pk=None, **kwargs):
        if pk is not None:
            return self.http_method_not_allowed(request)
        return self.mutate(request, CategoryCreateInput(data=request.data))

    def patch(self, request, pk=None, **kwargs):
        if pk is None:
            return self.http_method_not_allowed(request)
        return self.mutate(request, CategoryUpdateInput(data=request.data), pk)

    def mutate(self, request, serializer, pk=None):
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        supplied = {field: values[field] for field in request.data if field != "challenge"}
        return mutate_category(actor=request.user, workspace=self.get_workspace(), key=request.headers.get("Idempotency-Key"),
            supplied=supplied, values=values, category_id=pk, challenge=values.get("challenge"))


class CategoryApplicationsView(WorkspaceScopedMixin, APIView):
    def get(self, request, pk, **kwargs):
        category = Category.objects.filter(workspace=self.get_workspace(), pk=pk).first()
        if category is None:
            raise NotFound()
        require_live(category)
        if category.archived and request.query_params.get("show_archived", "").lower() not in {"1", "true"}:
            return Response([])
        applications = Application.objects.live().filter(workspace=self.get_workspace(), category_membership__category=category).select_related("override", "category_membership__category").order_by("pk")
        if request.query_params.get("show_archived", "").lower() not in {"1", "true"}:
            applications = applications.exclude(override__archived=True)
        return Response(ApplicationSerializer(applications, many=True).data)


class ApplicationCategoryView(CreationContentionMixin, WorkspaceScopedMixin, APIView):
    action = "category"

    def put(self, request, pk, **kwargs):
        serializer = MembershipInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        return assign_category(actor=request.user, workspace=self.get_workspace(), application_id=pk, **serializer.validated_data)
