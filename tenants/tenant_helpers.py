"""Helpers for tenant-aware URLs and runtime checks (used from tenant and shared apps)."""

from __future__ import annotations

from django.conf import settings


def get_tenant_site_url() -> str:
    """
    Base URL for this tenant (QR codes, links). Uses primary Domain when present,
    otherwise schema_name + TENANT_BASE_DOMAIN.
    Non-multitenant / missing tenant falls back to SITE_URL_FALLBACK.
    """
    if not getattr(settings, "USE_MULTITENANT", False):
        return getattr(settings, "SITE_URL_FALLBACK", "http://localhost:8000")

    from django.db import connection
    from django_tenants.utils import get_public_schema_name

    tenant = getattr(connection, "tenant", None)
    if tenant is None:
        return getattr(settings, "SITE_URL_FALLBACK", "http://localhost:8000")
    if tenant.schema_name == get_public_schema_name():
        return getattr(settings, "SITE_URL_FALLBACK", "http://localhost:8000")

    scheme = "http" if settings.DEBUG else "https"
    domain_obj = None
    if hasattr(tenant, "domains"):
        domain_obj = tenant.domains.filter(is_primary=True).first() or tenant.domains.first()
    if domain_obj and domain_obj.domain:
        return f"{scheme}://{domain_obj.domain}"

    base = getattr(settings, "TENANT_BASE_DOMAIN", "carnitrack.samperlabs.com")
    return f"{scheme}://{tenant.schema_name}.{base}"
