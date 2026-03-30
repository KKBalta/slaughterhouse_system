"""
Backfill public EmailTenantMembership from all tenant schemas.
Run: python manage.py backfill_email_tenant_membership
(use migrate_schemas --shared first if model is new)
"""

from django.core.management.base import BaseCommand

from tenants.email_index import backfill_all_tenants


class Command(BaseCommand):
    help = "Scan tenant user tables and upsert public email -> tenant index rows."

    def handle(self, *args, **options):
        tenants_n, rows = backfill_all_tenants()
        self.stdout.write(self.style.SUCCESS(f"Processed {tenants_n} tenant(s), upserted {rows} membership row(s)."))
