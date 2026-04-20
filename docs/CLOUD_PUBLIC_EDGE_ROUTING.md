# Cloud: Public-Schema Edge API Routing

## Problem

Edge devices call `api.carnitrack.com/api/v1/edge/*` (public domain) for **all** API
requests — heartbeat, sessions, events, print-jobs, etc.

Currently only `/api/v1/activate` is available on the public schema.
All other Edge routes (`/api/v1/edge/*`) are in the **tenant URLconf** only, so requests
hitting the public domain get a redirect → HTML → the Edge sees `403` / `Failed to parse JSON`.

## Solution

Route Edge API requests through the **public schema** by:

1. Creating an `EdgeDeviceIndex` public-schema table (edge_id → tenant_schema)
2. Adding a `public_require_edge_id` decorator that resolves the tenant via this index
3. Registering wrapped Edge views in `urls_public.py`

This follows the exact same pattern as `EdgeSetupCodeIndex` + `public_edge_activate`.

---

## Step 1 — New Model: `EdgeDeviceIndex`

**File:** `tenants/models.py`

Add after `EdgeSetupCodeIndex`:

```python
class EdgeDeviceIndex(models.Model):
    """
    Public-schema lookup table mapping registered Edge device UUIDs to tenant schemas.

    Enables Edge API requests on the public domain (api.carnitrack.com) without
    requiring the Edge to know its tenant subdomain. The decorator
    public_require_edge_id uses this table to resolve the tenant, then switches
    to the tenant schema via schema_context() before calling the actual view.

    Rows are created during activation (public_edge_activate) and synced via
    post_save/post_delete signals on EdgeDevice in each tenant schema.
    """

    edge_id = models.UUIDField(unique=True, db_index=True, help_text="EdgeDevice.id from the tenant schema.")
    tenant = models.ForeignKey("tenants.Client", on_delete=models.CASCADE, related_name="edge_device_index_entries")
    tenant_schema = models.CharField(max_length=63, help_text="Cached schema_name for fast lookup without JOIN.")
    edge_name = models.CharField(max_length=200, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants_edge_device_index"
        indexes = [
            models.Index(fields=["edge_id"]),
            models.Index(fields=["tenant", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Edge {self.edge_id} -> {self.tenant_schema}"
```

### Migration

```bash
python manage.py makemigrations tenants --name add_edge_device_index
python manage.py migrate_schemas --shared
```

---

## Step 2 — Populate Index During Activation

**File:** `tenants/api_views_edge.py`

