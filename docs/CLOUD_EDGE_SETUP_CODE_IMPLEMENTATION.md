# Cloud: Edge Setup Code System — Implementation Guide

> **Context:** This document is a complete implementation spec for adding a Cloud-first Edge
> provisioning flow. An Edge device compiled as a standalone `.exe`/binary needs a way to
> link itself to a tenant's site without manual `.env` editing. The solution: generate a
> short-lived **setup code** in Cloud, enter it in the Edge's first-run wizard.
>
> **Parallel work:** The Edge-side (setup wizard + `bun build --compile`) is being built
> simultaneously in the `Carnitrack_EDGE` repo.
>
> **Printer integration:** The setup code flow also provisions printer configuration so
> the Edge is ready to print immediately after activation — no manual printer setup needed.

---

## Overview

```
Cloud Dashboard (tenant schema)              Edge Device (.exe)
───────────────────────────────              ──────────────────
Admin → Edge Management                      User runs .exe
     → [+ Add Edge Device]                   Opens http://localhost:3000
     → Fills: name, site, printers           Sees setup wizard
     → Gets: CT-8K4M-XNPR                   Enters: CT-8K4M-XNPR
     → Signal syncs code to public schema          │
       (EdgeSetupCodeIndex)          ┌─────────────┘
                                     ▼
                    POST https://api.carnitrack.com/api/v1/activate
                    { "code": "CT-8K4M-XNPR", "version": "0.3.0",
                      "capabilities": ["weighing", "printing"] }
                                     │
                                     ▼
                    Cloud: look up code in public schema → resolve tenant
                         → switch to tenant schema
                         → validate code, create EdgeDevice, return identity
                    {
                      "edgeId": "uuid",
                      "siteId": "uuid",
                      "siteName": "...",
                      "config": { "baseUrl": "https://farm1.carnitrack.com", ... },
                      "printers": [{ host, port, role, name, localPrinterId }]
                    }
                                     │
                                     ▼
                    Edge stores identity, saves config.baseUrl as CLOUD_API_URL,
                    auto-configures printers, pushes inventory to tenant URL
```

---

## Step 1: New Model — `EdgeSetupCode`

**File:** `scales/models.py`

Add after the `EdgeDevice` class:

```python
import secrets


def generate_setup_code():
    """Generate a human-friendly setup code like CT-8K4M-XNPR."""
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    part1 = "".join(secrets.choice(alphabet) for _ in range(4))
    part2 = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"CT-{part1}-{part2}"


class EdgeSetupCode(BaseModel):
    """
    Short-lived activation code for Edge device provisioning.
    Generated from Cloud dashboard, consumed by Edge's first-run wizard via POST /edge/activate.
    """
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="setup_codes")
    code = models.CharField(max_length=16, unique=True, default=generate_setup_code)
    edge_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Pre-configured name for the Edge device."
    )
    printers_config = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Pre-configured printer list for the Edge. Each entry: "
            '{"localPrinterId": "carcass-01", "host": "192.168.1.220", '
            '"port": 9100, "role": "carcass", "displayName": "Carcass Line"}. '
            "Returned in the /activate response so the Edge auto-configures printers."
        ),
    )
    expires_at = models.DateTimeField(
        help_text="Code expires after this time (default 48 hours from creation)."
    )
    used_at = models.DateTimeField(null=True, blank=True)
    used_by_edge = models.ForeignKey(
        EdgeDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="setup_code",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["site", "-created_at"]),
        ]

    def is_valid(self):
        """True if code is not expired and not yet used."""
        from django.utils import timezone
        return self.used_at is None and self.expires_at > timezone.now()

    def __str__(self):
        status = "used" if self.used_at else ("expired" if not self.is_valid() else "active")
        return f"{self.code} ({status}) → {self.site.name}"
```

### Design notes

- `code` has `unique=True` which implicitly creates an index — no need for extra `db_index=True` or `Meta.indexes` on `code`.
- `printers_config` is the key link to the printer system. When an admin creates a setup code, they also configure which printers the Edge should connect to. This list is returned verbatim in the `/activate` response so the Edge can auto-configure its local printer registry and immediately push a `POST /printers/inventory` to Cloud.
- `BaseModel` provides `id` (UUID PK), `created_at`, `updated_at`, and `is_active` (soft-delete).

### Migration

```bash
python manage.py makemigrations scales -n "add_edge_setup_code"
python manage.py migrate_schemas
```

---

## Step 2: New API Endpoint — `POST /api/v1/edge/activate`

**File:** `scales/api_urls.py`

Add one line:

```python
path("activate", api_views.edge_activate, name="edge-activate"),
```

**File:** `scales/api_views.py`

Add this view function right after `edge_register`. Note: `timezone`, `JsonResponse`, `csrf_exempt`, `parse_json_body`, `_log_edge_activity`, `_edge_runtime_config`, `EdgeDevice`, `Site`, and `transaction` are already imported in this file.

