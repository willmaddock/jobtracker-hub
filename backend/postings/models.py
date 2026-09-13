"""
postings models.

Phase 3 port of job_postings from overrides_store.py -- see Phase 6
of docs/DJANGO_MIGRATION_PLAN.md for making JobPosting fully
first-class (this model already matches that phase's target shape,
just without the extraction pipeline behind it yet).
"""
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
        indexes = [models.Index(fields=["status"], name="postings_status_idx")]

    def save(self, *args, **kwargs):
        if self.pk:
            using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
            original = type(self).objects.using(using).filter(pk=self.pk).values(
                "workspace_id", "account_id"
            ).first()
            if original and (
                original["workspace_id"] != self.workspace_id
                or original["account_id"] != self.account_id
            ):
                raise ValidationError("Existing posting workspace and account are immutable.")
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
