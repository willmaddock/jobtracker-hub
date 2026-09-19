"""Add live defaults without inventing history; protect retained ownership."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('documents', '0004_backfill_synthetic_categories'), ('accounts', '0001_initial'), ('applications', '0005_retained_lifecycle')]

    operations = [
        migrations.AddField("category", "trashed_at", models.DateTimeField(null=True, blank=True, editable=False)),
        migrations.AddField("category", "lifecycle_revision", models.PositiveBigIntegerField(default=0, editable=False)),
        migrations.AlterField("category", "workspace", models.ForeignKey(to="accounts.workspace", on_delete=models.PROTECT, related_name="categories")),
        migrations.AddField("document", "trashed_at", models.DateTimeField(null=True, blank=True, editable=False)),
        migrations.AddField("document", "lifecycle_revision", models.PositiveBigIntegerField(default=0, editable=False)),
        migrations.AlterField("document", "workspace", models.ForeignKey(to="accounts.workspace", on_delete=models.PROTECT, related_name="documents")),
        migrations.AlterField("document", "application", models.ForeignKey(to="applications.application", on_delete=models.PROTECT, related_name="documents")),
    ]
