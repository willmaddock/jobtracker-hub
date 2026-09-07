"""
email_sync models.

Phase 3 slice of the accounts/discoveries/sync cluster from
overrides_store.py. Per docs/DJANGO_MIGRATION_PLAN.md's Phase 0
inventory note: this cluster's *shape* (Mail.app-only, AppleScript-
driven) is entirely a Phase 9 rewrite target -- OAuth providers
replace "is Mail.app available" -- so nothing here should be read as
the final DRF/provider design. This is a like-for-like model port so
Override/StatusHistory/Discovery/JobPosting all have real FKs from
day one, not a preview of the Phase 9 sync design.

Named EmailAccount (not Account) to avoid colliding with the
`accounts` Django app from Phase 1+2.
"""
from django.db import models

from applications.models import Application


class EmailAccount(models.Model):
    """A connected mailbox. Currently always Mail.app (provider is
    always 'mail_app'; older rows could say gmail/outlook/icloud/imap
    from before this app went macOS-only -- see overrides_store.
    _migrate()). No credentials of any kind are ever stored here,
    same as the source table.
    """

    PROVIDER_CHOICES = [
        ("mail_app", "Mail.app"),
        ("gmail", "Gmail (legacy)"),
        ("outlook", "Outlook (legacy)"),
        ("icloud", "iCloud (legacy)"),
        ("imap", "IMAP (legacy)"),
    ]
    STATUS_CHOICES = [
        ("connected", "Connected"),
        ("blocked", "Blocked"),
        ("disconnected", "Disconnected"),
    ]

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="email_accounts"
    )
    provider = models.CharField(
        max_length=16, choices=PROVIDER_CHOICES, default="mail_app"
    )
    email = models.EmailField()
    # Mail.app's own account name (what mail_app_store.search_messages
    # queries by) -- may differ from `email`.
    account_name = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="connected")
    last_synced_at = models.DateTimeField(blank=True, null=True)
    matched_email_count = models.PositiveIntegerField(default=0)
    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.account_name or self.email


class AccountMatch(models.Model):
    """One email matched to an Application, so the dossier/timeline
    can cite "via which account" without re-fetching the inbox. Only
    extracted text/metadata is ever stored, never the raw message.
    """

    account = models.ForeignKey(
        EmailAccount, on_delete=models.CASCADE, related_name="matches"
    )
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="account_matches"
    )
    message_id = models.CharField(max_length=512)
    subject = models.CharField(max_length=998, blank=True, null=True)
    received_at = models.DateTimeField(blank=True, null=True)
    matched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "message_id"], name="unique_account_match_message"
            )
        ]
        indexes = [models.Index(fields=["application"], name="email_sync_match_app_idx")]
        verbose_name_plural = "account matches"

    def __str__(self) -> str:
        return f"{self.subject or self.message_id} -> {self.application}"


class Discovery(models.Model):
    """Review-queue row for "possible new applications" -- a message
    that looks application-related but doesn't match any tracked
    Application yet. Nothing becomes a real Application (or an
    AccountMatch) until the user explicitly accepts it. Replaces
    discovered_matches.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("dismissed", "Dismissed"),
    ]
    # match_kind: matching *confidence* -- does this clearly belong to
    # one Application, or could it be several?
    MATCH_KIND_CHOICES = [
        ("unmatched", "Unmatched"),
        ("ambiguous", "Ambiguous"),
    ]
    # kind: what the email itself *is*, orthogonal to match_kind.
    KIND_CHOICES = [
        ("application", "Application"),
        ("posting", "Posting"),
    ]

    account = models.ForeignKey(
        EmailAccount, on_delete=models.CASCADE, related_name="discoveries"
    )
    message_id = models.CharField(max_length=512)
    subject = models.CharField(max_length=998, blank=True, null=True)
    sender = models.CharField(max_length=255, blank=True, null=True)
    received_at = models.DateTimeField(blank=True, null=True)
    guessed_company = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    match_kind = models.CharField(
        max_length=16, choices=MATCH_KIND_CHOICES, default="unmatched"
    )
    # Ambiguous-only: candidate Applications sharing the guessed
    # company, offered as the /attach picker options. A real M2M now,
    # replacing the old JSON-encoded item_key list.
    candidate_applications = models.ManyToManyField(
        Application, blank=True, related_name="candidate_discoveries"
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default="application")
    # Populated lazily on preview, same as posting_urls below.
    posting_url = models.URLField(max_length=2048, blank=True, null=True)
    # Every job-board/listing URL found in the message body, for
    # digest emails bundling several postings in one message.
    # posting_url mirrors posting_urls[0] for backward compat.
    posting_urls = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name_plural = "discoveries"
        constraints = [
            models.UniqueConstraint(
                fields=["account", "message_id"], name="unique_discovery_message"
            )
        ]
        indexes = [models.Index(fields=["status"], name="email_sync_disc_status_idx")]

    def __str__(self) -> str:
        return self.subject or self.message_id


class JobPostingSender(models.Model):
    """Senders explicitly taught to always be treated as job-posting
    mail, regardless of subject phrasing -- the escape hatch for
    digest senders whose subject shape the heuristics don't recognize.
    Matched with `contains` at read time, not by domain, so a real
    person at the same domain (e.g. a recruiter @linkedin.com) is
    never swept in.
    """

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="job_posting_senders"
    )
    sender = models.CharField(max_length=255)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "sender"], name="unique_job_posting_sender_per_workspace"
            )
        ]

    def __str__(self) -> str:
        return self.sender


class ThreadIdentifier(models.Model):
    """Every Message-ID known to belong to an Application's email
    thread -- both confirmed matches and any Message-ID their In-
    Reply-To/References headers cited. Purely additive: rows are only
    ever inserted, never removed except via the Application's own
    deletion cascade.
    """

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="thread_identifiers"
    )
    message_id = models.CharField(max_length=512)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "message_id"], name="unique_thread_identifier"
            )
        ]

    def __str__(self) -> str:
        return f"{self.application} <{self.message_id}>"
