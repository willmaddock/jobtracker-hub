"""Workspace-owned email evidence and prospective authentication bindings.

retention.py owns evidence/principal writes; OAuth owns account bindings. Deleting
an EmailAccount removes its binding only, never lineage, principal or evidence.
"""
import uuid

from django.core.exceptions import ValidationError
from django.db import models


class ImmutableEvidence(models.Model):
    """Reject ordinary edits/deletes; internal conflict flags use guarded updates.

QuerySet/raw SQL remain privileged maintenance surfaces, not public writers.
"""
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Retained evidence is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Retained evidence deletion is not implemented.")


class MailboxLineage(ImmutableEvidence):
    workspace = models.ForeignKey("accounts.Workspace", on_delete=models.PROTECT)
    portable_id = models.UUIDField(default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=16)
    # Explicit established evidence, never an email-address-derived identity.
    evidence = models.JSONField()
    established_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "portable_id"], name="retained_mailbox_portable")]


class MailboxPrincipal(ImmutableEvidence):
    """Verified identity extension; old lineages are never guessed into this table."""
    workspace = models.ForeignKey("accounts.Workspace", on_delete=models.PROTECT)
    mailbox = models.OneToOneField(MailboxLineage, on_delete=models.PROTECT, related_name="principal")
    provider = models.CharField(max_length=16)
    namespace = models.CharField(max_length=64)
    value = models.CharField(max_length=255)
    verified_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["workspace", "provider", "namespace", "value"], name="mailbox_verified_principal")]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Verified mailbox identity is immutable.")
        if self.mailbox.workspace_id != self.workspace_id or self.mailbox.provider != self.provider:
            raise ValidationError("Mailbox principal scope mismatch.")
        return super().save(*args, **kwargs)


class AccountMailboxBinding(ImmutableEvidence):
    """Prospective connection link, never evidence about historical account messages.

    Account deletion removes only this link. The durable principal/lineage survives.
    """
    account = models.OneToOneField("email_sync.EmailAccount", on_delete=models.CASCADE, related_name="mailbox_binding")
    mailbox = models.OneToOneField(MailboxLineage, on_delete=models.PROTECT, related_name="account_binding")
    bound_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Verified account binding is immutable.")
        if self.account.workspace_id != self.mailbox.workspace_id or self.account.provider != self.mailbox.provider:
            raise ValidationError("Account mailbox scope mismatch.")
        return super().save(*args, **kwargs)


class RetainedMessage(ImmutableEvidence):
    workspace = models.ForeignKey("accounts.Workspace", on_delete=models.PROTECT)
    portable_id = models.UUIDField(default=uuid.uuid4, editable=False)
    mailbox = models.ForeignKey(MailboxLineage, on_delete=models.PROTECT)
    provider = models.CharField(max_length=16)
    locator_kind = models.CharField(max_length=32)
    locator_value = models.CharField(max_length=512)
    folder = models.CharField(max_length=512, blank=True)
    stability = models.CharField(max_length=128)
    representation_version = models.PositiveSmallIntegerField(default=1, editable=False)
    content = models.JSONField()
    content_digest = models.CharField(max_length=64)
    has_conflict = models.BooleanField(default=False, editable=False)
    retained_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "portable_id"], name="retained_message_portable"),
            models.UniqueConstraint(fields=["workspace", "mailbox", "provider", "locator_kind", "locator_value", "folder", "stability"], name="retained_source_namespace"),
        ]


class RetentionKey(ImmutableEvidence):
    workspace = models.ForeignKey("accounts.Workspace", on_delete=models.PROTECT)
    key = models.CharField(max_length=128)
    initial_digest = models.CharField(max_length=64)
    has_conflict = models.BooleanField(default=False, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "key"], name="retained_observation_key")]


class RetainedObservation(ImmutableEvidence):
    workspace = models.ForeignKey("accounts.Workspace", on_delete=models.PROTECT)
    key = models.ForeignKey(RetentionKey, on_delete=models.PROTECT, related_name="observations")
    message = models.ForeignKey(RetainedMessage, null=True, on_delete=models.PROTECT, related_name="observations")
    mailbox = models.ForeignKey(MailboxLineage, null=True, on_delete=models.PROTECT)
    digest = models.CharField(max_length=64)
    payload = models.JSONField()
    state = models.CharField(max_length=16, choices=[("retained", "Retained"), ("unresolved", "Unresolved"), ("conflict", "Conflict")])
    conflict_reason = models.CharField(max_length=32, blank=True)
    observed_at = models.DateTimeField()
    retained_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["key", "digest"], name="retained_observation_variant")]
