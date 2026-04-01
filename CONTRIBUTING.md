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

Use a **virtual environment** so dependencies match CI and do not touch system Python:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

The [Makefile](Makefile) defaults `PYTHON` to **`.venv/bin/python`** when that path exists (otherwise `python3`). So after creating `.venv`, `make install-deps`, `make dev`, and `make migrate-dev` all use the venv without extra flags.

After cloning, you can install Python and frontend build tooling in one step (matches CI):

```bash
make install-deps
```

This runs `pip install -r requirements.txt` and `npm ci && npm run build` under `theme/static_src`. See [README.md](README.md) for the full dev quickstart.

Run tests and one-off commands with the same interpreter, for example:

```bash
.venv/bin/python -m pytest
.venv/bin/python manage.py migrate
```

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
