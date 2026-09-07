# Generated manually to match `python manage.py makemigrations core` output.
# Run `python manage.py makemigrations --check core` after installing
# dependencies to confirm this matches what Django itself would generate.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='hubsettings',
            name='role',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AlterField(
            model_name='hubsettings',
            name='location',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
