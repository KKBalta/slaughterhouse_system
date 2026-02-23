import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("scales", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="EdgeActivityLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("updated_at", models.DateTimeField(auto_now=True, editable=False)),
                ("is_active", models.BooleanField(default=True)),
                ("level", models.CharField(choices=[("info", "Info"), ("warning", "Warning"), ("error", "Error")], default="info", max_length=20)),
                ("action", models.CharField(max_length=50)),
                ("message", models.CharField(max_length=255)),
                ("request_path", models.CharField(blank=True, max_length=255)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("device", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="activity_logs", to="scales.scaledevice")),
                ("edge", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="activity_logs", to="scales.edgedevice")),
                ("site", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="edge_activity_logs", to="scales.site")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="edgeactivitylog",
            index=models.Index(fields=["site", "-created_at"], name="scales_edge_site_id_269e63_idx"),
        ),
        migrations.AddIndex(
            model_name="edgeactivitylog",
            index=models.Index(fields=["edge", "-created_at"], name="scales_edge_edge_id_fe405e_idx"),
        ),
        migrations.AddIndex(
            model_name="edgeactivitylog",
            index=models.Index(fields=["action"], name="scales_edge_action_7340f0_idx"),
        ),
        migrations.AddIndex(
            model_name="edgeactivitylog",
            index=models.Index(fields=["level"], name="scales_edge_level_45d19d_idx"),
        ),
    ]
