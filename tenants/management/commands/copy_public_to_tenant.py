"""
One-time migration utility: copy all tenant-app table data from the public
schema into a named tenant schema created by django-tenants.

Handles:
  - FK ordering via topological sort
  - Schema drift: only copies columns present in both schemas
  - NOT NULL coercion: wraps source NULLs in COALESCE with type-safe defaults
    when the target column is NOT NULL but the source data may have NULLs
  - Error isolation via SAVEPOINTs (one failure doesn't roll back others)
  - Idempotent: safe to re-run (ON CONFLICT DO NOTHING)

Usage:
    python manage.py copy_public_to_tenant --schema=pomet
    python manage.py copy_public_to_tenant --schema=pomet --dry-run
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

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

# Fallback defaults by PostgreSQL data type category
_NULL_DEFAULTS = {
    "character varying": "''",
    "text": "''",
    "character": "''",
    "uuid": "gen_random_uuid()",
    "integer": "0",
    "bigint": "0",
    "smallint": "0",
    "numeric": "0",
    "real": "0",
    "double precision": "0",
    "boolean": "false",
    "jsonb": "'{}'",
    "json": "'{}'",
    "date": "CURRENT_DATE",
    "timestamp with time zone": "NOW()",
    "timestamp without time zone": "NOW()",
}


def _coalesce_default(data_type: str) -> str:
    return _NULL_DEFAULTS.get(data_type, "''")


def _build_copy_sql(cursor, schema: str, table: str) -> tuple[str, list[str]]:
    """
    Return (SELECT expression, [target column names]) for copying public.table → schema.table.

    - Only includes columns present in both source and target.
    - Wraps nullable source columns with COALESCE when target column is NOT NULL.
    """
    cursor.execute(
        """
        SELECT column_name, is_nullable, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        [schema, table],
    )
    target_meta = {row[0]: {"nullable": row[1], "type": row[2]} for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT column_name, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        [table],
    )
    source_meta = {row[0]: row[1] for row in cursor.fetchall()}

    cols = []
    select_parts = []

    for col, meta in target_meta.items():
        target_not_null = meta["nullable"] == "NO"

        if col in source_meta:
            # Column exists in both schemas — SELECT from source
            if target_not_null:
                default = _coalesce_default(meta["type"])
                select_parts.append(f"COALESCE({col}, {default}) AS {col}")
            else:
                select_parts.append(col)
        else:
            # Column only in target (added by newer migration).
            # Must supply a value if NOT NULL; skip if nullable (DEFAULT handles it).
            if not target_not_null:
                continue
            default = _coalesce_default(meta["type"])
            select_parts.append(f"{default} AS {col}")

        cols.append(col)

    return ", ".join(select_parts), cols


def _topological_sort(tables: set, cursor, schema: str) -> list[str]:
    """Return tables ordered so FK parents are inserted before children."""
    cursor.execute(
        """
        SELECT DISTINCT
            kcu.table_name  AS child,
            ccu.table_name  AS parent
        FROM information_schema.referential_constraints rc
        JOIN information_schema.key_column_usage kcu
            ON rc.constraint_name      = kcu.constraint_name
           AND kcu.constraint_schema   = rc.constraint_schema
        JOIN information_schema.constraint_column_usage ccu
            ON rc.unique_constraint_name  = ccu.constraint_name
           AND ccu.constraint_schema      = rc.unique_constraint_schema
        WHERE kcu.table_schema = %s
        """,
        [schema],
    )
    deps: dict[str, set] = {t: set() for t in tables}
    for child, parent in cursor.fetchall():
        if child in deps and parent in deps and parent != child:
            deps[child].add(parent)

    ordered: list[str] = []
    visited: set[str] = set()

    def visit(t: str) -> None:
        if t in visited:
            return
        visited.add(t)
        for parent in deps.get(t, []):
            visit(parent)
        ordered.append(t)

    for t in sorted(tables):
        visit(t)
    return ordered


