# CarniTrack

Django 5 application for slaughterhouse operations: reception, processing, inventory, labeling, reporting, and integrations. It uses PostgreSQL, Tailwind CSS (via `django-tailwind`), Google Cloud Storage for file storage in non-local environments, and is designed to run on **Cloud Run** with **Cloud SQL** in production.

## Prerequisites

- **Python 3.11** on your PATH as `python3` (the Makefile uses `python3`; override with `make dev PYTHON=/path/to/python` if needed).
- **Node.js 20** — for building Tailwind assets (`theme/static_src`).
- **PostgreSQL 15** for local development — either installed locally or via `docker-compose.yml`.
- **Google Cloud SDK** (`gcloud`) — for staging and production database access through the proxy.
- **Cloud SQL Auth Proxy v1** — place the `cloud_sql_proxy` binary in the repository root (see [Cloud SQL Proxy](https://cloud.google.com/sql/docs/postgres/sql-proxy)). The Makefile invokes `./cloud_sql_proxy` for staging; production proxy targets use the same binary by default.

## Development quickstart

From a fresh clone, set up Python and frontend assets first. Install dependencies with the same `python3` you use to run Django (user-level or system `pip` is fine).

**1. pip and Tailwind (one command)**

```bash
make install-deps
```

This runs `pip install -r requirements.txt` and `npm ci && npm run build` in `theme/static_src` (same pattern as CI).

Equivalent manual steps:

```bash
pip install -r requirements.txt
cd theme/static_src && npm ci && npm run build && cd ../..
```

You can also run `make pip-install` or `make tailwind-build` separately. Use `npm run dev` in `theme/static_src` for Tailwind watch mode while editing styles.

**2. Database and run server**

```bash
cp env/examples/.env.dev.example .env.dev
make db-setup-dev
make migrate-dev && make dev
```

Django serves on [http://127.0.0.1:8000](http://127.0.0.1:8000).

**Postgres in Docker (optional):** `docker compose up -d` first, then the same commands. Credentials in `env/examples/.env.dev.example` match the compose service.

## Staging quickstart

One-time GCP credentials:

```bash
gcloud auth application-default login
```

Then:

```bash
cp env/examples/.env.staging.example .env.staging
# Set DB_PASSWORD, then:
make migrate-staging && make staging
```

`make staging` and `make migrate-staging` start the Cloud SQL Proxy to staging on port **5433** and stop it when the command exits. For a long-running proxy only: `make proxy-staging`.

## Tests

Tests use `config.settings_test` and are configured in `setup.cfg`.

- **Default (SQLite in-memory, fast):**

  ```bash
  make test
  # or:
  pytest
  ```

- **Coverage locally:**

  ```bash
  make test-cov
  # or:
  pytest --cov --cov-fail-under=59.50 --cov-report=term-missing
  ```

  The full SQLite suite in CI enforces the same `59.50%` minimum. For partial marker or app-only runs, either skip coverage or override with `--cov-fail-under=0`.

  To scope either target, pass `TEST_ARGS`, for example `make test TEST_ARGS='processing/'` or `make test TEST_ARGS='-m "integration or not slow" -q'`.

- **PostgreSQL (closer to production):** set `USE_POSTGRES_FOR_TESTS=true` and the `TEST_DB_*` variables (see `.github/workflows/ci.yml` `test-postgres` job), then for example:

  ```bash
  USE_POSTGRES_FOR_TESTS=true \
  TEST_DB_HOST=localhost TEST_DB_PORT=5432 \
  TEST_DB_NAME=test_carnitrack TEST_DB_USER=postgres TEST_DB_PASSWORD=postgres \
  pytest -m "integration or not slow"
  ```

Before running tests locally, ensure dependencies and CSS are built: `make install-deps` or at least `make tailwind-build`.

## Environments

| Env       | Database                                      | GCS                                   | How to run                                      |
| --------- | --------------------------------------------- | ------------------------------------- | ----------------------------------------------- |
| `dev`     | Local Postgres `carnitrack_dev`               | Local filesystem                      | `make dev`                                      |
| `staging` | GCP Cloud SQL `carnitrack-db-belgium-staging` | `gs://carnitrack-bucket/staging/`     | `make staging` (proxy auto-started)             |
| `prod`    | GCP Cloud SQL `carnitrack-db-belgium`         | `gs://carnitrack-bucket/`             | Cloud Run (CI/CD); local prod-like: see Makefile |

## Deploying

Production deploy is scripted as **`scripts/deploy_prod.sh`** and wired to **`make prod-deploy`**. Runtime configuration for Cloud Run is supplied via **`env.yaml`** (gitignored); copy from **`env/examples/env.yaml.example`** and edit.

## Environment templates

Committed templates live under **`env/examples/`** (`.env.dev.example`, `.env.staging.example`, `.env.production.example`, `env.yaml.example`). Copy them to the repo root as `.env.dev`, `.env.staging`, `.env.production`, or `env.yaml` as needed; those generated files stay gitignored.

## Documentation

Specs, reports, and notes are in **`docs/`** (for example `docs/DJANGO_CLOUD_INTEGRATION_SPEC.md`, `docs/IOT_SCALE_INTEGRATION_PLAN.md`, `docs/CODEBASE_ANALYSIS_REPORT.md`, `docs/TESTING_REPORT.md`, `docs/MULTI_TENANT_CHECKLIST.md`).

## Makefile reference

| Target               | Description |
| -------------------- | ----------- |
| `make install-deps`  | `pip install -r requirements.txt` + `npm ci` / `npm run build` for Tailwind. |
| `make pip-install`   | Install Python packages from `requirements.txt`. |
| `make tailwind-build`| Build Tailwind assets under `theme/static_src`. |
| `make test`          | Run `pytest`; pass selectors or flags with `TEST_ARGS='...'`. |
| `make test-cov`      | Run `pytest` with the local coverage gate (`59.50%` by default). |
| `make dev`           | Run Django with `.env.dev` (local Postgres). |
| `make staging`       | Start staging Cloud SQL Proxy on 5433, run Django with `.env.staging`, stop proxy on exit. |
| `make production-local` | Gunicorn on `:8080` with `.env.production`; run `make proxy` separately for prod DB. |
| `make prod-deploy`   | Build, push, and deploy to Cloud Run (`scripts/deploy_prod.sh`). |
| `make db-setup-dev`  | Create local Postgres role and database from `.env.dev`. |
| `make migrate-dev`   | Migrations using `.env.dev`. |
| `make migrate-staging` | Staging proxy + migrations using `.env.staging`. |
| `make import-prod-dev` | Destructive: wipe dev DB and load `db_exports/prod.sql`. |
| `make proxy`         | Cloud SQL Proxy (production instance) → `127.0.0.1:5434`. |
| `make proxy-v2`      | Same as `proxy` using `cloud-sql-proxy` CLI. |
| `make proxy-staging` | Staging instance → `127.0.0.1:5433`. |

Override env file paths, ports, or instance names via Makefile variables (see `Makefile` `help` and comments).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