```python
_ACTIVATE_RL_LIMIT = 10
_ACTIVATE_RL_WINDOW = 60


@csrf_exempt
@parse_json_body
def edge_activate(request):
    """
    Activate an Edge device using a setup code generated from the Cloud dashboard.
    This is the primary registration path for standalone Edge binaries (.exe).

    The existing /register endpoint remains for backward compatibility (Docker/env-var flow).
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    from tenants.redis_support import atomic_rate_incr

    ip = request.META.get("REMOTE_ADDR", "unknown")
    if atomic_rate_incr(f"edge_rl:activate:ip:{ip}", _ACTIVATE_RL_WINDOW) > _ACTIVATE_RL_LIMIT:
        return JsonResponse({"error": "rate limit exceeded"}, status=429)

    body = request.json_body
    code_raw = (body.get("code") or "").strip().upper()
    version = (body.get("version") or "").strip()
    capabilities = body.get("capabilities") or []

    if not code_raw:
        return JsonResponse({"error": "code is required"}, status=400)

    from .models import EdgeSetupCode

    # select_for_update prevents two Edge devices from racing on the same code
    with transaction.atomic():
        try:
            setup_code = (
                EdgeSetupCode.objects
                .select_for_update()
                .select_related("site")
                .get(code=code_raw, is_active=True)
            )
        except EdgeSetupCode.DoesNotExist:
            return JsonResponse(
                {"error": "Setup code not found. Check the code and try again."},
                status=404,
            )

        if setup_code.used_at is not None:
            return JsonResponse(
                {"error": "This setup code has already been used by another Edge device."},
                status=409,
            )

        if setup_code.expires_at < timezone.now():
            return JsonResponse(
                {"error": "This setup code has expired. Please generate a new one from Cloud."},
                status=410,
            )

        # Create the Edge device
        site = setup_code.site
        edge_name = setup_code.edge_name or site.name

        edge = EdgeDevice.objects.create(
            site=site,
            name=edge_name,
            is_online=True,
            last_seen_at=timezone.now(),
            version=version or "",
        )

        # Mark code as used
        setup_code.used_at = timezone.now()
        setup_code.used_by_edge = edge
        setup_code.save(update_fields=["used_at", "used_by_edge", "updated_at"])

    # Log the activation
    _log_edge_activity(
        action="activate",
        request=request,
        edge=edge,
        site=site,
        message=f"Edge activated via setup code: {code_raw}",
        payload={
            "version": version,
            "code": code_raw,
            "mode": "setup_code_activation",
            "capabilities": capabilities,
        },
    )

    # Build printers list from setup code config
    printers_config = setup_code.printers_config or []
    printers_out = []
    for p in printers_config:
        printers_out.append({
            "localPrinterId": p.get("localPrinterId", ""),
            "displayName": p.get("displayName", ""),
            "role": p.get("role", "generic"),
            "transport": p.get("transport", "tcp"),
            "host": p.get("host", ""),
            "port": p.get("port", 9100),
            "model": p.get("model", ""),
            "priority": p.get("priority", 100),
        })

    return JsonResponse(
        {
            "edgeId": str(edge.id),
            "siteId": str(site.id),
            "siteName": site.name,
            "config": _edge_runtime_config(request),
            "printers": printers_out,
        }
    )
```

### Key Design Decisions

- **`select_for_update()` inside `transaction.atomic()`** — prevents a race condition where two Edge devices submit the same code simultaneously. The first one wins; the second sees `used_at is not None` and gets a 409.
- **Same base response shape as `/register`** plus `printers[]` — Edge code handles both paths with a single response type.
- **No `@require_edge_id`** — this is the first call, no identity exists yet.
- **Rate limited per IP** — prevents brute-forcing codes.
- **Code is case-insensitive** — `.upper()` normalizes input.
- **HTTP 404** for unknown code, **409** for already used, **410** for expired — distinct errors for the Edge UI.
- **Existing `/register` stays unchanged** — backward compatible for Docker deployments.
- **`printers[]` in the response** — the Edge uses this to auto-configure its local printer registry, then immediately pushes `POST /printers/inventory` to Cloud. This means the Edge is print-ready seconds after activation, with no manual printer setup.

---

## Step 3: Dashboard — "Add Edge Device" Flow

### 3a. Add URL routes for setup code management

**File:** `scales/urls.py`

Add these routes:

```python
path("edge-management/setup-codes/", views.EdgeSetupCodeListView.as_view(), name="edge_setup_code_list"),
path("edge-management/setup-codes/create/", views.EdgeSetupCodeCreateView.as_view(), name="edge_setup_code_create"),
path("edge-management/setup-codes/<uuid:pk>/", views.EdgeSetupCodeDetailView.as_view(), name="edge_setup_code_detail"),
path("edge-management/setup-codes/<uuid:pk>/revoke/", views.EdgeSetupCodeRevokeView.as_view(), name="edge_setup_code_revoke"),
```

### 3b. Add the views

**File:** `scales/views.py`

```python
from datetime import timedelta
from .models import EdgeSetupCode, Printer


class EdgeSetupCodeListView(LoginRequiredMixin, AdminOnlyMixin, ListView):
    """List all setup codes with status indicators."""
    model = EdgeSetupCode
    template_name = "scales/edge_setup_code_list.html"
    context_object_name = "setup_codes"
    paginate_by = 25

    def get_queryset(self):
        return (
            EdgeSetupCode.objects
            .filter(is_active=True)
            .select_related("site", "used_by_edge")
            .order_by("-created_at")
        )


class EdgeSetupCodeCreateView(LoginRequiredMixin, AdminOnlyMixin, View):
    """Handle the 'Add Edge Device' form submission."""

    def get(self, request):
        sites = Site.objects.filter(is_active=True).order_by("name")
        printers = (
            Printer.objects
            .filter(is_active=True, enabled=True)
            .select_related("site", "edge")
            .order_by("site__name", "role", "priority")
        )
        return render(request, "scales/edge_setup_code_create.html", {
            "sites": sites,
            "printers": printers,
        })

    def post(self, request):
        site_id = request.POST.get("site_id")
        edge_name = (request.POST.get("edge_name") or "").strip()
        expiry_hours = int(request.POST.get("expiry_hours", 48))

        if not site_id:
            messages.error(request, _("Please select a site."))
            return redirect("scales:edge_setup_code_create")

        try:
            site = Site.objects.get(id=site_id, is_active=True)
        except Site.DoesNotExist:
            messages.error(request, _("Site not found."))
            return redirect("scales:edge_setup_code_create")

        # Build printers_config from form data
        printers_config = []
        printer_ids = request.POST.getlist("printer_ids")
        for pid in printer_ids:
            try:
                printer = Printer.objects.get(id=pid, site=site, is_active=True)
                printers_config.append({
                    "localPrinterId": printer.local_printer_id,
                    "displayName": printer.display_name,
                    "role": printer.role,
                    "transport": printer.transport,
                    "host": printer.host,
                    "port": printer.port,
                    "model": printer.model,
                    "priority": printer.priority,
                })
            except Printer.DoesNotExist:
                continue

        # Also accept manually entered printers (for new sites with no existing printers)
        manual_hosts = request.POST.getlist("manual_printer_host")
        manual_roles = request.POST.getlist("manual_printer_role")
        manual_names = request.POST.getlist("manual_printer_name")
        for i, host in enumerate(manual_hosts):
            host = host.strip()
            if not host:
                continue
            role = manual_roles[i].strip() if i < len(manual_roles) else "generic"
            name = manual_names[i].strip() if i < len(manual_names) else ""
            printers_config.append({
                "localPrinterId": f"{role}-{i+1:02d}",
                "displayName": name or f"{role.title()} Printer",
                "role": role,
                "transport": "tcp",
                "host": host,
                "port": 9100,
                "model": "",
                "priority": 100,
            })

        setup_code = EdgeSetupCode.objects.create(
            site=site,
            edge_name=edge_name,
            printers_config=printers_config,
            expires_at=timezone.now() + timedelta(hours=expiry_hours),
        )

        return redirect("scales:edge_setup_code_detail", pk=setup_code.pk)


class EdgeSetupCodeDetailView(LoginRequiredMixin, AdminOnlyMixin, DetailView):
    """Show the setup code + instructions after creation."""

    model = EdgeSetupCode
    template_name = "scales/edge_setup_code_detail.html"
    context_object_name = "setup_code"

    def get_queryset(self):
        return EdgeSetupCode.objects.filter(is_active=True).select_related("site", "used_by_edge")

    def get_context_data(self, **kwargs):
        from tenants.tenant_helpers import get_tenant_site_url
        context = super().get_context_data(**kwargs)
        context["tenant_url"] = get_tenant_site_url()
        context["activate_url"] = f"{get_tenant_site_url()}/api/v1/edge/activate"
        return context


class EdgeSetupCodeRevokeView(LoginRequiredMixin, AdminOnlyMixin, View):
    """Revoke (soft-delete) an unused setup code."""

    def post(self, request, pk):
        try:
            setup_code = EdgeSetupCode.objects.get(pk=pk, is_active=True, used_at__isnull=True)
        except EdgeSetupCode.DoesNotExist:
            messages.error(request, _("Setup code not found or already used."))
            return redirect("scales:edge_setup_code_list")

        setup_code.soft_delete()
        messages.success(request, _("Setup code revoked successfully."))
        return redirect("scales:edge_setup_code_list")
```

