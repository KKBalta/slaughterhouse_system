# Cloud Printer Module — Phase 1B Implementation Plan

**Date:** 2026-04-13
**Repo:** `Core/slaughterhouse_system` (Django)
**Phase:** 1B — Django cloud side (runs in parallel with edge Phase 1A)
**Architecture doc:** `docs/2026-04-13_EDGE_PRINTER_INTEGRATION_PLAN.md`
**Edge plan:** `Carnitrack_EDGE/docs/2026-04-12_PRINTER_INTEGRATION_PLAN.md`
**Edge Phase 1A plan:** `Carnitrack_EDGE/docs/2026-04-13_FULL_STACK_PRINTER_IMPLEMENTATION_MAP.md`

---

## Todos

```
- [ ] 1. scales.Printer model + migration
- [ ] 2. labeling.PrintJob extensions + migration
- [ ] 3. enqueue_print_job() in labeling/services.py
- [ ] 4. GET  /api/v1/edge/print-jobs/pending  view + URL
- [ ] 5. POST /api/v1/edge/print-jobs/<uuid>/ack  view + URL
- [ ] 6. POST /api/v1/edge/printers/inventory  view + URL
- [ ] 7. edge_heartbeat extension for printers[]
- [ ] 8. scales/admin.py — PrinterAdmin + PrinterInline
- [ ] 9. labeling/admin.py — extend PrintJobAdmin
- [ ] 10. Unit tests
```

---

## Context

Django already generates TSPL label content (`AnimalLabel.prn_content`) and stores it as text.
The current delivery mechanism is a `.bat` file download — the user downloads it and runs it locally.
This phase replaces that with a cloud-managed `PrintJob` table that the edge polls and dispatches.

**Nothing changes about PRN generation.** `labeling/utils.py` is not touched.
**The `.bat` download path stays.** It is not removed — only a new parallel path is added.

Multi-tenancy is free: all new models live in the tenant schema. The `@require_edge_id` decorator
already sets `request.edge_site` (a `scales.Site` instance scoped to the active schema). No new
auth or tenant-routing work is needed.

---

## File change map

| File | Action |
|---|---|
| `scales/models.py` | Add `Printer` model |
| `scales/migrations/00NN_printer.py` | New migration |
| `labeling/models.py` | Extend `PrintJob` with 9 new fields; fix `item_id` nullability |
| `labeling/migrations/00NN_printjob_edge.py` | New migration |
| `labeling/services.py` | Add `enqueue_print_job()` |
| `scales/api_views.py` | Add 3 new views + extend `edge_heartbeat` |
| `scales/api_urls.py` | Register 3 new URL patterns |
| `scales/admin.py` | Add `PrinterAdmin`, `PrinterInline` on `EdgeDeviceAdmin` |
| `labeling/admin.py` | Extend `PrintJobAdmin` |

---

## 1. `scales.Printer` model

Add to `scales/models.py` directly after the `ScaleDevice` class.
Follows the same `BaseModel` pattern as `ScaleDevice`.

