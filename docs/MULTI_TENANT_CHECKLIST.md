# CarniTrack Multi-Tenant Migration Checklist

> Pivot from single-tenant to schema-isolated multi-tenant SaaS under **samperlabs.com**
> using `django-tenants`, PostgreSQL schema-per-client, fully isolated users, Redis caching,
> and subdomain routing (`{client}.carnitrack.samperlabs.com`).

---

## Phase 0 -- Pre-Migration Groundwork

### DNS and Domain

- [ ] Purchase/configure DNS for `samperlabs.com`
- [ ] Set up `carnitrack.samperlabs.com` as public/landing subdomain
- [ ] Configure wildcard DNS: `*.carnitrack.samperlabs.com` -> Cloud Run / LB
- [ ] Obtain wildcard SSL certificate for `*.carnitrack.samperlabs.com`

### GCP Infrastructure

- [ ] Set up **Global HTTPS Load Balancer** with Serverless NEG -> Cloud Run (Cloud Run does NOT support wildcard domain mapping natively) -- OR put **Cloudflare** in front as reverse proxy
- [ ] Attach wildcard SSL cert to the LB (or Cloudflare)
- [ ] Map `carnitrack.samperlabs.com` to the Cloud Run service
- [ ] Verify Cloud SQL connectivity from new infra if network topology changes

### Repository Cleanup

- [ ] Verify `django-tenants` compatibility with Django 5.2.5 (check release notes / test install)
- [ ] Keep `env/examples/` templates up to date for developer onboarding
- [ ] Remove unused deps from `requirements.txt`: `dj-database-url`, `cloud-sql-python-connector`
- [ ] Rename GCP project references from "carnitrack" to reflect SamperLabs ownership where needed

---

## Phase 1 -- django-tenants + Redis Integration

### 1.1 Install Dependencies

- [ ] Add `django-tenants` to `requirements.txt`
- [ ] Add `django-redis` and `redis` to `requirements.txt`
- [ ] `pip install` and verify imports

### 1.2 Create `tenants` App

- [ ] `python manage.py startapp tenants`
- [ ] Define **Client** model (extends `TenantMixin`) with fields:
  - [ ] `name` (display name)
  - [ ] `slug` (subdomain identifier)
  - [ ] `company_name` (was `settings.COMPANY_NAME` = `"GUNDOGDULAR GIDA"`)
  - [ ] `company_full_name` (was `settings.COMPANY_FULL_NAME`)
  - [ ] `company_address` (was `settings.COMPANY_ADDRESS`)
  - [ ] `license_no` (was `settings.LICENSE_NO` = `"17-0509"`)
  - [ ] `operation_no` (was `settings.OPERATION_NO` = `"4290056890"`)
  - [ ] `contact_email`, `contact_phone`
  - [ ] `is_active`, `created_on`
  - [ ] `printer_turkish_mode` (was `settings.PRINTER_TURKISH_MODE`)
  - [ ] `logo` (ImageField for tenant branding)
  - [ ] `timezone`, `language_code` (per-tenant locale)
- [ ] Define **Domain** model (extends `DomainMixin`)
- [ ] Define **PlatformAdmin** model (shared/public schema, for SamperLabs staff)
- [ ] Register models in `tenants/admin.py`

### 1.3 Configure Settings (`config/settings.py`)

- [ ] Change DB engine to `django_tenants.postgresql_backend`
- [ ] Set `DATABASE_ROUTERS = ["django_tenants.routers.TenantSyncRouter"]`
- [ ] Set `TENANT_MODEL = "tenants.Client"`
- [ ] Set `TENANT_DOMAIN_MODEL = "tenants.Domain"`
- [ ] Define `SHARED_APPS` (complete list):
  - `django_tenants`
  - `django.contrib.contenttypes`
  - `django.contrib.admin`
  - `django.contrib.messages`
  - `django.contrib.staticfiles`
  - `tenants`
  - `tailwind` (model-less, safe as shared)
  - `widget_tweaks` (model-less)
  - `theme` (model-less)
  - `storages` (model-less)
- [ ] Define `TENANT_APPS` (complete list):
  - `django.contrib.contenttypes` (must be in both)
  - `django.contrib.auth` (User table per tenant)
  - `django.contrib.sessions`
  - `django_fsm` (used by processing/inventory FSM fields)
  - `users`
  - `core`
  - `reception`
  - `processing`
  - `inventory`
  - `labeling`
  - `reporting`
  - `scales`
  - `portal`