### 3c. Create the templates

**File:** `scales/templates/scales/edge_setup_code_create.html`

```html
{% extends "base.html" %}
{% load i18n %}

{% block title %}{% trans "Add Edge Device" %}{% endblock %}

{% block content %}
<div class="max-w-2xl mx-auto">
    <div class="mb-6">
        <h1 class="text-2xl font-bold text-gray-900">{% trans "Add Edge Device" %}</h1>
        <p class="mt-2 text-gray-600">
            {% trans "Create a setup code for a new Edge device. The operator at the site will enter this code when they first run the Edge software." %}
        </p>
    </div>

    <form method="post" class="space-y-6 bg-white shadow rounded-lg p-6">
        {% csrf_token %}

        <div>
            <label for="site_id" class="block text-sm font-medium text-gray-700">
                {% trans "Site" %} *
            </label>
            <select name="site_id" id="site_id" required
                    class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500">
                <option value="">{% trans "Select a site..." %}</option>
                {% for site in sites %}
                <option value="{{ site.id }}">{{ site.name }}</option>
                {% endfor %}
            </select>
        </div>

        <div>
            <label for="edge_name" class="block text-sm font-medium text-gray-700">
                {% trans "Edge Device Name" %}
            </label>
            <input type="text" name="edge_name" id="edge_name"
                   placeholder="{% trans 'e.g., Main Facility Edge' %}"
                   class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500">
            <p class="mt-1 text-sm text-gray-500">
                {% trans "Optional. If left empty, the site name will be used." %}
            </p>
        </div>

        <div>
            <label for="expiry_hours" class="block text-sm font-medium text-gray-700">
                {% trans "Code Valid For" %}
            </label>
            <select name="expiry_hours" id="expiry_hours"
                    class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500">
                <option value="24">24 {% trans "hours" %}</option>
                <option value="48" selected>48 {% trans "hours" %}</option>
                <option value="168">7 {% trans "days" %}</option>
            </select>
        </div>

        <!-- Printer Configuration Section -->
        <div class="border-t pt-6">
            <h2 class="text-lg font-semibold text-gray-900 mb-2">{% trans "Printer Configuration" %}</h2>
            <p class="text-sm text-gray-600 mb-4">
                {% trans "Configure printers for this Edge device. These will be auto-configured on the Edge when the setup code is used." %}
            </p>

            <!-- Existing printers (select from site's registered printers) -->
            <div id="existing-printers-section" class="mb-4 hidden">
                <label class="block text-sm font-medium text-gray-700 mb-2">
                    {% trans "Select from existing printers at this site" %}
                </label>
                <div id="existing-printers-list" class="space-y-2">
                </div>
            </div>

            <!-- Manual printer entry -->
            <div>
                <label class="block text-sm font-medium text-gray-700 mb-2">
                    {% trans "Add printers manually" %}
                </label>
                <div id="manual-printers" class="space-y-3">
                    <div class="grid grid-cols-12 gap-2 items-end manual-printer-row">
                        <div class="col-span-4">
                            <label class="block text-xs text-gray-500">{% trans "IP Address" %}</label>
                            <input type="text" name="manual_printer_host" placeholder="192.168.1.220"
                                   class="block w-full rounded-md border-gray-300 shadow-sm text-sm focus:border-blue-500 focus:ring-blue-500">
                        </div>
                        <div class="col-span-3">
                            <label class="block text-xs text-gray-500">{% trans "Role" %}</label>
                            <select name="manual_printer_role"
                                    class="block w-full rounded-md border-gray-300 shadow-sm text-sm focus:border-blue-500 focus:ring-blue-500">
                                <option value="carcass">{% trans "Carcass" %}</option>
                                <option value="meat_cut">{% trans "Meat Cut" %}</option>
                                <option value="offal">{% trans "Offal" %}</option>
                                <option value="by_product">{% trans "By-Product" %}</option>
                                <option value="animal">{% trans "Animal" %}</option>
                                <option value="generic" selected>{% trans "Generic" %}</option>
                            </select>
                        </div>
                        <div class="col-span-4">
                            <label class="block text-xs text-gray-500">{% trans "Display Name" %}</label>
                            <input type="text" name="manual_printer_name" placeholder="{% trans 'Carcass Line' %}"
                                   class="block w-full rounded-md border-gray-300 shadow-sm text-sm focus:border-blue-500 focus:ring-blue-500">
                        </div>
                        <div class="col-span-1">
                            <button type="button" onclick="this.closest('.manual-printer-row').remove()"
                                    class="text-red-400 hover:text-red-600 text-sm p-1">✕</button>
                        </div>
                    </div>
                </div>
                <button type="button" id="add-printer-btn"
                        class="mt-2 text-sm text-blue-600 hover:text-blue-800 font-medium">
                    + {% trans "Add another printer" %}
                </button>
            </div>
        </div>

        <div class="flex justify-end gap-3 border-t pt-4">
            <a href="{% url 'scales:edge_management' %}"
               class="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50">
                {% trans "Cancel" %}
            </a>
            <button type="submit"
                    class="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700">
                {% trans "Generate Setup Code" %}
            </button>
        </div>
    </form>
</div>

<script>
document.addEventListener("DOMContentLoaded", function() {
    const printerRowTemplate = document.querySelector(".manual-printer-row").outerHTML;
    document.getElementById("add-printer-btn").addEventListener("click", function() {
        const container = document.getElementById("manual-printers");
        container.insertAdjacentHTML("beforeend", printerRowTemplate);
        const newRow = container.lastElementChild;
        newRow.querySelectorAll("input").forEach(function(el) { el.value = ""; });
    });

    // Show existing printers when a site is selected
    const siteSelect = document.getElementById("site_id");
    const existingSection = document.getElementById("existing-printers-section");
    const existingList = document.getElementById("existing-printers-list");
    const printers = {{ printers_json|safe }};

    siteSelect.addEventListener("change", function() {
        const siteId = this.value;
        existingList.innerHTML = "";
        if (!siteId) { existingSection.classList.add("hidden"); return; }
        const sitePrinters = printers.filter(function(p) { return p.site_id === siteId; });
        if (!sitePrinters.length) { existingSection.classList.add("hidden"); return; }
        existingSection.classList.remove("hidden");
        sitePrinters.forEach(function(p) {
            existingList.insertAdjacentHTML("beforeend",
                '<label class="flex items-center gap-2 p-2 border rounded-md hover:bg-gray-50">' +
                '<input type="checkbox" name="printer_ids" value="' + p.id + '" class="rounded border-gray-300">' +
                '<span class="text-sm">' + p.display_name + ' (' + p.role + ') — ' + p.host + ':' + p.port + '</span>' +
                '</label>'
            );
        });
    });
});
</script>
{% endblock %}
```

