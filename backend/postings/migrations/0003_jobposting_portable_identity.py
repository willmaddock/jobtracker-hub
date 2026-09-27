"""Allocate portable identity only; reversing schema discards those identities."""
import uuid

from django.db import migrations, models


def backfill_portable_ids(apps, schema_editor):
    JobPosting = apps.get_model("postings", "JobPosting")
    rows = JobPosting.objects.using(schema_editor.connection.alias)
    for pk in rows.filter(portable_id__isnull=True).values_list("pk", flat=True).iterator():
        rows.filter(pk=pk, portable_id__isnull=True).update(portable_id=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [("postings", "0002_posting_application_conversions")]

    operations = [
        migrations.AddField(
            model_name="jobposting", name="portable_id",
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(backfill_portable_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="jobposting", name="portable_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddConstraint(
            model_name="jobposting",
            constraint=models.UniqueConstraint(fields=("workspace", "portable_id"),
                                               name="unique_posting_portable_per_ws"),
        ),
    ]
