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

import hashlib
import re

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


# --- doc_type classification -------------------------------------------------
# Ported unchanged from _app/classify.py's classify_doc_type -- pure
# filename regexes with zero filesystem dependency, so unlike
# classify_section (see documents/views.py's module docstring on why
# categories don't need it anymore) this one carries over as-is.
_RESUME_RE = re.compile(r"resume", re.I)
_COVER_RE = re.compile(r"cover\s*-?letter|coverletter", re.I)
_PREP_RE = re.compile(
    r"cheat\s*sheet|cheatsheet|interview\s*prep|prep\b|quiz|study|mock|troubleshoot",
    re.I,
)
_REJECT_RE = re.compile(r"reject|not referred|eligible list not referred", re.I)
_INTERVIEW_RE = re.compile(r"interview|phone screen|screener|schedule", re.I)
_CONFIRM_RE = re.compile(
    r"thank you|application received|received by|confirmation|application status|"
    r"got it application|successful application|update",
    re.I,
)
_POSTING_RE = re.compile(r"job bulletin|job description|job id|careers|job details", re.I)
_CERT_RE = re.compile(r"coursera|certificat", re.I)
_README_RE = re.compile(r"^readme", re.I)


def classify_doc_type(filename: str) -> str:
    if _README_RE.match(filename):
        return "readme"
    if _RESUME_RE.search(filename):
        return "resume"
    if _COVER_RE.search(filename):
        return "cover_letter"
    if _PREP_RE.search(filename):
        return "interview_prep"
    if _REJECT_RE.search(filename):
        return "rejection_notice"
    if _INTERVIEW_RE.search(filename):
        return "interview_notice"
    if _CONFIRM_RE.search(filename):
        return "application_confirmation"
    if _POSTING_RE.search(filename):
        return "job_posting"
    if _CERT_RE.search(filename):
        return "certificate"
    return "other"


def effective_doc_type(document: Document) -> str:
    """The doc_type a caller should actually treat this Document as --
    the manual DocumentOverride.doc_type_override when one is set,
    otherwise the classifier's own Document.doc_type. Same rule
    documents/serializers.py's DocumentSerializer.get_effective_doc_type
    applies for API output; factored out here so applications/
    dossier.py (which needs the same rule to pick the job-posting
    document and the date-evidence documents) doesn't have to
    reimplement it.
    """
    override = getattr(document, "override", None)
    if override is not None and override.doc_type_override:
        return override.doc_type_override
    return document.doc_type


def sha256_of(uploaded_file) -> str:
    """Content hash for an in-memory/streamed upload -- the Document
    equivalent of _app/build_index.py's sha256_of(path), just reading
    from Django's UploadedFile chunks instead of a filesystem path.
    Rewinds the file afterwards so the caller can still read/save it.
    """
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()


def duplicate_counts(workspace, content_hashes: list[str]) -> dict[str, int]:
    """How many OTHER documents in this workspace share each content
    hash -- ported from db.annotate_duplicates, now workspace-scoped
    (S3 keys are already namespaced per workspace, so "duplicate"
    only ever means "duplicate within your own tracker") instead of
    scoped to the whole local jobtracker.db.
    """
    from django.db.models import Count

    hashes = [h for h in content_hashes if h]
    if not hashes:
        return {}
    rows = (
        Document.objects.filter(workspace=workspace, content_hash__in=set(hashes))
        .values("content_hash")
        .annotate(count=Count("id"))
    )
    return {row["content_hash"]: row["count"] for row in rows}
