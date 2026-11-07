"""
accounts models.

User and Workspace are deliberately the very first models in this
migration -- see docs/DJANGO_MIGRATION_PLAN.md, Phase 2. Every other
model added in later phases (JobPosting, Application, Document, ...)
gets a `workspace` FK from the moment it's created, so ownership never
needs to be retrofitted onto live data.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model, in place before the first migration.

    No extra fields yet -- this exists so AUTH_USER_MODEL points at an
    app we own from day one, rather than django.contrib.auth.User,
    which is effectively impossible to swap out later without a data
    migration nightmare.
    """
    pass


class Workspace(models.Model):
    """
    Replaces the current app's "which JobTracker folder am I pointed
    at" concept. In the local single-user app this was a literal path
    on disk (see _app/db.py DEFAULT_ROOT); here it's a row owned by a
    User, and everything else (postings, applications, documents,
    email accounts) will hang off this via FK in later phases.
    """
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="workspaces"
    )
    name = models.CharField(max_length=255)
    calendar_timezone = models.CharField(max_length=64, default="UTC", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.owner})"


class MfaDevice(models.Model):
    """A user's authenticator-app (TOTP) enrolment. See docs/MFA_DESIGN.md.

    The secret is stored only as a Fernet token (accounts.mfa handles encryption). It is
    never returned by any API after enrolment starts, and is not shown in the admin.
    ``confirmed_at`` stays null until the user proves their app works with a first code.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="mfa_device")
    secret_encrypted = models.TextField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_step = models.BigIntegerField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"MFA for {self.user_id} ({'confirmed' if self.confirmed_at else 'pending'})"


class MfaRecoveryCode(models.Model):
    """One single-use recovery code, stored only as a salted hash."""
    device = models.ForeignKey(MfaDevice, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=255)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
