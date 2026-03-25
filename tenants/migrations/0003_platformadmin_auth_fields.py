from django.contrib.auth.hashers import make_password
from django.db import migrations, models


def _set_unusable_password_where_empty(apps, schema_editor):
    PlatformAdmin = apps.get_model("tenants", "PlatformAdmin")
    for row in PlatformAdmin.objects.filter(password__in=["", None]):
        row.password = make_password(None)
        row.save(update_fields=["password"])


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0002_client_slug_platformadmin"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformadmin",
            name="last_login",
            field=models.DateTimeField(blank=True, null=True, verbose_name="last login"),
        ),
        migrations.AddField(
            model_name="platformadmin",
            name="password",
            field=models.CharField(default="", max_length=128, verbose_name="password"),
            preserve_default=False,
        ),
        migrations.RunPython(_set_unusable_password_where_empty, migrations.RunPython.noop),
    ]
