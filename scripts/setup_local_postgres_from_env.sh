#!/usr/bin/env bash
# Create PostgreSQL role + database from a shell-style env file (DB_NAME, DB_USER, DB_PASSWORD, …).
# Requires psql access as a superuser (default: postgres). Override with POSTGRES_SUPERUSER / PGPASSWORD.
set -euo pipefail

ENV_FILE="${1:-}"
if [[ -z "$ENV_FILE" ]]; then
  echo "Usage: $0 <path-to-env-file>" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE" >&2
  echo "Copy from: cp env/examples/.env.dev.example .env.dev" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

: "${DB_NAME:?DB_NAME must be set in $ENV_FILE}"
: "${DB_USER:?DB_USER must be set in $ENV_FILE}"
: "${DB_PASSWORD:?DB_PASSWORD must be set in $ENV_FILE}"

DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
SUPERUSER="${POSTGRES_SUPERUSER:-postgres}"
FALLBACK_SUPERUSER="${USER:-}"

escape_sql_literal() {
  printf '%s' "$1" | sed "s/'/''/g"
}

PW_ESC="$(escape_sql_literal "$DB_PASSWORD")"

psql_super() {
  psql -v ON_ERROR_STOP=1 -h "$DB_HOST" -p "$DB_PORT" -U "$SUPERUSER" -d postgres "$@"
}

echo "Connecting to PostgreSQL at ${DB_HOST}:${DB_PORT} as superuser '${SUPERUSER}' (database postgres)…"

if ! psql_super -tc "SELECT 1" >/dev/null 2>&1; then
  if [[ -z "${POSTGRES_SUPERUSER:-}" && -n "$FALLBACK_SUPERUSER" && "$FALLBACK_SUPERUSER" != "$SUPERUSER" ]]; then
    SUPERUSER="$FALLBACK_SUPERUSER"
    echo "Could not connect as 'postgres'; retrying with OS user '${SUPERUSER}'…" >&2
  fi
fi

if ! psql_super -tc "SELECT 1" >/dev/null 2>&1; then
  echo "Could not connect. Ensure PostgreSQL is running and you can connect as superuser." >&2
  echo "Tip: export PGPASSWORD for '${SUPERUSER}', or set POSTGRES_SUPERUSER explicitly." >&2
  exit 1
fi

EXISTS_USER="$(psql_super -Atc "SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}'" || true)"
if [[ "$EXISTS_USER" != "1" ]]; then
  echo "Creating role ${DB_USER}…"
  psql_super -c "CREATE ROLE \"${DB_USER}\" WITH LOGIN PASSWORD '${PW_ESC}';"
else
  echo "Role ${DB_USER} already exists; setting password…"
  psql_super -c "ALTER ROLE \"${DB_USER}\" WITH LOGIN PASSWORD '${PW_ESC}';"
fi

EXISTS_DB="$(psql_super -Atc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" || true)"
if [[ "$EXISTS_DB" != "1" ]]; then
  echo "Creating database ${DB_NAME}…"
  psql_super -c "CREATE DATABASE \"${DB_NAME}\" OWNER \"${DB_USER}\";"
else
  echo "Database ${DB_NAME} already exists."
fi

echo "Done. You can run: make migrate-dev && make dev"
