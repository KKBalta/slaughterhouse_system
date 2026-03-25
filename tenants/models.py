from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Client(TenantMixin):
    """One row per tenant in the public schema; company fields drive labels and branding."""

    name = models.CharField(max_length=255, help_text="Business / display name")
    company_name = models.CharField(max_length=255, blank=True)
    company_full_name = models.CharField(max_length=255, blank=True)
    company_address = models.CharField(max_length=500, blank=True)
    license_no = models.CharField(max_length=64, blank=True)
    operation_no = models.CharField(max_length=64, blank=True)
    logo = models.ImageField(upload_to="tenant_logos/", blank=True, null=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)
    created_on = models.DateTimeField(auto_now_add=True)
    printer_turkish_mode = models.CharField(max_length=32, default="unicode")
    timezone = models.CharField(max_length=64, default="Europe/Istanbul")
    language_code = models.CharField(max_length=16, default="tr")

    auto_create_schema = True

    class Meta:
        db_table = "tenants_client"

    def __str__(self) -> str:
        return self.name or self.schema_name


class Domain(DomainMixin):
    class Meta:
        db_table = "tenants_domain"