> **Note:** The view should pass `printers_json` to the template context as a serialized JSON list. For the initial implementation, the manual-entry path is sufficient since the first Edge at a site won't have existing Cloud-registered printers yet.

**File:** `scales/templates/scales/edge_setup_code_detail.html`

```html
{% extends "base.html" %}
{% load i18n %}

{% block title %}{% trans "Edge Setup Code" %}{% endblock %}

{% block content %}
<div class="max-w-3xl mx-auto">
    <div class="bg-white shadow rounded-lg overflow-hidden">
        <!-- Header -->
        <div class="bg-green-50 border-b border-green-200 px-6 py-4">
            <div class="flex items-center gap-3">
                <svg class="h-8 w-8 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                          d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                <div>
                    <h1 class="text-xl font-bold text-green-900">{% trans "Edge Device Created" %}</h1>
                    <p class="text-green-700">
                        {{ setup_code.edge_name|default:setup_code.site.name }} &mdash; {{ setup_code.site.name }}
                    </p>
                </div>
            </div>
        </div>

        <!-- Setup Code Display -->
        <div class="px-6 py-8 text-center border-b">
            <p class="text-sm font-medium text-gray-500 uppercase tracking-wider mb-2">
                {% trans "Setup Code" %}
            </p>
            <div class="inline-block bg-gray-100 rounded-xl px-8 py-4 border-2 border-dashed border-gray-300">
                <span class="text-4xl font-mono font-bold tracking-widest text-gray-900"
                      id="setup-code">{{ setup_code.code }}</span>
            </div>
            <div class="mt-3">
                <button onclick="navigator.clipboard.writeText('{{ setup_code.code }}')"
                        class="text-sm text-blue-600 hover:text-blue-800 font-medium">
                    {% trans "Copy to clipboard" %}
                </button>
            </div>
            {% if setup_code.used_at %}
            <div class="mt-4 inline-flex items-center gap-2 bg-yellow-50 text-yellow-800 px-4 py-2 rounded-full text-sm">
                {% trans "Already used" %} — {{ setup_code.used_at|date:"d M Y H:i" }}
            </div>
            {% else %}
            <p class="mt-4 text-sm text-gray-500">
                {% trans "Expires:" %} {{ setup_code.expires_at|date:"d M Y H:i" }}
            </p>
            {% endif %}
        </div>

        <!-- Printer Configuration Summary -->
        {% if setup_code.printers_config %}
        <div class="px-6 py-4 border-b bg-blue-50">
            <h3 class="text-sm font-semibold text-blue-900 mb-2">
                {% trans "Pre-configured Printers" %} ({{ setup_code.printers_config|length }})
            </h3>
            <div class="space-y-1">
                {% for printer in setup_code.printers_config %}
                <div class="flex items-center gap-2 text-sm text-blue-800">
                    <span class="inline-block w-2 h-2 bg-blue-400 rounded-full"></span>
                    <span class="font-medium">{{ printer.displayName|default:printer.localPrinterId }}</span>
                    <span class="text-blue-600">({{ printer.role }})</span>
                    <span class="text-blue-500">{{ printer.host }}:{{ printer.port }}</span>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        <!-- Connection Info -->
        <div class="px-6 py-4 border-b bg-gray-50">
            <h3 class="text-sm font-semibold text-gray-700 mb-1">{% trans "Cloud API URL" %}</h3>
            <div class="flex items-center gap-2">
                <code class="bg-white px-3 py-1.5 rounded border text-sm font-mono text-gray-900">{{ tenant_url }}</code>
                <button onclick="navigator.clipboard.writeText('{{ tenant_url }}')"
                        class="text-sm text-blue-600 hover:text-blue-800">{% trans "Copy" %}</button>
            </div>
            <p class="mt-1 text-xs text-gray-500">
                {% trans "The Edge device will use this URL for all API calls. It is pre-configured during activation." %}
            </p>
        </div>

        <!-- Instructions -->
        <div class="px-6 py-6">
            <h2 class="text-lg font-semibold text-gray-900 mb-4">
                {% trans "Setup Instructions" %}
            </h2>
            <p class="text-gray-600 mb-4">
                {% trans "Send these instructions to the site operator:" %}
            </p>
            <ol class="space-y-4 text-gray-700">
                <li class="flex gap-3">
                    <span class="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-700 rounded-full flex items-center justify-center font-bold text-sm">1</span>
                    <div>
                        <p class="font-medium">{% trans "Download CarniTrack Edge" %}</p>
                        <div class="mt-2 flex gap-2">
                            <a href="#" class="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700">
                                {% trans "Windows (.exe)" %}
                            </a>
                            <a href="#" class="inline-flex items-center gap-2 px-4 py-2 bg-gray-600 text-white rounded-md text-sm font-medium hover:bg-gray-700">
                                {% trans "Linux" %}
                            </a>
                        </div>
                    </div>
                </li>
                <li class="flex gap-3">
                    <span class="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-700 rounded-full flex items-center justify-center font-bold text-sm">2</span>
                    <div>
                        <p class="font-medium">{% trans "Extract and run the application" %}</p>
                        <p class="text-sm text-gray-500">{% trans "On Windows: double-click carnitrack-edge.exe" %}</p>
                    </div>
                </li>
                <li class="flex gap-3">
                    <span class="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-700 rounded-full flex items-center justify-center font-bold text-sm">3</span>
                    <div>
                        <p class="font-medium">{% trans "Open browser" %}</p>
                        <p class="text-sm text-gray-500">
                            {% trans "Go to" %} <code class="bg-gray-100 px-2 py-0.5 rounded">http://localhost:3000</code>
                        </p>
                    </div>
                </li>
                <li class="flex gap-3">
                    <span class="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-700 rounded-full flex items-center justify-center font-bold text-sm">4</span>
                    <div>
                        <p class="font-medium">{% trans "Enter the setup code" %}</p>
                        <p class="text-sm text-gray-500">
                            {% trans "Type or paste:" %}
                            <code class="bg-gray-100 px-2 py-0.5 rounded font-bold">{{ setup_code.code }}</code>
                        </p>
                    </div>
                </li>
                <li class="flex gap-3">
                    <span class="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-700 rounded-full flex items-center justify-center font-bold text-sm">5</span>
                    <div>
                        <p class="font-medium">{% trans "Verify printers are connected" %}</p>
                        <p class="text-sm text-gray-500">
                            {% trans "After activation, the Edge will auto-configure printers and test connectivity. Check the Edge dashboard for printer status." %}
                        </p>
                    </div>
                </li>
                <li class="flex gap-3">
                    <span class="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-700 rounded-full flex items-center justify-center font-bold text-sm">6</span>
                    <div>
                        <p class="font-medium">{% trans "Install as a service (optional)" %}</p>
                        <p class="text-sm text-gray-500">
                            {% trans "Run install-service.bat as Administrator so it starts automatically on reboot." %}
                        </p>
                    </div>
                </li>
            </ol>
        </div>

        <!-- Back button -->
        <div class="px-6 py-4 bg-gray-50 border-t flex justify-between">
            <a href="{% url 'scales:edge_management' %}"
               class="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50">
                {% trans "Back to Edge Management" %}
            </a>
            {% if not setup_code.used_at %}
            <form method="post" action="{% url 'scales:edge_setup_code_revoke' pk=setup_code.pk %}"
                  onsubmit="return confirm('{% trans "Are you sure you want to revoke this setup code?" %}');">
                {% csrf_token %}
                <button type="submit"
                        class="px-4 py-2 text-sm font-medium text-red-700 bg-white border border-red-300 rounded-md hover:bg-red-50">
                    {% trans "Revoke Code" %}
                </button>
            </form>
            {% endif %}
        </div>
    </div>
</div>
{% endblock %}
```