```python
class Printer(BaseModel):
    """
    Physical label printer on the site LAN, managed by an EdgeDevice.
    Rows are created/updated by the edge via POST /api/v1/edge/printers/inventory.
    Status fields are updated via heartbeat — Django never writes them directly.
    """

    ROLE_CHOICES = [
        ("carcass",    "Carcass"),
        ("meat_cut",   "Meat Cut"),
        ("offal",      "Offal"),
        ("by_product", "By-Product"),
        ("animal",     "Animal"),
        ("generic",    "Generic"),
    ]
    STATUS_CHOICES = [
        ("unknown", "Unknown"),
        ("online",  "Online"),
        ("offline", "Offline"),
        ("error",   "Error"),
    ]

    edge = models.ForeignKey(
        EdgeDevice,
        on_delete=models.CASCADE,
        related_name="printers",
    )
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="printers",
        help_text="Denormalized from edge.site for efficient site-wide queries.",
    )
    local_printer_id = models.CharField(
        max_length=64,
        help_text="Stable local ID set by the operator (e.g. 'carcass-01'). Unique within one edge.",
    )
    display_name = models.CharField(max_length=200, blank=True)
    role = models.CharField(
        max_length=32,
        choices=ROLE_CHOICES,
        default="generic",
        help_text="Routing role. PrintJobs with target_role=X go to any online Printer with role=X at the same site.",
    )
    transport = models.CharField(max_length=16, default="tcp")
    host = models.CharField(max_length=64, help_text="IPv4 address on the site LAN.")
    port = models.PositiveIntegerField(default=9100)
    model = models.CharField(max_length=64, blank=True, help_text="e.g. 'TE210'")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="unknown")
    priority = models.PositiveSmallIntegerField(
        default=100,
        help_text="Lower = preferred. Use 100/200 for primary/backup. Edge resolves by this value.",
    )
    enabled = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True)
    version = models.CharField(max_length=64, blank=True, help_text="Firmware version from ~!T query.")

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

    def clean(self):
        # Invariant: site must match edge.site
        if self.edge_id and self.site_id and self.site_id != self.edge.site_id:
            from django.core.exceptions import ValidationError
            raise ValidationError("Printer.site must match Printer.edge.site")

    def save(self, *args, **kwargs):
        if self.edge_id and not self.site_id:
            self.site = self.edge.site
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.local_printer_id} @ {self.edge.name or str(self.edge.id)[:8]} [{self.role}]"
```

**Role vocabulary** is identical to `LabelTemplate.TARGET_ITEM_TYPE_CHOICES` plus `generic`.
This makes `LabelTemplate → PrintJob.target_role → Printer.role` a direct string match — no translation.

---

## 2. `labeling.PrintJob` extensions

Existing fields stay as-is. Add the following to `labeling/models.py`.

### Fix: make `item_id` nullable

```python
# BEFORE (current)
item_id = models.UUIDField(help_text="The ID of the specific inventory item being labeled.")

# AFTER (migration required)
item_id = models.UUIDField(
    null=True, blank=True,
    help_text="The ID of the specific inventory item being labeled.",
)
```

Required because `enqueue_print_job()` may be called without a linked item (e.g. custom labels).

### New fields

```python
# --- Edge dispatch fields (all nullable/defaulted for backwards compat) ---

site = models.ForeignKey(
    "scales.Site",
    on_delete=models.CASCADE,
    related_name="print_jobs",
    null=True, blank=True,
    help_text="Which site's edge dispatches this job. Required for edge dispatch.",
)

target_printer = models.ForeignKey(
    "scales.Printer",
    on_delete=models.SET_NULL,
    related_name="print_jobs",
    null=True, blank=True,
    help_text="Optional explicit printer override. If set, wins over target_role.",
)

target_role = models.CharField(
    max_length=32,
    blank=True,
    help_text="Role-based routing: 'carcass'|'meat_cut'|'offal'|'by_product'|'animal'. "
              "Edge picks the best available Printer with this role at the job's site.",
)

prn_content = models.TextField(
    blank=True,
    help_text="TSPL bytes copied from AnimalLabel.prn_content at enqueue time. "
              "Returned inline in the edge poll response as a UTF-8 JSON string. "
              "Edge re-encodes to Windows-1254 before TCP send.",
)

dispatch_mode = models.CharField(
    max_length=16,
    choices=[
        ("edge",       "Edge dispatch (TCP → printer)"),
        ("legacy_bat", "Legacy .bat file download"),
    ],
    default="edge",
    help_text="'edge' = edge polls and dispatches. 'legacy_bat' = old .bat download flow.",
)

attempts = models.PositiveSmallIntegerField(default=0)
max_attempts = models.PositiveSmallIntegerField(default=8)
error_text = models.CharField(max_length=500, blank=True)

edge_received_at = models.DateTimeField(
    null=True, blank=True,
    help_text="When edge first picked up this job (set on first 'dispatched' ack).",
)
printed_at = models.DateTimeField(
    null=True, blank=True,
    help_text="When edge confirmed successful print (set on 'completed' ack).",
)
```

### Updated `STATUS_CHOICES`

