#!/usr/bin/env bash
# Dump the staging Cloud SQL database to a local SQL file.
#
# Usage:
#   bash scripts/dump_staging_backup.sh
#   OUT=sql_backup/custom_name.sql bash scripts/dump_staging_backup.sh
#
# Env overrides:
#   ENV_FILE=.env.staging
#   CLOUD_SQL_PROXY=./cloud_sql_proxy
#   STAGING_INSTANCE=carnitrack:europe-west1:carnitrack-db-belgium-staging
#   PROXY_PORT=5433
#   BACKUP_DIR=sql_backup
#   BACKUP_PREFIX=staging_backup
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env.staging}"
CLOUD_SQL_PROXY="${CLOUD_SQL_PROXY:-./cloud_sql_proxy}"
STAGING_INSTANCE="${STAGING_INSTANCE:-carnitrack:europe-west1:carnitrack-db-belgium-staging}"
PROXY_PORT="${PROXY_PORT:-5433}"
BACKUP_DIR="${BACKUP_DIR:-sql_backup}"
BACKUP_PREFIX="${BACKUP_PREFIX:-staging_backup}"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

step() { echo -e "\n${GREEN}==> $1${NC}"; }
fail() { echo -e "${RED}ERROR: $1${NC}"; exit 1; }

[ -f "$ENV_FILE" ] || fail "$ENV_FILE not found. Run: cp env/examples/.env.staging.example .env.staging"
[ -f "$CLOUD_SQL_PROXY" ] || fail "Cloud SQL Proxy not found at $CLOUD_SQL_PROXY"

set -a
. "$ENV_FILE"
set +a

mkdir -p "$BACKUP_DIR"

if [ -n "${OUT:-}" ]; then
  BACKUP_FILE="$OUT"
else
  BACKUP_FILE="$BACKUP_DIR/${BACKUP_PREFIX}_$(date +%Y%m%d_%H%M%S).sql"
fi

BACKUP_PARENT="$(dirname "$BACKUP_FILE")"
mkdir -p "$BACKUP_PARENT"

step "Starting Cloud SQL Proxy for staging on port $PROXY_PORT..."
"$CLOUD_SQL_PROXY" -instances="$STAGING_INSTANCE"=tcp:"$PROXY_PORT" &
PROXY_PID=$!
sleep 3
trap "echo 'Stopping proxy...'; kill $PROXY_PID 2>/dev/null" EXIT INT TERM

PGHOST="127.0.0.1"
PGPORT="$PROXY_PORT"

PGPASSWORD="$DB_PASSWORD" psql -h "$PGHOST" -p "$PGPORT" -U "$DB_USER" "$DB_NAME" \
  -c "SELECT 1" > /dev/null 2>&1 || fail "Cannot connect to staging DB through proxy on port $PROXY_PORT"

step "Dumping staging database to $BACKUP_FILE..."
PGPASSWORD="$DB_PASSWORD" pg_dump \
  -h "$PGHOST" \
  -p "$PGPORT" \
  -U "$DB_USER" \
  "$DB_NAME" \
  > "$BACKUP_FILE"

SIZE_HUMAN="$(du -h "$BACKUP_FILE" | cut -f1)"
step "Verifying dump file..."
[ -s "$BACKUP_FILE" ] || fail "Dump file was created but is empty: $BACKUP_FILE"

echo ""
echo -e "${GREEN}Done. Staging DB dumped to: $BACKUP_FILE${NC}"
echo "Size: $SIZE_HUMAN"
