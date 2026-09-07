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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.owner})"
