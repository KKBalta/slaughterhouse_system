# CarniTrack — run and deploy by environment
#
# Env files use shell-safe KEY=value lines; python-decouple picks them up.
#
# Environments:
#   dev     — local Postgres (carnitrack_dev). No proxy needed.
#   staging — GCP Cloud SQL staging instance via proxy (auto-started by make staging).
#   prod    — Cloud Run + Cloud SQL. Deploy via make prod-deploy.

.DEFAULT_GOAL := help

# Prefer ./.venv when present (create with: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)
# Override: make dev PYTHON=/usr/bin/python3
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
MANAGE := $(PYTHON) manage.py
# Use the pytest entrypoint directly so the active test runner stays aligned
# with the environment's installed interpreter.
PYTEST ?= $(shell if [ -x .venv/bin/pytest ]; then echo .venv/bin/pytest; else echo pytest; fi)
TEST_ARGS ?=
COVERAGE_MIN ?= 59.50

DEV_ENV     ?= .env.dev
STAGING_ENV ?= .env.staging
PROD_ENV    ?= .env.production

# Production Cloud SQL (used by proxy / proxy-v2 and production-local)
CLOUDSQL_INSTANCE ?= carnitrack:europe-west1:carnitrack-db-belgium
PROXY_PORT        ?= 5434

# Staging Cloud SQL (auto-used by make staging)
STAGING_CLOUDSQL_INSTANCE ?= carnitrack:europe-west1:carnitrack-db-belgium-staging
STAGING_PROXY_PORT        ?= 5433

CLOUD_SQL_PROXY_V1 ?= ./cloud_sql_proxy
CLOUD_SQL_PROXY_V2 ?= cloud-sql-proxy

TAILWIND_DIR ?= theme/static_src

# Tenant schema for create_tenant_superuser (must match Client.schema_name, e.g. dev for dev.localhost)
SCHEMA ?= dev

.PHONY: help dev staging production-local prod-deploy proxy proxy-v2 proxy-staging migrate-dev migrate-staging import-prod-dev import-prod-staging db-setup-dev pip-install tailwind-build install-deps tenant-superuser-dev redis-shell test test-cov

help:
	@echo "CarniTrack Makefile"
	@echo ""
	@echo "  make install-deps       First-time setup: pip install -r requirements.txt + Tailwind build ($(TAILWIND_DIR))"
	@echo "  make pip-install        pip install -r requirements.txt ($(PYTHON))"
	@echo "  make tailwind-build     cd $(TAILWIND_DIR) && npm ci && npm run build"
	@echo "  make test               Run pytest (pass extra args with TEST_ARGS='...')"
	@echo "  make test-cov           Run pytest with coverage gate ($(COVERAGE_MIN)%)"
	@echo ""
	@echo "  make dev                Django runserver — local Postgres ($(DEV_ENV))"
	@echo "  make staging            Django runserver — GCP Cloud SQL staging via proxy ($(STAGING_ENV))"
	@echo "                          (proxy starts automatically on port $(STAGING_PROXY_PORT) and stops on exit)"
	@echo "  make production-local   Gunicorn on :8080 — needs $(PROD_ENV) + proxy running"
	@echo "  make prod-deploy        Docker build/push + Cloud Run deploy"
	@echo ""
	@echo "  make db-setup-dev       Create local Postgres role+DB from $(DEV_ENV)"
	@echo "  make migrate-dev        Run migrations using $(DEV_ENV)"
	@echo "  make tenant-superuser-dev  createsuperuser in tenant DB (SCHEMA=$(SCHEMA) by default; needs a Client + Domain)"
	@echo "  make migrate-staging    Run migrations using $(STAGING_ENV)"
	@echo "  make import-prod-dev    Wipe dev DB + load db_exports/prod.sql (destructive)"
	@echo ""
	@echo "  make redis-shell        Open redis-cli inside the docker compose redis container"
	@echo ""
	@echo "  make proxy              Cloud SQL Proxy v1 (prod) → 127.0.0.1:$(PROXY_PORT)"
	@echo "  make proxy-v2           Cloud SQL Proxy v2 (prod) → 127.0.0.1:$(PROXY_PORT)"
	@echo "  make proxy-staging      Cloud SQL Proxy v1 (staging) → 127.0.0.1:$(STAGING_PROXY_PORT)"
	@echo ""
	@echo "First time (dev):     make install-deps && cp env/examples/.env.dev.example .env.dev && make db-setup-dev && make migrate-dev && make dev"
	@echo "First time (staging): cp env/examples/.env.staging.example .env.staging  # fill in DB_PASSWORD, then:"
	@echo "                      make migrate-staging && make staging"
	@echo ""
	@echo "Override examples:"
	@echo "  make dev DEV_ENV=.env"
	@echo "  make proxy PROXY_PORT=5435 CLOUDSQL_INSTANCE=project:region:instance"
	@echo "  make test TEST_ARGS='processing/'"
	@echo "  make test TEST_ARGS='-m \"integration or not slow\" -q'"

