# Backfill DisassemblySession.animals from session.animal

from django.db import migrations


def backfill_session_animals(apps, schema_editor):
    DisassemblySession = apps.get_model("scales", "DisassemblySession")
    for session in DisassemblySession.objects.filter(animal_id__isnull=False):
        if not session.animals.filter(pk=session.animal_id).exists():
            session.animals.add(session.animal_id)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('scales', '0007_multi_animal_and_allocation'),
    ]

    operations = [
        migrations.RunPython(backfill_session_animals, noop_reverse),
    ]
