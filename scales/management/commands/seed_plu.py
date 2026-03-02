"""
Seed PLUItem from embedded catalog (scales.plu_catalog) or optional --file.
Format: PLU_CODE NAME per line. Category is auto-derived from product name prefix.
"""

from pathlib import Path

from django.core.management.base import BaseCommand

from scales.models import PLUItem, Site
from scales.plu_catalog import PLU_CATALOG


def derive_category(name):
    """Derive category from product name (Turkish)."""
    n = (name or "").strip().upper()
    if n.startswith("DANA") or n.startswith("SIĞIR") or n.startswith("SIGIR") or n.startswith("DÜVE"):
        return "Dana"
    if n.startswith("KUZU"):
        return "Kuzu"
    if n.startswith("KOYUN"):
        return "Koyun"
    if n.startswith("OĞLAK") or n.startswith("OGLAK"):
        return "Oglak"
    return "Genel"


class Command(BaseCommand):
    help = "Seed PLUItem from embedded catalog. Use --file to load from external file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=None,
            help="Path to external PLU file (overrides embedded catalog)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing PLU items for the default site before seeding.",
        )

    def handle(self, *args, **options):
        file_path = options.get("file")
        if file_path:
            file_path = Path(file_path)
            if not file_path.exists():
                self.stderr.write(self.style.ERROR(f"File not found: {file_path}"))
                return
            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()
        else:
            lines = PLU_CATALOG.splitlines()

        site, _ = Site.objects.get_or_create(
            name="Default",
            defaults={"address": ""},
        )

        if options.get("clear"):
            deleted, _ = PLUItem.objects.filter(site=site).delete()
            self.stdout.write(self.style.WARNING(f"Cleared {deleted} existing PLU items."))

        created = 0
        updated = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            plu_code = parts[0].strip()
            name = parts[1].strip()
            category = derive_category(name)
            name_turkish = (name[:16]).strip()

            obj, created_flag = PLUItem.objects.update_or_create(
                site=site,
                plu_code=plu_code,
                defaults={
                    "name": name,
                    "name_turkish": name_turkish,
                    "barcode": plu_code,
                    "category": category,
                    "is_active": True,
                },
            )
            if created_flag:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"PLU seed done: {created} created, {updated} updated."))