```python
STATUS_CHOICES = (
    ("pending",    "Pending"),     # waiting for edge to pick up
    ("dispatched", "Dispatched"),  # NEW: edge has picked up, print in progress
    ("completed",  "Completed"),   # edge confirmed print success
    ("failed",     "Failed"),      # all attempts exhausted
    ("cancelled",  "Cancelled"),   # NEW: user cancelled before dispatch
)
```

### Index to add in `Meta`

```python
class Meta:
    indexes = [
        models.Index(fields=["site", "status", "dispatch_mode"]),  # edge poll query
    ]
```

---

## 3. `item_type` mapping — `AnimalLabel.label_type` → `PrintJob.target_role`

`AnimalLabel.label_type` uses different vocabulary from `PrintJob.target_role` / `Printer.role`.
This mapping lives at the call site in `enqueue_print_job()`:

```python
_LABEL_TYPE_TO_ROLE = {
    "hot_carcass":  "carcass",
    "cold_carcass": "carcass",
    "final":        "meat_cut",
    "cut":          "meat_cut",
}
```

---

## 4. `enqueue_print_job()` in `labeling/services.py`

```python
_LABEL_TYPE_TO_ROLE = {
    "hot_carcass":  "carcass",
    "cold_carcass": "carcass",
    "final":        "meat_cut",
    "cut":          "meat_cut",
}


def enqueue_print_job(
    *,
    site,
    prn_content: str,
    target_role: str = "",
    target_printer=None,
    animal_label=None,
    custom_label=None,
    printed_by=None,
) -> "PrintJob":
    """
    Create a PrintJob for edge dispatch.

    The edge polls GET /api/v1/edge/print-jobs/pending and picks this up
    on its next 5-second cycle. No files are written to disk.

    Args:
        site:           scales.Site instance (the tenant's site whose edge dispatches).
        prn_content:    TSPL string from AnimalLabel.prn_content (UTF-8 text).
        target_role:    Routing role. If omitted, derived from animal_label.label_type.
        target_printer: Optional scales.Printer instance for explicit routing.
        animal_label:   AnimalLabel instance — used to derive item_type/item_id/role.
        custom_label:   CustomLabel instance — used to derive item_type/item_id.
        printed_by:     User instance.
    """
    from labeling.models import PrintJob

    # Derive role from label type if not explicitly provided
    resolved_role = target_role
    if not resolved_role and animal_label:
        resolved_role = _LABEL_TYPE_TO_ROLE.get(animal_label.label_type, "carcass")

    # Derive item fields from linked label
    item_type = ""
    item_id = None
    if animal_label:
        item_type = resolved_role or "carcass"
        item_id = animal_label.animal_id
    elif custom_label:
        item_type = "animal"
        item_id = custom_label.id

    return PrintJob.objects.create(
        site=site,
        target_printer=target_printer,
        target_role=resolved_role,
        prn_content=prn_content,
        dispatch_mode="edge",
        status="pending",
        item_type=item_type,
        item_id=item_id,
        printed_by=printed_by,
    )
```

### How to get `site` from a Django view

```python
# From a view that has request.edge_site (edge API views):
site = request.edge_site

# From a user-facing web view:
from scales.models import Site
site = Site.objects.first()   # single-site tenants (Phase 1B)
# Phase 3: let user pick from Site.objects.filter(edges__isnull=False)
```

---

## 5. New views in `scales/api_views.py`

Add these three functions. Import `Printer` at the top of the file alongside existing model imports.

### 5a. `GET /api/v1/edge/print-jobs/pending`

