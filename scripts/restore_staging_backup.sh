#!/usr/bin/env bash
# Restore a SQL backup to the staging Cloud SQL database.
# Wipes the existing DB and restores from the given backup file.
#
# Usage:
#   bash scripts/restore_staging_backup.sh sql_backup/staging_backup_20260402_1958.sql
#
# Env overrides:
#   ENV_FILE=.env.staging  PROXY_PORT=5433
set -euo pipefail

BACKUP_FILE="${1:?Usage: $0 <backup.sql>}"
ENV_FILE="${ENV_FILE:-.env.staging}"
CLOUD_SQL_PROXY="${CLOUD_SQL_PROXY:-./cloud_sql_proxy}"
STAGING_INSTANCE="${STAGING_INSTANCE:-carnitrack:europe-west1:carnitrack-db-belgium-staging}"
PROXY_PORT="${PROXY_PORT:-5433}"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

step() { echo -e "\n${GREEN}==> $1${NC}"; }
fail() { echo -e "${RED}ERROR: $1${NC}"; exit 1; }

[ -f "$BACKUP_FILE" ] || fail "Backup file not found: $BACKUP_FILE"
[ -f "$ENV_FILE" ]    || fail "$ENV_FILE not found"
[ -f "$CLOUD_SQL_PROXY" ] || fail "Cloud SQL Proxy not found at $CLOUD_SQL_PROXY"

set -a; . "$ENV_FILE"; set +a

step "Starting Cloud SQL Proxy on port $PROXY_PORT..."
$CLOUD_SQL_PROXY -instances="$STAGING_INSTANCE"=tcp:"$PROXY_PORT" &
PROXY_PID=$!
sleep 3
trap "echo 'Stopping proxy...'; kill $PROXY_PID 2>/dev/null" EXIT INT TERM

PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
  -c "SELECT 1" > /dev/null 2>&1 || fail "Cannot connect to staging DB"

step "Dropping and recreating database '$DB_NAME'..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
  -c "DROP DATABASE IF EXISTS $DB_NAME;" \
  -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

step "Granting django_user role to $DB_USER (for prod backups)..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
  -c "GRANT django_user TO $DB_USER;" 2>/dev/null || true

step "Restoring $(du -h "$BACKUP_FILE" | cut -f1) backup..."
ERROR_COUNT=$(PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" \
  < "$BACKUP_FILE" 2>&1 | grep -c "^ERROR:" || true)
echo "    Errors: $ERROR_COUNT (role/sequence errors are usually harmless)"

step "Verifying restore..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -c "
  SELECT
    (SELECT count(*) FROM information_schema.tables
     WHERE table_schema = 'public' AND table_type = 'BASE TABLE') AS tables,
    (SELECT count(*) FROM information_schema.schemata
     WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast','public')) AS tenant_schemas;
"

echo ""
echo -e "${GREEN}Done. Staging DB restored from: $BACKUP_FILE${NC}"
