import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0009_retained_application_review_disposition"),
        ("core", "0004_applicationrequestintent_category"),
    ]
    operations = [migrations.CreateModel(
        name="RetainedReviewCreationResult",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("snapshot_version", models.PositiveSmallIntegerField(default=1, editable=False)),
            ("input_snapshot", models.JSONField(editable=False)),
            ("review", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                related_name="creation_results", to="applications.retainedapplicationreview")),
            ("request_intent", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                related_name="review_creation_result", to="core.applicationrequestintent")),
            ("candidate", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                to="applications.retainedapplicationreviewcandidate")),
            ("application_message", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                related_name="review_creation_result", to="applications.applicationmessage")),
        ],
        options={"constraints": [models.CheckConstraint(condition=models.Q(snapshot_version=1),
                                                       name="review_creation_snapshot_version")]},
    )]
