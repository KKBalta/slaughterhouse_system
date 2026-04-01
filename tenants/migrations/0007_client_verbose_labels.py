# Generated manually for Client field verbose_name / help_text (labels & admin).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0006_rename_tenants_ema_email_n_7a8b2c_idx_tenants_ema_email_n_0a8f45_idx_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="client",
            name="company_name",
            field=models.CharField(
                blank=True,
                help_text="Short trading name printed on labels.",
                max_length=255,
                verbose_name="Company name (label header)",
            ),
        ),
        migrations.AlterField(
            model_name="client",
            name="company_full_name",
            field=models.CharField(
                blank=True,
                help_text="Full legal title on labels.",
                max_length=255,
                verbose_name="Legal company name",
            ),
        ),
        migrations.AlterField(
            model_name="client",
            name="company_address",
            field=models.CharField(
                blank=True,
                help_text="Address block on labels and reports.",
                max_length=500,
                verbose_name="Company address",
            ),
        ),
        migrations.AlterField(
            model_name="client",
            name="license_no",
            field=models.CharField(
                blank=True,
                help_text="Government approval number; same value as ISLETME ONAY NO on printed labels.",
                max_length=64,
                verbose_name="İşletme onay no",
            ),
        ),
        migrations.AlterField(
            model_name="client",
            name="operation_no",
            field=models.CharField(
                blank=True,
                help_text="Tax office / operation number (e.g. ÇKALE VD line on labels).",
                max_length=64,
                verbose_name="Vergi dairesi / işletme no (VD)",
            ),
        ),
        migrations.AlterField(
            model_name="client",
            name="logo",
            field=models.ImageField(
                blank=True,
                help_text="Optional branding image in the app header.",
                null=True,
                upload_to="tenant_logos/",
                verbose_name="Logo",
            ),
        ),
        migrations.AlterField(
            model_name="client",
            name="contact_email",
            field=models.EmailField(blank=True, max_length=254, verbose_name="Contact email"),
        ),
        migrations.AlterField(
            model_name="client",
            name="contact_phone",
            field=models.CharField(blank=True, max_length=64, verbose_name="Contact phone"),
        ),
        migrations.AlterField(
            model_name="client",
            name="printer_turkish_mode",
            field=models.CharField(
                default="unicode",
                help_text="unicode, ascii, or codepage1254 for label printers.",
                max_length=32,
                verbose_name="Printer Turkish mode",
            ),
        ),
        migrations.AlterField(
            model_name="client",
            name="timezone",
            field=models.CharField(default="Europe/Istanbul", max_length=64, verbose_name="Timezone"),
        ),
        migrations.AlterField(
            model_name="client",
            name="language_code",
            field=models.CharField(default="tr", max_length=16, verbose_name="Language code"),
        ),
    ]
