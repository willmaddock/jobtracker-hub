import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_mfa'),
    ]

    operations = [
        migrations.CreateModel(
            name='PasskeyCredential',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('credential_id', models.CharField(max_length=512, unique=True)),
                ('public_key', models.BinaryField()),
                ('sign_count', models.PositiveBigIntegerField(default=0)),
                ('name', models.CharField(max_length=80)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('device', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='passkeys', to='accounts.mfadevice')),
            ],
        ),
    ]