```python
_PRINT_JOBS_PENDING_RL_WINDOW = 60   # seconds
_PRINT_JOBS_PENDING_RL_LIMIT  = 60   # 60 req/min

@csrf_exempt
@require_edge_id
def edge_pending_print_jobs(request):
    """
    Edge polls this every ~5s to get pending print jobs for its site.
    Returns up to 50 jobs ordered by creation time (oldest first).
    """
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    from tenants.redis_support import atomic_rate_incr
    if atomic_rate_incr(
        f"edge_rl:print_jobs_pending:{request.edge_device.id}",
        _PRINT_JOBS_PENDING_RL_WINDOW
    ) > _PRINT_JOBS_PENDING_RL_LIMIT:
        return JsonResponse({"error": "rate limit exceeded"}, status=429)

    request.edge_device.last_seen_at = timezone.now()
    request.edge_device.save(update_fields=["last_seen_at", "updated_at"])

    from labeling.models import PrintJob
    qs = (
        PrintJob.objects
        .filter(
            site=request.edge_site,
            status="pending",
            dispatch_mode="edge",
        )
        .order_by("print_date")[:50]
    )

    jobs = [
        {
            "jobId":          str(j.id),
            "targetRole":     j.target_role or None,
            "targetPrinter":  str(j.target_printer_id) if j.target_printer_id else None,
            "prnContent":     j.prn_content,
            "labelCount":     1,           # all current templates use PRINT 1,1
            "attempts":       j.attempts,
            "createdAt":      j.print_date.isoformat(),
        }
        for j in qs
    ]

    return JsonResponse({"jobs": jobs})
```

**Notes:**
- `site=request.edge_site` — middleware already resolved this; tenant isolation is automatic.
- `labelCount: 1` is hardcoded. All current TSPL templates lay out 4 physical copies spatially
  in the TSPL string itself (not via `PRINT m,n` repetition). The edge uses this for its dispatch
  timeout formula (`labelCount × 2s + 5s`). Add a real `PrintJob.label_count` field only if
  multi-set jobs are introduced later.
- No `dispatch_mode` in the response — the edge only receives jobs of mode `'edge'` by definition.

### 5b. `POST /api/v1/edge/print-jobs/<uuid:job_id>/ack`

```python
_PRINT_JOB_ACK_RL_WINDOW = 60
_PRINT_JOB_ACK_RL_LIMIT  = 120   # higher — a burst of retries is normal

@csrf_exempt
@require_edge_id
@parse_json_body
def edge_ack_print_job(request, job_id):
    """
    Idempotent ACK from the edge after a print attempt.
    Edge sends this for both success ('completed') and failure ('failed').
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    from tenants.redis_support import atomic_rate_incr
    if atomic_rate_incr(
        f"edge_rl:print_job_ack:{request.edge_device.id}",
        _PRINT_JOB_ACK_RL_WINDOW
    ) > _PRINT_JOB_ACK_RL_LIMIT:
        return JsonResponse({"error": "rate limit exceeded"}, status=429)

    from labeling.models import PrintJob
    try:
        job = PrintJob.objects.get(id=job_id, site=request.edge_site)
    except PrintJob.DoesNotExist:
        return JsonResponse({"error": "Job not found"}, status=404)

    body = request.json_body
    status = (body.get("status") or "").strip()
    if status not in ("dispatched", "completed", "failed"):
        return JsonResponse({"error": "status must be dispatched|completed|failed"}, status=400)

    update_fields = ["status", "attempts", "error_text", "updated_at"]
    job.status     = status
    job.attempts   = int(body.get("attempts") or job.attempts)
    job.error_text = (body.get("errorText") or "")[:500]

    # Resolve the printer UUID from the edge's global_printer_id
    resolved_printer_raw = body.get("resolvedPrinter")
    if resolved_printer_raw:
        try:
            job.target_printer_id = uuid.UUID(str(resolved_printer_raw))
            update_fields.append("target_printer")
        except (ValueError, TypeError):
            pass

    if status == "dispatched" and not job.edge_received_at:
        job.edge_received_at = timezone.now()
        update_fields.append("edge_received_at")

    if status == "completed":
        job.printed_at = _parse_iso(body.get("printedAt")) or timezone.now()
        update_fields.append("printed_at")

    job.save(update_fields=update_fields)

    _log_edge_activity(
        action="print_job_ack",
        request=request,
        edge=request.edge_device,
        site=request.edge_site,
        message=f"Print job {job_id} → {status}",
        payload={"attempts": job.attempts, "error": job.error_text[:120] or None},
    )

    return JsonResponse({"ok": True})
```

