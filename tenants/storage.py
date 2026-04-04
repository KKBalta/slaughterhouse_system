"""GCS storage with per-schema object key prefix (avoids cross-tenant overwrites)."""

from django.conf import settings
from django.db import connection
from storages.backends.gcloud import GoogleCloudStorage


class TenantGCSStorage(GoogleCloudStorage):
    def _with_tenant_prefix(self, name: str) -> str:
        if not name or not getattr(settings, "USE_MULTITENANT", False):
            return name
        schema = getattr(connection, "schema_name", None) or ""
        if not schema:
            return name
        prefix = f"{schema}/"
        if name.startswith(prefix):
            return name
        return prefix + name

    def _normalize_name(self, name):
        name = self._with_tenant_prefix(name)
        return super()._normalize_name(name)


class PublicGCSStorage(GoogleCloudStorage):
    """GCS storage that always uses the public schema prefix.

    Use for models that live in the public schema (e.g. Client.logo)
    so the URL is the same regardless of which tenant schema is active.
    """

    def _normalize_name(self, name):
        if name and getattr(settings, "USE_MULTITENANT", False):
            prefix = "public/"
            if not name.startswith(prefix):
                name = prefix + name
        return super()._normalize_name(name)
