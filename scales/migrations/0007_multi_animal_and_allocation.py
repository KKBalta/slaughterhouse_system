# Generated for multi-animal scale sessions and event allocation

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scales', '0006_weighingevent_deleted_at_deleted_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='disassemblysession',
            name='animals',
            field=models.ManyToManyField(
                blank=True,
                help_text='All animals in this session (multi-animal scaling).',
                related_name='disassembly_session_animals',
                to='processing.animal',
            ),
        ),
        migrations.AddField(
            model_name='weighingevent',
            name='allocation_mode',
            field=models.CharField(
                choices=[('split', 'Split'), ('manual', 'Manual')],
                default='split',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='weighingevent',
            name='allocated_weight_grams',
            field=models.IntegerField(blank=True, help_text='Cached weight allocated to assigned_animal for display.', null=True),
        ),
        migrations.AddField(
            model_name='weighingevent',
            name='assigned_animal',
            field=models.ForeignKey(
                blank=True,
                help_text='When set (manual mode), this event is fully allocated to this animal.',
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name='weighing_events_assigned',
                to='processing.animal',
            ),
        ),
        migrations.AddIndex(
            model_name='weighingevent',
            index=models.Index(fields=['assigned_animal'], name='scales_weig_assigne_idx'),
        ),
    ]