**Notes:**
- Idempotent — edge can re-ack on retry; fields are simply overwritten.
- `site=request.edge_site` in the lookup makes cross-site access return 404, not 403, leaking
  nothing about other tenants.
- `resolvedPrinter` in the request body is the `global_printer_id` UUID that the edge stored
  after the inventory push. The edge looks this up from its local `printers.global_printer_id`
  column before sending the ACK.

### 5c. `POST /api/v1/edge/printers/inventory`

```python
_PRINTER_INVENTORY_RL_WINDOW = 60
_PRINTER_INVENTORY_RL_LIMIT  = 10   # startup/config-change only

@csrf_exempt
@require_edge_id
@parse_json_body
def edge_printer_inventory(request):
    """
    Edge pushes its physical printer list on startup and on config change.
    Upserts Printer rows. Returns the Django UUID for each printer so the
    edge can store it as global_printer_id and include it in future ACKs.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    from tenants.redis_support import atomic_rate_incr
    if atomic_rate_incr(
        f"edge_rl:printer_inventory:{request.edge_device.id}",
        _PRINTER_INVENTORY_RL_WINDOW
    ) > _PRINTER_INVENTORY_RL_LIMIT:
        return JsonResponse({"error": "rate limit exceeded"}, status=429)

    body   = request.json_body
    items  = body.get("printers") or []
    if not isinstance(items, list):
        return JsonResponse({"error": "printers must be a list"}, status=400)

    results = []
    with transaction.atomic():
        for item in items:
            local_id = (item.get("localPrinterId") or "").strip()
            host     = (item.get("host") or "").strip()
            if not local_id or not host:
                continue

            printer, _ = Printer.objects.update_or_create(
                edge=request.edge_device,
                local_printer_id=local_id,
                defaults={
                    "site":         request.edge_site,
                    "display_name": (item.get("displayName") or "")[:200],
                    "role":         (item.get("role") or "generic").strip(),
                    "transport":    (item.get("transport") or "tcp").strip(),
                    "host":         host,
                    "port":         int(item.get("port") or 9100),
                    "model":        (item.get("model") or "")[:64],
                    "priority":     int(item.get("priority") or 100),
                    "version":      (item.get("version") or "")[:64],
                    "enabled":      True,
                },
            )
            results.append({
                "localPrinterId":  local_id,
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

**Note:** `update_or_create` uses `(edge, local_printer_id)` as the lookup key — matching the
`UniqueConstraint` on the model. Subsequent pushes update fields in-place.

---

## 6. `edge_heartbeat` extension

Find the existing `edge_heartbeat` view in `scales/api_views.py`. After the existing
`devices_payload` processing loop, add:

```python
# --- printers[] heartbeat update (additive, backwards-compatible) ---
printers_payload = body.get("printers") or []
for item in printers_payload:
    local_id   = (item.get("localPrinterId") or "").strip()
    status_val = (item.get("status") or "unknown").strip()
    last_seen  = _parse_iso(item.get("lastSeenAt")) or timezone.now()
    last_error = (item.get("lastError") or "")[:255]

    if not local_id:
        continue

    Printer.objects.filter(
        edge=edge,
        local_printer_id=local_id,
    ).update(
        status=status_val,
        last_seen_at=last_seen,
        last_error=last_error,
    )
```

Add `from .models import Printer` to the existing import block at the top of `api_views.py`.

**Invariant:** heartbeat only updates runtime fields. It never creates rows. Only
`edge_printer_inventory` creates rows. This ensures inventory changes are explicit events.

---

## 7. URL registration in `scales/api_urls.py`

```python
from django.urls import path
from . import api_views

