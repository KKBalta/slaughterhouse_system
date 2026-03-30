"""Public API: tenant self-service registration (public schema)."""

from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from tenants.email_index import normalize_email
from tenants.models import TenantRegistrationRequest
from tenants.services import (
    allocate_unique_schema_name,
    derive_base_schema_name,
    generate_status_token_pair,
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
    ip = _client_ip(request)
    key = f"{REG_RATE_PREFIX}{ip}"
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


@csrf_exempt
@require_http_methods(["POST"])
def tenant_registration_create(request):
    if not getattr(settings, "USE_MULTITENANT", False):
        return JsonResponse({"detail": "Tenant registration is only available in multi-tenant mode."}, status=400)

    if _rate_limited(request):
        return JsonResponse({"detail": "Too many registration attempts. Try again later."}, status=429)

    payload = _json_body(request)
    company_name = (payload.get("company_name") or "").strip()
    owner_email = normalize_email(payload.get("owner_email"))
    password = payload.get("owner_password") or ""
    password_confirm = payload.get("owner_password_confirm") or ""

    errors: dict[str, list[str]] = {}
    if not company_name:
        errors.setdefault("company_name", []).append("This field is required.")
    if not owner_email:
        errors.setdefault("owner_email", []).append("This field is required.")
    if not password:
        errors.setdefault("owner_password", []).append("This field is required.")
    if password != password_confirm:
        errors.setdefault("owner_password_confirm", []).append("Passwords do not match.")

    if errors:
        return JsonResponse({"errors": errors}, status=400)

    try:
        validate_password(password)
    except ValidationError as e:
        return JsonResponse({"errors": {"owner_password": list(e.messages)}}, status=400)

    base = derive_base_schema_name(company_name)
    try:
        schema_name = allocate_unique_schema_name(base)
    except ValidationError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    from django.contrib.auth.hashers import make_password

    raw_token, token_hash = generate_status_token_pair()

    reg = TenantRegistrationRequest.objects.create(
        company_name=company_name,
        company_full_name=(payload.get("company_full_name") or "").strip()[:255],
        company_address=(payload.get("company_address") or "").strip()[:500],
        license_no=(payload.get("license_no") or "").strip()[:64],
        operation_no=(payload.get("operation_no") or "").strip()[:64],
        contact_phone=(payload.get("contact_phone") or "").strip()[:64],
        derived_schema_name=schema_name,
        owner_email=owner_email,
        owner_password_hash=make_password(password),
        status_token_hash=token_hash,
    )

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

    if not token:
        return JsonResponse({"detail": "Missing status token."}, status=401)

    try:
        reg = TenantRegistrationRequest.objects.get(pk=registration_id)
    except TenantRegistrationRequest.DoesNotExist:
        return JsonResponse({"detail": "Not found."}, status=404)

    if not verify_status_token(reg.status_token_hash, token):
        return JsonResponse({"detail": "Invalid token."}, status=403)

    out = {
        "id": str(reg.id),
        "status": reg.status,
        "derived_schema_preview": reg.derived_schema_name,
    }
    if reg.status == TenantRegistrationRequest.Status.REJECTED:
        out["rejection_reason"] = reg.rejection_reason
    if reg.status == TenantRegistrationRequest.Status.APPROVED and reg.approved_tenant_id:
        out["schema_name"] = reg.approved_tenant.schema_name
    return JsonResponse(out)
