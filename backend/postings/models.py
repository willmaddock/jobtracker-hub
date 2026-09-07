"""
postings models.

Phase 3 port of job_postings from overrides_store.py -- see Phase 6
of docs/DJANGO_MIGRATION_PLAN.md for making JobPosting fully
first-class (this model already matches that phase's target shape,
just without the extraction pipeline behind it yet).
"""
from django.db import models

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
    # The Application this posting was turned into via "Apply",
    # NULL until that happens. A real nullable FK now -- the old
    # store kept this as a bare item_key string specifically because
    # item_keys weren't reliable identifiers; Application.id doesn't
    # have that problem, so on_delete=SET_NULL keeps a posting around
    # (un-applied) if its Application is later deleted, rather than
    # requiring the "re-check against the live list" workaround the
    # old code needed.
    applied_application = models.ForeignKey(
        Application,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="job_postings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # account + normalized posting URL when available, else account +
    # message_id + normalized title + normalized company. Unique here
    # is what makes ingesting a posting safe to call repeatedly across
    # syncs -- a re-extracted digest is a no-op, not a duplicate row.
    dedupe_key = models.CharField(max_length=512, unique=True)

    class Meta:
        indexes = [models.Index(fields=["status"], name="postings_status_idx")]

    def __str__(self) -> str:
        return f"{self.title or '?'} @ {self.company or '?'}"
