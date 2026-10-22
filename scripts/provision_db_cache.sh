#!/usr/bin/env bash
# ============================================================================
# Provision DB-backed cache + sessions for USE_REDIS=False
# ============================================================================
# Creates the two tables the app needs when it is NOT using Redis:
#   - public.django_cache_table   (DatabaseCache)            via createcachetable
#   - public.django_session       (DB session engine)        via migrate_schemas --shared
#
# Both are additive and idempotent. Tenant schemas already have django_session
# (sessions is in TENANT_APPS); only the public schema + the single cache table
# are new. Safe to re-run.
#
# Usage:
#   scripts/provision_db_cache.sh [ENV_FILE] [-y]
#     ENV_FILE  env file to load (default: .env.production)
#     -y        skip the confirmation prompt (non-interactive)
#
# Examples:
#   scripts/provision_db_cache.sh                      # prod, interactive
#   scripts/provision_db_cache.sh .env.staging -y      # staging, no prompt
#   scripts/provision_db_cache.sh .env -y              # local dev DB
# ============================================================================
set -euo pipefail

# ---- resolve repo root (works from any CWD) ----
case "${BASH_SOURCE[0]}" in
  /*) _SD="$(dirname "${BASH_SOURCE[0]}")" ;;
  *)  _SD="$(dirname "$PWD/${BASH_SOURCE[0]}")" ;;
esac
REPO_ROOT="$(cd "$_SD/.." && pwd)"
cd "$REPO_ROOT"

# ---- args ----
ENV_FILE=".env.production"
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    *) ENV_FILE="$arg" ;;
  esac
done

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
step() { echo -e "\n${GREEN}==> $1${NC}"; }
warn() { echo -e "${YELLOW}    $1${NC}"; }
fail() { echo -e "${RED}ERROR: $1${NC}"; exit 1; }

[ -f "$ENV_FILE" ] || fail "$ENV_FILE not found (cwd: $REPO_ROOT)"

# ---- load env, then FORCE USE_REDIS=False so the management commands target
#      the DatabaseCache table + shared sessions regardless of the file's value ----
set -a; . "$ENV_FILE"; set +a
export DOTENV_FILE="$ENV_FILE"   # honored by settings if it reads it
export USE_REDIS=False

DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-}"
DB_USER="${DB_USER:-}"
INSTANCE="${CLOUD_SQL_CONNECTION_NAME:-}"
PROXY_BIN="${CLOUD_SQL_PROXY:-./cloud_sql_proxy}"

step "Target"
echo "    Env file : $ENV_FILE"
echo "    Database : ${DB_NAME:-?}  (user ${DB_USER:-?})"
echo "    Host:Port: $DB_HOST:$DB_PORT"
echo "    Instance : ${INSTANCE:-<none / direct>}"
echo "    USE_REDIS: False (forced for this provisioning run)"

if [ "$ASSUME_YES" -ne 1 ]; then
  echo -ne "\n${YELLOW}Proceed against this database? [y/N] ${NC}"
  read -r reply
  [ "$reply" = "y" ] || [ "$reply" = "Y" ] || fail "Aborted."
fi

# ---- start Cloud SQL proxy if we connect via 127.0.0.1 and nothing is listening ----
STARTED_PROXY=0
PROXY_PID=""
cleanup() {
  if [ "$STARTED_PROXY" = "1" ] && [ -n "$PROXY_PID" ]; then
    step "Stopping Cloud SQL proxy (pid $PROXY_PID)"
    kill "$PROXY_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

port_open() { nc -z "$DB_HOST" "$DB_PORT" >/dev/null 2>&1; }

if { [ "$DB_HOST" = "127.0.0.1" ] || [ "$DB_HOST" = "localhost" ]; } && [ -n "$INSTANCE" ]; then
  if port_open; then
    warn "Port $DB_PORT already open — reusing existing proxy/connection."
  else
    [ -x "$PROXY_BIN" ] || fail "Cloud SQL proxy not found/executable at $PROXY_BIN"
    step "Starting Cloud SQL proxy: $INSTANCE -> tcp:$DB_PORT"
    "$PROXY_BIN" -instances="$INSTANCE"=tcp:"$DB_PORT" >/tmp/csql_proxy_$DB_PORT.log 2>&1 &
    PROXY_PID=$!
    STARTED_PROXY=1
    # wait up to ~20s for the port
    for _ in $(seq 1 40); do port_open && break; sleep 0.5; done
    port_open || { cat /tmp/csql_proxy_$DB_PORT.log; fail "Proxy did not open $DB_PORT in time"; }
    warn "Proxy ready (pid $PROXY_PID)."
  fi
else
  warn "Direct connection (no proxy): $DB_HOST:$DB_PORT"
fi

# ---- run the two provisioning commands (idempotent) ----
step "1/2  migrate_schemas --shared  (creates public.django_session)"
python manage.py migrate_schemas --shared 2>&1 | tail -8

step "2/2  createcachetable          (creates public.django_cache_table)"
python manage.py createcachetable 2>&1 | tail -8

# ---- verify both tables exist in the public schema ----
step "Verifying tables in public schema"
if [ -n "${DB_NAME}" ] && [ -n "${DB_USER}" ] && command -v psql >/dev/null 2>&1; then
  PGPASSWORD="${DB_PASSWORD:-}" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -tAc \
    "SELECT 'django_cache_table=' || (to_regclass('public.django_cache_table') IS NOT NULL),
            'django_session='     || (to_regclass('public.django_session') IS NOT NULL);" \
    | sed 's/^/    /'
else
  warn "psql or DB creds unavailable — skipping direct verify."
fi

step "Done"
echo "    DB-backed cache + sessions are provisioned for USE_REDIS=False."
echo "    Deploy/serve with USE_REDIS=False (env.yaml) and the app no longer needs Redis."
