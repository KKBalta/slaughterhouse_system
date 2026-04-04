from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0007_clientprofile_default_destination"),
    ]

    operations = [
        migrations.AlterField(
            model_name="clientprofile",
            name="account_type",
            field=models.CharField(
                choices=[
                    ("UNCLASSIFIED", "Unclassified"),
                    ("INDIVIDUAL", "Individual"),
                    ("ENTERPRISE", "Enterprise"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="clientprofile",
            name="address",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("OWNER", "Owner"),
                    ("ADMIN", "Admin"),
                    ("MANAGER", "Manager"),
                    ("OPERATOR", "Operator"),
                    ("CLIENT", "Client"),
                    ("WALKIN", "Walk-in"),
                ],
                max_length=50,
            ),
        ),
    ]
