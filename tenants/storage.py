"""GCS storage with per-schema object key prefix (avoids cross-tenant overwrites)."""

from django.conf import settings
from django.db import connection
from django_tenants.utils import get_public_schema_name
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