**File:** `scales/templates/scales/edge_setup_code_list.html`

```html
{% extends "base.html" %}
{% load i18n %}

{% block title %}{% trans "Setup Codes" %}{% endblock %}

{% block content %}
<div class="container mx-auto px-4 py-6">
    <div class="flex justify-between items-center mb-6">
        <div>
            <h1 class="text-2xl font-bold text-gray-900">{% trans "Edge Setup Codes" %}</h1>
            <p class="text-sm text-gray-600 mt-1">{% trans "Manage provisioning codes for Edge devices." %}</p>
        </div>
        <a href="{% url 'scales:edge_setup_code_create' %}"
           class="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700">
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
            </svg>
            {% trans "New Setup Code" %}
        </a>
    </div>

    <div class="bg-white shadow rounded-lg overflow-hidden">
        <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{% trans "Code" %}</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{% trans "Site" %}</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{% trans "Edge Name" %}</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{% trans "Printers" %}</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{% trans "Status" %}</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{% trans "Created" %}</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{% trans "Expires" %}</th>
                </tr>
            </thead>
            <tbody class="bg-white divide-y divide-gray-200">
                {% for code in setup_codes %}
                <tr>
                    <td class="px-4 py-3">
                        <a href="{% url 'scales:edge_setup_code_detail' pk=code.pk %}"
                           class="font-mono font-bold text-blue-600 hover:text-blue-800">{{ code.code }}</a>
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-700">{{ code.site.name }}</td>
                    <td class="px-4 py-3 text-sm text-gray-700">{{ code.edge_name|default:"—" }}</td>
                    <td class="px-4 py-3 text-sm text-gray-700">{{ code.printers_config|length }}</td>
                    <td class="px-4 py-3 text-sm">
                        {% if code.used_at %}
                        <span class="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-green-100 text-green-800">{% trans "Used" %}</span>
                        {% elif code.is_valid %}
                        <span class="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-blue-100 text-blue-800">{% trans "Active" %}</span>
                        {% else %}
                        <span class="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-gray-100 text-gray-600">{% trans "Expired" %}</span>
                        {% endif %}
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-600">{{ code.created_at|date:"d M Y H:i" }}</td>
                    <td class="px-4 py-3 text-sm text-gray-600">{{ code.expires_at|date:"d M Y H:i" }}</td>
                </tr>
                {% empty %}
                <tr>
                    <td colspan="7" class="px-4 py-6 text-center text-sm text-gray-500">{% trans "No setup codes yet." %}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
{% endblock %}
```

### 3d. Add buttons to existing Edge Management page

**File:** `scales/templates/scales/edge_management.html`

Find the page header / title area and add these buttons nearby:

```html
<div class="flex gap-2">
    <a href="{% url 'scales:edge_setup_code_list' %}"
       class="inline-flex items-center gap-2 px-3 py-2 bg-gray-100 text-gray-700 rounded-md text-sm font-medium hover:bg-gray-200">
        {% trans "Setup Codes" %}
    </a>
    <a href="{% url 'scales:edge_setup_code_create' %}"
       class="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700">
        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
        </svg>
        {% trans "Add Edge Device" %}
    </a>
</div>
```

---

## Step 4: Admin Registration for EdgeSetupCode

**File:** `scales/admin.py`

```python
from .models import EdgeSetupCode

@admin.register(EdgeSetupCode)
class EdgeSetupCodeAdmin(admin.ModelAdmin):
    list_display = ["code", "site", "edge_name", "expires_at", "used_at", "printers_count", "created_at"]
    list_filter = ["site", "used_at"]
    search_fields = ["code", "edge_name"]
    readonly_fields = ["code", "used_at", "used_by_edge"]

    @admin.display(description="Printers")
    def printers_count(self, obj):
        return len(obj.printers_config or [])
```

