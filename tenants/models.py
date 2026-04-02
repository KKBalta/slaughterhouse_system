import os
import uuid

from django.contrib.auth.models import AbstractBaseUser
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django_tenants.models import DomainMixin, TenantMixin

_LOGO_SLUG_MAX_LEN = 80
LOGO_ALLOWED_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})


def tenant_logo_upload_to(instance, filename: str) -> str:
    """
    Store logos as tenant_logos/<schema>/<company_slug>_logo.<ext> for stable, readable paths.
    """
    schema = (getattr(instance, "schema_name", None) or "tenant").strip() or "tenant"
    label = (getattr(instance, "company_name", None) or getattr(instance, "name", None) or schema or "logo") or "logo"
    label = str(label).strip() or "logo"
    base = slugify(label) or "logo"
    if len(base) > _LOGO_SLUG_MAX_LEN:
        base = base[:_LOGO_SLUG_MAX_LEN]
    _, ext = os.path.splitext(filename or "")
    ext = ext.lower()
    if ext not in LOGO_ALLOWED_EXTENSIONS:
        ext = ".png"
    return f"tenant_logos/{schema}/{base}_logo{ext}"


class Client(TenantMixin):
    """One row per tenant in the public schema; company fields drive labels and branding."""

    name = models.CharField(max_length=255, help_text="Business / display name")
    slug = models.SlugField(
        max_length=63,
        unique=True,
        blank=True,
        help_text="Subdomain identifier; auto-populated from schema_name if left blank",
    )
    company_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Company name (label header)"),
        help_text=_("Short trading name printed on labels."),
    )
    company_full_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Legal company name"),
        help_text=_("Full legal title on labels."),
    )
    company_address = models.CharField(
        max_length=500,
        blank=True,
        verbose_name=_("Company address"),
        help_text=_("Address block on labels and reports."),
    )
    license_no = models.CharField(
        max_length=64,
        blank=True,
        verbose_name=_("İşletme onay no"),
        help_text=_("Government approval number; same value as ISLETME ONAY NO on printed labels."),
    )
    operation_no = models.CharField(
        max_length=64,
        blank=True,
        verbose_name=_("Vergi dairesi / işletme no (VD)"),
        help_text=_("Tax office / operation number (e.g. ÇKALE VD line on labels)."),
    )
    logo = models.ImageField(
        upload_to=tenant_logo_upload_to,
        blank=True,
        null=True,
        verbose_name=_("Logo"),
        help_text=_("Optional branding image in the app header."),
    )
    contact_email = models.EmailField(blank=True, verbose_name=_("Contact email"))
    contact_phone = models.CharField(max_length=64, blank=True, verbose_name=_("Contact phone"))
    is_active = models.BooleanField(default=True)
    created_on = models.DateTimeField(auto_now_add=True)
    printer_turkish_mode = models.CharField(
        max_length=32,
        default="unicode",
        verbose_name=_("Printer Turkish mode"),
        help_text=_("unicode, ascii, or codepage1254 for label printers."),
    )
    timezone = models.CharField(max_length=64, default="Europe/Istanbul", verbose_name=_("Timezone"))
    language_code = models.CharField(max_length=16, default="tr", verbose_name=_("Language code"))

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
    phone_normalized = models.CharField(max_length=20, blank=True, default="", db_index=True)
    tenant = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="email_memberships")
    tenant_user_id = models.PositiveIntegerField(
        help_text="Primary key of users.User in the tenant schema (for stable upserts).",
    )
    role = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Mirrors users.User.role from the tenant schema (synced on save).",
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
