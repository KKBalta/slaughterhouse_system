from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.utils import ProgrammingError
from django_tenants.utils import get_public_schema_name, schema_context

from tenants.models import Client
from users.services import backfill_legacy_walk_in_profiles_from_orders


class Command(BaseCommand):
    help = (
        "Create WALKIN users and UNCLASSIFIED ClientProfile rows for legacy walk-in orders, "
        "then link matching historical orders by normalized phone. "
        "Profiles appear under user management as Unclassified walk-in prospects for staff to edit."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview the backfill and roll back all database changes.",
        )
        parser.add_argument(
            "--schema",
            action="append",
            dest="schemas",
            default=[],
            help="Limit the backfill to one or more tenant schema names.",
        )
        parser.add_argument(
            "--include-public",
            action="store_true",
            help="Also run the backfill against the public schema for legacy single-schema data.",
        )

    def _run_schema_backfill(self, schema_name: str) -> dict[str, int]:
        try:
            return backfill_legacy_walk_in_profiles_from_orders()
        except ProgrammingError as exc:
            message = str(exc)
            if "users_clientprofile" in message and "default_destination" in message:
                raise CommandError(
                    f"Schema '{schema_name}' is missing users.0007 "
                    "(ClientProfile.default_destination). Apply the users migrations first, "
                    "then rerun this command. In this multitenant setup, use "
                    "`python manage.py migrate_schemas`."
                ) from exc
            raise

    def _write_schema_stats(self, schema_name: str, stats: dict[str, int]) -> None:
        self.stdout.write(
            f"[{schema_name}] Legacy walk-in order scan: "
            f"unlinked_orders={stats['unlinked_orders']} "
            f"eligible_orders={stats['eligible_orders']} "
            f"skipped_missing_name_or_phone={stats['skipped_missing_name_or_phone']}"
        )
        self.stdout.write(
            f"[{schema_name}] Walk-in profile backfill: "
            f"processed_phone_groups={stats['processed_phone_groups']} "
            f"created_users={stats['created_users']} "
            f"created_profiles={stats['created_profiles']} "
            f"reused_profiles={stats['reused_profiles']} "
            f"linked_orders={stats['linked_orders']} "
            f"skipped_invalid_phone_groups={stats['skipped_invalid_phone_groups']} "
            f"skipped_unmanageable_phone_groups={stats['skipped_unmanageable_phone_groups']}"
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        target_schemas = {value.strip() for value in options["schemas"] if value and value.strip()}
        include_public = bool(options["include_public"])

        with transaction.atomic():
            if getattr(settings, "USE_MULTITENANT", False):
                public_schema = get_public_schema_name()
                with schema_context(public_schema):
                    tenants = (
                        Client.objects.filter(is_active=True).exclude(schema_name=public_schema).order_by("schema_name")
                    )
                    if target_schemas:
                        tenants = tenants.filter(schema_name__in=sorted(target_schemas))
                    tenants = list(tenants)

                if target_schemas and not tenants and not (include_public and public_schema in target_schemas):
                    raise CommandError(f"No active tenant schemas matched: {', '.join(sorted(target_schemas))}")

                for tenant in tenants:
                    with schema_context(tenant.schema_name):
                        stats = self._run_schema_backfill(tenant.schema_name)
                    self._write_schema_stats(tenant.schema_name, stats)

                should_run_public = include_public or (target_schemas and public_schema in target_schemas)
                if should_run_public:
                    with schema_context(public_schema):
                        stats = self._run_schema_backfill(public_schema)
                    self._write_schema_stats(public_schema, stats)
            else:
                stats = self._run_schema_backfill("default")
                self._write_schema_stats("default", stats)

            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run complete. Database changes were rolled back."))
                return

        self.stdout.write(self.style.SUCCESS("Legacy walk-in profile backfill completed."))
