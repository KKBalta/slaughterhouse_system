"""
Public-schema Edge API helpers.

Resolves tenant from X-Edge-Id via EdgeDeviceIndex, then executes wrapped views
inside that tenant's schema_context.
"""

from __future__ import annotations

import uuid
from functools import wraps

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django_tenants.utils import schema_context

from scales.middleware import parse_json_body
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


@csrf_exempt
@parse_json_body
def public_edge_register(request):
    """
    POST /api/v1/edge/register on the public host.

    scales.EdgeDevice exists only in tenant schemas; first-time registration without
    a tenant must use POST /api/v1/activate with a setup code. Re-registration
    includes edgeId in the JSON body — we resolve the tenant via EdgeDeviceIndex
    and run the standard edge_register view in that schema.
    """
    from scales import api_views

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    body = request.json_body
    edge_id_raw = body.get("edgeId")
    if not edge_id_raw:
        return JsonResponse(
            {
                "error": (
                    "edgeId is required on the public API. "
                    "For a new device, POST to /api/v1/activate with your setup code."
                ),
            },
            status=400,
        )

    try:
        edge_uuid = uuid.UUID(str(edge_id_raw))
    except (ValueError, TypeError):
        return JsonResponse(
            {"error": "Invalid edgeId format; expected UUID"},
            status=400,
        )

    try:
        index_entry = EdgeDeviceIndex.objects.get(edge_id=edge_uuid, is_active=True)
    except EdgeDeviceIndex.DoesNotExist:
        return JsonResponse({"error": "Unknown Edge ID"}, status=401)

    with schema_context(index_entry.tenant_schema):
        return api_views.edge_register(request)
