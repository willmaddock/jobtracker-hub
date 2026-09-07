"""
documents models.

Phase 4 (see docs/DJANGO_MIGRATION_PLAN.md) introduces the real
`Document` model -- a row per uploaded file, `FileField` backed by
S3-compatible storage via django-storages instead of a local path
(config/settings/prod.py). This replaces the `documents`/`items`
tables from jobtracker.db, the disposable index build_index.py used
to produce by walking a folder on disk: there's no folder to walk
once files live in per-workspace object storage, so "rebuild the
index" becomes "re-derive Application.status/last_activity/
first_activity from this workspace's Document rows" (see
applications/models.py's Application docstring).

DocumentOverride and DocumentExtraction, ported in Phase 3 as
relpath/content-hash-keyed placeholders (see git history), now carry
real FKs to Document as planned. DESIGN NOTE on how each of the two
got wired up, since they didn't get the same treatment:

- DocumentOverride becomes a straight OneToOneField(Document) --
  identity *is* the document now, so the standalone `workspace` FK
  it had in Phase 3 (needed back when there was no Document row to
  hang off of) is redundant and dropped, same as Override already
  does for Application in applications/models.py.

- DocumentExtraction keeps its Phase 3 (workspace, content_hash)
  identity rather than switching to a Document FK, on purpose: the
  whole point of that shape was that an identical resume filed under
  two different Applications (two different Document rows, same
  bytes) only ever gets extracted once per workspace. A OneToOne to
  Document would silently throw that cache hit away -- every
  duplicate upload would re-run extraction. So the cache key stays
  content-hash-based, and a nullable, non-unique `document` FK is
  added only for traceability (which upload actually triggered a
  given cache write), not as the lookup key.
"""
from django.db import models


def document_upload_path(instance: "Document", filename: str) -> str:
    """Storage key for an uploaded Document. Namespaced by workspace
    and application so per-tenant isolation carries into the object
    key itself, not just into DB row ownership -- two workspaces
    can't collide on the same S3 key even if they upload
    identically-named files. `filename` is the original filename;
    django-storages/Django itself appends a random suffix if the
    resulting key already exists (see AWS_S3_FILE_OVERWRITE=False in
    prod.py), so accidental overwrite isn't a concern here.
    """
    return (
        f"workspaces/{instance.workspace_id}/applications/"
        f"{instance.application_id}/{filename}"
    )


class Document(models.Model):
    """One uploaded file (resume, cover letter, evidence PDF, ...)
    belonging to an Application. Replaces a jobtracker.db
    `documents` row; `doc_type` mirrors classify.classify_doc_type's
    return values so the existing classification logic (Phase 5)
    needs no schema changes to port over.
    """

    DOC_TYPE_CHOICES = [
        ("readme", "Readme"),
        ("resume", "Resume"),
        ("cover_letter", "Cover letter"),
        ("interview_prep", "Interview prep"),
        ("rejection_notice", "Rejection notice"),
        ("interview_notice", "Interview notice"),
        ("application_confirmation", "Application confirmation"),
        ("job_posting", "Job posting"),
        ("certificate", "Certificate"),
        ("other", "Other"),
    ]

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="documents"
    )
    application = models.ForeignKey(
        "applications.Application", on_delete=models.CASCADE, related_name="documents"
    )
    file = models.FileField(upload_to=document_upload_path)
    # Original filename, kept separate from the storage key -- the
    # key gets a dedupe suffix on collision (see document_upload_path
    # above), but the UI should still show the name the user uploaded.
    filename = models.CharField(max_length=255)
    doc_type = models.CharField(max_length=32, choices=DOC_TYPE_CHOICES, default="other")
    ext = models.CharField(max_length=16)
    content_hash = models.CharField(max_length=64, db_index=True)
    size = models.PositiveBigIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["workspace", "application"], name="doc_workspace_app_idx"),
            models.Index(fields=["workspace", "content_hash"], name="doc_workspace_hash_idx"),
        ]

    def __str__(self) -> str:
        return self.filename


class DocumentOverride(models.Model):
    """Manual doc-type correction when a filename gives the
    classifier no real signal. Never changes the uploaded file
    itself. Now a real OneToOne to Document -- see the module
    docstring for why this one (unlike DocumentExtraction) moved to
    a straight FK identity.
    """

    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, primary_key=True, related_name="override"
    )
    doc_type_override = models.CharField(max_length=64, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Override for {self.document}"


class DocumentExtraction(models.Model):
    """Cached extraction result (emails/phones/URLs/etc, see
    extract.py), still keyed by (workspace, content_hash) rather
    than by Document -- see the module docstring for why that cache
    key is preserved deliberately rather than becoming a Document
    FK. `document` here is provenance only (which upload most
    recently produced/hit this cache row), never the lookup key.
    """

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="document_extractions"
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="extractions",
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
