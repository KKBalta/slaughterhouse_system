from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, schema_context

from tenants.models import Client, Domain


class Command(BaseCommand):
    help = "Rewrite tenant primary domains to <slug>.localhost-style hosts for local dev."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-domain",
            default=(getattr(settings, "TENANT_BASE_DOMAIN", "localhost") or "localhost").strip().lstrip("."),
            help="Base domain to use for generated tenant hosts (default: settings.TENANT_BASE_DOMAIN).",
        )
        parser.add_argument(
            "--schema",
            action="append",
            dest="schemas",
            default=[],
            help="Limit the rewrite to one or more tenant schema names.",
        )

    def handle(self, *args, **options):
        base_domain = (options["base_domain"] or "").strip().lstrip(".")
        if not base_domain:
            raise CommandError("--base-domain cannot be empty.")
        if "localhost" not in base_domain and getattr(settings, "DEBUG", False):
            self.stdout.write(self.style.WARNING(f"Using non-localhost base domain in DEBUG: {base_domain}"))

        target_schemas = {value.strip() for value in options["schemas"] if value and value.strip()}
        updated = 0
        created = 0
        demoted = 0
        public_schema = get_public_schema_name()

        with schema_context(public_schema):
            tenants = Client.objects.exclude(schema_name=public_schema).order_by("schema_name")
            if target_schemas:
                tenants = tenants.filter(schema_name__in=sorted(target_schemas))
            for tenant in tenants:
                desired = f"{(tenant.slug or tenant.schema_name).strip() or tenant.schema_name}.{base_domain}"
                current_primary = tenant.get_primary_domain()
                target = tenant.domains.filter(domain=desired).first()

                if target is None and current_primary is None:
                    Domain.objects.create(domain=desired, tenant=tenant, is_primary=True)
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"{tenant.schema_name}: created primary domain {desired}"))
                    continue

                if target is None and current_primary is not None:
                    if current_primary.domain != desired:
                        current_primary.domain = desired
                        current_primary.is_primary = True
                        current_primary.save(update_fields=["domain", "is_primary"])
                        updated += 1
                        self.stdout.write(
                            self.style.SUCCESS(f"{tenant.schema_name}: updated primary domain -> {desired}")
                        )
                    continue

                if current_primary is not None and current_primary.pk != target.pk and current_primary.is_primary:
                    current_primary.is_primary = False
                    current_primary.save(update_fields=["is_primary"])
                    demoted += 1

                if not target.is_primary:
                    target.is_primary = True
                    target.save(update_fields=["is_primary"])
                    updated += 1

                self.stdout.write(self.style.SUCCESS(f"{tenant.schema_name}: using existing domain {desired}"))

        self.stdout.write(
            self.style.SUCCESS(f"Localhost domain sync complete. updated={updated} created={created} demoted={demoted}")
        )
