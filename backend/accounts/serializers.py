"""
accounts serializers.

Phase 8 (docs/DJANGO_MIGRATION_PLAN.md). login/logout/me are new
surface -- the Phase 0 endpoint inventory has no auth section at all,
since the old app was a single-user desktop tool with no login
screen. Workspace CRUD IS in that inventory, but most of its original
routes (inspect/link/import/import-folder/import-folder-local/export/
switch/rebuild) existed to bootstrap a workspace from a literal local
folder or to track one global "active" workspace -- concepts that
don't exist once a workspace is just an owned DB row and every query
is already ownership-scoped (see accounts/views.py's docstring for
the full breakdown of what's ported vs. deferred to Phase 10).
"""
from __future__ import annotations

from rest_framework import serializers

from .models import User, Workspace


class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = ["id", "name", "created_at"]
        read_only_fields = fields


class WorkspaceWriteSerializer(serializers.ModelSerializer):
    """Used for both create and rename -- name is the only field a
    caller can ever set. owner is assigned server-side from
    request.user (see WorkspaceViewSet.perform_create), never accepted
    from the client.
    """
    class Meta:
        model = Workspace
        fields = ["name"]

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("This field may not be blank.")
        return value


class UserSerializer(serializers.ModelSerializer):
    workspaces = WorkspaceSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "workspaces"]
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False, style={"input_type": "password"})
