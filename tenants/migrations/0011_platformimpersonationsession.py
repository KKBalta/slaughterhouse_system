from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0010_logo_public_storage"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformImpersonationSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_user_id", models.PositiveIntegerField()),
                ("target_username", models.CharField(max_length=150)),
                ("target_email", models.EmailField(blank=True, max_length=254)),
                ("target_role", models.CharField(blank=True, max_length=50)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                (
                    "destination",
                    models.CharField(
                        choices=[("dashboard", "Dashboard"), ("django_admin", "Django admin")],
                        default="dashboard",
                        max_length=32,
                    ),
                ),
                ("created_from_ip", models.CharField(blank=True, max_length=64)),
                ("consumed_host", models.CharField(blank=True, max_length=255)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("stopped_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "platform_admin",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="impersonation_sessions",
                        to="tenants.platformadmin",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="platform_impersonation_sessions",
                        to="tenants.client",
                    ),
                ),
            ],
            options={
                "db_table": "tenants_platform_impersonation_session",
                "indexes": [
                    models.Index(fields=["tenant", "created_at"], name="tenants_pla_tenant__39a4ec_idx"),
                    models.Index(
                        fields=["platform_admin", "created_at"], name="tenants_pla_platfor_39254e_idx"
                    ),
                    models.Index(fields=["expires_at"], name="tenants_pla_expires_ba2ae7_idx"),
                ],
            },
        ),
    ]
