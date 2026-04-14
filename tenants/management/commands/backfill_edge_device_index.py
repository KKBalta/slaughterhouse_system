from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context

from tenants.models import EdgeDeviceIndex


class Command(BaseCommand):
    help = "Backfill EdgeDeviceIndex from all tenant EdgeDevice rows."

    def handle(self, *args, **options):
        TenantModel = get_tenant_model()
        tenants = TenantModel.objects.exclude(schema_name=get_public_schema_name())
        created_count = 0
        updated_count = 0

        for tenant in tenants:
            with schema_context(tenant.schema_name):
                from scales.models import EdgeDevice

                for edge in EdgeDevice.objects.all():
                    with schema_context(get_public_schema_name()):
                        _, created = EdgeDeviceIndex.objects.update_or_create(
                            edge_id=edge.id,
                            defaults={
                                "tenant": tenant,
                                "tenant_schema": tenant.schema_name,
                                "edge_name": edge.name or "",
                                "is_active": edge.is_active,
                            },
                        )
                    if created:
                        created_count += 1
                        self.stdout.write(f"  Created index: {edge.id} -> {tenant.schema_name}")
                    else:
                        updated_count += 1
                        self.stdout.write(f"  Updated index: {edge.id} -> {tenant.schema_name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {created_count} new index entries, {updated_count} updated."
            )
        )
