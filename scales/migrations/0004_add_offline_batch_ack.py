# Generated for OfflineBatchAck model (offline batch ACK idempotency)

import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("scales", "0003_unique_active_session_per_device"),
    ]

    operations = [
        migrations.CreateModel(
            name="OfflineBatchAck",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("updated_at", models.DateTimeField(auto_now=True, editable=False)),
                ("is_active", models.BooleanField(default=True)),
                ("batch_id", models.CharField(db_index=True, max_length=100, unique=True)),
                ("received_at", models.DateTimeField()),
                ("device_id", models.CharField(blank=True, max_length=50)),
                ("event_count", models.IntegerField(blank=True, null=True)),
                ("total_weight_grams", models.IntegerField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("edge", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="batch_acks", to="scales.edgedevice")),
                ("site", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="batch_acks", to="scales.site")),
            ],
            options={
                "ordering": ["-received_at"],
            },
        ),
    ]
