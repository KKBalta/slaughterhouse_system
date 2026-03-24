#!/usr/bin/env bash
# Wrapper: create DB from .env.dev (see setup_local_postgres_from_env.sh).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT/scripts/setup_local_postgres_from_env.sh" "$ROOT/.env.dev"
