"""
Tenant provisioning and registration helpers (public schema + tenant_context).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, tenant_context
from slugify import slugify

from tenants.models import Client, Domain, TenantRegistrationRequest

if TYPE_CHECKING:
    from tenants.models import PlatformAdmin

# Subdomains / schema names that must never be used by a tenant.
RESERVED_SCHEMA_NAMES = frozenset(
    {
        "public",
        "www",
        "api",
        "app",
        "admin",
        "static",
        "media",
        "mail",
        "ftp",
        "localhost",
        "platform-admin",
        "carnitrack",
    }
)


def _normalize_company_for_slug(company_name: str) -> str:
    s = (company_name or "").strip()
    return s


def derive_base_schema_name(company_name: str) -> str:
    """ASCII slug from company name (DNS-safe)."""
    raw = _normalize_company_for_slug(company_name)
    base = slugify(raw, allow_unicode=False, max_length=60)
    if not base:
        base = "tenant"
    base = base.lower()
    if len(base) > 63:
        base = base[:63].rstrip("-")
    return base


def is_valid_schema_slug(value: str) -> bool:
    if not value or len(value) > 63:
        return False
    if value in RESERVED_SCHEMA_NAMES:
        return False
    return bool(re.match(r"^[a-z0-9][a-z0-9\-]{0,62}$", value))


def allocate_unique_schema_name(base: str) -> str:
    """
    Ensure `base` is unique among Client.schema_name and pending TenantRegistrationRequest.
    Appends -2, -3, ... if needed.
    """
    candidate = base[:63].rstrip("-") or "tenant"
    n = 0
    while True:
        name = candidate if n == 0 else f"{candidate}-{n + 1}"[:63].rstrip("-")
        if len(name) > 63:
            name = name[:63].rstrip("-")
        if is_valid_schema_name_available(name):
            return name
        n += 1
        if n > 5000:
            raise ValidationError("Could not allocate a unique tenant slug.")


def is_valid_schema_name_available(schema_name: str) -> bool:
    if not is_valid_schema_slug(schema_name):
        return False
    if Client.objects.filter(schema_name=schema_name).exists():
        return False
    pending = TenantRegistrationRequest.objects.filter(
        status=TenantRegistrationRequest.Status.PENDING,
        derived_schema_name=schema_name,
    ).exists()
    if pending:
        return False
    return True


def hash_status_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_status_token_pair() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_status_token(raw)


def verify_status_token(stored_hash: str, raw_token: str) -> bool:
    if not stored_hash or not raw_token:
        return False
    return secrets.compare_digest(stored_hash, hash_status_token(raw_token))


@transaction.atomic
def provision_tenant(
    *,
    schema_name: str,
    name: str,
    company_name: str = "",
    company_full_name: str = "",
    company_address: str = "",
    license_no: str = "",
    operation_no: str = "",
    contact_email: str = "",
    contact_phone: str = "",
    domain_name: str | None = None,
) -> Client:
    """
    Create Client + primary Domain (PostgreSQL schema + migrations via django-tenants).
    Caller must ensure schema_name is unique and valid.
    """
    base_domain = settings.TENANT_BASE_DOMAIN
    if domain_name is None:
        domain_name = f"{schema_name}.{base_domain}"

    tenant = Client(
        schema_name=schema_name,
        name=name,
        company_name=company_name or name,
        company_full_name=company_full_name,
        company_address=company_address,
        license_no=license_no,
        operation_no=operation_no,
        contact_email=contact_email,
        contact_phone=contact_phone,
    )
    tenant.save()
    Domain.objects.create(domain=domain_name, tenant=tenant, is_primary=True)
    return tenant


@transaction.atomic
def hard_delete_tenant(*, schema_name: str) -> None:
    """
    Remove the tenant row, domains, CASCADE public rows, and DROP SCHEMA ... CASCADE.
    Must run with DB connection on the public schema (e.g. platform admin request).
    """
    public = get_public_schema_name()
    if schema_name == public:
        raise ValidationError("Cannot delete the public schema.")
    if schema_name in RESERVED_SCHEMA_NAMES:
        raise ValidationError(f'Schema name "{schema_name}" is reserved.')
    tenant = Client.objects.filter(schema_name=schema_name).first()
    if tenant is None:
        raise ValidationError("Tenant not found.")
    tenant.delete(force_drop=True)


def _derive_owner_username(email: str) -> str:
    local = (email or "").split("@")[0].strip().lower()
    local = re.sub(r"[^a-z0-9._-]+", "-", local).strip("-") or "owner"
    return local[:150]


@transaction.atomic
def approve_registration(
    reg: TenantRegistrationRequest,
    reviewer: PlatformAdmin,
) -> Client:
    """
    Provision tenant and create the first tenant user with role OWNER (same app permissions as MANAGER).
    OWNER is not created via platform-admin "Create user" — that flow creates ADMIN / Django superuser only.
    """
    if reg.status == TenantRegistrationRequest.Status.APPROVED and reg.approved_tenant_id:
        return reg.approved_tenant

    if reg.status != TenantRegistrationRequest.Status.PENDING:
        raise ValidationError("Registration is not pending.")

    tenant = None
    try:
        tenant = provision_tenant(
            schema_name=reg.derived_schema_name,
            name=reg.company_name,
            company_name=reg.company_name,
            company_full_name=reg.company_full_name,
            company_address=reg.company_address,
            license_no=reg.license_no,
            operation_no=reg.operation_no,
            contact_email=reg.owner_email,
            contact_phone=reg.contact_phone,
        )

        User = get_user_model()
        email = reg.owner_email.strip().lower()
        username = _derive_owner_username(email)
        with tenant_context(tenant):
            if User.objects.filter(username__iexact=username).exists():
                base = username
                for i in range(2, 1000):
                    candidate = f"{base}-{i}"[:150]
                    if not User.objects.filter(username__iexact=candidate).exists():
                        username = candidate
                        break
            user = User(
                username=username,
                email=email,
                role=User.Role.OWNER.value,
                is_staff=False,
                is_superuser=False,
                is_active=True,
            )
            user.password = reg.owner_password_hash
            user.save()
    except Exception:
        if tenant is not None and getattr(tenant, "pk", None):
            try:
                tenant.delete(force_drop=True)
            except TypeError:
                tenant.delete()
        raise

    reg.status = TenantRegistrationRequest.Status.APPROVED
    reg.reviewed_at = timezone.now()
    reg.reviewed_by = reviewer
    reg.approved_tenant = tenant
    reg.rejection_reason = ""
    reg.save(
        update_fields=[
            "status",
            "reviewed_at",
            "reviewed_by",
            "approved_tenant",
            "rejection_reason",
            "updated_at",
        ]
    )
    return tenant


def reject_registration(reg: TenantRegistrationRequest, reviewer: PlatformAdmin, reason: str = "") -> None:
    if reg.status != TenantRegistrationRequest.Status.PENDING:
        raise ValidationError("Registration is not pending.")
    reg.status = TenantRegistrationRequest.Status.REJECTED
    reg.reviewed_at = timezone.now()
    reg.reviewed_by = reviewer
    reg.rejection_reason = reason.strip()
    reg.save(update_fields=["status", "reviewed_at", "reviewed_by", "rejection_reason", "updated_at"])
