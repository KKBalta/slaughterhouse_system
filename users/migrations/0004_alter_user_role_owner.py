# Generated manually for Role.OWNER

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_alter_clientprofile_user_alter_user_role"),
    ]

    operations = [
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
                ],
                max_length=50,
            ),
        ),
    ]
