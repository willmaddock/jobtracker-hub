"""Retained direct state; unfiltered managers preserve identity/replay lookups."""
from django.db import models


class LifecycleQuerySet(models.QuerySet):
    def live(self):
        return self.filter(trashed_at__isnull=True)


class DocumentQuerySet(LifecycleQuerySet):
    def live(self):
        return super().live().filter(application__trashed_at__isnull=True)


class RetainedLifecycle(models.Model):
    trashed_at = models.DateTimeField(null=True, blank=True, editable=False)
    lifecycle_revision = models.PositiveBigIntegerField(default=0, editable=False)
    objects = LifecycleQuerySet.as_manager()

    class Meta:
        abstract = True

    @property
    def is_trashed(self):
        return self.trashed_at is not None

    @property
    def effective_trashed(self):
        return self.is_trashed
