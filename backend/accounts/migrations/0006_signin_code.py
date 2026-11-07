from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_email_codes'),
    ]

    operations = [
        migrations.CreateModel(
            name='SignInCode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('address', models.EmailField(db_index=True, max_length=254)),
                ('code_hash', models.CharField(max_length=160)),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('used_at', models.DateTimeField(blank=True, null=True)),
            ],
        ),
    ]
