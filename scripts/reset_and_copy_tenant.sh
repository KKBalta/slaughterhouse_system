#!/usr/bin/env bash
# Reset a tenant schema and re-copy all data from the public schema.
# Usage: ./scripts/reset_and_copy_tenant.sh <schema> <domain> <display_name> <env_file>
# Example: ./scripts/reset_and_copy_tenant.sh pomet pomet.carnitrack.com POMET .env.staging
set -euo pipefail

SCHEMA="${1:?Usage: $0 <schema> <domain> <display_name> <env_file>}"
DOMAIN="${2:?}"
NAME="${3:?}"
ENV_FILE="${4:-.env.staging}"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found"
  exit 1
fi

# Load env for shell commands AND for manage.py (DOTENV_FILE)
set -a; . "$ENV_FILE"; set +a
export DOTENV_FILE="$ENV_FILE"

echo "==> Dropping schema '$SCHEMA' if it exists..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" \
  -c "DROP SCHEMA IF EXISTS $SCHEMA CASCADE;"

echo "==> Removing Client+Domain records for '$SCHEMA'..."
python manage.py shell -c "
from tenants.models import Client, Domain
Client.objects.filter(schema_name='$SCHEMA').delete()
print('Cleaned up any existing Client records.')
"

echo "==> Creating tenant '$SCHEMA' (runs migrations automatically)..."
python manage.py shell -c "
from tenants.models import Client, Domain
client = Client.objects.create(schema_name='$SCHEMA', name='$NAME')
Domain.objects.create(domain='$DOMAIN', tenant=client, is_primary=True)
print(f'Created: {client} / {client.schema_name}')
"

echo "==> Copying data from public → '$SCHEMA'..."
python manage.py copy_public_to_tenant --schema="$SCHEMA"

echo "==> Done."
