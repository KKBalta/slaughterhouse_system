"""
Public-schema email -> tenant index for login discovery (EmailTenantMembership).

Only tenant users (users.User) are indexed; platform admins are never included.
"""

from __future__ import annotations

from django.conf import settings
from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context, tenant_context

from tenants.models import Client, EmailTenantMembership


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _tenant_primary_host(tenant: Client) -> str:
    primary = tenant.get_primary_domain()
    return primary.domain if primary else f"{tenant.slug or tenant.schema_name}.localhost"


def build_tenant_api_base_url(tenant: Client) -> str:
    """
    Base URL for tenant API host (scheme + host + optional port for local dev).
    """
    host = _tenant_primary_host(tenant)
    if "localhost" in host or host.startswith("127.0.0.1"):
        port = getattr(settings, "PUBLIC_TENANT_HTTP_PORT", "8000")
        return f"http://{host}:{port}"
    return f"https://{host}"


def build_tenant_web_app_base_url(tenant: Client) -> str:
    """
    Base URL for the tenant-facing web app (SPA) used after login redirects.
    Local dev typically uses a different port than the API (e.g. 3000 vs 8000).
    """
    host = _tenant_primary_host(tenant)
    if "localhost" in host or host.startswith("127.0.0.1"):
        port = getattr(settings, "PUBLIC_TENANT_WEB_HTTP_PORT", "3000")
        return f"http://{host}:{port}"
    return f"https://{host}"


def build_post_login_redirect_url(tenant: Client, *, use_api_host: bool | None = None) -> str:
    """
    Full URL to open in the browser after a successful tenant session login.

    use_api_host:
      None — follow TENANT_POST_LOGIN_USE_API_HOST in settings.
      True — Django app on api_base_url (same origin as session cookie; use for template pages).
      False — SPA on web_app_base_url (port :3000 in dev).

    Django URLs use i18n prefix (e.g. /tr/dashboard/); SPA URLs use the raw path on the web origin.
    """
    if use_api_host is None:
        use_api_host = getattr(settings, "TENANT_POST_LOGIN_USE_API_HOST", False)
    if use_api_host:
        base = build_tenant_api_base_url(tenant)
    else:
        base = build_tenant_web_app_base_url(tenant)
    path = getattr(settings, "TENANT_LOGIN_SUCCESS_REDIRECT_PATH", "/dashboard")
    if not path.startswith("/"):
        path = "/" + path
    path = path.rstrip("/") or "/dashboard"
    base = base.rstrip("/")
    if use_api_host:
        lang = (getattr(tenant, "language_code", "") or getattr(settings, "LANGUAGE_CODE", "tr") or "tr").strip()
        # Trailing slash avoids APPEND_SLASH 301 before login_required runs (cleaner logs).
        if not path.endswith("/"):
            path = path + "/"
        return f"{base}/{lang}{path}"
    return f"{base}{path}"


def get_client_tenant_from_connection() -> Client | None:
    """Resolve current `Client` from `connection.tenant` (tenant HTTP requests only)."""
    return _get_client_tenant()


def _get_client_tenant() -> Client | None:
    tenant = getattr(connection, "tenant", None)
    if tenant is None:
        return None
    if tenant.schema_name == get_public_schema_name():
        return None
    if isinstance(tenant, Client):
        return tenant
    try:
        return Client.objects.get(schema_name=tenant.schema_name)
    except Client.DoesNotExist:
        return None


def sync_user_membership(user) -> None:
    """Upsert or delete index row for a tenant User (call from tenant schema context)."""
    if not settings.USE_MULTITENANT:
        return
    tenant = _get_client_tenant()
    if tenant is None:
        return

    email = normalize_email(getattr(user, "email", "") or "")
    uid = user.pk

    with schema_context(get_public_schema_name()):
        if not email:
            EmailTenantMembership.objects.filter(tenant_id=tenant.pk, tenant_user_id=uid).delete()
            return
        EmailTenantMembership.objects.update_or_create(
            tenant=tenant,
            tenant_user_id=uid,
            defaults={
                "email_normalized": email,
                "is_active": bool(getattr(user, "is_active", True)),
            },
        )


def remove_user_membership(user) -> None:
    """Remove index row when a tenant User is deleted."""
    if not settings.USE_MULTITENANT:
        return
    tenant = _get_client_tenant()
    if tenant is None:
        return
    uid = user.pk
    with schema_context(get_public_schema_name()):
        EmailTenantMembership.objects.filter(tenant_id=tenant.pk, tenant_user_id=uid).delete()


def backfill_all_tenants() -> tuple[int, int]:
    """
    Scan every active tenant schema and upsert memberships for users with email.
    Returns (tenants_processed, rows_upserted).
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    tenants_processed = 0
    rows = 0
    for client in Client.objects.filter(is_active=True).exclude(schema_name=get_public_schema_name()):
        tenants_processed += 1
        with tenant_context(client):
            for user in User.objects.iterator(chunk_size=500):
                email = normalize_email(getattr(user, "email", "") or "")
                if not email:
                    continue
                with schema_context(get_public_schema_name()):
                    EmailTenantMembership.objects.update_or_create(
                        tenant=client,
                        tenant_user_id=user.pk,
                        defaults={
                            "email_normalized": email,
                            "is_active": bool(getattr(user, "is_active", True)),
                        },
                    )
                    rows += 1
    return tenants_processed, rows
