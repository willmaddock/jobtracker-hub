"""Admin may inspect retained records but cannot bypass lifecycle authority."""
from django.core.exceptions import PermissionDenied
from applications.creation import lock_workspace
from core.lifecycle import require_live, LifecycleConflict


class LifecycleAdminMixin:
    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.effective_trashed:
            return False
        return super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        # ModelAdmin changeform owns a transaction. Use the same gate as product
        # mutations and recheck after waiting; never trust a stale admin form.
        from accounts.models import Workspace
        workspace = Workspace.objects.get(pk=obj.workspace_id)
        lock_workspace(workspace.owner, workspace)
        if change:
            current = type(obj).objects.get(pk=obj.pk)
            try:
                require_live(current)
            except LifecycleConflict as exc:
                raise PermissionDenied(str(exc))
            obj.trashed_at = current.trashed_at
            obj.lifecycle_revision = current.lifecycle_revision
            if hasattr(current, "category_revision"):
                obj.category_revision = current.category_revision
        super().save_model(request, obj, form, change)
