"""
accounts views.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md).

Auth (login/logout/me) is new surface introduced by Phase 2 -- the old
single-user desktop app had no login screen at all, so there's
nothing in _app/api.py's endpoint inventory to port here.
SessionAuthentication is what every other app's DRF views
authenticate against; this is where that session actually gets
created and destroyed.

Workspace CRUD ports 4 of the original 11 workspace routes -- list,
create, rename, delete. The other 7
(inspect/link/import/import-folder/import-folder-local/export/switch)
plus /api/rebuild all existed to manage a workspace as a literal local
folder with one global "active" workspace, neither of which exists
anymore:

- inspect/link/import/import-folder/import-folder-local were ways to
  point a new workspace at an existing folder or zip of one. The
  Phase 10 one-off management command to migrate real existing local
  data ("not a manual process," per that phase's own description) is
  the actual replacement for this -- a real data-format bridge, not
  an ongoing API a browser client calls.
- export streamed the workspace's folder back as a zip. A real
  equivalent (a proper data export, once Documents/Applications/
  JobPostings all exist to export) is worth building, but as its own
  designed feature later, not a like-for-like zip-of-a-folder port
  when there's no folder anymore.
- switch existed only because the old app tracked one global "active"
  workspace in workspaces.json. Every DRF view in this codebase is
  already ownership-scoped per request (workspace__owner=request.user)
  rather than reading a mutable "current" pointer, so there's no
  server-side state left for "switch" to flip.
- POST /api/rebuild re-derived Application status/last_activity from a
  filesystem walk. Its Phase 4-era replacement ("re-derive from
  Document rows, not a filesystem walk") depends on the Document/
  Application override-derivation logic a later Phase 8 slice builds
  -- tracked there, not here.

WorkspaceViewSet's own responses are simpler than the originals for
the same reason postings/services.py's build_apply_response is
simpler than its predecessor: Workspace.id is the one real identity,
so there's no separate stale_siblings_found/ok wrapper needed once
creating a workspace is just an ordinary owned DB row, not folder
setup with side effects to report on.
"""
from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Workspace
from .serializers import LoginSerializer, UserSerializer, WorkspaceSerializer, WorkspaceWriteSerializer


@method_decorator(never_cache, name="dispatch")
class CsrfView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            return Response(
                {"code": "invalid_credentials", "detail": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        login(request, user)
        return Response(UserSerializer(user).data)


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(never_cache, name="dispatch")
class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class WorkspaceViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    def get_queryset(self):
        return Workspace.objects.filter(owner=self.request.user)

    def get_serializer_class(self):
        if self.action in ("create", "rename"):
            return WorkspaceWriteSerializer
        return WorkspaceSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def create(self, request, *args, **kwargs):
        # CreateModelMixin's default response re-serializes with
        # get_serializer_class()'s write serializer, which only has
        # `name` -- respond with the full read shape (id, created_at)
        # instead, since that's what a caller actually needs back from
        # a create call.
        write_serializer = self.get_serializer(data=request.data)
        write_serializer.is_valid(raise_exception=True)
        self.perform_create(write_serializer)
        workspace = write_serializer.instance
        headers = self.get_success_headers(write_serializer.data)
        return Response(
            WorkspaceSerializer(workspace).data, status=status.HTTP_201_CREATED, headers=headers,
        )

    @action(detail=True, methods=["post"])
    def rename(self, request, pk=None):
        workspace = self.get_object()
        serializer = self.get_serializer(workspace, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(WorkspaceSerializer(workspace).data)