dev:
	@if [ ! -f "$(DEV_ENV)" ]; then echo "Missing $(DEV_ENV) — run: cp env/examples/.env.dev.example .env.dev"; exit 1; fi
	bash -c 'set -a; . "$(DEV_ENV)"; set +a; $(MANAGE) runserver'

staging:
	@if [ ! -f "$(STAGING_ENV)" ]; then echo "Missing $(STAGING_ENV) — run: cp env/examples/.env.staging.example .env.staging"; exit 1; fi
	@bash -c '\
		echo "Starting Cloud SQL Proxy for staging on port $(STAGING_PROXY_PORT)..."; \
		$(CLOUD_SQL_PROXY_V1) -instances=$(STAGING_CLOUDSQL_INSTANCE)=tcp:$(STAGING_PROXY_PORT) & \
		PROXY_PID=$$!; \
		sleep 2; \
		trap "echo Stopping Cloud SQL Proxy...; kill $$PROXY_PID 2>/dev/null" EXIT INT TERM; \
		set -a; . "$(STAGING_ENV)"; set +a; \
		$(MANAGE) runserver; \
	'

production-local:
	@if [ ! -f "$(PROD_ENV)" ]; then echo "Missing $(PROD_ENV)"; exit 1; fi
	bash -c 'set -a; . "$(PROD_ENV)"; set +a; gunicorn --bind :8080 --workers 1 --threads 8 --timeout 0 config.wsgi:application'

prod-deploy:
	bash scripts/deploy_prod.sh

proxy:
	$(CLOUD_SQL_PROXY_V1) -instances=$(CLOUDSQL_INSTANCE)=tcp:$(PROXY_PORT)

proxy-v2:
	$(CLOUD_SQL_PROXY_V2) --port $(PROXY_PORT) $(CLOUDSQL_INSTANCE)

proxy-staging:
	$(CLOUD_SQL_PROXY_V1) -instances=$(STAGING_CLOUDSQL_INSTANCE)=tcp:$(STAGING_PROXY_PORT)

pip-install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

tailwind-build:
	cd $(TAILWIND_DIR) && npm ci && npm run build

install-deps: pip-install tailwind-build

test:
	$(PYTEST) $(TEST_ARGS)

test-cov:
	$(PYTEST) --cov --cov-fail-under=$(COVERAGE_MIN) --cov-report=term-missing $(TEST_ARGS)

db-setup-dev:
	@if [ ! -f "$(DEV_ENV)" ]; then echo "Missing $(DEV_ENV) — run: cp env/examples/.env.dev.example .env.dev"; exit 1; fi
	@bash scripts/setup_local_postgres_from_env.sh "$(DEV_ENV)"

migrate-dev:
	@if [ ! -f "$(DEV_ENV)" ]; then echo "Missing $(DEV_ENV)"; exit 1; fi
	bash -c 'set -a; . "$(DEV_ENV)"; set +a; $(MANAGE) migrate'

# Per-tenant Django admin login: auth_user exists only in tenant schemas (not public).
tenant-superuser-dev:
	@if [ ! -f "$(DEV_ENV)" ]; then echo "Missing $(DEV_ENV)"; exit 1; fi
	bash -c 'set -a; . "$(DEV_ENV)"; set +a; $(MANAGE) create_tenant_superuser --schema="$(SCHEMA)"'

migrate-staging:
	@if [ ! -f "$(STAGING_ENV)" ]; then echo "Missing $(STAGING_ENV)"; exit 1; fi
	@bash -c '\
		echo "Starting Cloud SQL Proxy for staging on port $(STAGING_PROXY_PORT)..."; \
		$(CLOUD_SQL_PROXY_V1) -instances=$(STAGING_CLOUDSQL_INSTANCE)=tcp:$(STAGING_PROXY_PORT) & \
		PROXY_PID=$$!; \
		sleep 2; \
		trap "echo Stopping Cloud SQL Proxy...; kill $$PROXY_PID 2>/dev/null" EXIT INT TERM; \
		set -a; . "$(STAGING_ENV)"; set +a; \
		$(MANAGE) migrate; \
	'

import-prod-staging:
	@bash scripts/import_prod_copy.sh staging

import-prod-dev:
	@bash scripts/import_prod_copy.sh dev

redis-shell:
	docker compose exec redis redis-cli
