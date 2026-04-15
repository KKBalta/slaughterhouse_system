"""Fail print jobs stuck in dispatched state (e.g. edge lost after ACK)."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from labeling.models import PrintJob
from scales.api_views import _bump_edge_print_jobs_version


class Command(BaseCommand):
    help = "Mark dispatched print jobs as failed when they have not progressed for N minutes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes",
            type=int,
            default=30,
            help="Jobs in dispatched status older than this are failed (default: 30).",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=options["minutes"])
        qs = PrintJob.objects.filter(status="dispatched", updated_at__lt=cutoff)
        site_ids = set(qs.values_list("site_id", flat=True))
        n = qs.update(
            status="failed",
            error_text="Auto-failed: stuck in dispatched state.",
            updated_at=timezone.now(),
        )
        for sid in site_ids:
            if sid is not None:
                _bump_edge_print_jobs_version(sid)
        self.stdout.write(self.style.SUCCESS(f"Failed {n} stale dispatched job(s)."))
