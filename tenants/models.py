import os
import uuid

from django.contrib.auth.models import AbstractBaseUser
from django.core.files.storage import default_storage
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django_tenants.models import DomainMixin, TenantMixin

from tenants.turkey_provinces import PROVINCE_CHOICES


def _get_public_storage():
    from django.conf import settings

    if getattr(settings, "USE_GCS", False):
        from tenants.storage import PublicGCSStorage

        return PublicGCSStorage()
    return default_storage


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
    registered_province_plaka = models.CharField(
        max_length=2,
        choices=PROVINCE_CHOICES,
        default="17",
        verbose_name=_("Company registration province"),
        help_text=_(
            "Turkish province (plaka) where the company is registered; drives the VD prefix on printed labels."
        ),
    )
    logo = models.ImageField(
        upload_to=tenant_logo_upload_to,
        storage=_get_public_storage,
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
        from django.conf import settings

        if not self.slug:
            self.slug = self.schema_name
        # When django_tenants is not installed (e.g. test settings — some tests
        # still set USE_MULTITENANT=True via override_settings to exercise view
        # behavior), its `migrate_schemas` management command is not registered.
        # TenantMixin.save() would otherwise call create_schema() →
        # call_command("migrate_schemas") on PostgreSQL and raise CommandError.
        # Production has django_tenants in INSTALLED_APPS, so this branch is
        # skipped and normal schema creation runs.
        if "django_tenants" not in settings.INSTALLED_APPS:
            original = self.auto_create_schema
            self.auto_create_schema = False
            try:
                super().save(*args, **kwargs)
            finally:
                self.auto_create_schema = original
            return
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


class PlatformImpersonationSession(models.Model):
    class Destination(models.TextChoices):
        DASHBOARD = "dashboard", "Dashboard"
        DJANGO_ADMIN = "django_admin", "Django admin"

    platform_admin = models.ForeignKey(
        "tenants.PlatformAdmin",
        on_delete=models.CASCADE,
        related_name="impersonation_sessions",
    )
    tenant = models.ForeignKey(
        "tenants.Client",
        on_delete=models.CASCADE,
        related_name="platform_impersonation_sessions",
    )
    target_user_id = models.PositiveIntegerField()
    target_username = models.CharField(max_length=150)
    target_email = models.EmailField(blank=True)
    target_role = models.CharField(max_length=50, blank=True)
    token_hash = models.CharField(max_length=64, unique=True)
    destination = models.CharField(
        max_length=32,
        choices=Destination.choices,
        default=Destination.DASHBOARD,
    )
    created_from_ip = models.CharField(max_length=64, blank=True)
    consumed_host = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenants_platform_impersonation_session"
        indexes = [
            models.Index(fields=["tenant", "created_at"]),
            models.Index(fields=["platform_admin", "created_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.tenant.schema_name}:{self.target_username} by {self.platform_admin.email}"


class EdgeSetupCodeIndex(models.Model):
    """
    Public-schema lookup table mapping setup codes to tenant schemas.
    Enables Edge activation via a single public API endpoint (api.carnitrack.com)
    without requiring the Edge to know its tenant subdomain ahead of time.

    Rows are created/deleted in sync with EdgeSetupCode in each tenant schema.
    """

    code = models.CharField(max_length=16, unique=True, db_index=True)
    tenant = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="edge_code_index_entries")
    tenant_schema = models.CharField(max_length=63, help_text="Cached schema_name for fast lookup without JOIN.")
    setup_code_id = models.UUIDField(help_text="PK of the EdgeSetupCode row in the tenant schema.")
    expires_at = models.DateTimeField()
    is_consumed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenants_edge_setup_code_index"
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["tenant", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} -> {self.tenant_schema}"


class EdgeDeviceIndex(models.Model):
    """
    Public-schema lookup table mapping registered Edge device UUIDs to tenant schemas.

    Enables Edge API requests on the public domain (api.carnitrack.com) without
    requiring the Edge to know its tenant subdomain. The decorator
    public_require_edge_id uses this table to resolve the tenant, then switches
    to the tenant schema via schema_context() before calling the actual view.

    Rows are created during activation (public_edge_activate) and synced via
    post_save/post_delete signals on EdgeDevice in each tenant schema.
    """

    edge_id = models.UUIDField(unique=True, db_index=True, help_text="EdgeDevice.id from the tenant schema.")
    tenant = models.ForeignKey("tenants.Client", on_delete=models.CASCADE, related_name="edge_device_index_entries")
    tenant_schema = models.CharField(max_length=63, help_text="Cached schema_name for fast lookup without JOIN.")
    edge_name = models.CharField(max_length=200, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants_edge_device_index"
        indexes = [
            models.Index(fields=["tenant", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Edge {self.edge_id} -> {self.tenant_schema}"


class PlatformImpersonationEvent(models.Model):
    class Mode(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MANAGER = "manager", "Manager"
        OPERATOR = "operator", "Operator"
        CLIENT = "client", "Client"
        WALKIN = "walkin", "Walk-in"
        GOD_MODE = "god_mode", "God mode"

    class EndReason(models.TextChoices):
        MANUAL = "manual", "Manual"
        EXPIRED = "expired", "Expired"
        LOGOUT = "logout", "Logout"

    platform_admin = models.ForeignKey(
        PlatformAdmin,
        on_delete=models.CASCADE,
        related_name="impersonation_events",
    )
    tenant = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="impersonation_events",
    )
    mode = models.CharField(max_length=32, choices=Mode.choices, default=Mode.GOD_MODE)
    target_user_id = models.PositiveIntegerField()
    target_username = models.CharField(max_length=150)
    target_email = models.EmailField(blank=True)
    target_role = models.CharField(max_length=50, blank=True)
    target_is_superuser = models.BooleanField(default=False)
    issued_at = models.DateTimeField(auto_now_add=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        db_table = "tenants_platform_impersonation_event"
        indexes = [
            models.Index(fields=["tenant", "issued_at"]),
            models.Index(fields=["platform_admin", "issued_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.platform_admin.email} -> {self.tenant.schema_name}:{self.target_username}"
