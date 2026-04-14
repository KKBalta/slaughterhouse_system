# Edge Printer Integration Plan — Django (cloud) side

**Date:** 2026-04-13
**Status:** Design ready, pending edge Phase 1A completion before implementation starts
**Companion doc (edge side):** `carnitrack-edge/docs/2026-04-12_PRINTER_INTEGRATION_PLAN.md`
**Related:** `docs/DJANGO_CLOUD_INTEGRATION_SPEC.md`, `docs/IOT_SCALE_INTEGRATION_PLAN.md`

---

## Goal

Add cloud-driven label printing to CarniTrack. Django (this repo) generates the label's TSPL `.prn` content — which it already does for `AnimalLabel` and `CustomLabel` — and dispatches it to a physical TSC TE210 (or equivalent) at the client site through the existing `carnitrack-edge` container, replacing the current workflow of "download a `.bat` file to your browser and run it locally".

**The cloud generates and schedules. The edge dispatches and confirms.** Everything between the two sides goes through the existing `/api/v1/edge/*` REST surface so there's only one auth/transport/multi-tenancy story.

---

## Why now

- Client #2 is being onboarded this week. The current `.bat`-file workflow doesn't work well when the slaughterhouse floor lacks a reliable always-on PC, which is the norm.
- The edge container is already deployed at client #1 for scales. Adding a printer module to it is a drop-in container update, not a new deployment footprint.
- The label-generation pipeline (`labeling/services.py`, the PRN text stored in `AnimalLabel.prn_content` / `CustomLabel.prn_content`) is already correct. We just need a delivery mechanism that doesn't involve a browser download and a manual click.
- No existing edge-printer dispatch code exists in the repo (`grep -rn "printnode\|edge_print\|print-jobs"` returns nothing relevant), so there are no legacy contracts to preserve. Clean slate.

---

## Multi-tenancy — what it buys us for free

This repo uses **`django-tenants` (schema-per-tenant PostgreSQL)**. Key consequences for printer integration:

- Every new model (`Printer`, extended `PrintJob`) lives **inside the tenant schema**, not the public schema. Tenant isolation is enforced by the database, not by an application-level `tenant_id` filter.
- The Edge API is served at `<tenant>.<base-domain>/api/v1/edge/...`. `TenantMainMiddleware` resolves the subdomain to a schema before any view runs, so `request.edge_device` and `request.edge_site` — set by the existing `require_edge_id` decorator — are already guaranteed to belong to the right tenant.
- **No new auth work is needed.** The existing `X-Edge-Id` header + `require_edge_id` middleware already provide the right scoping for print-job polling and acks. We just add new views that use the same decorator.
- **Cross-tenant bugs are structurally impossible** for edge-initiated requests, because the Postgres schema is chosen from the subdomain before the query planner even sees the SQL.
- Super-admin visibility (one operator watching all tenants) is a separate read path that iterates tenants explicitly — designed later, not part of Phase 1.

**Mental model:**

```
Tenant A  (schema: slaughterhouse_a)
  └── Site "Ankara Main Plant"      (scales.Site, one per tenant)
        └── EdgeDevice <uuid-A>     (scales.EdgeDevice, existing)
              ├── ScaleDevice       (scales.ScaleDevice, existing)
              └── Printer           (scales.Printer, NEW — belongs next to EdgeDevice)
                    └── PrintJob    (labeling.PrintJob, EXTENDED — gains printer + prn fields)

Tenant B  (schema: slaughterhouse_b)
  └── (identical structure, fully isolated)
```

Both tenants' edge containers use the exact same container image, the exact same Bun code, and the exact same API contracts. Only the subdomain they point at and their `X-Edge-Id` differ.

---

## Existing state (what's already in the repo)

### `scales/models.py` — tenant-scoped, inside tenant schema

- `Site` — per-tenant site. One default Site auto-created on schema creation (see `tenants/signals.py`). `name`, `address`, optional `api_key`.
- `EdgeDevice` — UUID PK, FK to `Site`. `name`, `is_online`, `last_seen_at`, `version`. One row per running edge container.
- `ScaleDevice` — UUID PK, FK to `EdgeDevice`. `device_id` (local), `global_device_id`, `device_type` (`disassembly|retail|receiving`), `status`, heartbeat timestamps.
- `DisassemblySession`, `WeighingEvent`, `OrphanedBatch`, `OfflineBatchAck`, `EdgeActivityLog` — all tenant-scoped.

