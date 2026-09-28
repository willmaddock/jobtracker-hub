"""Append-only corrections; initial revision zero is derived, never backfilled."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("postings", "0005_retained_posting_items"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(name="RetainedPostingItemCorrection", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("operation_id", models.UUIDField(editable=False)),
            ("revision", models.PositiveBigIntegerField()),
            ("mode", models.CharField(choices=[("associate", "Associate"), ("withdraw", "Withdraw")], max_length=16)),
            ("method", models.CharField(default="explicit_owner", editable=False, max_length=32)),
            ("decision_version", models.PositiveSmallIntegerField(default=1, editable=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("initial_association", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                related_name="corrections", to="postings.retainedpostingitemassociation")),
            ("target_item", models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="association_corrections", to="postings.retainedpostingitem")),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                related_name="posting_item_corrections", to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.AddConstraint(model_name="retainedpostingitemcorrection", constraint=models.UniqueConstraint(
            fields=("initial_association", "operation_id"), name="posting_corr_operation")),
        migrations.AddConstraint(model_name="retainedpostingitemcorrection", constraint=models.UniqueConstraint(
            fields=("initial_association", "revision"), name="posting_corr_revision")),
        migrations.AddConstraint(model_name="retainedpostingitemcorrection", constraint=models.CheckConstraint(
            condition=models.Q(revision__gte=1), name="posting_corr_positive_revision")),
        migrations.AddConstraint(model_name="retainedpostingitemcorrection", constraint=models.CheckConstraint(
            condition=(models.Q(mode="associate", target_item__isnull=False)
                       | models.Q(mode="withdraw", target_item__isnull=True)), name="posting_corr_target")),
        migrations.AddConstraint(model_name="retainedpostingitemcorrection", constraint=models.CheckConstraint(
            condition=models.Q(method="explicit_owner"), name="posting_corr_method")),
        migrations.AddConstraint(model_name="retainedpostingitemcorrection", constraint=models.CheckConstraint(
            condition=models.Q(decision_version=1), name="posting_corr_version")),
    ]
