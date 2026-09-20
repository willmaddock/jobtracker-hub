"""
applications models.

Phase 3 (see docs/DJANGO_MIGRATION_PLAN.md) -- consolidates the
`items` identity concept from _app/build_index.py (jobtracker.db, the
disposable index) with `item_overrides` and `status_history` from
_app/overrides_store.py (overrides.db, the durable store).

The old app's item_key (a string: "section|company|role_label|
source_relpath") was the join key across item_overrides, status_
history, account_matches, thread_identifiers, and job_postings.
applied_item_key. Application.id replaces it everywhere: every table
that used to carry a loosely-matched item_key string now carries a
real ForeignKey(Application), giving referential integrity and
cascade deletes the old string-keyed joins never had.

Automatic fields are maintained by applications.derivation after explicit
eligible-evidence mutations. Historical rows remain pending until individually
reconciled; no model signal or migration backfills their business state.
"""
import uuid

from core.lifecycle_models import RetainedLifecycle
from django.core.exceptions import ValidationError
from django.db import models

from accounts.models import Workspace


class Application(RetainedLifecycle):
    """One tracked item -- an application, a credential, a network
    contact, etc. Replaces a jobtracker.db `items` row plus its
    item_key. Everything else in this app (and in email_sync/
    postings) hangs off this via FK instead of a string join.
    """

    SECTION_CHOICES = [
        ("applications", "Applications"),
        ("credentials", "Credentials"),
        ("network", "Network"),
        ("resume_library", "Resume library"),
        ("leads", "Leads"),
        ("personal", "Personal"),
        ("compliance", "Compliance"),
        ("misc", "Misc"),
    ]

    STATUS_CHOICES = [
        ("applied", "Applied"),
        ("interviewing", "Interviewing"),
        ("rejected", "Rejected"),
        ("drafted", "Drafted"),
        ("unknown", "Unknown"),
        ("n/a", "N/A"),
    ]

    workspace = models.ForeignKey(
        Workspace, on_delete=models.PROTECT, related_name="applications"
    )
    portable_id = models.UUIDField(default=uuid.uuid4, editable=False)
    category_revision = models.PositiveBigIntegerField(default=0, editable=False)
    section = models.CharField(max_length=32, choices=SECTION_CHOICES)
    company = models.CharField(max_length=255)
    role_label = models.CharField(max_length=255)
    # Transitional provenance only; never used to allocate or identify attempts.
    source_relpath = models.CharField(max_length=1024, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default="unknown"
    )
    last_activity = models.DateTimeField(null=True, blank=True)
    first_activity = models.DateTimeField(null=True, blank=True)
    # Date-only bounds never masquerade as midnight instants. Empty provenance
    # on existing rows means historical semantics have not been reconciled.
    first_activity_date = models.DateField(null=True, blank=True, editable=False)
    last_activity_date = models.DateField(null=True, blank=True, editable=False)
    activity_provenance = models.JSONField(default=dict, editable=False)
    automatic_date_applied = models.DateField(null=True, blank=True, editable=False)
    date_candidate = models.JSONField(default=dict, editable=False)
    derivation_version = models.CharField(max_length=16, blank=True, editable=False)
    derivation_fingerprint = models.CharField(max_length=64, blank=True, editable=False)
    derived_at = models.DateTimeField(null=True, editable=False)
    derivation_state = models.CharField(max_length=24, default="pending", editable=False,
        choices=[(s, s) for s in ("pending", "current", "incomplete", "needs_reconciliation")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(first_activity__isnull=True) | models.Q(first_activity_date__isnull=True),
                                   name="application_first_one_precision"),
            models.CheckConstraint(condition=models.Q(last_activity__isnull=True) | models.Q(last_activity_date__isnull=True),
                                   name="application_last_one_precision"),
            models.UniqueConstraint(
                fields=["workspace", "portable_id"],
                name="unique_application_portable_id_per_workspace",
            )
        ]
        indexes = [
            models.Index(fields=["workspace", "section"], name="app_workspace_section_idx")
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values("portable_id", "workspace_id").first()
            if original and (original["portable_id"] != self.portable_id or original["workspace_id"] != self.workspace_id):
                raise ValidationError("Application identity and workspace are immutable.")
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.company} / {self.role_label}"


class Override(models.Model):
    """User-entered corrections layered on top of an Application's
    auto-detected fields. One-to-one, mirroring item_overrides'
    `item_key TEXT PRIMARY KEY` design -- at most one override row per
    Application, created lazily on first save the same way the old
    store did.
    """

    DATE_APPLIED_SOURCE_CHOICES = [
        ("confirmation", "Confirmation"),
        ("posting", "Posting"),
    ]

    application = models.OneToOneField(
        Application,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="override",
    )
    manual_status = models.CharField(max_length=16, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    date_applied = models.DateField(blank=True, null=True)
    date_applied_mode = models.CharField(max_length=24, default="automatic",
        choices=[(s, s) for s in ("automatic", "manual", "legacy_preserved", "suppressed")])
    # How date_applied got its value -- "confirmation"/"posting" when
    # accepted from a detected-date suggestion, NULL when typed
    # manually. Display-only provenance; cleared whenever date_applied
    # is set without this field also being sent (mirrors api.py's
    # save_override behavior).
    date_applied_source = models.CharField(
        max_length=16, choices=DATE_APPLIED_SOURCE_CHOICES, blank=True, null=True
    )
    next_action = models.CharField(max_length=255, blank=True, null=True)
    next_action_date = models.DateField(blank=True, null=True)
    archived = models.BooleanField(default=False)
    snoozed_until = models.DateField(blank=True, null=True)
    # "Reset activity clock" -- takes priority over date_applied/
    # last_activity for the staleness countdown, without rewriting
    # date_applied itself.
    activity_override = models.DateField(blank=True, null=True)

    def __str__(self) -> str:
        return f"Override for {self.application}"


class StatusHistory(models.Model):
    """Append-only log of effective-status transitions for an
    Application. Rows are only ever inserted, never updated -- see
    the source file's append_status_history no-op-on-repeat-save
    behavior, which still applies at the service-layer, not here.
    """

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="status_history"
    )
    status = models.CharField(max_length=16)
    changed_at = models.DateTimeField()
    source = models.CharField(max_length=32, default="manual")

    class Meta:
        verbose_name_plural = "status histories"
        indexes = [
            models.Index(fields=["application", "changed_at"], name="applications_app_changed_idx")
        ]

    def __str__(self) -> str:
        return f"{self.application} -> {self.status} ({self.changed_at})"


class CompanyAlias(models.Model):
    """Maps a raw company/folder name to the canonical display name
    it should be grouped under. Workspace-scoped equivalent of
    company_aliases (`alias TEXT PRIMARY KEY`).
    """

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="company_aliases"
    )
    alias = models.CharField(max_length=255)
    canonical = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "alias"], name="unique_company_alias_per_workspace"
            )
        ]
        verbose_name_plural = "company aliases"

    def __str__(self) -> str:
        return f"{self.alias} -> {self.canonical}"