---

## Step 5: Tests

**File:** `scales/tests_activate.py`

```python
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from .models import EdgeSetupCode, EdgeDevice, Site


class EdgeActivateTests(TestCase):
    """Tests for POST /api/v1/edge/activate"""

    def setUp(self):
        self.site = Site.objects.create(name="Test Site", address="")
        self.valid_code = EdgeSetupCode.objects.create(
            site=self.site,
            edge_name="Test Edge",
            printers_config=[
                {
                    "localPrinterId": "carcass-01",
                    "host": "192.168.1.220",
                    "port": 9100,
                    "role": "carcass",
                    "displayName": "Carcass Line",
                },
            ],
            expires_at=timezone.now() + timedelta(hours=48),
        )
        self.expired_code = EdgeSetupCode.objects.create(
            site=self.site,
            edge_name="Expired Edge",
            expires_at=timezone.now() - timedelta(hours=1),
        )

    def test_activate_success(self):
        resp = self.client.post(
            "/api/v1/edge/activate",
            data={"code": self.valid_code.code, "version": "0.1.0"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("edgeId", data)
        self.assertIn("siteId", data)
        self.assertEqual(data["siteName"], "Test Site")
        self.assertIn("printers", data)
        self.assertEqual(len(data["printers"]), 1)
        self.assertEqual(data["printers"][0]["host"], "192.168.1.220")
        self.assertEqual(data["printers"][0]["role"], "carcass")
        self.assertIn("config", data)
        self.assertIn("baseUrl", data["config"])

        # Code should be marked as used
        self.valid_code.refresh_from_db()
        self.assertIsNotNone(self.valid_code.used_at)
        self.assertIsNotNone(self.valid_code.used_by_edge)

    def test_activate_already_used(self):
        self.client.post(
            "/api/v1/edge/activate",
            data={"code": self.valid_code.code, "version": "0.1.0"},
            content_type="application/json",
        )
        resp = self.client.post(
            "/api/v1/edge/activate",
            data={"code": self.valid_code.code, "version": "0.1.0"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 409)

    def test_activate_expired(self):
        resp = self.client.post(
            "/api/v1/edge/activate",
            data={"code": self.expired_code.code, "version": "0.1.0"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 410)

    def test_activate_unknown_code(self):
        resp = self.client.post(
            "/api/v1/edge/activate",
            data={"code": "CT-XXXX-XXXX", "version": "0.1.0"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_activate_case_insensitive(self):
        resp = self.client.post(
            "/api/v1/edge/activate",
            data={"code": self.valid_code.code.lower(), "version": "0.1.0"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_activate_creates_edge_device(self):
        self.assertEqual(EdgeDevice.objects.count(), 0)
        self.client.post(
            "/api/v1/edge/activate",
            data={"code": self.valid_code.code, "version": "0.1.0"},
            content_type="application/json",
        )
        self.assertEqual(EdgeDevice.objects.count(), 1)
        edge = EdgeDevice.objects.first()
        self.assertEqual(edge.site, self.site)
        self.assertEqual(edge.name, "Test Edge")
        self.assertTrue(edge.is_online)

    def test_activate_empty_code(self):
        resp = self.client.post(
            "/api/v1/edge/activate",
            data={"code": "", "version": "0.1.0"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_activate_revoked_code_returns_404(self):
        """A soft-deleted code should return 404 (is_active=False)."""
        self.valid_code.soft_delete()
        resp = self.client.post(
            "/api/v1/edge/activate",
            data={"code": self.valid_code.code, "version": "0.1.0"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_activate_no_printers_returns_empty_list(self):
        code = EdgeSetupCode.objects.create(
            site=self.site,
            edge_name="No Printers Edge",
            expires_at=timezone.now() + timedelta(hours=48),
        )
        resp = self.client.post(
            "/api/v1/edge/activate",
            data={"code": code.code, "version": "0.1.0"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["printers"], [])

    def test_method_not_allowed(self):
        resp = self.client.get("/api/v1/edge/activate")
        self.assertEqual(resp.status_code, 405)
```

> **Note for multitenancy:** If using `django-tenants`, these tests should extend `TenantTestCase` (from `django_tenants.test.cases`) instead of `django.test.TestCase` to ensure they run within a tenant schema. The existing `scales/tests_api.py` file shows the pattern to follow.

---

## API Contract (Edge ↔ Cloud)

### `POST /api/v1/edge/activate`

**Request:**
```json
{
    "code": "CT-8K4M-XNPR",
    "version": "0.1.0",
    "capabilities": ["weighing", "printing"]
}
```

**Success (200):**
```json
{
    "edgeId": "550e8400-e29b-41d4-a716-446655440000",
    "siteId": "660e8400-e29b-41d4-a716-446655440000",
    "siteName": "Ankara Kesimhane",
    "config": {
        "sessionPollIntervalMs": 5000,
        "heartbeatIntervalMs": 30000,
        "workHoursStart": "06:00",
        "workHoursEnd": "18:00",
        "timezone": "Europe/Istanbul",
        "baseUrl": "https://tenant.carnitrack.com"
    },
    "printers": [
        {
            "localPrinterId": "carcass-01",
            "displayName": "Carcass Line",
            "role": "carcass",
            "transport": "tcp",
            "host": "192.168.1.220",
            "port": 9100,
            "model": "TE210",
            "priority": 100
        },
        {
            "localPrinterId": "product-01",
            "displayName": "Product Line",
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

**Error — Code not found (404):**
```json
{ "error": "Setup code not found. Check the code and try again." }
```

**Error — Already used (409):**
```json
{ "error": "This setup code has already been used by another Edge device." }
```

**Error — Expired (410):**
```json
{ "error": "This setup code has expired. Please generate a new one from Cloud." }
```

**Error — Rate limited (429):**
```json
{ "error": "rate limit exceeded" }
```

---

## Edge Post-Activation Flow (What Happens After Activate)

After the Edge receives the `/activate` response, it should perform these steps automatically:

```
1. Store edgeId, siteId, config.baseUrl in local config / SQLite
2. Set X-Edge-Id header for all subsequent API calls
3. For each printer in printers[]:
   a. Create local printer entry in Edge's SQLite
   b. Test TCP connectivity to host:port
   c. Query printer firmware version via TSPL ~!T command
