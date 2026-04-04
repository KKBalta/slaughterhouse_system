from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0009_clientprofile_default_destination_client"),
        ("reception", "0006_rename_order_date_to_order_datetime"),
    ]

    operations = [
        migrations.AddField(
            model_name="slaughterorder",
            name="destination_client",
            field=models.ForeignKey(
                blank=True,
                help_text="Destination client selected for this order.",
                null=True,
                on_delete=models.SET_NULL,
                related_name="destination_orders",
                to="users.clientprofile",
            ),
        ),
    ]
