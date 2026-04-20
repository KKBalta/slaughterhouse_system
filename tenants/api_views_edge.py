"""
Public-schema Edge activation endpoint.

POST /api/v1/activate

Resolves the tenant from the setup code, switches to the tenant schema,
and performs the activation. This allows Edge devices to call a single
public API domain (e.g. api.carnitrack.com) without knowing their tenant
subdomain ahead of time.
"""

from __future__ import annotations

import json
import logging

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django_tenants.utils import schema_context

from tenants.email_index import build_tenant_api_base_url

logger = logging.getLogger(__name__)


def _parse_json_body(request):
    """Parse JSON body, attach as request.json_body. Return error response or None."""
    if request.content_type and "json" in request.content_type:
        try:
            request.json_body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)
    else:
        request.json_body = {}
    return None


@csrf_exempt
def public_edge_activate(request):
    """
    Public-schema activation endpoint.

    1. Look up the code in EdgeSetupCodeIndex (public schema).
    2. Switch to the tenant schema.
    3. Validate and consume the EdgeSetupCode.
    4. Create the EdgeDevice.
    5. Return the activation response including the tenant API base URL.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    err = _parse_json_body(request)
    if err:
        return err

    from tenants.redis_support import atomic_rate_incr

    ip = request.META.get("REMOTE_ADDR", "unknown")
    if atomic_rate_incr(f"edge_rl:pub_activate:ip:{ip}", 60) > 10:
        return JsonResponse({"error": "rate limit exceeded"}, status=429)

    body = request.json_body
    code_raw = (body.get("code") or "").strip().upper()
    version = (body.get("version") or "").strip()

    if not code_raw:
        return JsonResponse({"error": "code is required"}, status=400)

    from tenants.models import EdgeSetupCodeIndex

    try:
        index_entry = EdgeSetupCodeIndex.objects.select_related("tenant").get(
            code=code_raw,
        )
    except EdgeSetupCodeIndex.DoesNotExist:
        return JsonResponse(
            {"error": "Setup code not found. Check the code and try again."},
            status=404,
        )

    if index_entry.is_consumed:
        return JsonResponse(
            {"error": "This setup code has already been used by another Edge device."},
            status=409,
        )

    if index_entry.expires_at < timezone.now():
        return JsonResponse(
            {"error": "This setup code has expired. Please generate a new one from Cloud."},
            status=410,
        )

    tenant = index_entry.tenant
    if not tenant.is_active:
        return JsonResponse({"error": "Tenant is not active."}, status=403)

    tenant_schema = index_entry.tenant_schema

    with schema_context(tenant_schema):
        from scales.models import EdgeDevice, EdgeSetupCode

        with transaction.atomic():
            try:
                setup_code = (
                    EdgeSetupCode.objects.select_for_update().select_related("site").get(code=code_raw, is_active=True)
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

            site = setup_code.site
            edge_name = setup_code.edge_name or site.name

            edge = EdgeDevice.objects.create(
                site=site,
                name=edge_name,
                is_online=True,
                last_seen_at=timezone.now(),
                version=version or "",
            )

            setup_code.used_at = timezone.now()
            setup_code.used_by_edge = edge
            setup_code.save(update_fields=["used_at", "used_by_edge", "updated_at"])

        printers_config = setup_code.printers_config or []
        printers_out = []
        for p in printers_config:
            printers_out.append(
                {
                    "localPrinterId": p.get("localPrinterId", ""),
                    "displayName": p.get("displayName", ""),
                    "role": p.get("role", "generic"),
                    "transport": p.get("transport", "tcp"),
                    "host": p.get("host", ""),
                    "port": p.get("port", 9100),
                    "model": p.get("model", ""),
                    "priority": p.get("priority", 100),
                }
            )

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

    tenant_base_url = build_tenant_api_base_url(tenant)

    config = {
        "baseUrl": tenant_base_url,
        "sessionPollIntervalMs": 5000,
        "heartbeatIntervalMs": 30000,
        "workHoursStart": "06:00",
        "workHoursEnd": "18:00",
        "timezone": getattr(tenant, "timezone", "Europe/Istanbul") or "Europe/Istanbul",
    }

    return JsonResponse(
        {
            "edgeId": str(edge.id),
            "siteId": str(site.id),
            "siteName": site.name,
            "config": config,
            "printers": printers_out,
        }
    )
