"""Empty additive item/initial-decision authority; no historical inference."""
import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("postings", "0004_retained_posting_extraction_provenance"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RetainedPostingItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("portable_id", models.UUIDField(default=uuid.uuid4, editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("retained_message", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name="posting_items", to="email_sync.retainedmessage")),
            ],
        ),
        migrations.CreateModel(
            name="RetainedPostingItemAssociation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mode", models.CharField(choices=[("allocate_new", "Allocate new occurrence"),
                    ("attach_existing", "Attach to existing occurrence")], max_length=16)),
                ("method", models.CharField(default="explicit_owner", editable=False, max_length=32)),
                ("decision_version", models.PositiveSmallIntegerField(default=1, editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name="posting_item_associations", to=settings.AUTH_USER_MODEL)),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name="associations", to="postings.retainedpostingitem")),
                ("output", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                    related_name="initial_item_association", to="postings.retainedpostingextractionoutput")),
            ],
        ),
        migrations.AddConstraint(model_name="retainedpostingitem", constraint=models.UniqueConstraint(
            fields=("retained_message", "portable_id"), name="posting_item_portable")),
        migrations.AddConstraint(model_name="retainedpostingitemassociation", constraint=models.CheckConstraint(
            condition=models.Q(mode__in=["allocate_new", "attach_existing"]), name="posting_item_assoc_mode")),
        migrations.AddConstraint(model_name="retainedpostingitemassociation", constraint=models.CheckConstraint(
            condition=models.Q(method="explicit_owner"), name="posting_item_assoc_method")),
        migrations.AddConstraint(model_name="retainedpostingitemassociation", constraint=models.CheckConstraint(
            condition=models.Q(decision_version=1), name="posting_item_assoc_version")),
    ]
