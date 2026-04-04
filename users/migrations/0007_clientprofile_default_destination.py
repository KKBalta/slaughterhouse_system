from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0006_alter_user_managers_user_uniq_user_phone_nonempty"),
    ]

    operations = [
        migrations.AddField(
            model_name="clientprofile",
            name="default_destination",
            field=models.CharField(
                blank=True,
                help_text="Preferred delivery destination for this client. Used to prefill new orders.",
                max_length=255,
                null=True,
            ),
        ),
    ]
