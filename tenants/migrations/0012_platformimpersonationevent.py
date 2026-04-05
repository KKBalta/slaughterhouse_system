from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0011_platformimpersonationsession"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformImpersonationEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "mode",
                    models.CharField(
                        choices=[("owner", "Owner"), ("admin", "Admin"), ("god_mode", "God mode")],
                        default="god_mode",
                        max_length=32,
                    ),
                ),
                ("target_user_id", models.PositiveIntegerField()),
                ("target_username", models.CharField(max_length=150)),
                ("target_email", models.EmailField(blank=True, max_length=254)),
                ("target_role", models.CharField(blank=True, max_length=50)),
                ("target_is_superuser", models.BooleanField(default=False)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("ended_reason", models.CharField(blank=True, default="", max_length=32)),
                (
                    "platform_admin",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="impersonation_events",
                        to="tenants.platformadmin",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="impersonation_events",
                        to="tenants.client",
                    ),
                ),
            ],
            options={
                "db_table": "tenants_platform_impersonation_event",
                "indexes": [
                    models.Index(fields=["tenant", "issued_at"], name="tenants_pla_tenant__5a2e21_idx"),
                    models.Index(fields=["platform_admin", "issued_at"], name="tenants_pla_platfor_d2bda8_idx"),
                ],
            },
        ),
    ]
