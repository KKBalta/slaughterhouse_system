# Generated manually for unique_active_session_per_device constraint

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("scales", "0002_edgeactivitylog"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="disassemblysession",
            constraint=models.UniqueConstraint(
                condition=Q(
                    device__isnull=False,
                    status__in=["pending", "active", "paused"],
                    is_active=True,
                ),
                fields=("device",),
                name="unique_active_session_per_device",
            ),
        ),
    ]
