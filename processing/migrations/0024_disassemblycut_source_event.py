import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("processing", "0023_add_disassemblycut_session"),
        ("scales", "0009_rename_scales_weig_assigne_idx_scales_weig_assigne_164d71_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="disassemblycut",
            name="source_event",
            field=models.ForeignKey(
                blank=True,
                help_text="Scale event that generated this cut (if auto-synced from scales).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="derived_disassembly_cuts",
                to="scales.weighingevent",
            ),
        ),
    ]
