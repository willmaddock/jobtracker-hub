"""
postings models.

Phase 3 port of job_postings from overrides_store.py -- see Phase 6
of docs/DJANGO_MIGRATION_PLAN.md for making JobPosting fully
first-class (this model already matches that phase's target shape,
just without the extraction pipeline behind it yet).
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, router

from applications.models import Application
from email_sync.models import EmailAccount


class JobPosting(models.Model):
    """One individual job listing extracted from a digest email. One
    row per job, not per email -- a single digest message can (and
    usually does) produce several of these, all sharing message_id
    but with different dedupe_key values (see posting_extract.
    compute_dedupe_key()).
    """

    # PK is runtime identity; UUID is portable identity within the Workspace.
    portable_id = models.UUIDField(default=uuid.uuid4, editable=False)

    STATUS_CHOICES = [
        ("new", "New"),
        ("dismissed", "Dismissed"),
    ]

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="job_postings"
    )
    account = models.ForeignKey(
        EmailAccount, on_delete=models.CASCADE, related_name="job_postings"
    )
    message_id = models.CharField(max_length=512)
    source = models.CharField(max_length=64, blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)
    company = models.CharField(max_length=255, blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    salary = models.CharField(max_length=255, blank=True, null=True)
    employment_type = models.CharField(max_length=64, blank=True, null=True)
    posting_url = models.URLField(max_length=2048, blank=True, null=True)
    received_at = models.DateTimeField(blank=True, null=True)
    email_subject = models.CharField(max_length=998, blank=True, null=True)
    sender = models.CharField(max_length=255, blank=True, null=True)
    # Dismissing hides a job from the board without deleting it, same
    # UX shape as Discovery.
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="new")
    # Starred/saved by the user. Independent of status: a saved job
    # can still be dismissed.
    saved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # account + normalized posting URL when available, else account +
    # message_id + normalized title + normalized company. Unique here
    # is what makes ingesting a posting safe to call repeatedly across
    # syncs -- a re-extracted digest is a no-op, not a duplicate row.
    dedupe_key = models.CharField(max_length=512, unique=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["workspace", "portable_id"], name="unique_posting_portable_per_ws")]
        indexes = [models.Index(fields=["status"], name="postings_status_idx")]

    def save(self, *args, **kwargs):
        if self.pk:
            using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
            original = type(self).objects.using(using).filter(pk=self.pk).values(
                "workspace_id", "account_id", "portable_id"
            ).first()
            if original and (
                original["workspace_id"] != self.workspace_id
                or original["account_id"] != self.account_id
                or original["portable_id"] != self.portable_id
            ):
                raise ValidationError("Existing posting workspace, account and portable identity are immutable.")
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.title or '?'} @ {self.company or '?'}"


class PostingApplicationConversion(models.Model):
    """Durable conversion fact; historical unknown operation/time remain null."""
    workspace = models.ForeignKey("accounts.Workspace", on_delete=models.CASCADE)
    posting = models.ForeignKey(JobPosting, null=True, on_delete=models.SET_NULL, related_name="conversions")
    application = models.ForeignKey(Application, null=True, on_delete=models.SET_NULL, related_name="posting_conversions")
    application_portable_id = models.UUIDField()
    request_intent = models.OneToOneField("core.ApplicationRequestIntent", null=True, on_delete=models.SET_NULL)
    converted_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["posting", "application"], name="unique_surviving_posting_attempt")]


class PostingExtractionProvenance(models.Model):
    """Insert-only ordinary ORM evidence; bulk/raw SQL are maintenance surfaces."""
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        if not self._state.adding or (self.pk and type(self).objects.using(using).filter(pk=self.pk).exists()):
            raise ValidationError("Posting extraction provenance is immutable.")
        self.validate_insertion()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Posting extraction provenance deletion is not implemented.")


class RetainedPostingExtraction(PostingExtractionProvenance):
    """Completed producer-declared extraction, not a task or durable source item.

    retained_extractions.record_posting_extraction owns atomic batch writes. Source
    ownership derives through the protected message; future purge is explicit.
    """
    retained_message = models.ForeignKey("email_sync.RetainedMessage", on_delete=models.PROTECT,
                                         related_name="posting_extractions")
    operation_id = models.UUIDField(editable=False)
    extractor_method = models.CharField(max_length=64)
    extractor_version = models.CharField(max_length=32)
    snapshot_version = models.PositiveSmallIntegerField(default=1, editable=False)
    input_spec = models.JSONField()
    payload_digest = models.CharField(max_length=64, editable=False)
    extracted_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["retained_message", "operation_id"],
                                              name="posting_extraction_operation")]

    def validate_insertion(self):
        from . import extraction_contract as contract
        from django.utils.timezone import is_aware
        from datetime import datetime
        import re
        try:
            contract.require(type(self.snapshot_version) is int and self.snapshot_version == contract.SNAPSHOT_VERSION)
            contract.require(isinstance(self.extracted_at, datetime) and is_aware(self.extracted_at))
            contract.validate_envelope(self.operation_id, self.extractor_method, self.extractor_version,
                                       self.input_spec, self.extracted_at.isoformat(), [])
            contract.require(type(self.payload_digest) is str and
                             re.fullmatch(r"[0-9a-f]{64}", self.payload_digest) is not None)
        except contract.InvalidExtraction:
            raise ValidationError("Invalid posting extraction.") from None


class RetainedPostingExtractionOutput(PostingExtractionProvenance):
    """One output observation; UUID/position never establish cross-run continuity."""
    extraction = models.ForeignKey(RetainedPostingExtraction, on_delete=models.PROTECT, related_name="outputs")
    portable_id = models.UUIDField(default=uuid.uuid4, editable=False)
    position = models.PositiveIntegerField()
    fields = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["extraction", "portable_id"], name="posting_output_portable"),
            models.UniqueConstraint(fields=["extraction", "position"], name="posting_output_position"),
        ]

    def validate_insertion(self):
        from . import extraction_contract as contract
        try:
            contract.operation_uuid(self.portable_id)
            contract.require(type(self.position) is int and 0 <= self.position < contract.MAX_OUTPUTS)
            contract.validate_fields(self.fields)
        except contract.InvalidExtraction:
            raise ValidationError("Invalid posting extraction output.") from None


class PostingItemProvenance(models.Model):
    """Ordinary insert-only writes; privileged bulk/raw writes are maintenance."""
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        if not self._state.adding or (self.pk and type(self).objects.using(using).filter(pk=self.pk).exists()):
            raise ValidationError("Posting item provenance is immutable.")
        self.validate_insertion(using)
        return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.validate_insertion(router.db_for_write(type(self), instance=self))

    def delete(self, *args, **kwargs):
        raise ValidationError("Posting item provenance deletion is not implemented.")


class RetainedPostingItem(PostingItemProvenance):
    """Explicit occurrence within one retained source, independent of interpretation.

    retained_items atomically allocates this identity with its first association.
    Portable reference includes Workspace lineage and retained-source portable ID.
    """
    retained_message = models.ForeignKey("email_sync.RetainedMessage", on_delete=models.PROTECT,
                                         related_name="posting_items")
    portable_id = models.UUIDField(default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["retained_message", "portable_id"],
                                              name="posting_item_portable")]

    def validate_insertion(self, using):
        from .extraction_contract import InvalidExtraction, operation_uuid
        try:
            operation_uuid(self.portable_id)
        except InvalidExtraction:
            raise ValidationError("Invalid posting item identity.") from None
        if not self.retained_message_id:
            raise ValidationError("Posting item source is required.")


class RetainedPostingItemAssociation(PostingItemProvenance):
    """Initial assertion only; no current interpretation or correction authority."""
    class Mode(models.TextChoices):
        ALLOCATE = "allocate_new", "Allocate new occurrence"
        ATTACH = "attach_existing", "Attach to existing occurrence"

    item = models.ForeignKey(RetainedPostingItem, on_delete=models.PROTECT, related_name="associations")
    output = models.OneToOneField(RetainedPostingExtractionOutput, on_delete=models.PROTECT,
                                  related_name="initial_item_association")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="posting_item_associations")
    mode = models.CharField(max_length=16, choices=Mode.choices)
    method = models.CharField(max_length=32, default="explicit_owner", editable=False)
    decision_version = models.PositiveSmallIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(mode__in=["allocate_new", "attach_existing"]),
                                   name="posting_item_assoc_mode"),
            models.CheckConstraint(condition=models.Q(method="explicit_owner"), name="posting_item_assoc_method"),
            models.CheckConstraint(condition=models.Q(decision_version=1), name="posting_item_assoc_version"),
        ]

    def validate_insertion(self, using):
        if (self.mode not in self.Mode.values or self.method != "explicit_owner"
                or type(self.decision_version) is not int or self.decision_version != 1 or not self.actor_id):
            raise ValidationError("Invalid posting item decision.")
        # Query persisted endpoints on the write database, not cached related objects.
        source = RetainedPostingItem.objects.using(using).filter(pk=self.item_id).values_list(
            "retained_message_id", flat=True).first()
        output_source = RetainedPostingExtractionOutput.objects.using(using).filter(pk=self.output_id).values_list(
            "extraction__retained_message_id", flat=True).first()
        if source is None or source != output_source:
            raise ValidationError("Posting item association source mismatch.")


class RetainedPostingItemCorrection(PostingItemProvenance):
    """Immutable explicit transition; revision, never timestamp, orders effects."""
    class Mode(models.TextChoices):
        ASSOCIATE = "associate", "Associate"
        WITHDRAW = "withdraw", "Withdraw"

    initial_association = models.ForeignKey(RetainedPostingItemAssociation, on_delete=models.PROTECT,
                                            related_name="corrections")
    operation_id = models.UUIDField(editable=False)
    revision = models.PositiveBigIntegerField()
    mode = models.CharField(max_length=16, choices=Mode.choices)
    target_item = models.ForeignKey(RetainedPostingItem, null=True, on_delete=models.PROTECT,
                                    related_name="association_corrections")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name="posting_item_corrections")
    method = models.CharField(max_length=32, default="explicit_owner", editable=False)
    decision_version = models.PositiveSmallIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["initial_association", "operation_id"], name="posting_corr_operation"),
            models.UniqueConstraint(fields=["initial_association", "revision"], name="posting_corr_revision"),
            models.CheckConstraint(condition=models.Q(revision__gte=1), name="posting_corr_positive_revision"),
            models.CheckConstraint(condition=(models.Q(mode="associate", target_item__isnull=False)
                | models.Q(mode="withdraw", target_item__isnull=True)), name="posting_corr_target"),
            models.CheckConstraint(condition=models.Q(method="explicit_owner"), name="posting_corr_method"),
            models.CheckConstraint(condition=models.Q(decision_version=1), name="posting_corr_version"),
        ]

    def validate_insertion(self, using):
        from .extraction_contract import InvalidExtraction, operation_uuid
        from .retained_item_corrections import MAX_REVISION, CorrectionConflict, resolve_chain
        try:
            operation_uuid(self.operation_id)
        except InvalidExtraction:
            raise ValidationError("Invalid correction operation identity.") from None
        if (type(self.revision) is not int or not 1 <= self.revision <= MAX_REVISION
                or self.method != "explicit_owner" or type(self.decision_version) is not int
                or self.decision_version != 1 or not self.actor_id
                or not ((self.mode == "associate" and self.target_item_id is not None)
                        or (self.mode == "withdraw" and self.target_item_id is None))):
            raise ValidationError("Invalid correction decision.")
        initial = RetainedPostingItemAssociation.objects.using(using).filter(pk=self.initial_association_id).first()
        if initial is None:
            raise ValidationError("Initial association is required.")
        try:
            chain = resolve_chain(initial, using=using)
        except CorrectionConflict:
            raise ValidationError("Invalid correction history.") from None
        if self.revision != chain.revision + 1:
            raise ValidationError("Correction revision must be contiguous.")
        if self.mode == "associate" and not RetainedPostingItem.objects.using(using).filter(
                pk=self.target_item_id, retained_message_id=chain.source_id).exists():
            raise ValidationError("Correction target source mismatch.")
        if self.target_item_id == (chain.item.pk if chain.item else None):
            raise ValidationError("Correction must change the effective target.")


class PostingSource(PostingItemProvenance):
    """Immutable initial item-to-posting assertion, not effective mapping authority."""
    item = models.OneToOneField(RetainedPostingItem, on_delete=models.PROTECT,
                               related_name="initial_posting_source")
    posting = models.ForeignKey(JobPosting, on_delete=models.PROTECT,
                                related_name="initial_posting_sources")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name="posting_source_assertions")
    method = models.CharField(max_length=32, default="explicit_owner", editable=False)
    decision_version = models.PositiveSmallIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(method="explicit_owner"), name="posting_source_method"),
            models.CheckConstraint(condition=models.Q(decision_version=1), name="posting_source_version"),
        ]

    def validate_insertion(self, using):
        from django.contrib.auth import get_user_model
        if (self.method != "explicit_owner" or type(self.decision_version) is not int
                or self.decision_version != 1
                or not get_user_model().objects.using(using).filter(pk=self.actor_id).exists()):
            raise ValidationError("Invalid posting source attribution or policy.")
        source = RetainedPostingItem.objects.using(using).filter(pk=self.item_id).values(
            "retained_message__workspace_id", "retained_message__mailbox__workspace_id",
            "retained_message__provider", "retained_message__mailbox__provider").first()
        posting = JobPosting.objects.using(using).filter(pk=self.posting_id).values(
            "workspace_id", "account__workspace_id").first()
        if (source is None or posting is None
                or source["retained_message__workspace_id"] != source["retained_message__mailbox__workspace_id"]
                or source["retained_message__provider"] != source["retained_message__mailbox__provider"]
                or source["retained_message__workspace_id"] != posting["workspace_id"]
                or posting["workspace_id"] != posting["account__workspace_id"]):
            raise ValidationError("Posting source endpoint scope mismatch.")