class Command(BaseCommand):
    help = "Copy tenant-app table data from public schema into a named tenant schema."

    def add_arguments(self, parser):
        parser.add_argument("--schema", required=True, help="Target tenant schema_name (e.g. pomet)")
        parser.add_argument("--dry-run", action="store_true", help="Print SQL without executing")

    def handle(self, *args, **options):
        schema = options["schema"]
        dry_run = options["dry_run"]

        with connection.cursor() as cursor:
            # Verify schema exists
            cursor.execute(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                [schema],
            )
            if not cursor.fetchone():
                raise CommandError(f'Schema "{schema}" does not exist. Create the tenant first.')

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

            candidates = (public_tables & target_tables) - SHARED_ONLY_TABLES
            to_copy = _topological_sort(candidates, cursor, schema)

            self.stdout.write(f"Schema: public → {schema}  |  tables: {len(to_copy)} (FK-ordered)\n")

            if dry_run:
                for table in to_copy:
                    select_expr, cols = _build_copy_sql(cursor, schema, table)
                    col_list = ", ".join(cols)
                    self.stdout.write(
                        f"INSERT INTO {schema}.{table} ({col_list})\n  SELECT {select_expr} FROM public.{table};\n"
                    )
                return

            # Build FK parent map so we can skip children of failed tables.
            cursor.execute(
                """
                SELECT DISTINCT kcu.table_name AS child, ccu.table_name AS parent
                FROM information_schema.referential_constraints rc
                JOIN information_schema.key_column_usage kcu
                    ON rc.constraint_name    = kcu.constraint_name
                   AND kcu.constraint_schema = rc.constraint_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON rc.unique_constraint_name = ccu.constraint_name
                   AND ccu.constraint_schema     = rc.unique_constraint_schema
                WHERE kcu.table_schema = %s
                """,
                [schema],
            )
            fk_parents: dict[str, set] = {}
            for child, parent in cursor.fetchall():
                if child in candidates and parent in candidates:
                    fk_parents.setdefault(child, set()).add(parent)

            errors: list[tuple[str, str]] = []
            failed_tables: set[str] = set()

            # Each table commits individually — avoids commit-time FK re-checks
            # across tables and keeps partial progress on re-runs.
            for table in to_copy:
                blocking = failed_tables & fk_parents.get(table, set())
                if blocking:
                    msg = f"depends on failed: {', '.join(sorted(blocking))}"
                    self.stdout.write(self.style.WARNING(f"  SKIP {table} ({msg})"))
                    failed_tables.add(table)
                    errors.append((table, msg))
                    continue

                select_expr, cols = _build_copy_sql(cursor, schema, table)
                col_list = ", ".join(cols)
                sql = (
                    f"INSERT INTO {schema}.{table} ({col_list}) "
                    f"SELECT {select_expr} FROM public.{table} "
                    f"ON CONFLICT DO NOTHING"
                )
                try:
                    with transaction.atomic():
                        cursor.execute(sql)
                    self.stdout.write(f"  OK  {table} ({cursor.rowcount} rows)")
                except Exception as exc:
                    failed_tables.add(table)
                    errors.append((table, str(exc)))
                    self.stdout.write(self.style.ERROR(f"  ERR {table}: {exc}"))

            # Reset sequences so new inserts don't collide with copied IDs.
            # Uses pg_get_serial_sequence for reliable column→sequence mapping.
            cursor.execute(
                "SELECT table_name, column_name "
                "FROM information_schema.columns "
                "WHERE table_schema = %s AND column_default LIKE %s",
                [schema, "nextval(%"],
            )
            seq_cols = cursor.fetchall()
            for tbl, col in seq_cols:
                try:
                    cursor.execute(
                        f"SELECT setval(pg_get_serial_sequence('{schema}.{tbl}', '{col}'),"
                        f" COALESCE((SELECT MAX({col}) FROM {schema}.{tbl}), 1))"
                    )
                    self.stdout.write(f"  SEQ {schema}.{tbl}.{col} reset")
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f"  SEQ {schema}.{tbl}.{col} skip: {exc}"))

            self.stdout.write("")
            if errors:
                self.stdout.write(self.style.ERROR(f"{len(errors)} error(s):"))
                for tbl, exc in errors:
                    self.stdout.write(self.style.ERROR(f"  {tbl}: {exc}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Done. {len(to_copy)} tables copied, sequences reset."))