- [ ] Set `INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]`
- [ ] Remove hardcoded company info from settings (lines 238-242): `COMPANY_NAME`, `COMPANY_FULL_NAME`, `COMPANY_ADDRESS`, `LICENSE_NO`, `OPERATION_NO`
- [ ] Remove `PRINTER_TURKISH_MODE` from settings (moved to Client model)
- [ ] Remove `SITE_URL` from settings (will be derived per-tenant)

### 1.4 Redis Cache and Session Setup

- [ ] Deploy Redis: GCP Memorystore (managed) or Cloud Run sidecar
- [ ] Add `REDIS_URL` to `.env`, `.env.production`, `env.yaml`
- [ ] Configure `CACHES` in settings with `django_redis.cache.RedisCache`
- [ ] Set `KEY_FUNCTION = "django_tenants.cache.make_key"` (tenant-prefixed cache keys)
- [ ] Set `REVERSE_KEY_FUNCTION = "django_tenants.cache.reverse_key"`
- [ ] Set `SESSION_ENGINE = "django.contrib.sessions.backends.cache"`
- [ ] Set `SESSION_CACHE_ALIAS = "default"`

### 1.5 Add Tenant Middleware

- [ ] Add `django_tenants.middleware.main.TenantMainMiddleware` as **first** entry in `MIDDLEWARE` (before `SecurityMiddleware`)

### 1.6 Update URL Configuration

- [ ] Set `PUBLIC_SCHEMA_URLCONF = "config.urls_public"`
- [ ] Create `config/urls_public.py` with landing page + platform admin routes
- [ ] Verify Edge API (`/api/v1/edge/`) is **NOT** included in `urls_public.py`

### 1.7 Run Initial Migrations

- [ ] `python manage.py makemigrations tenants`
- [ ] `python manage.py migrate_schemas --shared`

---

## Phase 2 -- Model and Data Architecture Changes

### 2.1 ClientProfile (No Move Needed)

- [ ] Confirm `users.ClientProfile` stays in `users` app (both User and ClientProfile are tenant-scoped, no cross-schema FK issues)
- [ ] Confirm FK chain `reception.SlaughterOrder -> users.ClientProfile -> users.User` works within same tenant schema

### 2.2 Reconcile `scales.Site` with Tenant Model

- [ ] Keep `Site` in tenant schema (backward compat with EdgeDevice registration)
- [ ] Auto-create one `Site` per tenant during provisioning
- [ ] Verify `api_key` field on `Site` still aligns with Edge device auth

### 2.3 Company Info -> Tenant Model

- [ ] Refactor `get_company_info()` in `labeling/utils.py` (line 1840) to read from `connection.tenant` instead of `settings`:
  ```
  BEFORE: getattr(settings, "COMPANY_NAME", "GUNDOGDULAR GIDA")
  AFTER:  connection.tenant.company_name
  ```
- [ ] Update `labeling/tests_utils.py` (lines 179-182) to use tenant fixture instead of `settings.COMPANY_NAME`
- [ ] Remove company settings from `config/settings_test.py` (lines 158-162)

### 2.4 Tenant Context Processor

- [ ] Create `tenants/context_processors.py` with `tenant_context(request)` returning `{"tenant": request.tenant}`
- [ ] Add to `TEMPLATES[0]["OPTIONS"]["context_processors"]` in settings
- [ ] Verify `{{ tenant.company_name }}`, `{{ tenant.logo.url }}` available in templates

### 2.5 SITE_URL Per-Tenant (QR Codes / Links)

> **Risk:** If `SITE_URL` stays global, all QR codes on meat labels across all tenants will point to the same host.

- [ ] Create `get_tenant_site_url()` helper that derives URL from tenant's primary Domain record
- [ ] Update `labeling/utils.py` **line 177** -- replace `getattr(settings, "SITE_URL", ...)` with `get_tenant_site_url()`
- [ ] Update `labeling/utils.py` **line 479** -- same replacement
- [ ] Update `users/views.py` **line 63-67** -- replace `settings.SITE_URL` host check with `request.get_host()`
- [ ] Remove `SITE_URL` from `config/settings.py` (line 235) and `config/settings_test.py` (line 155)

### 2.6 GCS Media Isolation (Object Key Collision Prevention)

> **Risk:** Without per-tenant prefix, two tenants with same animal tag (e.g., `TR123456`) will overwrite each other's files at `animal_pictures/TR123456_photo.jpg`.

Affected `upload_to` paths:
- `processing/models.py`: `animal_pictures/{tag}_photo.{ext}`
- `processing/models.py`: `animal_passports/{tag}_passport.{ext}`
- `processing/models.py`: `scale_receipts/{tag}_receipt.{ext}`
- `labeling/models.py`: `animal_labels/pdf/`
- `labeling/models.py`: `custom_labels/pdf/`

