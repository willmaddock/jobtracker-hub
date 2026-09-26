import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0008_retained_application_review"),
    ]

    operations = [
        migrations.CreateModel(
            name="RetainedApplicationReviewDisposition",
            fields=[
                ("review", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    primary_key=True, related_name="disposition", serialize=False,
                    to="applications.retainedapplicationreview")),
                ("dismissed_at", models.DateTimeField(
                    blank=True, default=None, editable=False, null=True)),
                ("revision", models.PositiveBigIntegerField(default=0, editable=False)),
            ],
        ),
    ]
