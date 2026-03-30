# Contributing to CarniTrack

## Branches

Use a short, descriptive prefix:

- `feature/` — new functionality
- `fix/` — bug fixes
- `chore/` — tooling, dependencies, maintenance

Example: `feature/slaughter-batch-export`, `fix/inventory-qty-rounding`.

## Pull requests

- Open feature and fix branches against **`develop`**.
- Releases and production promotion flow **`develop` → `main`** as your team agrees.
- Keep PRs focused; reference issues when applicable.

## Local setup (dependencies)

After cloning, install Python and frontend build tooling (matches CI):

```bash
make install-deps
```

This runs `pip install -r requirements.txt` and `npm ci && npm run build` under `theme/static_src`. See [README.md](README.md) for the full dev quickstart.

## Code style

- Python is linted and formatted with **Ruff** in CI (`ruff check .`, `ruff format --check`).
- Run Ruff locally before pushing:

  ```bash
  ruff check .
  ruff format --check .
  ```

## Loading production-like data locally

To replace the **dev** database with a prod export (destructive):

```bash
make import-prod-dev
```

See `db_exports/README.md` for export format and expectations.

## GitHub Actions secrets (CI/CD)

These are used for keyless deploys and injecting production configuration. Exact job wiring lives in `.github/workflows/ci.yml`.

| Secret                             | Purpose |
| ---------------------------------- | ------- |
| `GCP_WORKLOAD_IDENTITY_PROVIDER`   | Workload Identity Federation — authenticate GitHub Actions to GCP without long-lived JSON keys. |
| `GCP_SERVICE_ACCOUNT`              | Service account email used for deploy (Artifact Registry, Cloud Run, etc.). |
| `PROD_ENV_YAML`                    | Full contents of the real `env.yaml` for production; injected at deploy time (never commit this file). |

Coordinate with a maintainer to rotate credentials or add new secrets.
