"""Add live defaults without inventing history; protect retained ownership."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('applications', '0004_application_category_revision'), ('accounts', '0001_initial')]

    operations = [
        migrations.AddField("application", "trashed_at", models.DateTimeField(null=True, blank=True, editable=False)),
        migrations.AddField("application", "lifecycle_revision", models.PositiveBigIntegerField(default=0, editable=False)),
        migrations.AlterField("application", "workspace", models.ForeignKey(to="accounts.workspace", on_delete=models.PROTECT, related_name="applications")),
    ]