In `public_edge_activate`, right after creating the `EdgeDevice` inside `schema_context`,
add the public-schema index entry **outside** the schema_context (since it's a public model):

```python
# After the schema_context block, before building the response:
from tenants.models import EdgeDeviceIndex

EdgeDeviceIndex.objects.update_or_create(
    edge_id=edge.id,
    defaults={
        "tenant": tenant,
        "tenant_schema": tenant_schema,
        "edge_name": edge_name,
        "is_active": True,
    },
)
```

Insert this between the `with schema_context(tenant_schema):` block (line ~145) and
`tenant_base_url = build_tenant_api_base_url(tenant)` (line ~161).

---

## Step 3 — Signal Sync for EdgeDevice Changes

**File:** `scales/signals.py`

Add signals so that if an EdgeDevice is updated (e.g. deactivated, renamed) or deleted,
the public index stays in sync:

```python
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db import connection

from .models import EdgeDevice


@receiver(post_save, sender=EdgeDevice)
def sync_edge_device_index_on_save(sender, instance, created, **kwargs):
    """Keep public EdgeDeviceIndex in sync when EdgeDevice is saved."""
    from django_tenants.utils import get_public_schema_name, schema_context
    from tenants.models import Client, EdgeDeviceIndex

    current_schema = connection.schema_name
    if current_schema == get_public_schema_name():
        return  # avoid recursion if somehow called from public

    try:
        tenant = Client.objects.get(schema_name=current_schema)
    except Client.DoesNotExist:
        return

    with schema_context(get_public_schema_name()):
        EdgeDeviceIndex.objects.update_or_create(
            edge_id=instance.id,
            defaults={
                "tenant": tenant,
                "tenant_schema": current_schema,
                "edge_name": instance.name or "",
                "is_active": instance.is_active,
            },
        )


@receiver(post_delete, sender=EdgeDevice)
def sync_edge_device_index_on_delete(sender, instance, **kwargs):
    """Remove public EdgeDeviceIndex when EdgeDevice is deleted."""
    from django_tenants.utils import get_public_schema_name, schema_context
    from tenants.models import EdgeDeviceIndex

    with schema_context(get_public_schema_name()):
        EdgeDeviceIndex.objects.filter(edge_id=instance.id).delete()
```

Make sure these signals are connected in `scales/apps.py`:

```python
class ScalesConfig(AppConfig):
    ...
    def ready(self):
        import scales.signals  # noqa: F401
```

---

## Step 4 — Public Edge API Decorator

**File:** `tenants/edge_middleware.py` (new file)

```python
"""
Public-schema Edge API decorator.

Resolves tenant from X-Edge-Id via EdgeDeviceIndex, then executes the
wrapped view inside that tenant's schema_context.
"""

import uuid
from functools import wraps

from django.http import JsonResponse
from django_tenants.utils import schema_context

from tenants.models import EdgeDeviceIndex


def public_require_edge_id(view_func):
    """
    Like scales.middleware.require_edge_id, but works on the public schema.

    1. Reads X-Edge-Id header
    2. Looks up EdgeDeviceIndex (public schema) to find tenant_schema
    3. Switches to tenant schema via schema_context
    4. Loads the actual EdgeDevice and sets request.edge_device / request.edge_site
    5. Calls the original view inside the tenant context
    """

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        edge_id_raw = request.headers.get("X-Edge-Id") or request.META.get("HTTP_X_EDGE_ID")
        if not edge_id_raw:
            return JsonResponse({"error": "Missing X-Edge-Id header"}, status=401)

        try:
            edge_uuid = uuid.UUID(str(edge_id_raw))
        except (ValueError, TypeError):
            return JsonResponse(
                {"error": "Invalid X-Edge-Id format; expected UUID"},
                status=401,
            )

        try:
            index_entry = EdgeDeviceIndex.objects.get(edge_id=edge_uuid, is_active=True)
        except EdgeDeviceIndex.DoesNotExist:
            return JsonResponse({"error": "Unknown Edge ID"}, status=401)

        tenant_schema = index_entry.tenant_schema

        with schema_context(tenant_schema):
            from scales.models import EdgeDevice

            try:
                edge = EdgeDevice.objects.get(id=edge_uuid, is_active=True)
            except EdgeDevice.DoesNotExist:
                return JsonResponse({"error": "Edge device not found in tenant"}, status=401)

            request.edge_device = edge
            request.edge_site = edge.site
            return view_func(request, *args, **kwargs)

    return wrapped
```

---

## Step 5 — Public URL Routes

**File:** `config/urls_public.py`

Replace the catch-all and add Edge API routes. The views already exist in `scales.api_views`;
we just need to **re-decorate** them with the public-schema-aware decorator.

Add a new file to keep it clean:

**File:** `tenants/public_edge_urls.py` (new file)

```python
"""
Public-schema Edge API URL routes.

These are the same views as scales.api_urls, but wrapped with
public_require_edge_id which resolves the tenant from X-Edge-Id
via the public EdgeDeviceIndex table.
"""

from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from scales import api_views
from tenants.edge_middleware import public_require_edge_id


def _pub(view_func):
    """Wrap a tenant-scoped Edge view for public-schema use."""
    return csrf_exempt(public_require_edge_id(view_func))


urlpatterns = [
    path("register", _pub(api_views.edge_register), name="pub-edge-register"),
    path("activate", _pub(api_views.edge_activate), name="pub-edge-activate-v2"),
    path("sessions", _pub(api_views.edge_sessions), name="pub-edge-sessions"),
    path("events", _pub(api_views.edge_post_event), name="pub-edge-post-event"),
    path("events/batch", _pub(api_views.edge_post_event_batch), name="pub-edge-post-event-batch"),
    path("offline-batches/ack", _pub(api_views.edge_offline_batch_ack), name="pub-edge-offline-batch-ack"),
    path("config", _pub(api_views.edge_config), name="pub-edge-config"),
    path("devices/status", _pub(api_views.edge_device_status), name="pub-edge-device-status"),
    path("heartbeat", _pub(api_views.edge_heartbeat), name="pub-edge-heartbeat"),
    path("print-jobs/pending", _pub(api_views.edge_pending_print_jobs), name="pub-edge-pending-print-jobs"),
    path("print-jobs/<uuid:job_id>/ack", _pub(api_views.edge_ack_print_job), name="pub-edge-ack-print-job"),
    path("printers/inventory", _pub(api_views.edge_printer_inventory), name="pub-edge-printer-inventory"),
]
```

**File:** `config/urls_public.py`

Add the include **before** the catch-all redirect:

```python
# Add this import at the top:
# (no new imports needed, just use include)

# Add this line BEFORE the re_path catch-all:
path("api/v1/edge/", include("tenants.public_edge_urls")),
```

The updated urlpatterns should look like:

```python
urlpatterns = [
    path("api/v1/auth/", include("users.api_urls")),
    path("api/v1/tenant-registration/", include("tenants.api_urls")),
    path("api/v1/activate", public_edge_activate, name="public-edge-activate"),
    path("api/v1/edge/", include("tenants.public_edge_urls")),   # <-- NEW
    path("", public_landing, name="public_landing"),
    # ... rest unchanged ...
    re_path(r"^.+$", RedirectView.as_view(pattern_name="public_landing", permanent=False)),
]
```

---

## Step 6 — Handle Double-Decoration

The existing tenant-scoped views already have `@csrf_exempt` and `@require_edge_id`.
When wrapped with `public_require_edge_id`, the inner `@require_edge_id` will try to
do `EdgeDevice.objects.get(...)` again — but this time it **will work** because
`public_require_edge_id` already switched to the correct tenant schema via `schema_context`.

So the views don't need any changes. The double lookup is harmless (one extra SELECT)
and keeps the views working on both tenant subdomains and the public domain.

If you want to optimize, you could make `require_edge_id` skip the lookup when
`request.edge_device` is already set:

```python
# In scales/middleware.py, at the top of require_edge_id's wrapped():
if hasattr(request, "edge_device") and request.edge_device is not None:
    return view_func(request, *args, **kwargs)
```

---

## Step 7 — Backfill Existing EdgeDevices

For any EdgeDevices created before this change, run a management command to
populate `EdgeDeviceIndex`:

**File:** `tenants/management/commands/backfill_edge_device_index.py`

```python
from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, schema_context, get_tenant_model

from tenants.models import EdgeDeviceIndex


class Command(BaseCommand):
    help = "Backfill EdgeDeviceIndex from all tenant EdgeDevice rows."

    def handle(self, *args, **options):
        TenantModel = get_tenant_model()
        tenants = TenantModel.objects.exclude(schema_name=get_public_schema_name())
        total = 0

        for tenant in tenants:
            with schema_context(tenant.schema_name):
                from scales.models import EdgeDevice

                for edge in EdgeDevice.objects.all():
                    with schema_context(get_public_schema_name()):
                        _, created = EdgeDeviceIndex.objects.update_or_create(
                            edge_id=edge.id,
                            defaults={
                                "tenant": tenant,
                                "tenant_schema": tenant.schema_name,
                                "edge_name": edge.name or "",
                                "is_active": edge.is_active,
                            },
                        )
                    if created:
                        total += 1
                        self.stdout.write(f"  Created index: {edge.id} -> {tenant.schema_name}")
                    else:
                        self.stdout.write(f"  Updated index: {edge.id} -> {tenant.schema_name}")

        self.stdout.write(self.style.SUCCESS(f"Done. {total} new index entries created."))
```

Run:
```bash
python manage.py backfill_edge_device_index
```

---

## Summary of Files to Create/Modify

| Action | File | What |
|--------|------|------|
| **MODIFY** | `tenants/models.py` | Add `EdgeDeviceIndex` model |
| **CREATE** | `tenants/edge_middleware.py` | `public_require_edge_id` decorator |
| **CREATE** | `tenants/public_edge_urls.py` | Public-schema Edge URL routes |
| **MODIFY** | `tenants/api_views_edge.py` | Create `EdgeDeviceIndex` row during activation |
| **MODIFY** | `config/urls_public.py` | Include `tenants.public_edge_urls` |
| **MODIFY** | `scales/signals.py` | Sync `EdgeDeviceIndex` on EdgeDevice save/delete |
| **MODIFY** | `scales/apps.py` | Ensure signals are imported in `ready()` |
| **MODIFY** | `scales/middleware.py` | (Optional) Skip re-lookup if already resolved |
| **CREATE** | `tenants/management/commands/backfill_edge_device_index.py` | One-time backfill |
| **RUN** | migration | `makemigrations tenants` + `migrate_schemas --shared` |
| **RUN** | backfill | `python manage.py backfill_edge_device_index` |

## Request Flow After Implementation

```
Edge (Windows .exe)
  │
  │  POST https://api.carnitrack.com/api/v1/edge/heartbeat
  │  Headers: X-Edge-Id: 56cb06f7-5806-4095-a8f1-8ca0bb82f5e9
  │
  ▼
Cloud (public schema — urls_public.py)
  │
  │  public_require_edge_id decorator:
  │    1. Read X-Edge-Id header
  │    2. SELECT * FROM tenants_edge_device_index WHERE edge_id = ?
  │    3. Found: tenant_schema = "acme_meats"
  │    4. schema_context("acme_meats") { ... call view ... }
  │
  ▼
scales.api_views.edge_heartbeat (runs inside tenant schema)
  │
  │  EdgeDevice.objects.get(id=...) ← works because we're in the right schema
  │  Returns: {"ok": true, "serverTime": "..."}
  │
  ▼
Edge receives JSON response ✓
```
