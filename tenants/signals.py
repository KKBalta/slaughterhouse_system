from django.dispatch import receiver
from django_tenants.models import TenantMixin
from django_tenants.signals import post_schema_sync
from django_tenants.utils import get_public_schema_name, schema_context


@receiver(post_schema_sync, sender=TenantMixin)
def ensure_default_scales_site(sender, tenant, **kwargs):
    """
    One scales.Site per tenant schema (Edge / PLU / sessions reference Site).
    Runs after tenant schema is created and migrated.
    """
    if tenant.schema_name == get_public_schema_name():
        return

    def _name() -> str:
        n = (getattr(tenant, "name", None) or "").strip()
        return n or tenant.schema_name

    with schema_context(tenant.schema_name):
        from scales.models import Site

        if not Site.objects.exists():
            Site.objects.create(name=_name(), address="")
