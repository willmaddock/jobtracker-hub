"""Gateway-only authentication coordination; never an authentication credential."""
import uuid
from django.db import models


class GatewaySessionLineage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    generation = models.PositiveBigIntegerField(default=0)
    session_key = models.CharField(max_length=40, unique=True, null=True, editable=False)
    expires_at = models.DateTimeField(db_index=True)
