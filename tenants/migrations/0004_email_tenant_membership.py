# Generated manually for EmailTenantMembership public index.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0003_platformadmin_auth_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailTenantMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email_normalized", models.CharField(db_index=True, max_length=254)),
                ("tenant_user_id", models.PositiveIntegerField(help_text="Primary key of users.User in the tenant schema (for stable upserts).")),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="email_memberships",
                        to="tenants.client",
                    ),
                ),
            ],
            options={
                "db_table": "tenants_email_tenant_membership",
            },
        ),
        migrations.AddConstraint(
            model_name="emailtenantmembership",
            constraint=models.UniqueConstraint(
                fields=("tenant", "tenant_user_id"),
                name="uniq_email_membership_tenant_user",
            ),
        ),
        migrations.AddIndex(
            model_name="emailtenantmembership",
            index=models.Index(fields=["email_normalized"], name="tenants_ema_email_n_7a8b2c_idx"),
        ),
    ]
