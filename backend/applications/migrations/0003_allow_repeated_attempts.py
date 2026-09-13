from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0002_application_portable_identity"),
        ("postings", "0002_posting_application_conversions"),
    ]
    operations = [
        migrations.RemoveConstraint(
            model_name="application", name="unique_application_identity_per_workspace",
        ),
    ]
