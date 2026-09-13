"""
core models.

Phase 3 port of hub_settings from overrides_store.py. The source
table is a hardcoded singleton (`id INTEGER PRIMARY KEY CHECK (id =
1)`) because there was only ever one workspace per local install --
exactly the case the migration plan calls out as becoming
OneToOneField(Workspace) in the multi-tenant version.
"""
from django.db import models


class HubSettings(models.Model):
    """Per-workspace settings: role/location used for extraction
    context, plus user-authored edits to the built-in dashboard cards
    and any custom cards/links they've added.
    """

    workspace = models.OneToOneField(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="hub_settings",
    )
    role = models.CharField(max_length=255, blank=True, default="")
    location = models.CharField(max_length=255, blank=True, default="")
    # { [linkName]: {title?, url?} } -- edits to built-in cards.
    custom_links = models.JSONField(default=dict, blank=True)
    # { [categoryId]: [{id, title, url, note}] } -- cards you've added.
    custom_cards = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "hub settings"

    def __str__(self) -> str:
        return f"Settings for {self.workspace}"


class ApplicationRequestIntent(models.Model):
    """Compact synchronous allocation identity, retained until workspace deletion.

    No request bodies or descriptive result snapshots. A null result on a completed
    intent is terminal removal, never permission to allocate again.
    """
    actor = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    workspace = models.ForeignKey("accounts.Workspace", on_delete=models.CASCADE)
    key = models.CharField(max_length=128)
    digest = models.CharField(max_length=64)
    kind = models.CharField(max_length=16)
    completed = models.BooleanField(default=False)
    application = models.ForeignKey("applications.Application", null=True, on_delete=models.SET_NULL)
    result_portable_id = models.UUIDField(null=True)
    challenge_token = models.CharField(max_length=64, blank=True)
    challenge_revision = models.CharField(max_length=64, blank=True)
    challenge_expires_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor", "workspace", "key"], name="unique_application_request_key")]
