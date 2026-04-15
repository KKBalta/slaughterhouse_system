import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("labeling", "0007_printjob_edge_dispatch"),
        ("scales", "0011_add_edge_setup_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="printjob",
            name="claimed_by_edge",
            field=models.ForeignKey(
                blank=True,
                help_text="Edge that first ACK'd this job as dispatched (worker claim).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="claimed_print_jobs",
                to="scales.edgedevice",
            ),
        ),
    ]
