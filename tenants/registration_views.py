"""Public API: tenant self-service registration (public schema)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from tenants.forms import PublicTenantRegistrationForm
from tenants.models import TenantRegistrationRequest
from tenants.services import (
    create_registration_request,
    verify_status_token,
)

REG_RATE_PREFIX = "tenant_reg_ip:"
REG_RATE_LIMIT = 30  # per hour
REG_RATE_WINDOW = 3600


def _client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _rate_limited(request) -> bool:
    from tenants.redis_support import atomic_rate_incr

    ip = _client_ip(request)
    key = f"{REG_RATE_PREFIX}{ip}"
    count = atomic_rate_incr(key, REG_RATE_WINDOW)
    if count:
        # Redis path: count is the authoritative atomic increment.
        return count > REG_RATE_LIMIT
    # Fallback for LocMemCache / test env (single-process, non-atomic but acceptable).
    n = cache.get(key)
    if n is None:
        cache.set(key, 1, REG_RATE_WINDOW)
        return False
    if n >= REG_RATE_LIMIT:
        return True
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, REG_RATE_WINDOW)
    return False


def _json_body(request) -> dict:
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8")) if request.body else {}
        except json.JSONDecodeError:
            return {}
    return request.POST


@dataclass
class TenantRegistrationStatusLookupError(Exception):
    detail: str
    status_code: int


def _flatten_form_errors(form: PublicTenantRegistrationForm) -> dict[str, list[str]]:
    flat_errors: dict[str, list[str]] = {}
    for field, items in form.errors.get_json_data().items():
        flat_errors[field] = [item["message"] for item in items]
    return flat_errors


def get_tenant_registration_status_payload(registration_id, token: str) -> dict:
    if not token:
        raise TenantRegistrationStatusLookupError("Missing status token.", 401)

    try:
        reg = TenantRegistrationRequest.objects.get(pk=registration_id)
    except TenantRegistrationRequest.DoesNotExist as exc:
        raise TenantRegistrationStatusLookupError("Not found.", 404) from exc

    if not verify_status_token(reg.status_token_hash, token):
        raise TenantRegistrationStatusLookupError("Invalid token.", 403)

    out = {
        "id": str(reg.id),
        "status": reg.status,
        "derived_schema_preview": reg.derived_schema_name,
    }
    if reg.status == TenantRegistrationRequest.Status.REJECTED:
        out["rejection_reason"] = reg.rejection_reason
    if reg.status == TenantRegistrationRequest.Status.APPROVED and reg.approved_tenant_id:
        out["schema_name"] = reg.approved_tenant.schema_name
    return out


@csrf_exempt
@require_http_methods(["POST"])
def tenant_registration_create(request):
    if not getattr(settings, "USE_MULTITENANT", False):
        return JsonResponse({"detail": "Tenant registration is only available in multi-tenant mode."}, status=400)

    if _rate_limited(request):
        return JsonResponse({"detail": "Too many registration attempts. Try again later."}, status=429)

    payload = _json_body(request)
    form = PublicTenantRegistrationForm(payload)
    if not form.is_valid():
        errors = _flatten_form_errors(form)
        response_payload: dict[str, object] = {
            "detail": "Please correct the highlighted fields.",
            "errors": errors,
        }
        response_payload.update(errors)
        return JsonResponse(response_payload, status=400)

    reg, raw_token = create_registration_request(**form.registration_kwargs())

    return JsonResponse(
        {
            "id": str(reg.id),
            "status": reg.status,
            "derived_schema_preview": reg.derived_schema_name,
            "status_token": raw_token,
        },
        status=201,
    )


@csrf_exempt
@require_GET
def tenant_registration_status(request, registration_id):
    if not getattr(settings, "USE_MULTITENANT", False):
        return JsonResponse({"detail": "Tenant registration is only available in multi-tenant mode."}, status=400)

    auth = request.META.get("HTTP_AUTHORIZATION", "")
    token = None
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        # Same name as POST response field — frontends often use ?status_token=
        token = request.GET.get("status_token") or request.GET.get("token")

    try:
        payload = get_tenant_registration_status_payload(registration_id, token)
    except TenantRegistrationStatusLookupError as exc:
        return JsonResponse({"detail": exc.detail}, status=exc.status_code)
    return JsonResponse(payload)
