# Database exports (local only)

Put **`pg_dump`** / **`pg_restore`** artifacts here so the repo root stays clean.

- Files in this directory are **ignored by git** (they often contain **production data**).
- **Plain SQL:** name it **`prod.sql`** (preferred by the import script).
- **Custom format:** name it **`prod.dump`**.

## Full prod copy into local dev or staging

**Do not run `migrate` before import** — an empty database + dump is required, or you get “relation already exists”.

From the repo root:

```bash
make import-prod-staging   # or: make import-prod-dev
make migrate-staging     # or: make migrate-dev
```

This **drops** the target database and recreates it, then loads `prod.sql` if present, otherwise `prod.dump`.

Manual example (staging):

```bash
bash scripts/import_prod_copy.sh staging
CARNITRACK_ENV=staging python manage.py migrate
```

Do not commit exports.
