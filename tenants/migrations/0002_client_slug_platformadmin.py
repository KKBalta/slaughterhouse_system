from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0001_initial"),
    ]

    operations = [
        # Use SeparateDatabaseAndState so Django's migration state tracks the slug
        # field correctly, while raw SQL handles the actual DDL. This avoids a
        # double-deferred-index bug in Django's PostgreSQL SchemaEditor for
        # SlugField(unique=True) when split across AddField + AlterField.
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
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE tenants_client
                            ADD COLUMN IF NOT EXISTS slug varchar(63) NOT NULL DEFAULT '';
                        UPDATE tenants_client SET slug = schema_name WHERE slug = '';
                        CREATE UNIQUE INDEX IF NOT EXISTS tenants_client_slug_key
                            ON tenants_client (slug);
                        CREATE INDEX IF NOT EXISTS tenants_client_slug_8a691f8f_like
                            ON tenants_client (slug varchar_pattern_ops);
                    """,
                    reverse_sql="ALTER TABLE tenants_client DROP COLUMN IF EXISTS slug;",
                ),
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
