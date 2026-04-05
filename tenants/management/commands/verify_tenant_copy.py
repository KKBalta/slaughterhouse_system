"""
Verify that data was correctly copied from the public schema to a tenant schema.
Compares row counts and spot-checks key tables.

Usage:
    python manage.py verify_tenant_copy --schema=pomet
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

SHARED_ONLY_TABLES = {
    "django_migrations",
    "tenants_client",
    "tenants_domain",
    "tenants_email_tenant_membership",
    "tenants_platform_admin",
    "tenants_platform_impersonation_session",
    "tenants_platform_impersonation_event",
    "tenants_tenant_registration_request",
}


class Command(BaseCommand):
    help = "Verify data integrity after copy_public_to_tenant."

    def add_arguments(self, parser):
        parser.add_argument("--schema", required=True, help="Tenant schema to verify")

    def handle(self, *args, **options):
        schema = options["schema"]

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                [schema],
            )
            if not cursor.fetchone():
                raise CommandError(f'Schema "{schema}" does not exist.')

            # Get tables in target schema
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
                [schema],
            )
            target_tables = {row[0] for row in cursor.fetchall()}

            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
            public_tables = {row[0] for row in cursor.fetchall()}

            comparable = sorted((public_tables & target_tables) - SHARED_ONLY_TABLES)

            self.stdout.write(f"\nVerifying: public → {schema}  |  {len(comparable)} tables\n")
            self.stdout.write(f"{'Table':<45} {'Public':>8} {'Tenant':>8} {'Status':>8}")
            self.stdout.write("-" * 75)

            mismatches = []
            for table in comparable:
                cursor.execute(f"SELECT COUNT(*) FROM public.{table}")
                pub_count = cursor.fetchone()[0]

                cursor.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
                tenant_count = cursor.fetchone()[0]

                if pub_count == tenant_count:
                    status = self.style.SUCCESS("OK")
                elif tenant_count >= pub_count:
                    status = self.style.SUCCESS("OK+")
                else:
                    status = self.style.ERROR("DIFF")
                    mismatches.append((table, pub_count, tenant_count))

                self.stdout.write(f"  {table:<43} {pub_count:>8} {tenant_count:>8}   {status}")

            # Check platform admin exists
            self.stdout.write("")
            cursor.execute("SELECT COUNT(*) FROM public.tenants_platform_admin")
            admin_count = cursor.fetchone()[0]
            cursor.execute("SELECT email, is_active FROM public.tenants_platform_admin")
            admins = cursor.fetchall()
            self.stdout.write(f"Platform admins: {admin_count}")
            for email, active in admins:
                self.stdout.write(f"  {email} (active={active})")

            # Check tenant record
            cursor.execute(
                "SELECT schema_name, name, is_active FROM public.tenants_client WHERE schema_name = %s",
                [schema],
            )
            row = cursor.fetchone()
            if row:
                self.stdout.write(f"\nTenant: {row[0]} / {row[1]} (active={row[2]})")
            else:
                self.stdout.write(self.style.ERROR(f"\nTenant record for '{schema}' NOT FOUND!"))

            cursor.execute(
                "SELECT domain, is_primary FROM public.tenants_domain "
                "WHERE tenant_id = (SELECT id FROM public.tenants_client WHERE schema_name = %s)",
                [schema],
            )
            domains = cursor.fetchall()
            for domain, primary in domains:
                self.stdout.write(f"  Domain: {domain} (primary={primary})")

            # Summary
            self.stdout.write("")
            if mismatches:
                self.stdout.write(self.style.ERROR(f"MISMATCHES ({len(mismatches)}):"))
                for table, pub, tenant in mismatches:
                    self.stdout.write(self.style.ERROR(f"  {table}: public={pub}, {schema}={tenant}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"All {len(comparable)} tables verified. Row counts match."))
