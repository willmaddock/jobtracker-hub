"""Initial explicit mappings only. No inferred historical relationships."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("postings", "0006_retained_posting_item_corrections"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(name="PostingSource", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("method", models.CharField(default="explicit_owner", editable=False, max_length=32)),
            ("decision_version", models.PositiveSmallIntegerField(default=1, editable=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("item", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                related_name="initial_posting_source", to="postings.retainedpostingitem")),
            ("posting", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                related_name="initial_posting_sources", to="postings.jobposting")),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                related_name="posting_source_assertions", to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.AddConstraint(model_name="postingsource", constraint=models.CheckConstraint(
            condition=models.Q(method="explicit_owner"), name="posting_source_method")),
        migrations.AddConstraint(model_name="postingsource", constraint=models.CheckConstraint(
            condition=models.Q(decision_version=1), name="posting_source_version")),
    ]
