#!/usr/bin/env bash
# Reset staging DB to pre-multi-tenant state (simulates production before cutover)
# Public schema data stays intact — only tenant schemas + tenant records are removed.
#
# Usage: bash scripts/reset_staging_to_single_tenant.sh
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env.staging}"
CLOUD_SQL_PROXY="${CLOUD_SQL_PROXY:-./cloud_sql_proxy}"
STAGING_INSTANCE="${STAGING_INSTANCE:-carnitrack:europe-west1:carnitrack-db-belgium-staging}"
PROXY_PORT="${PROXY_PORT:-5433}"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

step() { echo -e "\n${GREEN}==> $1${NC}"; }
fail() { echo -e "${RED}ERROR: $1${NC}"; exit 1; }

[ -f "$ENV_FILE" ] || fail "$ENV_FILE not found"
[ -f "$CLOUD_SQL_PROXY" ] || fail "Cloud SQL Proxy not found at $CLOUD_SQL_PROXY"

set -a; . "$ENV_FILE"; set +a

step "Starting Cloud SQL Proxy on port $PROXY_PORT..."
$CLOUD_SQL_PROXY -instances="$STAGING_INSTANCE"=tcp:"$PROXY_PORT" &
PROXY_PID=$!
sleep 2
trap "echo 'Stopping proxy...'; kill $PROXY_PID 2>/dev/null" EXIT INT TERM

PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" \
  -c "SELECT 1" > /dev/null 2>&1 || fail "Cannot connect to staging DB"

step "Current schemas (besides public):"
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -c "
  SELECT schema_name FROM information_schema.schemata
  WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast','public')
  ORDER BY schema_name;
"

step "Dropping tenant schemas..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -c "
  DO \$\$
  DECLARE r RECORD;
  BEGIN
    FOR r IN SELECT schema_name FROM information_schema.schemata
      WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast','public')
    LOOP
      EXECUTE 'DROP SCHEMA ' || quote_ident(r.schema_name) || ' CASCADE';
      RAISE NOTICE 'Dropped schema: %', r.schema_name;
    END LOOP;
  END \$\$;
"

step "Clearing tenant tables in public schema..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -c "
  TRUNCATE
    tenants_domain,
    tenants_client,
    tenants_platform_admin,
    tenants_email_tenant_membership,
    tenants_tenant_registration_request
  CASCADE;
"

step "Verifying reset..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -c "
  SELECT 'tenant_schemas' AS check,
    (SELECT count(*) FROM information_schema.schemata
     WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast','public'))::text AS count
  UNION ALL
  SELECT 'clients', (SELECT count(*) FROM tenants_client)::text
  UNION ALL
  SELECT 'domains', (SELECT count(*) FROM tenants_domain)::text
  UNION ALL
  SELECT 'platform_admins', (SELECT count(*) FROM tenants_platform_admin)::text;
"

echo ""
echo -e "${GREEN}Done. Staging DB is back to single-tenant state.${NC}"
echo "Public schema data is untouched — ready for: bash scripts/staging_full_migration.sh"
