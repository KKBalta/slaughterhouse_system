# Generated manually for EdgeDeviceIndex (public schema).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0015_edge_setup_code_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="EdgeDeviceIndex",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "edge_id",
                    models.UUIDField(
                        db_index=True,
                        help_text="EdgeDevice.id from the tenant schema.",
                        unique=True,
                    ),
                ),
                (
                    "tenant_schema",
                    models.CharField(
                        help_text="Cached schema_name for fast lookup without JOIN.",
                        max_length=63,
                    ),
                ),
                ("edge_name", models.CharField(blank=True, default="", max_length=200)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="edge_device_index_entries",
                        to="tenants.client",
                    ),
                ),
            ],
            options={
                "db_table": "tenants_edge_device_index",
                "indexes": [
                    models.Index(fields=["tenant", "-created_at"], name="tenants_edg_dev_tenant_idx"),
                ],
            },
        ),
    ]
