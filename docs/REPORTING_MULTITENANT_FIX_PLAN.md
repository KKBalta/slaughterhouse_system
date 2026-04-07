# Reporting Multitenant Gap Analysis And Fix Plan

Date: 2026-04-07

## Scope

This document covers the reporting paths that must be corrected for schema-isolated multitenant operation:

- interactive report generation
- scheduled daily report generation
- query correctness for report data
- report file storage and retrieval
- test coverage for tenant-specific behavior

## Current State

The reporting app is installed as a tenant app, so the base model placement is correct. The main gaps are not in model placement; they are in execution context, query design, and file handling.

Relevant code paths:

- `reporting/views.py`
- `reporting/services.py`
- `reporting/management/commands/generate_daily_reports.py`
- `reporting/management/commands/setup_default_reports.py`
- `reporting/management/commands/setup_system_user.py`
- `reporting/management/commands/create_test_data.py`
- `reporting/templates/reporting/report_list.html`
- `reporting/utils.py`

## Confirmed Gaps

### 1. Critical: background report execution loses tenant context

Files:

- `reporting/views.py:121`
- `reporting/views.py:131`
- `reporting/views.py:143`

Problem:

- `generate_daily_reports_api()` starts a new Python thread and calls `call_command("generate_daily_reports", ...)`.
- Django DB connections are thread-local.
- The new thread does not reliably inherit the active tenant schema set by `TenantMainMiddleware`.
- In multitenant mode this can execute on the wrong schema, usually public/default, or behave inconsistently.

Impact:

- scheduled reports can fail
- scheduled reports can read the wrong schema
- tenant-specific company headers and data may be incorrect

### 2. Critical: the command cannot target a tenant schema or all tenants

Files:

- `reporting/management/commands/generate_daily_reports.py:16`
- `reporting/management/commands/generate_daily_reports.py:41`
- `docs/MULTI_TENANT_CHECKLIST.md:290`

Problem:

- `generate_daily_reports` accepts date, report types, output format, and system user only.
- There is no `--schema` option.
- There is no `--all-tenants` mode.
- There is no explicit switch into `schema_context(...)`.

Impact:

- scheduler cannot safely generate reports per tenant
- platform-wide scheduled reporting cannot be implemented correctly
- operational scripts cannot target one tenant deterministically

### 3. High: report query filters are accepted by the service API but ignored

Files:

- `reporting/services.py:7`
- `reporting/services.py:21`

Problem:

- `ReportDataAggregator.__init__()` accepts `filters`, but `get_daily_slaughter_data()` never applies them.
- current query only filters by slaughter date and a hardcoded status list

Missing filter support:

- animal type
- client
- destination client
- service package
- status
- only active records
- explicit include/exclude walk-ins

Impact:

- report definitions with `default_filters` do not actually affect output
- tenant users cannot generate scoped reports with correct query predicates

### 4. High: date filtering is not tenant-timezone aware and uses a cast-based predicate

Files:

- `reporting/services.py:22`
- `reporting/management/commands/generate_daily_reports.py:50`

Problem:

- query uses `slaughter_date__date__range=[start_date, end_date]`
- this depends on DB/date casting and current connection timezone instead of explicit tenant-local boundaries
- scheduled reports use `(timezone.now() - timedelta(days=1)).date()` without considering `Client.timezone`

Impact:

- wrong day boundaries for tenants in different timezones
- slower queries because `__date` often prevents clean index usage

Required fix:

- resolve the tenant timezone from `connection.tenant.timezone`
- compute `[start_datetime, end_datetime)` boundaries in that timezone
- query with `slaughter_date__gte` and `slaughter_date__lt`

### 5. High: destination and client joins are incomplete for reporting semantics

Files:

- `reporting/services.py:213`
- `reporting/services.py:219`
- `reception/models.py:24`
- `reception/models.py:27`
- `reception/models.py:51`

Problem:

- `_get_destination()` uses `slaughter_order.destination` only
- it ignores `SlaughterOrder.destination_client`
- `_get_client_name()` does not normalize all `ClientProfile` display cases through one method such as `get_full_name()`

Impact:

- tenant reports can display wrong customer names
- destination-based filtering cannot be made correct until the source fields are unified

