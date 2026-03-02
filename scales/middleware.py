"""
Edge API authentication: validate X-Edge-Id (and optionally X-Site-Id) for Edge requests.
Registration endpoint does not require a pre-existing edge; others do after first registration.
"""

import json
import uuid
from functools import wraps

from django.core.exceptions import ValidationError
from django.http import JsonResponse

from .models import EdgeDevice


def require_edge_id(view_func):
    """
    Decorator for Edge API views that require an already-registered Edge.
    Expects X-Edge-Id header. Sets request.edge_device and request.edge_site.
    Returns 401 JSON if header missing or edge not found.
    """

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        edge_id = request.headers.get("X-Edge-Id") or request.META.get("HTTP_X_EDGE_ID")
        if not edge_id:
            return JsonResponse(
                {"error": "Missing X-Edge-Id header"},
                status=401,
            )
        try:
            edge_uuid = uuid.UUID(str(edge_id))
        except (ValueError, TypeError):
            return JsonResponse(
                {"error": "Invalid X-Edge-Id format; expected UUID from /edge/register"},
                status=401,
            )
        try:
            edge = EdgeDevice.objects.get(id=edge_uuid, is_active=True)
        except (EdgeDevice.DoesNotExist, ValueError, ValidationError):
            return JsonResponse(
                {"error": "Invalid or unknown Edge ID"},
                status=401,
            )
        request.edge_device = edge
        request.edge_site = edge.site
        return view_func(request, *args, **kwargs)

    return wrapped


def parse_json_body(view_func):
    """Attach parsed JSON body as request.json_body. Return 400 on invalid JSON."""

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.body:
            try:
                request.json_body = json.loads(request.body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return JsonResponse(
                    {"error": "Invalid JSON body"},
                    status=400,
                )
        else:
            request.json_body = {}
        return view_func(request, *args, **kwargs)

    return wrapped
