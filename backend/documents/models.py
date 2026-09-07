"""
documents models.

Phase 3 slice only. The `documents`/`items` tables from jobtracker.db
(the disposable, folder-walked index) are Phase 4 territory -- they
become derived-from-Document data once uploads go through storage
instead of a filesystem walk (see docs/DJANGO_MIGRATION_PLAN.md Phase
4). What Phase 3 *does* need are the two overrides.db tables that key
off a document without needing a real Document row yet:
DocumentOverride (relpath-keyed) and DocumentExtraction (content-hash-
keyed) -- plus FolderOverride, which is folder/category-scoped rather
than per-document. All three get workspace scoping now so they don't
need it retrofitted once the real Document model lands.

DESIGN NOTE surfaced during porting, not present in the original
schema: the source `document_extractions` table keys purely on
content_hash with no workspace column, so it acts as one *global*
cache across every local install. In a single-tenant desktop app that
was fine. In this multi-tenant version, keying it globally would mean
one workspace's cached extraction (which includes emails/phones/URLs
pulled from the file's text) could be served back to a *different*
workspace that happens to upload a byte-identical file -- a real
cross-tenant data leak, not just a cache-correctness question. This
port scopes DocumentExtraction by workspace instead of leaving
content_hash as a bare global primary key, trading away the original
"identical resume across two unrelated installs only ever extracted
once" savings for tenant isolation. Worth confirming this tradeoff is
what you want before Phase 4 wires real extraction into it.
"""
from django.db import models


class DocumentOverride(models.Model):
    """Manual doc-type correction when a filename gives the
    classifier no real signal. Never changes the file on disk. Keyed
    by relpath for now (same as documents.relpath in jobtracker.db);
    becomes a FK to Document once Phase 4 lands.
    """

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="document_overrides"
    )
    relpath = models.CharField(max_length=1024)
    doc_type_override = models.CharField(max_length=64, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "relpath"], name="unique_document_override_per_workspace"
            )
        ]

    def __str__(self) -> str:
        return self.relpath


class DocumentExtraction(models.Model):
    """Cached extraction result (emails/phones/URLs/etc, see
    extract.py) keyed by content hash so an identical file filed
    under two applications is only ever extracted once *within a
    workspace* -- see the module docstring above for why this is
    workspace-scoped rather than a bare global content_hash key like
    the source table.
    """

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="document_extractions"
    )
    content_hash = models.CharField(max_length=64)
    # extract.EXTRACTOR_VERSION at write time; a stale version is a
    # cache miss rather than reused, so logic changes take effect
    # without a manual cache-clear step.
    extractor_version = models.CharField(max_length=32)
    extracted_json = models.JSONField()
    extracted_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "content_hash"], name="unique_extraction_per_workspace"
            )
        ]

    def __str__(self) -> str:
        return self.content_hash


class FolderOverride(models.Model):
    """Archive/section state for a physical top-level folder (or, for
    the nested-compliance case, a two-part folder path). Folder-scoped
    rather than section-scoped because several folders can share one
    Browse tab, and archiving needs to target just one without
    touching its siblings.
    """

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="folder_overrides"
    )
    folder = models.CharField(max_length=1024)
    # The Browse-tab section this folder currently resolves to.
    # Stored for display/lookup convenience only -- not used to
    # determine identity, since a folder name is already unique on
    # disk (within a workspace).
    section = models.CharField(max_length=32)
    archived = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "folder"], name="unique_folder_override_per_workspace"
            )
        ]

    def __str__(self) -> str:
        return self.folder
