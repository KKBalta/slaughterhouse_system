# Generated manually for Turkish labels on ServicePackage.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicepackage",
            name="name_tr",
            field=models.CharField(
                blank=True,
                help_text="Turkish display name (optional). Used when the active language is Turkish.",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="servicepackage",
            name="description_tr",
            field=models.TextField(blank=True, help_text="Turkish description (optional)."),
        ),
    ]