4. Push POST /api/v1/edge/printers/inventory with the full printer list
   (receives globalPrinterId UUIDs back — store these locally)
5. Start normal heartbeat loop (POST /heartbeat with printers[] status)
6. Start polling GET /print-jobs/pending
```

This means a freshly activated Edge is **print-ready within seconds** — the admin pre-configures the printers in the setup code, and the Edge auto-discovers them on activation.

---

## Multitenancy & Public Activation (Option A — Code-Based Tenant Resolution)

### Problem

Edge devices are standalone `.exe` binaries. They don't know which tenant subdomain to call.
The old flow required the Edge to call `https://tenant-x.carnitrack.com/api/v1/edge/activate`,
which meant the admin had to manually configure the API URL on each Edge.

### Solution: Single Public Activation Endpoint

The Edge calls **one public domain** for activation:

```
POST https://api.carnitrack.com/api/v1/activate
{
    "code": "CT-8K4M-XNPR",
    "version": "0.3.0",
    "capabilities": ["weighing", "printing"]
}
```

The server resolves the tenant from the setup code automatically.

### Architecture

```
                          Public Schema                    Tenant Schema
                          ─────────────                    ─────────────
EdgeSetupCode created  ──post_save signal──► EdgeSetupCodeIndex
in tenant dashboard       (sync code,         (code → tenant mapping,
                           tenant_schema,       public schema table)
                           expires_at)

Edge calls POST /api/v1/activate
    │
    ▼
public_edge_activate()    ──► Look up code in EdgeSetupCodeIndex
    │                          (public schema)
    │                     ──► Resolve tenant from index entry
    │                     ──► switch to tenant schema via schema_context()
    │                     ──► Validate & consume EdgeSetupCode (tenant schema)
    │                     ──► Create EdgeDevice (tenant schema)
    │                     ──► Return response with config.baseUrl = tenant URL
    ▼
Edge stores config.baseUrl and uses it for all subsequent API calls
(heartbeat, sessions, events, print-jobs all go to tenant subdomain)
```

### New Model — `EdgeSetupCodeIndex` (Public Schema)

**File:** `tenants/models.py`

```python
class EdgeSetupCodeIndex(models.Model):
    code = models.CharField(max_length=16, unique=True, db_index=True)
    tenant = models.ForeignKey(Client, on_delete=models.CASCADE)
    tenant_schema = models.CharField(max_length=63)
    setup_code_id = models.UUIDField()
    expires_at = models.DateTimeField()
    is_consumed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenants_edge_setup_code_index"
```

### Signal Sync — `scales/signals.py`

A `post_save` signal on `EdgeSetupCode` automatically upserts the public-schema
`EdgeSetupCodeIndex` row. When a code is used or soft-deleted, `is_consumed` is set
to `True`.

### Public Activate View — `tenants/api_views_edge.py`

`public_edge_activate()` is registered at:
- `config/urls_public.py` → `path("api/v1/activate", ...)`
- `config/urls.py` → `path("api/v1/activate", ...)` (also reachable on tenant subdomains)

Flow:
1. Rate-limit by IP (10 req/60s)
2. Look up code in `EdgeSetupCodeIndex` (public schema)
3. Pre-flight checks: not consumed, not expired, tenant is active
4. Switch to tenant schema via `schema_context(tenant_schema)`
5. `select_for_update()` on `EdgeSetupCode` → validate → create `EdgeDevice` → mark used
6. Return JSON response with `config.baseUrl` pointing to the tenant subdomain

### Response Contract

```json
{
    "edgeId": "uuid",
    "siteId": "uuid",
    "siteName": "Ankara Main Plant",
    "config": {
        "baseUrl": "https://farm1.carnitrack.com",
        "sessionPollIntervalMs": 5000,
        "heartbeatIntervalMs": 30000,
        "workHoursStart": "06:00",
        "workHoursEnd": "18:00",
        "timezone": "Europe/Istanbul"
    },
    "printers": [
        {
            "localPrinterId": "carcass-01",
            "displayName": "Carcass Line",
            "role": "carcass",
            "transport": "tcp",
            "host": "192.168.1.220",
            "port": 9100,
            "model": "",
            "priority": 100
        }
    ]
}
```

### Error Responses

| Status | Condition |
|--------|-----------|
| 400 | Missing or empty `code` |
| 403 | Tenant is not active |
| 404 | Code not found in index or tenant schema |
| 405 | Non-POST method |
| 409 | Code already used |
| 410 | Code expired |
| 429 | Rate limited |

### Backward Compatibility

The existing tenant-scoped `POST /api/v1/edge/activate` endpoint in `scales/api_views.py`
remains functional for Docker/env-var deployments where the Edge already knows its tenant URL.

### CORS

Already handled. `django-cors-headers` in `config/settings.py` uses regex patterns for
`*.carnitrack.com` and `localhost:*` (DEBUG mode). The Edge's setup wizard at
`http://localhost:3000` can call both the public domain and tenant subdomains.

---

## File Change Summary

| File | Action | What |
|------|--------|------|
| `scales/models.py` | Edit | Add `generate_setup_code()` + `EdgeSetupCode` model |
| `scales/api_urls.py` | Edit | Add `path("activate", ...)` (tenant-scoped) |
| `scales/api_views.py` | Edit | Add `edge_activate()` view (tenant-scoped, backward compat) |
| `scales/urls.py` | Edit | Add 4 routes: list, create, detail, revoke |
| `scales/views.py` | Edit | Add setup code views, public activate URL in detail context |
| `scales/signals.py` | Create | `post_save` sync of `EdgeSetupCode` → `EdgeSetupCodeIndex` |
| `scales/apps.py` | Edit | Wire up signals in `ScalesConfig.ready()` |
| `scales/templates/scales/edge_setup_code_create.html` | Create | Form template with printer config |
| `scales/templates/scales/edge_setup_code_detail.html` | Create | Result/instructions with public activate URL + tenant URL |
| `scales/templates/scales/edge_setup_code_list.html` | Create | List view for all setup codes |
| `scales/templates/scales/edge_management.html` | Edit | Add "Add Edge Device" + "Setup Codes" buttons |
| `scales/admin.py` | Edit | Register `EdgeSetupCode` in admin |
| `scales/tests_activate.py` | Create | Tests for tenant-scoped `/activate` + dashboard views |
| `tenants/models.py` | Edit | Add `EdgeSetupCodeIndex` model (public schema) |
| `tenants/api_views_edge.py` | Create | `public_edge_activate()` — public-schema activation view |
| `tenants/tests_public_activate.py` | Create | 25 tests for public activation, signal sync, model |
| `config/urls_public.py` | Edit | Add `path("api/v1/activate", ...)` |
| `config/urls.py` | Edit | Add `path("api/v1/activate", ...)` (also reachable on tenant) |
| `tenants/migrations/0015_edge_setup_code_index.py` | Auto | Migration for `EdgeSetupCodeIndex` |
| `scales/migrations/0011_add_edge_setup_code.py` | Auto | Migration for `EdgeSetupCode` |

