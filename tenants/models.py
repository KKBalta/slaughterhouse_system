import uuid

from django.contrib.auth.models import AbstractBaseUser
from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Client(TenantMixin):
    """One row per tenant in the public schema; company fields drive labels and branding."""

    name = models.CharField(max_length=255, help_text="Business / display name")
    slug = models.SlugField(
        max_length=63,
        unique=True,
        blank=True,
        help_text="Subdomain identifier; auto-populated from schema_name if left blank",
    )
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

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self.schema_name
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name or self.schema_name


class Domain(DomainMixin):
    class Meta:
        db_table = "tenants_domain"


class EmailTenantMembership(models.Model):
    """
    Public-schema index: maps normalized email (+ tenant user id) to a tenant for login discovery.
    Excludes platform-admin accounts (they live only in tenants_platform_admin).
    """

    email_normalized = models.CharField(max_length=254, db_index=True)
    tenant = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="email_memberships")
    tenant_user_id = models.PositiveIntegerField(
        help_text="Primary key of users.User in the tenant schema (for stable upserts).",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants_email_tenant_membership"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "tenant_user_id"),
                name="uniq_email_membership_tenant_user",
            ),
        ]
        indexes = [
            models.Index(fields=["email_normalized"]),
        ]

    def __str__(self) -> str:
        return f"{self.email_normalized} @ {self.tenant.schema_name}"


class TenantRegistrationRequest(models.Model):
    """
    Public-schema queue: self-service tenant signup before PlatformAdmin approval.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    company_name = models.CharField(max_length=255)
    company_full_name = models.CharField(max_length=255, blank=True)
    company_address = models.CharField(max_length=500, blank=True)
    license_no = models.CharField(max_length=64, blank=True)
    operation_no = models.CharField(max_length=64, blank=True)
    contact_phone = models.CharField(max_length=64, blank=True)

    derived_schema_name = models.CharField(
        max_length=63,
        db_index=True,
        help_text="Candidate PostgreSQL schema / subdomain slug (from company name).",
    )

    owner_email = models.EmailField()
    owner_password_hash = models.CharField(max_length=128)

    status_token_hash = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA-256 hex of opaque token for GET status (empty after rotate or if disabled).",
    )

    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "tenants.PlatformAdmin",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_tenant_registrations",
    )
    rejection_reason = models.TextField(blank=True)

    approved_tenant = models.OneToOneField(
        "tenants.Client",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_registration",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants_tenant_registration_request"
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.company_name} ({self.derived_schema_name}) — {self.status}"


class PlatformAdmin(AbstractBaseUser):
    """
    SamperLabs internal staff; lives only in the public schema.
    Authenticated via PlatformAdminBackend (no auth_user table on public).
    """

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_on = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        db_table = "tenants_platform_admin"
        verbose_name = "Platform Admin"
        verbose_name_plural = "Platform Admins"

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"
