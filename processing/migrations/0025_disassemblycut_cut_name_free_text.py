from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("processing", "0024_disassemblycut_source_event"),
    ]

    operations = [
        migrations.AlterField(
            model_name="disassemblycut",
            name="cut_name",
            field=models.CharField(
                max_length=100,
                help_text="Name of the cut (depends on animal type)",
            ),
        ),
    ]