### 6. High: generated report files are not tenant-isolated

Files:

- `reporting/management/commands/generate_daily_reports.py:90`
- `reporting/management/commands/generate_daily_reports.py:92`
- `reporting/models.py:85`

Problem:

- files are written to `MEDIA_ROOT/reports/daily/<year>/<month>/daily_slaughter_<date>.xlsx`
- schema name is not part of the path
- the command writes directly with `os.path.join(...)` and `workbook.save(...)`, bypassing Django storage abstractions
- `GeneratedReport.file_path` is a plain `CharField`

Impact:

- different tenants generating the same report date can overwrite each other
- storage behavior differs from the rest of the multitenant media strategy
- download URLs cannot be safely derived from a raw string path

### 7. Medium: report archive UI is currently inconsistent with the model

Files:

- `reporting/templates/reporting/report_list.html:50`
- `reporting/templates/reporting/report_list.html:55`
- `reporting/templates/reporting/report_list.html:70`
- `reporting/templates/reporting/report_list.html:78`
- `reporting/models.py:62`

Problem:

- template uses `report.report.*` but the FK is `report_definition`
- template checks `completed` and `processing`, but model statuses are `success`, `failed`, `pending`
- template calls `report.file_path.url` even though `file_path` is a `CharField`

Impact:

- report archive/download UI is not reliable
- file retrieval needs a proper download path before multitenant rollout

### 8. Medium: reporting utility module is stale and uses obsolete query fields

Files:

- `reporting/utils.py:21`
- `reporting/utils.py:37`
- `reporting/utils.py:41`

Problem:

- `generate_report_data()` still expects old report types: `operational`, `financial`, `analytics`
- it queries `order_date`, but the actual field is `order_datetime`
- it is not aligned with the current `Report.REPORT_TYPE_CHOICES`

Impact:

- future contributors may reuse incorrect code
- stale helpers increase the chance of wrong queries re-entering the codebase

### 9. Medium: tenant bootstrap commands are not explicitly schema-aware

Files:

- `reporting/management/commands/setup_default_reports.py`
- `reporting/management/commands/setup_system_user.py`
- `reporting/management/commands/create_test_data.py`

Problem:

- these commands create tenant-scoped data but do not accept `--schema`
- they rely on the caller already being in the right schema

Impact:

- tenant provisioning is fragile
- automation scripts are harder to reason about

### 10. High: there are no reporting tests for multitenant execution flow

Files:

- `reporting/tests.py`
- `config/settings_test.py:26`

Problem:

- reporting tests run with `USE_MULTITENANT = False`
- there are no tests that verify schema capture, `schema_context(...)`, tenant-specific file paths, or tenant-timezone boundaries

Impact:

- regressions in tenant safety will not be caught in CI

## Target Design

### A. Separate query building from export formatting

Create a tenant-safe reporting query layer that:

- accepts a normalized filter object
- resolves tenant timezone once
- builds explicit query predicates
- returns a consistent DTO for Excel/PDF generators

Suggested structure:

- `reporting/query.py` or `reporting/services.py`
- `ReportFilterSet` dataclass
- `build_daily_slaughter_queryset(filters, tenant_timezone)`
- `serialize_daily_slaughter_rows(queryset)`

### B. Make report execution schema-explicit

All non-request execution paths must accept a tenant schema and switch explicitly:

- command: `--schema=<tenant>`
- command: `--all-tenants`
- task helper: `run_daily_reports_for_schema(schema_name, ...)`
- API: capture current `request.tenant.schema_name` and pass it to the background worker

Implementation options:

1. Minimal patch now:
   - keep threading
   - pass `schema_name`
   - wrap execution in `schema_context(schema_name)`

2. Better architecture:
   - replace ad hoc thread with RQ/Celery
   - enqueue a job containing `schema_name`, `date`, `report_types`, and `output_format`

### C. Make report files storage-backed and tenant-safe

Replace raw path strings with one of these:

1. Preferred:
   - `GeneratedReport.file = models.FileField(upload_to=generated_report_upload_to, ...)`
   - upload path includes schema name and report UUID

