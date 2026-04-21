from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0017_rename_tenants_edg_dev_tenant_idx_tenants_edg_tenant__d864ad_idx"),
    ]

    operations = [
        migrations.AlterField(
            model_name="platformimpersonationevent",
            name="mode",
            field=models.CharField(
                choices=[
                    ("owner", "Owner"),
                    ("admin", "Admin"),
                    ("manager", "Manager"),
                    ("operator", "Operator"),
                    ("client", "Client"),
                    ("walkin", "Walk-in"),
                    ("god_mode", "God mode"),
                ],
                default="god_mode",
                max_length=32,
            ),
        ),
    ]
