"""
Public-schema email -> tenant index for login discovery (EmailTenantMembership).

Only tenant users (users.User) are indexed; platform admins are never included.
"""

from __future__ import annotations

from django import forms
from django.conf import settings
from django.db import connection
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import get_public_schema_name, schema_context, tenant_context

from tenants.models import Client, EmailTenantMembership


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def normalize_phone(phone: str | None) -> str:
    """Strip formatting and return a leading-+ normalized phone string."""
    raw = (phone or "").strip()
    if not raw:
        return ""
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return ""
    return f"+{digits}"


def validate_normalized_phone_length(normalized: str) -> None:
    """
    Require full national length for supported regions (+90 Turkey, +1 NANP).

    Empty string is allowed (optional phone). Raises django.forms.ValidationError
    when a non-empty value does not match an expected length.
    """
    if not (normalized or "").strip():
        return
    value = normalized.strip()
    if not value.startswith("+"):
        raise forms.ValidationError(_("Enter a valid phone number including country code."))
    digits = value[1:]
    if not digits.isdigit():
        raise forms.ValidationError(_("Enter a valid phone number."))
    if len(digits) > 15:
        raise forms.ValidationError(_("Phone number is too long."))
    if digits.startswith("90"):
        if len(digits) != 12:
            raise forms.ValidationError(
                _("Turkish numbers must include 10 digits after +90 (for example +905551112233).")
            )
        return
    if digits.startswith("1"):
        if len(digits) != 11:
            raise forms.ValidationError(
                _("US/Canada numbers must include 10 digits after +1 (for example +12025551234).")
            )
        return
    raise forms.ValidationError(_("Only +90 (Turkey) and +1 (USA/Canada) are supported for this field."))


def _host_is_local(host: str) -> bool:
    value = (host or "").strip().lower()
    return "localhost" in value or value.startswith("127.0.0.1")


def _tenant_domain_label(tenant: Client) -> str:
    return ((getattr(tenant, "slug", "") or getattr(tenant, "schema_name", "") or "tenant").strip() or "tenant").lower()


def get_tenant_public_host(tenant: Client) -> str:
    """
    Resolve the tenant host used by discovery and redirect URLs.

    In local DEBUG mode, imported staging/prod domains should not send the browser
    back to remote infrastructure. When TENANT_BASE_DOMAIN is localhost, prefer the
    local schema host even if the primary Domain row still points at a remote host.
    """
    primary = None
    if hasattr(tenant, "get_primary_domain"):
        primary = tenant.get_primary_domain()
    elif hasattr(tenant, "domains"):
        primary = tenant.domains.filter(is_primary=True).first() or tenant.domains.first()
    host = (getattr(primary, "domain", "") or "").strip()
    base_domain = (getattr(settings, "TENANT_BASE_DOMAIN", "localhost") or "localhost").strip().lstrip(".")
    fallback = f"{_tenant_domain_label(tenant)}.{base_domain}"

    if (
        getattr(settings, "PREFER_DEBUG_TENANT_BASE_DOMAIN", True)
        and getattr(settings, "DEBUG", False)
        and base_domain.endswith("localhost")
        and host
        and not _host_is_local(host)
    ):
        return fallback
    return host or fallback


def build_tenant_api_base_url(tenant: Client) -> str:
    """
    Base URL for tenant API host (scheme + host + optional port for local dev).
    """
    host = get_tenant_public_host(tenant)
    if _host_is_local(host):
        port = getattr(settings, "PUBLIC_TENANT_HTTP_PORT", "8000")
        return f"http://{host}:{port}"
    return f"https://{host}"


def build_tenant_web_app_base_url(tenant: Client) -> str:
    """
    Base URL for the tenant-facing web app (SPA) used after login redirects.
    Local dev typically uses a different port than the API (e.g. 3000 vs 8000).
    """
    host = get_tenant_public_host(tenant)
    if _host_is_local(host):
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
    phone = normalize_phone(getattr(user, "phone_number", "") or "")
    role = getattr(user, "role", "") or ""
    uid = user.pk

    with schema_context(get_public_schema_name()):
        existing = (
            EmailTenantMembership.objects.filter(tenant_id=tenant.pk, tenant_user_id=uid)
            .values_list("email_normalized", "phone_normalized")
            .first()
        )
        old_email, old_phone = existing or ("", "")
        from django.core.cache import cache

        if not email and not phone:
            EmailTenantMembership.objects.filter(tenant_id=tenant.pk, tenant_user_id=uid).delete()
            if old_email:
                cache.delete(f"tenant_discovery:{old_email}")
            if old_phone:
                cache.delete(f"tenant_discovery_phone:{old_phone}")
            return
        EmailTenantMembership.objects.update_or_create(
            tenant=tenant,
            tenant_user_id=uid,
            defaults={
                "email_normalized": email,
                "phone_normalized": phone,
                "role": role,
                "is_active": bool(getattr(user, "is_active", True)),
            },
        )
        # Bust discovery caches so changes are visible immediately.
        if old_email:
            cache.delete(f"tenant_discovery:{old_email}")
        if email:
            cache.delete(f"tenant_discovery:{email}")
        if old_phone:
            cache.delete(f"tenant_discovery_phone:{old_phone}")
        if phone:
            cache.delete(f"tenant_discovery_phone:{phone}")


def remove_user_membership(user) -> None:
    """Remove index row when a tenant User is deleted."""
    if not settings.USE_MULTITENANT:
        return
    tenant = _get_client_tenant()
    if tenant is None:
        return
    uid = user.pk
    with schema_context(get_public_schema_name()):
        existing = (
            EmailTenantMembership.objects.filter(tenant_id=tenant.pk, tenant_user_id=uid)
            .values_list("email_normalized", "phone_normalized")
            .first()
        )
        EmailTenantMembership.objects.filter(tenant_id=tenant.pk, tenant_user_id=uid).delete()
        if existing:
            from django.core.cache import cache

            old_email, old_phone = existing
            if old_email:
                cache.delete(f"tenant_discovery:{old_email}")
            if old_phone:
                cache.delete(f"tenant_discovery_phone:{old_phone}")


def backfill_all_tenants() -> tuple[int, int]:
    """
    Scan every active tenant schema and upsert memberships for users with email or phone.
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
                phone = normalize_phone(getattr(user, "phone_number", "") or "")
                if not email and not phone:
                    continue
                role = getattr(user, "role", "") or ""
                with schema_context(get_public_schema_name()):
                    EmailTenantMembership.objects.update_or_create(
                        tenant=client,
                        tenant_user_id=user.pk,
                        defaults={
                            "email_normalized": email,
                            "phone_normalized": phone,
                            "role": role,
                            "is_active": bool(getattr(user, "is_active", True)),
                        },
                    )
                    rows += 1
    return tenants_processed, rows