2. Acceptable interim step:
   - keep `file_path`
   - generate schema-prefixed relative paths
   - serve files through a guarded download view instead of template `.url`

Suggested storage path:

- `reports/<schema>/<report_type>/<yyyy>/<mm>/<generated_report_id>.xlsx`

### D. Make date handling tenant-local

For daily scheduled reports:

- compute "yesterday" in tenant local time
- convert local day start/end to aware datetimes
- query with `>= start_dt` and `< end_dt`

## Phased Fix Plan

### Phase 1: Safety patch for multitenant execution

Priority: immediate

1. Add `--schema` to `generate_daily_reports`.
2. Add `--all-tenants` to `generate_daily_reports`.
3. Implement schema switching with `schema_context(...)`.
4. Update `generate_daily_reports_api()` to capture tenant schema and pass it explicitly.
5. Reject report generation on the public schema unless an explicit all-tenant admin workflow is being used.

Definition of done:

- one tenant can be targeted deterministically
- scheduler-triggered report generation does not depend on thread-local tenant state

### Phase 2: Query correctness

Priority: immediate after Phase 1

1. Implement normalized filters in `ReportDataAggregator`.
2. Apply filters to the queryset.
3. Replace `slaughter_date__date__range` with timezone-aware datetime boundaries.
4. Exclude inactive rows by default where `BaseModel.is_active` applies.
5. Use `destination_client` when present.
6. Normalize customer naming through a single display helper.

Minimum filter contract:

- `animal_types`
- `client_ids`
- `destination_client_ids`
- `service_package_ids`
- `statuses`
- `include_walkins`

Definition of done:

- a report definition's `default_filters` changes the generated dataset
- daily scheduled reports use the tenant's local date

### Phase 3: File storage and archive correctness

Priority: high

1. Move generated files to tenant-safe paths.
2. Stop using raw absolute filesystem paths in UI.
3. Add a download view that checks the current tenant owns the `GeneratedReport`.
4. Fix `report_list.html` to use `report_definition`, correct statuses, and the new download URL.

Definition of done:

- two tenants generating the same report date do not collide
- archive page renders correctly
- downloads are served only within the owning tenant context

### Phase 4: Command and provisioning cleanup

Priority: medium

1. Add `--schema` to:
   - `setup_default_reports`
   - `setup_system_user`
   - `create_test_data`
2. Update tenant provisioning to run these commands per tenant.
3. Document the required execution sequence.

Definition of done:

- provisioning and maintenance scripts are deterministic for tenant data

### Phase 5: Test coverage

Priority: immediate once Phase 1 and 2 are in progress

Add tests for:

1. API passes `schema_name` to background execution.
2. `generate_daily_reports --schema=acme` enters `schema_context("acme")`.
3. `generate_daily_reports --all-tenants` iterates active tenants only.
4. filter application changes the queryset as expected.
5. tenant-local date boundaries are used for daily reports.
6. generated file paths include tenant schema.
7. archive template/render uses the correct relation and status values.

Recommended test strategy:

- keep SQLite unit tests with mocked `schema_context`
- add a separate PostgreSQL tenant-schema suite for at least one end-to-end report command path

## Suggested Implementation Order

1. Fix execution context first.
2. Fix query correctness second.
3. Fix file storage and download semantics third.
4. Fix UI/archive template fourth.
5. Expand provisioning and test coverage last.

This order reduces the risk of generating incorrect cross-tenant data before the UI is polished.

## Acceptance Checklist

- [ ] Daily scheduled reports run in the intended tenant schema
- [ ] A single command can target one schema or all active schemas
- [ ] Daily report date windows use the tenant timezone
- [ ] Query filters are applied, not ignored
- [ ] Destination and client labels are sourced correctly
- [ ] Generated file paths are schema-isolated
- [ ] Archive UI renders and downloads correctly
- [ ] SQLite unit tests cover schema-passing behavior
- [ ] PostgreSQL tenant-schema tests cover at least one end-to-end reporting flow

## Immediate Recommendation

Do not roll out automated multitenant report scheduling until Phase 1 and Phase 2 are complete. The current code is tenant-app scoped at the model level, but the background execution path and query layer are not yet safe enough for reliable multitenant reporting.