urlpatterns = [
    # --- existing entries ---
    path("register",                                 api_views.edge_register,               name="edge-register"),
    path("sessions",                                 api_views.edge_sessions,               name="edge-sessions"),
    path("events",                                   api_views.edge_post_event,             name="edge-post-event"),
    path("events/batch",                             api_views.edge_post_event_batch,       name="edge-post-event-batch"),
    path("offline-batches/ack",                      api_views.edge_offline_batch_ack,      name="edge-offline-batch-ack"),
    path("config",                                   api_views.edge_config,                 name="edge-config"),
    path("devices/status",                           api_views.edge_device_status,          name="edge-device-status"),
    path("heartbeat",                                api_views.edge_heartbeat,              name="edge-heartbeat"),

    # --- NEW: printer module (Phase 1B) ---
    path("print-jobs/pending",                       api_views.edge_pending_print_jobs,     name="edge-pending-print-jobs"),
    path("print-jobs/<uuid:job_id>/ack",             api_views.edge_ack_print_job,          name="edge-ack-print-job"),
    path("printers/inventory",                       api_views.edge_printer_inventory,      name="edge-printer-inventory"),
]
```

No changes to `config/urls.py` — the `/api/v1/edge/` prefix is already mounted there.

---

## 8. Admin (`scales/admin.py`)

```python
from .models import Printer

class PrinterInline(admin.TabularInline):
    model = Printer
    extra = 0
    readonly_fields = ("status", "last_seen_at", "last_error", "version")
    fields = ("local_printer_id", "display_name", "role", "host", "port",
              "priority", "enabled", "status", "last_seen_at", "last_error")
    show_change_link = True


# Add inline to existing EdgeDeviceAdmin:
class EdgeDeviceAdmin(admin.ModelAdmin):
    inlines = [PrinterInline, ...]   # add to existing inlines list


@admin.register(Printer)
class PrinterAdmin(admin.ModelAdmin):
    list_display  = ("local_printer_id", "display_name", "role", "host",
                     "port", "status", "priority", "enabled", "last_seen_at")
    list_filter   = ("role", "status", "enabled", "site")
    search_fields = ("local_printer_id", "display_name", "host")
    readonly_fields = ("status", "last_seen_at", "last_error", "version",
                       "edge", "site")  # edge-owned fields are read-only
    ordering = ("site", "role", "priority")
```

## 9. Admin (`labeling/admin.py`)

Extend existing `PrintJobAdmin`:

```python
@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display  = ("id", "item_type", "status", "dispatch_mode",
                     "target_role", "site", "attempts", "print_date", "printed_at")
    list_filter   = ("status", "dispatch_mode", "target_role", "site")
    search_fields = ("id", "item_type", "error_text")
    readonly_fields = ("print_date", "edge_received_at", "printed_at",
                       "attempts", "error_text", "prn_content")

    actions = ["reenqueue_failed_jobs"]

    @admin.action(description="Re-enqueue selected failed jobs")
    def reenqueue_failed_jobs(self, request, queryset):
        updated = queryset.filter(status="failed").update(
            status="pending", attempts=0, error_text=""
        )
        self.message_user(request, f"{updated} job(s) re-enqueued.")
```

---

## 10. Migrations

Run in this order:

```bash
# 1. scales.Printer
./manage.py makemigrations scales --name printer
# → scales/migrations/00NN_printer.py

# 2. labeling.PrintJob extensions
./manage.py makemigrations labeling --name printjob_edge_dispatch
# → labeling/migrations/00NN_printjob_edge_dispatch.py