---

## How It Connects to the Printer System

The setup code flow is **the entry point** for the printer pipeline that already exists:

```
Setup Code created (with printers_config)
    │
    ▼
Edge calls POST /activate → gets printers[]
    │
    ▼
Edge auto-configures local printers
    │
    ▼
Edge calls POST /printers/inventory ← ALREADY IMPLEMENTED in api_views.py
    │                                   (creates/updates scales.Printer rows)
    ▼
Edge starts heartbeat loop ← ALREADY IMPLEMENTED
    │  (includes printers[] status)
    ▼
Cloud dispatches print jobs to site ← ALREADY IMPLEMENTED
    │  (labeling.PrintJob with target_role)
    ▼
Edge polls GET /print-jobs/pending ← ALREADY IMPLEMENTED
    │
    ▼
Edge dispatches to printer via TCP:9100
    │
    ▼
Edge calls POST /print-jobs/<uuid>/ack ← ALREADY IMPLEMENTED
```

**What this spec adds is the missing first step** — the provisioning flow that creates the
Edge device AND pre-configures its printers in one atomic operation. Without this, the admin
would have to:
1. Register the Edge via the old `.env` + Docker flow
2. Manually configure printers on the Edge
3. Wait for the Edge to push printer inventory

With setup codes, steps 1-3 happen automatically when the operator enters the code.

---

## Existing Infrastructure (Already Implemented — No Changes Needed)

These components are already in the codebase and work correctly. This spec does NOT modify them:

| Component | File | Status |
|---|---|---|
| `Printer` model | `scales/models.py` | Implemented (migration `0010_printer.py`) |
| `PrintJob` model with edge dispatch fields | `labeling/models.py` | Implemented (migration `0007_printjob_edge_dispatch.py`) |
| `enqueue_print_job()` helper | `labeling/services.py` | Implemented |
| Web UI “Print via Edge” + PDF-only download | `labeling/views.py`, templates | Implemented (`PrintAnimalLabelToEdgeView`, `PrintCustomLabelToEdgeView`, batch enqueue) |
| `GET /print-jobs/pending` | `scales/api_views.py` | Implemented |
| `POST /print-jobs/<uuid>/ack` | `scales/api_views.py` | Implemented |
| `POST /printers/inventory` | `scales/api_views.py` | Implemented |
| `POST /heartbeat` with `printers[]` | `scales/api_views.py` | Implemented |
| `PrinterAdmin` + `PrinterInline` | `scales/admin.py` | Implemented |
| `PrintJobAdmin` with re-enqueue | `labeling/admin.py` | Verify |
| CORS configuration | `config/settings.py` | Implemented |
| `atomic_rate_incr` rate limiting | `tenants/redis_support.py` | Implemented |
| `require_edge_id` middleware | `scales/middleware.py` | Implemented |
| `parse_json_body` middleware | `scales/middleware.py` | Implemented |

---

## Checklist

### Tenant-Scoped (Edge Setup Code in Dashboard)
- [x] Add `EdgeSetupCode` model to `scales/models.py`
- [x] Run `makemigrations` + `migrate_schemas`
- [x] Add `edge_activate` view to `scales/api_views.py` (tenant-scoped, backward compat)
- [x] Add route in `scales/api_urls.py`
- [x] Add `EdgeSetupCodeListView` to `scales/views.py`
- [x] Add `EdgeSetupCodeCreateView` to `scales/views.py`
- [x] Add `EdgeSetupCodeDetailView` to `scales/views.py`
- [x] Add `EdgeSetupCodeRevokeView` to `scales/views.py`
- [x] Add 4 routes in `scales/urls.py`
- [x] Create `edge_setup_code_create.html` template (with printer config form)
- [x] Create `edge_setup_code_detail.html` template (with activate URL + printer summary)
- [x] Create `edge_setup_code_list.html` template
- [x] Add "Add Edge Device" + "Setup Codes" buttons to `edge_management.html`
- [x] Register model in `scales/admin.py`
- [x] Write tests in `scales/tests_activate.py` (38 tests)

### Public Activation (Code-Based Tenant Resolution)
- [x] Add `EdgeSetupCodeIndex` model to `tenants/models.py` (public schema)
- [x] Create migration `tenants/migrations/0015_edge_setup_code_index.py`
- [x] Add `post_save` signal in `scales/signals.py` to sync codes to public index
- [x] Wire signals in `scales/apps.py` → `ScalesConfig.ready()`
- [x] Create `public_edge_activate()` view in `tenants/api_views_edge.py`
- [x] Add route `api/v1/activate` in `config/urls_public.py`
- [x] Add route `api/v1/activate` in `config/urls.py` (reachable on tenant subdomains too)
- [x] Update detail template to show public activation URL + tenant post-activation URL
- [x] Write tests in `tenants/tests_public_activate.py` (25 tests)

### Web UI — Edge print dispatch (labels)
- [x] Stop generating `.bat` content in `labeling/utils.py` (`create_animal_label`, `create_cut_label`, `create_custom_label`); keep `prn_content` for Edge `PrintJob` payload
- [x] PDF-only downloads (`DownloadAnimalLabelView`, `DownloadCustomLabelView`)
- [x] `PrintAnimalLabelToEdgeView` / `PrintCustomLabelToEdgeView` + routes in `labeling/urls.py`
- [x] Label detail templates: print button, latest `PrintJob` status, Edge printer availability hint
- [x] `BatchGenerateLabelsView` enqueues edge print jobs when a new label is created and a dispatchable printer exists
- [x] Remove dev-only BAT/troubleshooting views from `labeling/views.py`
- [x] Tests in `labeling/tests_views.py`

### Remaining
- [ ] Test end-to-end: create code → activate via api.carnitrack.com → verify printer inventory push
- [ ] Backfill existing EdgeSetupCode rows to EdgeSetupCodeIndex (management command, if needed)
- [ ] Set up GCS download links (post-MVP: replace `#` hrefs with real URLs)
