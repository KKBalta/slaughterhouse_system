from django.db import migrations, models


def _apply_slug(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE tenants_client
                    ADD COLUMN IF NOT EXISTS slug varchar(63) NOT NULL DEFAULT '';
                """
            )
            cursor.execute("UPDATE tenants_client SET slug = schema_name WHERE slug = '';")
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS tenants_client_slug_key
                    ON tenants_client (slug);
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS tenants_client_slug_8a691f8f_like
                    ON tenants_client (slug varchar_pattern_ops);
                """
            )
    elif schema_editor.connection.vendor == "sqlite":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE tenants_client ADD COLUMN slug varchar(63) NOT NULL DEFAULT '';"
            )
            cursor.execute("UPDATE tenants_client SET slug = schema_name WHERE slug = '';")
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS tenants_client_slug_key ON tenants_client (slug);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS tenants_client_slug_8a691f8f_like ON tenants_client (slug);"
            )
    else:
        raise NotImplementedError(
            f"Unsupported database for tenants 0002: {schema_editor.connection.vendor}"
        )


def _reverse_slug(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("ALTER TABLE tenants_client DROP COLUMN IF EXISTS slug;")
    elif schema_editor.connection.vendor == "sqlite":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("DROP INDEX IF EXISTS tenants_client_slug_8a691f8f_like;")
            cursor.execute("DROP INDEX IF EXISTS tenants_client_slug_key;")
            cursor.execute("ALTER TABLE tenants_client DROP COLUMN slug;")
    else:
        raise NotImplementedError(
            f"Unsupported database for tenants 0002 reverse: {schema_editor.connection.vendor}"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="client",
                    name="slug",
                    field=models.SlugField(
                        blank=True,
                        help_text="Subdomain identifier; auto-populated from schema_name if left blank",
                        max_length=63,
                        unique=True,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(_apply_slug, _reverse_slug),
            ],
        ),
        migrations.CreateModel(
            name="PlatformAdmin",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("created_on", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "tenants_platform_admin",
                "verbose_name": "Platform Admin",
                "verbose_name_plural": "Platform Admins",
            },
        ),
    ]
