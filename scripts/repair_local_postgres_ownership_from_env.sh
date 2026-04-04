#!/usr/bin/env bash
# Repair ownership/privileges in a local Postgres database after importing a dump
# that was created under a different role (for example staging/prod).
#
# Usage:
#   bash scripts/repair_local_postgres_ownership_from_env.sh .env.dev
#
# Requires superuser access to the local Postgres instance.
# Override with:
#   POSTGRES_SUPERUSER=postgres
set -euo pipefail

ENV_FILE="${1:-}"
if [[ -z "$ENV_FILE" ]]; then
  echo "Usage: $0 <path-to-env-file>" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

: "${DB_NAME:?DB_NAME must be set in $ENV_FILE}"
: "${DB_USER:?DB_USER must be set in $ENV_FILE}"

DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
SUPERUSER="${POSTGRES_SUPERUSER:-postgres}"
FALLBACK_SUPERUSER="${USER:-}"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

step() { echo -e "\n${GREEN}==> $1${NC}"; }
fail() { echo -e "${RED}ERROR: $1${NC}"; exit 1; }

escape_sql_identifier() {
  printf '%s' "$1" | sed 's/"/""/g'
}

DB_NAME_IDENT="\"$(escape_sql_identifier "$DB_NAME")\""
DB_USER_IDENT="\"$(escape_sql_identifier "$DB_USER")\""

psql_super_postgres() {
  psql -v ON_ERROR_STOP=1 -h "$DB_HOST" -p "$DB_PORT" -U "$SUPERUSER" -d postgres "$@"
}

psql_super_db() {
  psql -v ON_ERROR_STOP=1 -h "$DB_HOST" -p "$DB_PORT" -U "$SUPERUSER" -d "$DB_NAME" "$@"
}

step "Connecting to PostgreSQL at ${DB_HOST}:${DB_PORT} as superuser '${SUPERUSER}'..."
if ! psql_super_postgres -tc "SELECT 1" >/dev/null 2>&1; then
  if [[ -z "${POSTGRES_SUPERUSER:-}" && -n "$FALLBACK_SUPERUSER" && "$FALLBACK_SUPERUSER" != "$SUPERUSER" ]]; then
    SUPERUSER="$FALLBACK_SUPERUSER"
    step "Retrying with OS user '${SUPERUSER}'..."
  fi
fi

if ! psql_super_postgres -tc "SELECT 1" >/dev/null 2>&1; then
  fail "Could not connect as superuser '${SUPERUSER}'. Export PGPASSWORD or set POSTGRES_SUPERUSER."
fi

step "Ensuring database ${DB_NAME} is owned by ${DB_USER}..."
psql_super_postgres -c "ALTER DATABASE ${DB_NAME_IDENT} OWNER TO ${DB_USER_IDENT};"
psql_super_postgres -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME_IDENT} TO ${DB_USER_IDENT};"

step "Repairing schema, table, sequence, view, and routine ownership in ${DB_NAME}..."
psql_super_db <<SQL
DO \$\$
DECLARE
  schema_name text;
  rel record;
  fn record;
BEGIN
  FOR schema_name IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname NOT IN ('pg_catalog', 'information_schema')
      AND nspname NOT LIKE 'pg_toast%'
  LOOP
    EXECUTE format('ALTER SCHEMA %I OWNER TO %I', schema_name, '${DB_USER}');
    EXECUTE format('GRANT USAGE, CREATE ON SCHEMA %I TO %I', schema_name, '${DB_USER}');
  END LOOP;

  FOR rel IN
    SELECT
      n.nspname AS schema_name,
      c.relname AS object_name,
      c.relkind
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND n.nspname NOT LIKE 'pg_toast%'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND NOT EXISTS (
        SELECT 1
        FROM pg_depend d
        JOIN pg_extension e ON e.oid = d.refobjid
        WHERE d.classid = 'pg_class'::regclass
          AND d.objid = c.oid
          AND d.deptype = 'e'
      )
  LOOP
    IF rel.relkind IN ('r', 'p') THEN
      EXECUTE format('ALTER TABLE %I.%I OWNER TO %I', rel.schema_name, rel.object_name, '${DB_USER}');
    ELSIF rel.relkind = 'v' THEN
      EXECUTE format('ALTER VIEW %I.%I OWNER TO %I', rel.schema_name, rel.object_name, '${DB_USER}');
    ELSIF rel.relkind = 'm' THEN
      EXECUTE format('ALTER MATERIALIZED VIEW %I.%I OWNER TO %I', rel.schema_name, rel.object_name, '${DB_USER}');
    ELSIF rel.relkind = 'f' THEN
      EXECUTE format('ALTER FOREIGN TABLE %I.%I OWNER TO %I', rel.schema_name, rel.object_name, '${DB_USER}');
    END IF;
  END LOOP;

  FOR fn IN
    SELECT
      n.nspname AS schema_name,
      p.proname AS function_name,
      pg_get_function_identity_arguments(p.oid) AS args
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND n.nspname NOT LIKE 'pg_toast%'
      AND NOT EXISTS (
        SELECT 1
        FROM pg_depend d
        JOIN pg_extension e ON e.oid = d.refobjid
        WHERE d.classid = 'pg_proc'::regclass
          AND d.objid = p.oid
          AND d.deptype = 'e'
      )
  LOOP
    EXECUTE format('ALTER ROUTINE %I.%I(%s) OWNER TO %I', fn.schema_name, fn.function_name, fn.args, '${DB_USER}');
  END LOOP;
END
\$\$;

DO \$\$
DECLARE
  schema_name text;
BEGIN
  FOR schema_name IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname NOT IN ('pg_catalog', 'information_schema')
      AND nspname NOT LIKE 'pg_toast%'
  LOOP
    EXECUTE format('GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA %I TO %I', schema_name, '${DB_USER}');
    EXECUTE format('GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA %I TO %I', schema_name, '${DB_USER}');
    EXECUTE format('GRANT ALL PRIVILEGES ON ALL ROUTINES IN SCHEMA %I TO %I', schema_name, '${DB_USER}');
    EXECUTE format(
      'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL PRIVILEGES ON TABLES TO %I',
      schema_name,
      '${DB_USER}'
    );
    EXECUTE format(
      'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL PRIVILEGES ON SEQUENCES TO %I',
      schema_name,
      '${DB_USER}'
    );
    EXECUTE format(
      'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL PRIVILEGES ON ROUTINES TO %I',
      schema_name,
      '${DB_USER}'
    );
  END LOOP;
END
\$\$;
SQL

echo ""
echo -e "${GREEN}Done. Local database ownership repaired for role ${DB_USER}.${NC}"
echo "Run: make migrate-dev"