### `scales/middleware.py`

- `require_edge_id` decorator: reads `X-Edge-Id` header, validates it's a UUID, loads `EdgeDevice`, sets `request.edge_device` and `request.edge_site`. Returns 401 on any problem.
- `parse_json_body` decorator: attaches parsed JSON as `request.json_body`.

### `scales/api_urls.py`

Mounted at `/api/v1/edge/` in `config/urls.py`. Eight endpoints today, all `@csrf_exempt` + `@require_edge_id`:

```
POST   /api/v1/edge/register
GET    /api/v1/edge/sessions
POST   /api/v1/edge/events
POST   /api/v1/edge/events/batch
POST   /api/v1/edge/offline-batches/ack
GET    /api/v1/edge/config
POST   /api/v1/edge/devices/status
POST   /api/v1/edge/heartbeat
```

The `edge_heartbeat` view already accepts unknown fields in the JSON body (it only reads `version` and `devices[]`), so extending it to also process `printers[]` is additive and backward-compatible.

### `labeling/models.py` — tenant-scoped

- `LabelTemplate` — stores layout JSON and `target_item_type` in (`carcass | meat_cut | offal | by_product | animal`) and `label_format` (`prn | pdf | both`).
- `PrintJob` — **skeletal, needs extension.** Currently tracks `label_template` (nullable FK), `item_type`, `item_id`, `quantity`, `print_date`, `printed_by`, `status` (`pending | completed | failed`). **No site reference, no printer reference, no PRN content field, no attempt/error tracking, no ack timestamps.** This is a user-facing "I requested a label" record, not an edge-dispatchable job.
- `AnimalLabel` — stores `prn_content` (TSPL text) and `bat_content` (the .bat file we're replacing) per animal/cut. The PRN generation is already correct and already tenant-scoped.
- `CustomLabel` — same pattern for standalone custom labels.

### `labeling/views.py`

Currently generates `.bat` files on demand via `generate_enhanced_printer_config_bat(prn_content)` and serves them as `HttpResponse(..., content_type='application/octet-stream')` for the user to download and run. This path stays for a while as a fallback, but new prints default to the edge-dispatch flow once Phase 2 lands.

---

## What we need to add (summary)

1. **One new model** (`scales.Printer`) — edge-owned physical printer registry, one row per physical printer at each site.
2. **Extensions to `labeling.PrintJob`** — fields the edge needs to pick up, dispatch, and ack a job.
3. **Three new edge API endpoints** (`scales/api_views.py` + `scales/api_urls.py`) — print-job pull, ack, and printer inventory push.
4. **One extension to an existing endpoint** (`edge_heartbeat`) — accept and persist a `printers[]` array.
5. **A cloud-side dispatcher helper** (`labeling/services.py`) — one function that, given an `AnimalLabel` or `CustomLabel`, creates a `PrintJob` row targeting the right role at the right site.
6. **A Django admin page** showing each site's printers and recent print jobs, so operators can reprint, troubleshoot, and see status.
7. **A super-admin cross-tenant dashboard** (deferred to a later phase) — read-only view across all tenants for platform ops. Uses the `public` schema + explicit tenant iteration.

None of this touches existing PRN generation, existing label models, or existing edge endpoints (except the additive heartbeat change).

---

## New model: `scales.Printer`

Add to `scales/models.py` alongside `EdgeDevice` and `ScaleDevice`. Belongs in `scales` (not `labeling`) because it's infrastructure the edge manages, same class of thing as `ScaleDevice` — a physical device connected to an edge.

```python
class Printer(BaseModel):
    """
    Physical label printer connected to an Edge over the site LAN.
    One row per physical printer; the edge maintains its own local registry
    and pushes inventory here via POST /api/v1/edge/printers/inventory.
    """

    ROLE_CHOICES = [
        ("carcass", "Carcass"),
        ("meat_cut", "Meat Cut"),
        ("offal", "Offal"),
        ("by_product", "By-Product"),
        ("animal", "Animal"),
        ("generic", "Generic"),
    ]

    TRANSPORT_CHOICES = [
        ("tcp", "TCP (raw 9100 / JetDirect)"),
    ]

    STATUS_CHOICES = [
        ("unknown", "Unknown"),
        ("online", "Online"),
        ("offline", "Offline"),
        ("error", "Error"),
    ]

    edge = models.ForeignKey(
        EdgeDevice,
        on_delete=models.CASCADE,
        related_name="printers",
        help_text="The edge that owns this printer (must reach it on the site LAN).",
    )
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="printers",
        help_text="Denormalized for efficient site-wide queries; must match edge.site.",
    )
    local_printer_id = models.CharField(
        max_length=64,
        help_text="Stable local identifier chosen by the operator (e.g. 'carcass-01'). "
                  "Unique within one edge.",
    )
    display_name = models.CharField(max_length=200, blank=True)
    role = models.CharField(
        max_length=32,
        choices=ROLE_CHOICES,
        default="generic",
        help_text="Routing role for print jobs. Jobs with target_role=X go to any online "
                  "Printer with role=X at the job's site.",
    )
    transport = models.CharField(max_length=16, choices=TRANSPORT_CHOICES, default="tcp")
    host = models.CharField(max_length=64, help_text="IPv4 address on the site LAN.")
    port = models.PositiveIntegerField(default=9100)
    model = models.CharField(max_length=64, blank=True, help_text="e.g. 'TE210'")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="unknown")
    priority = models.PositiveSmallIntegerField(
        default=100,
        help_text="Lower value = preferred when multiple printers match a role. "
                  "Use for primary/backup setups.",
    )
    enabled = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True)
    version = models.CharField(max_length=64, blank=True, help_text="Firmware version if reported.")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["edge", "local_printer_id"],
                name="scales_printer_edge_local_id",
            ),
        ]
        indexes = [
            models.Index(fields=["site", "role", "status"]),
            models.Index(fields=["edge", "-last_seen_at"]),
        ]

    def __str__(self):
        return f"{self.local_printer_id} @ {self.edge.name or self.edge_id} [{self.role}]"
```

**Design notes:**

- `edge` and `site` are both FKs. `site` is denormalized so the most common query — "find all printers at a site with role X" — is a single index lookup, no join needed. An application-level invariant (enforced in `save()` or a `clean()` method) ensures `self.site == self.edge.site`.
- `local_printer_id` is the operator-friendly ID used in edge env vars and config. Unique within an edge. The Django PK (UUID) is the globally stable ID used in print-job foreign keys.
- `role` uses the same vocabulary as `LabelTemplate.TARGET_ITEM_TYPE_CHOICES` so `LabelTemplate → PrintJob → Printer` routing is a direct string match. No translation layer.
- `priority` enables primary/backup without code changes — add a second printer row with `priority=200`, the edge dispatcher prefers the lower number automatically.
- `status` is updated by the edge on every heartbeat tick via the extended `edge_heartbeat` endpoint, NOT written by Django directly. Django reads it; edge owns it.

---

## Extensions to `labeling.PrintJob`

Existing fields are fine. We add the following (migration `labeling/migrations/00NN_printjob_edge_dispatch.py`):

```python
# NEW FIELDS on labeling.PrintJob

site = models.ForeignKey(
    "scales.Site",
    on_delete=models.CASCADE,
    related_name="print_jobs",
    null=True, blank=True,   # nullable for backwards compat with existing rows
    help_text="Which site's edge should dispatch this job. Required for edge-dispatched jobs.",
)

target_printer = models.ForeignKey(
    "scales.Printer",
    on_delete=models.SET_NULL,
    related_name="print_jobs",
    null=True, blank=True,
    help_text="Optional explicit printer. If set, overrides target_role.",
)

target_role = models.CharField(
    max_length=32,
    blank=True,
    help_text="Routing role: 'carcass'|'meat_cut'|'offal'|'by_product'|'animal'. "
              "Edge picks any online printer with this role at the job's site.",
)

prn_content = models.TextField(
    blank=True,
    help_text="TSPL bytes to send to the printer. Copied from AnimalLabel.prn_content "
              "(or equivalent) at enqueue time so the edge never has to resolve an FK.",
)

# Status tracking (existing `status` field stays; new values added)
# STATUS_CHOICES = (
#     ("pending",    "Pending"),      # existing
#     ("dispatched", "Dispatched"),   # NEW: edge has picked it up
#     ("completed",  "Completed"),    # existing (was 'completed', semantically 'printed')
#     ("failed",     "Failed"),       # existing
#     ("cancelled",  "Cancelled"),    # NEW: user cancelled before dispatch
# )

dispatch_mode = models.CharField(
    max_length=16,
    choices=[
        ("edge", "Edge dispatch (TCP to printer)"),
        ("legacy_bat", "Legacy .bat file download"),
    ],
    default="edge",
    help_text="Which delivery mechanism this job uses. 'legacy_bat' is the pre-edge workflow.",
)

attempts = models.PositiveSmallIntegerField(default=0)
max_attempts = models.PositiveSmallIntegerField(default=8)
error_text = models.CharField(max_length=500, blank=True)

edge_received_at = models.DateTimeField(null=True, blank=True, help_text="When edge first polled this job.")
printed_at = models.DateTimeField(null=True, blank=True, help_text="When the edge confirmed success.")
```

**Migration notes:**

- All new fields are nullable/default-valued so existing `PrintJob` rows created before this change don't need backfill.
- `dispatch_mode` defaults to `edge` for new rows, which is safe because the legacy flow (`labeling/views.py` `.bat` download endpoints) doesn't create `PrintJob` rows — it just serves files. We'll switch it to create `PrintJob` rows in `dispatch_mode='legacy_bat'` for audit/traceability in a later phase.
- Index on `(site, status)` for the common edge query "give me pending jobs at my site" — which maps to `PrintJob.objects.filter(site=edge.site, status='pending', dispatch_mode='edge')`.

---

## New edge API endpoints

All three added to `scales/api_views.py` and registered in `scales/api_urls.py`. Same auth pattern as existing endpoints (`@csrf_exempt @require_edge_id @parse_json_body` where applicable).

### 1. `GET /api/v1/edge/print-jobs/pending`

Edge polls this on the same cadence as `/sessions` (~5s).

**Request:** headers only, no body.

**Response:**

```json
{
  "jobs": [
    {
      "jobId": "c8e2a1f4-7b3d-4e5f-a1b2-0123456789ab",
      "siteId": "2d3a-...",
      "targetRole": "carcass",
      "targetPrinter": null,
      "prnContent": "SIZE 40 mm,30 mm\r\nCLS\r\n...\r\nPRINT 1\r\n",
      "createdAt": "2026-04-13T20:45:12.345Z",
      "attempts": 0
    }
  ]
}
```

**View sketch:**

```python
@csrf_exempt
@require_edge_id
def edge_pending_print_jobs(request):
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    # Rate limit mirrors sessions: 60 req/min per edge
    if atomic_rate_incr(f"edge_rl:print_jobs_pending:{request.edge_device.id}", 60) > 60:
        return JsonResponse({"error": "rate limit exceeded"}, status=429)

    request.edge_device.last_seen_at = timezone.now()
    request.edge_device.save(update_fields=["last_seen_at", "updated_at"])

    from labeling.models import PrintJob
    qs = (PrintJob.objects
          .filter(site=request.edge_site,
                  status="pending",
                  dispatch_mode="edge")
          .order_by("print_date")[:50])

    jobs = [
        {
            "jobId": str(j.id),
            "siteId": str(j.site_id),
            "targetRole": j.target_role or None,
            "targetPrinter": str(j.target_printer_id) if j.target_printer_id else None,
            "prnContent": j.prn_content,
            "createdAt": j.print_date.isoformat(),
            "attempts": j.attempts,
        }
        for j in qs
    ]
    return JsonResponse({"jobs": jobs})
```

**Notes:**

- Filter is `site=request.edge_site` — the middleware already resolved this from `X-Edge-Id` which was already schema-scoped by subdomain. Tenant isolation is automatic.
- Returns up to 50 jobs per poll to avoid huge payloads; edge will paginate implicitly by re-polling.
- `prnContent` is inlined as text. TSPL is ASCII and typically <5KB per label, so no need for base64 or signed URLs until someone actually ships multi-megabyte raster jobs (which won't happen in this domain).

### 2. `POST /api/v1/edge/print-jobs/<uuid:job_id>/ack`

Edge reports the result of a dispatch attempt.

**Request:**

```json
{
  "status": "completed",
  "printedAt": "2026-04-13T20:45:14.789Z",
  "resolvedPrinter": "c8e2a1f4-...",
  "attempts": 1,
  "errorText": ""
}
```

`status` is one of `dispatched`, `completed`, `failed`. `resolvedPrinter` is the UUID of the `scales.Printer` row the edge actually sent bytes to (looked up by `global_printer_id` / Django PK).

**Response:**

```json
{ "ok": true }
```

**View sketch:**

```python
@csrf_exempt
@require_edge_id
@parse_json_body
def edge_ack_print_job(request, job_id):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    from labeling.models import PrintJob
    try:
        job = PrintJob.objects.get(id=job_id, site=request.edge_site)
    except PrintJob.DoesNotExist:
        return JsonResponse({"error": "Job not found"}, status=404)

    body = request.json_body
    status = body.get("status")
    if status not in ("dispatched", "completed", "failed"):
        return JsonResponse({"error": "Invalid status"}, status=400)

    job.status = status
    job.attempts = body.get("attempts", job.attempts)
    job.error_text = (body.get("errorText") or "")[:500]
    if body.get("resolvedPrinter"):
        try:
            job.target_printer_id = uuid.UUID(body["resolvedPrinter"])
        except (ValueError, TypeError):
            pass
    if status == "dispatched" and not job.edge_received_at:
        job.edge_received_at = timezone.now()
    if status == "completed":
        job.printed_at = _parse_iso(body.get("printedAt")) or timezone.now()
    job.save()

    _log_edge_activity(
        action="print_job_ack",
        request=request,
        edge=request.edge_device,
        site=request.edge_site,
        message=f"Print job {job_id} -> {status}",
        payload={"attempts": job.attempts, "error": job.error_text[:100]},
    )
    return JsonResponse({"ok": True})
```

**Notes:**

- Idempotent — edge can safely re-ack if the response was lost. Django overwrites with the latest values.
- `.filter(site=request.edge_site)` in the lookup makes cross-tenant/cross-site access impossible.
- Logs every ack via existing `_log_edge_activity` so ops has an audit trail.

### 3. `POST /api/v1/edge/printers/inventory`

Edge reports its physical printer inventory on startup and whenever config changes. Upserts into `scales.Printer`.

**Request:**

```json
{
  "printers": [
    {
      "localPrinterId": "carcass-01",
      "displayName": "Carcass Line Printer",
      "role": "carcass",
      "transport": "tcp",
      "host": "192.168.1.220",
      "port": 9100,
      "model": "TE210",
      "priority": 100
    },
    {
      "localPrinterId": "product-01",
      "displayName": "Retail Product Printer",
      "role": "meat_cut",
      "transport": "tcp",
      "host": "192.168.1.221",
      "port": 9100,
      "model": "TE210",
      "priority": 100
    }
  ]
}
```

**Response:**

```json
{
  "ok": true,
  "printers": [
    { "localPrinterId": "carcass-01", "globalPrinterId": "c8e2a1f4-7b3d-4e5f-a1b2-0123456789ab" },
    { "localPrinterId": "product-01", "globalPrinterId": "f1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d" }
  ]
}
```

The edge persists the returned `globalPrinterId` in its local `printers.global_printer_id` column. From then on, `PrintJob.target_printer` references by UUID, not local string.

**View sketch:**

```python
@csrf_exempt
@require_edge_id
@parse_json_body
def edge_printer_inventory(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    body = request.json_body
    items = body.get("printers") or []
    if not isinstance(items, list):
        return JsonResponse({"error": "printers must be a list"}, status=400)

    results = []
    with transaction.atomic():
        for item in items:
            local_id = (item.get("localPrinterId") or "").strip()
            if not local_id:
                continue
            role = (item.get("role") or "generic").strip()
            host = (item.get("host") or "").strip()
            port = int(item.get("port") or 9100)
            if not host:
                continue

            printer, created = Printer.objects.update_or_create(
                edge=request.edge_device,
                local_printer_id=local_id,
                defaults={
                    "site": request.edge_site,
                    "display_name": (item.get("displayName") or "")[:200],
                    "role": role,
                    "transport": (item.get("transport") or "tcp"),
                    "host": host,
                    "port": port,
                    "model": (item.get("model") or "")[:64],
                    "priority": int(item.get("priority") or 100),
                    "enabled": True,
                },
            )
            results.append({
                "localPrinterId": local_id,
                "globalPrinterId": str(printer.id),
            })

    _log_edge_activity(
        action="printer_inventory",
        request=request,
        edge=request.edge_device,
        site=request.edge_site,
        message=f"Inventory push: {len(results)} printer(s)",
        payload={"printers": results[:20]},
    )
    return JsonResponse({"ok": True, "printers": results})
```

---

## Extension to existing `edge_heartbeat`

The current `POST /api/v1/edge/heartbeat` view reads `body.get("version")` and `body.get("devices")`. We add a read of `body.get("printers")` and update the matching `Printer` rows' `status` / `last_seen_at` / `last_error` fields.

**Additive payload:**

```json
{
  "version": "0.4.0",
  "devices": [ ... existing scale device entries ... ],
  "printers": [
    {
      "localPrinterId": "carcass-01",
      "status": "online",
      "lastSeenAt": "2026-04-13T20:45:12.345Z",
      "lastError": ""
    },
    {
      "localPrinterId": "product-01",
      "status": "offline",
      "lastSeenAt": "2026-04-13T20:40:00.000Z",
      "lastError": "connect ETIMEDOUT 192.168.1.221:9100"
    }
  ]
}
```

**Code change in `edge_heartbeat`** (added after the existing `devices_payload` loop):

```python
printers_payload = body.get("printers") or []
for item in printers_payload:
    local_id = (item.get("localPrinterId") or "").strip()
    if not local_id:
        continue
    status_val = (item.get("status") or "unknown").strip()
    last_seen_at = _parse_iso(item.get("lastSeenAt")) or timezone.now()
    last_error = (item.get("lastError") or "")[:255]

    Printer.objects.filter(
        edge=edge,
        local_printer_id=local_id,
    ).update(
        status=status_val,
        last_seen_at=last_seen_at,
        last_error=last_error,
    )
```

No new rows are created here — inventory push is the only way to create a `Printer` row. Heartbeat only updates runtime fields. This keeps the data model clean (inventory changes are explicit events, status is ambient).

---

## Cloud-side dispatcher helper

New function in `labeling/services.py` that converts a finished label into a queued `PrintJob`:

```python
def enqueue_print_job(
    *,
    site,
    target_role: str,
    prn_content: str,
    target_printer=None,
    label_template=None,
    item_type: str = "",
    item_id=None,
    quantity: int = 1,
    printed_by=None,
) -> "PrintJob":
    """
    Create a PrintJob for edge dispatch. The edge will pick it up on its next poll.
    """
    from labeling.models import PrintJob

    return PrintJob.objects.create(
        site=site,
        target_printer=target_printer,
        target_role=target_role,
        prn_content=prn_content,
        label_template=label_template,
        item_type=item_type or target_role,
        item_id=item_id,
        quantity=quantity,
        printed_by=printed_by,
        status="pending",
        dispatch_mode="edge",
    )
```

Callers from `labeling/views.py` — wherever the existing code generates a `.prn` and currently sends a `.bat` download — gain a branch:

```python
if request.POST.get("dispatch") == "edge":
    enqueue_print_job(
        site=request.user.tenant_site,   # or however site is resolved for the request
        target_role="carcass",
        prn_content=animal_label.prn_content,
        label_template=animal_label.template,   # if applicable
        item_type="animal",
        item_id=animal_label.id,
        printed_by=request.user,
    )
    return JsonResponse({"ok": True, "mode": "edge"})
else:
    # existing .bat download code path stays as fallback
    ...
```

No touching of PRN generation, no new label formats, no template changes. The edge path is a new branch that coexists with the old one and becomes the default once we trust it.

---

## Django admin surface

### Tenant-scoped admin (standard)

Add two `ModelAdmin` classes in `scales/admin.py`:

- `PrinterAdmin` — list display `(local_printer_id, display_name, role, host, port, status, last_seen_at)`; list filter `(role, status, enabled)`; search by `local_printer_id`, `host`, `display_name`; read-only for `status`/`last_seen_at`/`last_error` (those belong to the edge).
- Inline `PrinterInline` on `EdgeDeviceAdmin` so you can see an edge's printers alongside its scales.

And in `labeling/admin.py`:

- Extend `PrintJobAdmin` with the new fields: `(status, dispatch_mode, target_role, target_printer, attempts, error_text, printed_at, edge_received_at)`. Add a custom action "Re-enqueue selected failed jobs" that resets `status='pending'`, `attempts=0`, `error_text=''`.

These are standard tenant-scoped admin views — each tenant only sees their own data because `django-tenants` routes Django admin by subdomain too.

### Super-admin cross-tenant dashboard (later phase, design note only)

Lives in a new app or under `tenants/admin_views.py`. Iterates all active `Client` rows, for each one switches into the tenant schema with `with schema_context(client.schema_name):`, queries `Printer.objects.filter(status__in=['offline','error'])` and `PrintJob.objects.filter(status='failed', created__gte=yesterday)`, and renders a single consolidated table.

Access restricted to `PlatformAdmin` (the model already exists in `tenants/models.py`). This is platform-ops tooling, not part of Phase 1 scope.

---

## Migration order

1. **Migration 1** — `scales/migrations/00NN_printer.py`: create `Printer` table.
2. **Migration 2** — `labeling/migrations/00NN_printjob_edge_dispatch.py`: add fields to `PrintJob`.
3. Run against the `tenants` management command `./manage.py migrate_schemas` to apply to all tenant schemas. (The cloud is already configured for this; every existing tenant gets the new tables/columns automatically.)
4. No data backfill needed — all new fields are nullable or default-valued.

---

## URL registration

Add to `scales/api_urls.py`:

```python
urlpatterns = [
    # existing entries...
    path("print-jobs/pending",   api_views.edge_pending_print_jobs,   name="edge-pending-print-jobs"),
    path("print-jobs/<uuid:job_id>/ack", api_views.edge_ack_print_job, name="edge-ack-print-job"),
    path("printers/inventory",   api_views.edge_printer_inventory,    name="edge-printer-inventory"),
]
```

No changes to `config/urls.py` — the `/api/v1/edge/` prefix is already mounted.

---

## Rate limits

Mirror the existing patterns:

- `print-jobs/pending` — 60 req/min per edge (same as `sessions`). Normal polling is 12/min.
- `print-jobs/*/ack` — 120 req/min per edge. High because a burst of failed jobs can each ack several times.
- `printers/inventory` — 10 req/min per edge. This is a startup/config-change operation, not a steady-state call.

All three use `atomic_rate_incr` from `tenants/redis_support` the same way existing endpoints do.

---

## Testing plan

### Unit tests (`scales/tests_api.py`, `labeling/tests.py`)

- `Printer` model: unique (edge, local_printer_id) constraint; `save()` enforces `site == edge.site`.
- `enqueue_print_job` helper: creates a PrintJob with correct site/role/dispatch_mode.
- `edge_pending_print_jobs`: auth required; returns only jobs for `request.edge_site`; cross-tenant/cross-site jobs are invisible.
- `edge_ack_print_job`: auth required; idempotent; rejects unknown status; updates fields correctly; cross-site access returns 404.
- `edge_printer_inventory`: creates new rows on first push; updates existing rows on second push with changed host/port; returns correct UUIDs.
- `edge_heartbeat` with `printers[]`: updates status/last_seen/last_error; never creates new Printer rows.

### Integration tests

- Full round-trip against `conftest.py` tenant fixtures: create a tenant, register an edge, push printer inventory, create a print job via `enqueue_print_job`, poll `pending`, ack `completed`, verify `PrintJob.status == 'completed'` and `printed_at` is set.

### Manual QA (paired with edge Phase 2)

- Edge running locally with `PRINTERS=main:127.0.0.1:9100` + `nc -l 9100` as fake printer.
- Django running locally with a test tenant on `localhost:8000`.
- Register the edge, verify `Printer` row appears.
- Click a "Print carcass label" action in Django admin, verify edge picks it up within 5s and `nc` shows the TSPL bytes.
- Verify the job status flips to `completed` in Django admin.

---

## Phases and timing

### Phase 1A — Edge local-only (edge repo, separate session — in progress)

No Django changes. Edge module builds against an env-var-configured printer and a local `POST /api/print-jobs` route. Testable with `nc`. See the edge-side plan for details.

### Phase 1B — This document's scope

1. **Models + migrations** (`Printer`, `PrintJob` extension). No API changes yet.
2. **`enqueue_print_job` helper** in `labeling/services.py`.
3. **Django admin** surfaces for both new models.
4. **Three new API endpoints** (`pending`, `ack`, `inventory`).
5. **`edge_heartbeat` extension** to process `printers[]`.
6. **Unit tests** for all new views and the helper.

**Exit criteria:** a manual `POST /api/v1/edge/printers/inventory` with curl creates Printer rows. A manual `enqueue_print_job()` in the Django shell creates a PrintJob. A manual `GET /api/v1/edge/print-jobs/pending` returns it. A manual ack marks it `completed`.

### Phase 2 — Integration (spans both repos)

- Edge `sync-service.ts` polls the new endpoints.
- Edge `buildHeartbeatPayload` includes `printers[]`.
- Edge pushes inventory on startup.
- End-to-end test with real TE210.

### Phase 3 — Hardening and UX

- Django-side "Print to edge" buttons in the user-facing label UIs (replacing the `.bat` download as the default path).
- Reprint and cancel actions in PrintJobAdmin.
- Dashboard widget on the tenant home page: "Last 20 print jobs, their printers, and their statuses."

### Phase 4 — Platform ops

- Super-admin cross-tenant dashboard (as outlined above).
- Alerting: page ops when any tenant's printer has been in `error` for >10min.
- Claude-API diagnostic escalation for sustained failures (mirrors what's planned on the edge side).

---

## Non-goals for this plan

- **Not replacing the `.bat` workflow yet.** The legacy path in `labeling/views.py` stays as a fallback. The edge path is added alongside and becomes the default in Phase 3 only after it has run reliably for a few weeks at client #1.
- **Not changing PRN generation.** Existing `AnimalLabel.prn_content` / `CustomLabel.prn_content` / `LabelTemplate` logic is reused verbatim.
- **Not supporting printers other than TCP/9100.** USB, serial, Bluetooth are all out of scope. The edge's `PrinterTransport` interface leaves room to add them later without Django changes.
- **Not implementing signed-URL PRN storage.** TSPL is tiny (<5KB) so we inline it in the API response. Can switch to GCS-signed URLs if label sizes ever grow past a few hundred KB.
- **Not touching `LabelTemplate`** — templates stay a pure cloud concept. The edge never sees a template.

---

## Open questions for the next session

1. **Dispatch triggers.** Should clicking "Print" in a tenant's label UI default to `dispatch_mode='edge'` or still `legacy_bat`? Probably per-tenant setting on `Client` so we can flip individual clients over gradually.
2. **Reprint from edge failure.** When a job fails on the edge, should the user be able to click "retry" from the Django admin, or only from the edge's own dashboard? Probably both — Django resets `status='pending'` and the edge picks it up again.
3. **PrintJob → AnimalLabel link.** Right now `PrintJob.item_id` is a UUID without a real FK. Should we add an optional `animal_label` and `custom_label` FK for direct traversal? Probably yes, but not blocking Phase 1B.
4. **Client-level default printer.** Should a `Client` have a `default_edge` pointer so the `enqueue_print_job` helper can resolve `site` without the caller specifying it? Yes, but not blocking Phase 1B.

All four are enhancements, not Phase 1B blockers.
