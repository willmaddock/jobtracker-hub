"""
documents services.

Phase 5 (docs/DJANGO_MIGRATION_PLAN.md). This is the "fetch the
object the user owns" replacement the migration plan called out for
_app/infrastructure/paths.py's resolve_safe/resolve_safe_dir --
those existed to stop a relpath from resolving outside the JobTracker
root on disk. There's no root to escape into any more (Phase 4 moved
uploads into per-workspace S3 keys), so the equivalent safety check
isn't a path-traversal guard at all -- it's an ordinary ownership
filter on the query. Getting this wrong the old way meant a crafted
relpath reading another user's files; getting it wrong the new way
would mean forgetting the `workspace=` filter and letting any
authenticated user fetch any Document by guessing its id. Same risk,
much simpler check.

No corresponding "resolve_safe_dir" here: that variant additionally
refused to resolve the JobTracker root itself or 'Applications/' as a
deletable target, guarding against a bad/blank source_relpath
trashing everything. An Application is deleted by its real id via the
ORM now (cascading to its Documents via Document.application's
on_delete=CASCADE -- see documents/models.py), so there's no
path-shaped "delete everything" footgun left to guard against.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404

from .models import Document


def get_owned_document(workspace, document_id: int) -> Document:
    """Fetch a Document by id, scoped to `workspace` -- a 404 (not a
    403) on mismatch, same as the rest of this codebase's
    "workspace-scoped or not found" convention (see applications/
    models.py's Application, which is looked up the same way),
    rather than confirming to the caller that the id exists but
    belongs to someone else.
    """
    return get_object_or_404(Document, pk=document_id, workspace=workspace)