- [ ] Create `tenants/storage.py` with `TenantGCSStorage` that prefixes object keys with `connection.schema_name`
- [ ] Set `STORAGES["default"]["BACKEND"] = "tenants.storage.TenantGCSStorage"` in settings
- [ ] Verify existing `upload_to` callables in `processing/models.py` generate only relative paths (they do -- no change needed)
- [ ] **Migration task:** Move existing GCS objects from `animal_pictures/...` to `gundogdular/animal_pictures/...` using `gsutil mv`
- [ ] Update DB file path column values to match new prefixed paths

---

## Phase 3 -- Auth and User Management

### 3.1 Tenant-Scoped Auth (Mostly Works As-Is)

- [ ] Verify `CustomLoginView` works on tenant subdomains (TenantMainMiddleware sets schema -> auth queries tenant's `users_user` table)
- [ ] Verify `User.role`, `role_required`, `manager_or_admin_required` decorators work unchanged
- [ ] Verify sessions in Redis are tenant-prefixed (no cross-tenant session leakage)

### 3.2 SamperLabs Platform Admin (Public Schema Has No `auth_user`)

> **Constraint:** `django.contrib.auth` is in TENANT_APPS only. Public schema has no `auth_user` table. `createsuperuser` will NOT work on public schema. `django.contrib.admin` login on `carnitrack.samperlabs.com/admin/` will fail.

- [ ] Create `PlatformAdmin` model in `tenants` app with: `email`, `password`, `name`, `is_active`, `last_login`
- [ ] Create custom auth backend `tenants/auth_backends.py` for `PlatformAdmin`
- [ ] Build platform admin dashboard at `carnitrack.samperlabs.com/platform-admin/` (NOT using `django.contrib.admin`)
- [ ] Platform admin capabilities: create/deactivate tenants, view tenant list, trigger provisioning
- [ ] Per-tenant Django admin works at `{tenant}.carnitrack.samperlabs.com/admin/` using tenant's `users.User` -- no changes needed

### 3.3 User Registration Within a Tenant

- [ ] Verify existing `RegisterView` creates users in current tenant schema
- [ ] Verify `ClientProfileRegisterView` works within tenant context
- [ ] No tenant self-signup for now (SamperLabs provisions manually)

---

## Phase 4 -- Template and Frontend Changes

### 4.1 Tenant-Aware Base Template

- [ ] Update `theme/templates/base.html` to show tenant branding from `{{ tenant }}`
- [ ] Replace any hardcoded "GUNDOGDULAR" or "CarniTrack" references with `{{ tenant.name }}`
- [ ] Add tenant logo display: `{{ tenant.logo.url }}`

### 4.2 Label Generation (Per-Tenant Company Info on Labels)

- [ ] Verify `get_company_info()` refactor from Phase 2.3 propagates to all label formats (PRN, BAT, PDF)
- [ ] Test label generation for two different tenants and confirm different company info appears
- [ ] Verify `PRINTER_TURKISH_MODE` reads from tenant model instead of settings

### 4.3 Public Landing Page

- [ ] Create server-rendered landing page for `carnitrack.samperlabs.com` (public schema)
- [ ] Include product info, tenant login redirect (link to `{slug}.carnitrack.samperlabs.com`)
- [ ] Later: replace with separate Firebase-hosted frontend

---

## Phase 5 -- Edge API Multi-Tenancy

### 5.1 Subdomain Dependency

> **Critical:** `EdgeDevice.objects.get(id=edge_uuid, is_active=True)` in `scales/middleware.py` (line 39) has NO explicit tenant filter. It relies entirely on `TenantMainMiddleware` having set `connection.schema_name` from the HTTP host. Edge devices MUST call the correct tenant subdomain.

- [ ] Verify Edge API works on tenant subdomains (auto-scoped by TenantMainMiddleware)
- [ ] Verify `/api/v1/edge/register` creates EdgeDevice in correct tenant schema
- [ ] Add tenant `baseUrl` to config endpoint response so Edge devices can self-configure

### 5.2 Edge Device Reconfiguration (Deployment Coordination)

- [ ] Inventory all physical Edge devices and their current API endpoint config
- [ ] **Before DNS cutover:** Update each Edge device config to call `https://{tenant}.carnitrack.samperlabs.com/api/v1/edge/...`
- [ ] Verify existing Edge device UUIDs are valid in tenant schema after data migration
- [ ] Plan for old Cloud Run URL (`carnitrack-app-*.run.app`) to stop working after cutover

### 5.3 Edge API URL Routing

- [ ] Verify Edge API (`/api/v1/edge/`) is in root URLconf (not language-prefixed)
- [ ] Verify Edge API is NOT included in `config/urls_public.py`

---

## Phase 6 -- Data Migration and Management Commands

### 6.1 Migrate Existing Data (HIGHEST RISK)

- [ ] **Clone Cloud SQL database** for testing -- NEVER run migration on production first
- [ ] Write migration script:
  1. [ ] Create public schema with shared tables (`tenants_client`, `tenants_domain`, `tenants_platformadmin`)
  2. [ ] Create first tenant Client record: slug=`gundogdular`, company_name=`GUNDOGDULAR GIDA`, license_no=`17-0509`, operation_no=`4290056890`, company_address=`BOZALAN - EZINE / CANAKKALE`, company_full_name=`SAN VE TUR. TIC. LTD STI`
  3. [ ] Create first Domain record: domain=`gundogdular.carnitrack.samperlabs.com`, is_primary=True
  4. [ ] Run `migrate_schemas --schema=gundogdular` to create tenant tables
  5. [ ] Copy ALL existing data into `gundogdular` schema (users, orders, animals, processing, inventory, labels, reports, scales)
  6. [ ] Reset auto-increment sequences in new schema
  7. [ ] Clean up old data from public schema
- [ ] Write rollback script
- [ ] Test migration on DB clone -- verify data integrity
- [ ] Test migration on DB clone -- verify all FK relationships intact
- [ ] Execute on production (during maintenance window)

### 6.2 GCS Media Migration

- [ ] Script `gsutil mv` to move objects: `animal_pictures/...` -> `gundogdular/animal_pictures/...` (and all other upload paths)
- [ ] Update file path columns in DB to match new prefixed paths
- [ ] Verify no broken image/file links in UI

### 6.3 Update Management Commands

- [ ] `seed_plu` -- run via `tenant_command seed_plu --schema=<tenant>`
- [ ] `generate_daily_reports` -- iterate over all tenants or accept `--schema`
- [ ] `setup_system_user` -- create per-tenant (lives in tenant schema now)
- [ ] `setup_default_reports` -- run per-tenant schema
- [ ] `create_test_data` -- run per-tenant

### 6.4 Create Tenant Provisioning Command

- [ ] Create `manage.py create_tenant` that:
  1. Creates Client record and Domain record
  2. Runs `migrate_schemas --schema=<new_tenant>`
  3. Seeds default data (PLU items, report definitions, ServicePackages)
  4. Creates tenant admin user
  5. Creates `Site` + initial EdgeDevice config
  6. Creates SamperLabs admin user in the tenant (if using Option B for platform admin)

### 6.5 Schema Migrations Strategy

- [ ] Replace `python manage.py migrate` with `python manage.py migrate_schemas` in all scripts/docs
- [ ] Update CI to run `migrate_schemas --shared` and `migrate_schemas --schema=test`
- [ ] Add migration tests for both shared and tenant schemas

---

## Phase 7 -- Deployment

### 7.1 Dockerfile

- [ ] Verify `django-tenants` and `django-redis` install correctly in Docker build
- [ ] Add `redis` client library to system deps if needed
- [ ] `collectstatic` remains unchanged (static files are shared)

### 7.2 Cloud Run Deployment

- [ ] Update `deploymenthatactuallyworks.sh`:
  - [ ] Add domain mapping / LB setup commands
  - [ ] Add `REDIS_URL` to env vars
  - [ ] Remove `COMPANY_NAME`, `LICENSE_NO`, etc. from `env.yaml`
  - [ ] Add `TENANT_DEFAULT_SCHEMA` if needed
- [ ] Update `env.yaml` with new variables

### 7.3 ALLOWED_HOSTS and CSRF

- [ ] Set `ALLOWED_HOSTS = [".carnitrack.samperlabs.com", "localhost", "127.0.0.1"]`
- [ ] Set `CSRF_TRUSTED_ORIGINS = ["https://*.carnitrack.samperlabs.com"]`
- [ ] Remove old Cloud Run / ngrok hosts from ALLOWED_HOSTS

---

## Phase 8 -- Testing

### 8.1 Update Test Infrastructure

- [ ] Switch `config/settings_test.py` to `django_tenants.postgresql_backend`
- [ ] Remove SQLite test path from CI (django-tenants requires PostgreSQL)
- [ ] Add `TenantTestCase` base class from django-tenants for all tests
- [ ] Update `conftest.py` with tenant-aware fixtures (create test tenant in setUp)

### 8.2 Critical Test Cases

- [ ] **Tenant isolation:** Data in schema A is invisible from schema B
- [ ] **Label generation:** Two tenants produce labels with their own company info
- [ ] **QR codes:** Each tenant's QR URLs point to their own subdomain
- [ ] **GCS uploads:** Files are stored under tenant-prefixed paths, no collision
- [ ] **Edge API:** Edge device in tenant A returns 404 when called on tenant B's subdomain
- [ ] **Auth:** User in tenant A cannot log in on tenant B's subdomain
- [ ] **Redis sessions:** Session from tenant A is not accessible in tenant B
- [ ] **Tenant provisioning:** End-to-end create_tenant command works
- [ ] **Migration rollback:** Rollback script restores pre-migration state

---

## Phase 9 -- Monitoring, Operations, and Onboarding

### 9.1 Tenant-Aware Logging

- [ ] Add tenant schema name to all log entries (middleware or logging filter)
- [ ] Tag Cloud Run logs with tenant slug for per-tenant filtering

### 9.2 Monitoring

- [ ] Set up per-tenant metrics (request count, error rate, response time)
- [ ] Database monitoring: schema sizes, slow queries per tenant
- [ ] Redis monitoring: memory usage, key count per tenant prefix

### 9.3 Backup Strategy

- [ ] Cloud SQL automated backups cover all schemas
- [ ] Script per-schema `pg_dump` for tenant-level restores
- [ ] Document restore procedure for single-tenant recovery

### 9.4 Tenant Onboarding Automation

- [ ] Build onboarding flow (script or admin UI):
  1. Collect client info (company name, license, address, contact)
  2. Run `create_tenant` command
  3. DNS: automatic with wildcard (no per-tenant config needed)
  4. Send welcome email with credentials
  5. Seed initial data (PLU, reports, ServicePackages)

### 9.5 Tenant Offboarding

- [ ] Deactivate tenant: set `is_active=False` on Client model
- [ ] Middleware returns 404/403 for inactive tenants
- [ ] Data export: `pg_dump` of tenant schema
- [ ] Schema deletion: after retention period

---

## Phase 10 -- Future (Separate Frontend)

- [ ] Create separate repo for `carnitrack.samperlabs.com` frontend
- [ ] Host on Firebase Hosting
- [ ] Django serves only API + tenant subdomains
- [ ] Eventually add Django REST Framework for proper API layer
- [ ] Tenant subdomains serve SPA frontend (React/Vue)

---

## Risk Register

| # | Risk | Impact | Mitigation |
|---|------|--------|------------|
| 1 | Data loss during migration | Critical | Clone Cloud SQL DB, test on clone first, write rollback script |
| 2 | Wildcard subdomain SSL/routing on GCP | Blocks launch | Use Cloudflare as proxy OR GCP Global HTTPS LB |
| 3 | django-tenants + Django 5.2 compat | Blocks Phase 1 | Verify before starting (test install + run) |
| 4 | Edge devices calling wrong host | Edge API down | Coordinate device reconfiguration before DNS cutover (Phase 5.2) |
| 5 | GCS object key collisions | Data corruption | `TenantGCSStorage` must be in place BEFORE 2nd tenant (Phase 2.6) |
| 6 | QR codes pointing to wrong host | Wrong labels in production | Replace `SITE_URL` with tenant-derived URLs (Phase 2.5) |
| 7 | Public schema has no `auth_user` | Admin login broken | Build `PlatformAdmin` custom auth (Phase 3.2) |
| 8 | `django_fsm` in wrong app list | FSM transitions fail | Must be in TENANT_APPS (Phase 1.3) |
| 9 | Redis downtime | All sessions lost | Configure persistence, consider DB session fallback |
| 10 | GCS media path migration missed | Broken images | Script `gsutil mv` + update DB paths (Phase 6.2) |

---

## Execution Order

```
Phase 0  DNS + GCP infra + cleanup .............. (no code changes, start immediately)
Phase 1  django-tenants + Redis integration ..... (core architectural change)
Phase 2  Model refactoring + tenant context ..... (depends on Phase 1)
Phase 3  Auth overhaul .......................... (depends on Phase 2)
Phase 4  Template / frontend updates ............ (can parallel with Phase 3)
Phase 5  Edge API updates ....................... (depends on Phase 2)
Phase 6  Data migration + commands .............. (depends on Phases 1-5)
Phase 7  Deployment ............................. (depends on Phases 0 + 6)
Phase 8  Testing ................................ (continuous, focused after Phase 7)
Phase 9  Operations tooling ..................... (post-deploy)
Phase 10 Frontend separation .................... (independent timeline)
```
