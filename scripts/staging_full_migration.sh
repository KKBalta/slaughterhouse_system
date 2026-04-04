#!/usr/bin/env bash
# ============================================================================
# CarniTrack — Full Staging Multi-Tenant Migration
# ============================================================================
#
# Performs the complete single-tenant → multi-tenant migration on the staging
# Cloud SQL instance. This is the rehearsal script for production cutover.
#
# What it does:
#   1. Backs up the staging database
#   2. Runs shared schema migrations (creates tenants_client, tenants_domain, etc.)
#   3. Creates the tenant + copies all data from public → tenant schema
#   4. Runs tenant schema migrations (e.g. logo storage changes)
#   5. Creates a platform admin account
#   6. Verifies the migration
#   7. Deploys to Cloud Run staging
#
# Prerequisites:
#   - .env.staging filled in (DB_PASSWORD, SECRET_KEY, REDIS_URL)
#   - env.staging.yaml filled in (ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, TENANT_BASE_DOMAIN)
#   - gcloud auth + Docker running
#   - ./cloud_sql_proxy in repo root
#
# Usage:
#   bash scripts/staging_full_migration.sh
#
# To skip the Cloud Run deploy (DB migration only):
#   SKIP_DEPLOY=1 bash scripts/staging_full_migration.sh
#
# ============================================================================
set -euo pipefail

# --------------- Configuration ---------------
ENV_FILE="${ENV_FILE:-.env.staging}"
ENV_YAML="${ENV_YAML:-env.staging.yaml}"
CLOUD_SQL_PROXY="${CLOUD_SQL_PROXY:-./cloud_sql_proxy}"
STAGING_INSTANCE="${STAGING_INSTANCE:-carnitrack:europe-west1:carnitrack-db-belgium-staging}"
PROXY_PORT="${PROXY_PORT:-5433}"
BACKUP_DIR="${BACKUP_DIR:-sql_backup}"

# Tenant config
SCHEMA="${SCHEMA:-pomet}"
DOMAIN="${DOMAIN:-pomet.carnitrack.com}"
TENANT_NAME="${TENANT_NAME:-POMET}"

# Platform admin
ADMIN_EMAIL="${ADMIN_EMAIL:-kaanbalta57@gmail.com}"
ADMIN_NAME="${ADMIN_NAME:-kaanbalta}"
ADMIN_PASS="${ADMIN_PASS:-}"

SKIP_DEPLOY="${SKIP_DEPLOY:-0}"
# ----------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

step() { echo -e "\n${GREEN}==> $1${NC}"; }
warn() { echo -e "${YELLOW}    $1${NC}"; }
fail() { echo -e "${RED}ERROR: $1${NC}"; exit 1; }

# Validate prerequisites
[ -f "$ENV_FILE" ] || fail "$ENV_FILE not found. Run: cp env/examples/.env.staging.example .env.staging"
[ -f "$CLOUD_SQL_PROXY" ] || fail "Cloud SQL Proxy not found at $CLOUD_SQL_PROXY"

if [ "$SKIP_DEPLOY" = "0" ]; then
  [ -f "$ENV_YAML" ] || fail "$ENV_YAML not found. Run: cp env/examples/env.staging.yaml.example env.staging.yaml"
fi

if [ -z "$ADMIN_PASS" ]; then
  echo -n "Enter platform admin password for $ADMIN_EMAIL: "
  read -s ADMIN_PASS
  echo
  [ -n "$ADMIN_PASS" ] || fail "Password cannot be empty"
fi

# Load env
set -a; . "$ENV_FILE"; set +a

# Start proxy
step "Starting Cloud SQL Proxy on port $PROXY_PORT..."
$CLOUD_SQL_PROXY -instances="$STAGING_INSTANCE"=tcp:"$PROXY_PORT" &
PROXY_PID=$!
sleep 2
trap "echo 'Stopping Cloud SQL Proxy...'; kill $PROXY_PID 2>/dev/null" EXIT INT TERM

# Test DB connection
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" \
  -c "SELECT 1" > /dev/null 2>&1 || fail "Cannot connect to staging DB"

# ============================================================================
# Step 1: Backup
# ============================================================================
step "Step 1/7 — Backing up staging database..."
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/staging_pre_migration_$(date +%Y%m%d_%H%M%S).sql"
PGPASSWORD="$DB_PASSWORD" pg_dump \
  -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" \
  > "$BACKUP_FILE"
echo "    Backup saved: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"

# ============================================================================
# Step 2: Run shared schema migrations
# ============================================================================
step "Step 2/7 — Running shared schema migrations..."
python manage.py migrate_schemas --shared 2>&1 | tail -5

# ============================================================================
# Step 3: Create tenant + copy data
# ============================================================================
step "Step 3/7 — Creating tenant '$SCHEMA' and copying data..."
bash scripts/reset_and_copy_tenant.sh "$SCHEMA" "$DOMAIN" "$TENANT_NAME" "$ENV_FILE"

# ============================================================================
# Step 4: Run tenant schema migrations
# ============================================================================
step "Step 4/7 — Running tenant schema migrations for '$SCHEMA'..."
python manage.py migrate_schemas --tenant 2>&1 | tail -5

# ============================================================================
# Step 5: Create platform admin
# ============================================================================
step "Step 5/7 — Creating platform admin ($ADMIN_EMAIL)..."
python manage.py create_platform_admin \
  --email="$ADMIN_EMAIL" \
  --name="$ADMIN_NAME" \
  --password="$ADMIN_PASS"

# ============================================================================
# Step 6: Verify migration
# ============================================================================
step "Step 6/7 — Verifying migration..."
python manage.py verify_tenant_copy --schema="$SCHEMA"

# ============================================================================
# Step 7: Deploy to Cloud Run
# ============================================================================
if [ "$SKIP_DEPLOY" = "1" ]; then
  warn "Skipping Cloud Run deploy (SKIP_DEPLOY=1)"
else
  step "Step 7/7 — Deploying to Cloud Run staging..."
  bash deploy_staging.sh "$ENV_YAML"
fi

# ============================================================================
# Summary
# ============================================================================
echo ""
echo -e "${GREEN}============================================================================${NC}"
echo -e "${GREEN} Staging migration complete!${NC}"
echo -e "${GREEN}============================================================================${NC}"
echo ""
echo "  Backup:         $BACKUP_FILE"
echo "  Tenant:         $SCHEMA → $DOMAIN"
echo "  Platform admin: $ADMIN_EMAIL"
echo ""
echo "  Test URLs:"
echo "    Public:  https://carnitrack-app-staging-1000671720976.europe-west1.run.app/platform-admin/login/"
echo "    Tenant:  https://$DOMAIN/"
echo ""
echo "  To rollback (restore backup):"
echo "    PGPASSWORD=\$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER $DB_NAME < $BACKUP_FILE"
echo ""
