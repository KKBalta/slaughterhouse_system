from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0012_platformimpersonationevent"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="platformimpersonationevent",
            old_name="tenants_pla_tenant__5a2e21_idx",
            new_name="tenants_pla_tenant__f18a28_idx",
        ),
        migrations.RenameIndex(
            model_name="platformimpersonationevent",
            old_name="tenants_pla_platfor_d2bda8_idx",
            new_name="tenants_pla_platfor_b44b84_idx",
        ),
        migrations.RenameIndex(
            model_name="platformimpersonationsession",
            old_name="tenants_pla_tenant__39a4ec_idx",
            new_name="tenants_pla_tenant__506637_idx",
        ),
        migrations.RenameIndex(
            model_name="platformimpersonationsession",
            old_name="tenants_pla_platfor_39254e_idx",
            new_name="tenants_pla_platfor_0733a5_idx",
        ),
        migrations.RenameIndex(
            model_name="platformimpersonationsession",
            old_name="tenants_pla_expires_ba2ae7_idx",
            new_name="tenants_pla_expires_bfcf56_idx",
        ),
    ]