# 3. Apply to ALL tenant schemas (existing command)
./manage.py migrate_schemas
```

Both migrations are zero-downtime: all new fields are nullable or have defaults.
No data backfill. Existing `PrintJob` rows (none reference a site or printer) are unaffected.

---

## API contract — aligned with edge Phase 1A

### `GET /api/v1/edge/print-jobs/pending` → response

```json
{
  "jobs": [
    {
      "jobId":         "c8e2a1f4-7b3d-4e5f-a1b2-0123456789ab",
      "targetRole":    "carcass",
      "targetPrinter": null,
      "prnContent":    "SIZE 97.5 mm, 260 mm\r\nGAP 3 mm, 0 mm\r\nCODEPAGE 1254\r\n...\r\nPRINT 1,1\r\n",
      "labelCount":    1,
      "attempts":      0,
      "createdAt":     "2026-04-13T10:00:00Z"
    }
  ]
}
```

**Edge intake:** `prnContent` is a UTF-8 JSON string. Edge encodes to Windows-1254 via
`iconv.encode(prnContent, "windows-1254")` **before** storing in SQLite as BLOB.
The BLOB is sent verbatim to TCP:9100. No further encoding at dispatch time.

### `POST /api/v1/edge/print-jobs/<uuid>/ack` → request

```json
{
  "status":          "completed",
  "printedAt":       "2026-04-13T10:00:14.789Z",
  "resolvedPrinter": "c8e2a1f4-7b3d-4e5f-a1b2-0123456789ab",
  "attempts":        1,
  "errorText":       ""
}
```

`resolvedPrinter` is the **UUID** from `printers.global_printer_id` in the edge's SQLite —
the value returned by the inventory push and stored locally. Not the local string ID.

### `POST /api/v1/edge/printers/inventory` → request / response

```json
// request
{
  "printers": [
    {
      "localPrinterId": "carcass-01",
      "displayName":    "Carcass Line",
      "role":           "carcass",
      "transport":      "tcp",
      "host":           "192.168.1.220",
      "port":           9100,
      "model":          "TE210",
      "priority":       100,
      "version":        "V7.02"
    }
  ]
}

// response
{
  "ok": true,
  "printers": [
    { "localPrinterId": "carcass-01", "globalPrinterId": "c8e2a1f4-..." }
  ]
}
```

Edge stores `globalPrinterId` in `printers.global_printer_id` column in SQLite immediately.

### Heartbeat extension → additive field

```json
{
  "version":  "0.4.0",
  "devices":  [ ...existing... ],
  "printers": [
    {
      "localPrinterId": "carcass-01",
      "status":         "online",
      "lastSeenAt":     "2026-04-13T10:00:00Z",
      "lastError":      ""
    }
  ]
}
```

---

## Known issues in the original architecture doc (resolved here)

| Issue | Original doc | This plan |
|---|---|---|
| `item_id` non-nullable | Silent (would cause IntegrityError when `label=None`) | **`null=True, blank=True` in migration** |
| `item_type` mapping | `item_type=label.label_type` — wrong choices | **`_LABEL_TYPE_TO_ROLE` mapping table** |
| `labelCount` in API response | Missing | **Hardcoded `1` in poll view** |
| `resolvedPrinter` is UUID not local string | Ambiguous | **Explicit: UUID from `global_printer_id`** |
| `STATUS_CHOICES` not updated | New statuses described in comments only | **`dispatched` and `cancelled` added explicitly** |
| `Printer` import in `api_views.py` | Not mentioned | **Add to top-level import block** |
| `site` resolution in user views | `request.user.tenant_site` (doesn't exist) | **`Site.objects.first()` for Phase 1B** |

---

## Exit criteria for Phase 1B

1. `./manage.py migrate_schemas` runs without errors on a clean DB.
2. `curl -X POST https://tenant.carnitrack.com/api/v1/edge/printers/inventory` with `X-Edge-Id` creates a `Printer` row visible in Django admin.
3. `python manage.py shell` → `enqueue_print_job(site=..., prn_content="...", target_role="carcass")` → creates a `PrintJob` with `status='pending'`.
4. `curl GET .../print-jobs/pending` returns that job with `prnContent` inline.
5. `curl POST .../print-jobs/<uuid>/ack` with `status=completed` → job shows `status='completed'` and `printed_at` is set in Django admin.
6. A second identical ACK returns `{"ok": true}` (idempotent).
7. Cross-site ACK (wrong `X-Edge-Id` for another tenant) returns 404.

---

## Phase sequencing

| Phase | Scope | Dependency |
|---|---|---|
| **1A** (edge) | `src/printers/` local-only, `POST /api/print-jobs`, SQLite queue, TCP dispatch | None (no Django needed) |
| **1B** (this doc) | Models, migrations, 3 API endpoints, admin, `enqueue_print_job` | Runs in parallel with 1A |
| **2** (integration) | Edge polls cloud; edge pushes heartbeat printers[]; inventory push on startup | Requires 1A + 1B complete |
| **3** (UX) | Django "Print to Edge" buttons in label UI; per-tenant dispatch default | Requires Phase 2 stable |
