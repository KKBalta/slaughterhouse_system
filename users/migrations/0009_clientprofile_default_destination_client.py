from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0008_walkin_role_and_unclassified_profiles"),
    ]

    operations = [
        migrations.AddField(
            model_name="clientprofile",
            name="default_destination_client",
            field=models.ForeignKey(
                blank=True,
                help_text="Preferred destination client for this client. Used to prefill new orders.",
                null=True,
                on_delete=models.SET_NULL,
                related_name="source_clients",
                to="users.clientprofile",
            ),
        ),
    ]
