from django.db import migrations, models
import uuid


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [migrations.CreateModel(
        name='GatewaySessionLineage',
        fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('generation', models.PositiveBigIntegerField(default=0)),
            ('session_key', models.CharField(max_length=40, unique=True, null=True, editable=False)),
            ('expires_at', models.DateTimeField(db_index=True)),
        ],
    )]
