from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.db.models import Count, Max, Q
from django.http import HttpRequest
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django_tenants.utils import get_public_schema_name, schema_context, tenant_context

from core.models import ServicePackage
from processing.models import Animal
from reception.models import SlaughterOrder
from tenants.email_index import (
    build_post_login_redirect_url,
    build_tenant_api_base_url,
    build_tenant_web_app_base_url,
    get_tenant_public_host,
)
from tenants.models import Client, PlatformImpersonationEvent


@dataclass(frozen=True)
class TenantImpersonationTarget:
    mode: str
    label: str
    user_id: int
    username: str
    email: str
    role: str
    is_superuser: bool


@dataclass(frozen=True)
class TenantHealthSnapshot:
    tone: str
    label: str
    reasons: tuple[str, ...] = ()

    @property
    def issues(self) -> tuple[str, ...]:
        return self.reasons

    @property
    def needs_attention(self) -> bool:
        return self.tone != "healthy"


@dataclass(frozen=True)
class TenantOperationalSnapshot:
    total_users: int = 0
    active_users: int = 0
    owner_count: int = 0
    admin_count: int = 0
    manager_count: int = 0
    operator_count: int = 0
    client_count: int = 0
    django_superuser_count: int = 0
    recent_logins_7d: int = 0
    total_orders: int = 0
    recent_orders_7d: int = 0
    pending_orders: int = 0
    in_progress_orders: int = 0
    completed_orders: int = 0
    total_animals: int = 0
    recent_animals_7d: int = 0
    carcass_ready_count: int = 0
    disassembled_count: int = 0
    delivered_count: int = 0
    latest_login_at: object | None = None
    latest_order_at: object | None = None
    latest_animal_at: object | None = None
    latest_activity_at: object | None = None
    service_package_count: int = 0

    @property
    def staff_users(self) -> int:
        return self.owner_count + self.admin_count + self.manager_count + self.operator_count

    @property
    def client_profiles(self) -> int:
        return self.client_count


@dataclass(frozen=True)
class TenantDashboardRow:
    tenant: Client
    app_url: str
    dashboard_url: str
    web_url: str
    admin_url: str
    primary_domain: str
    domain_count: int
    stats: TenantOperationalSnapshot
    health: TenantHealthSnapshot
    owner_target: TenantImpersonationTarget | None
    admin_target: TenantImpersonationTarget | None
    god_mode_target: TenantImpersonationTarget | None
    attention_flags: tuple[str, ...] = ()
    query_error: str = ""

    @property
    def host(self) -> str:
        return get_tenant_public_host(self.tenant)

    @property
    def latest_activity_at(self):
        return self.stats.latest_activity_at

    @property
    def needs_attention(self) -> bool:
        return self.health.needs_attention

    @property
    def health_state(self) -> str:
        return self.health.tone

    @property
    def health_label(self) -> str:
        return self.health.label

    @property
    def health_issues(self) -> tuple[str, ...]:
        return self.health.issues

    @property
    def god_mode_available(self) -> bool:
        return self.god_mode_target is not None and self.tenant.is_active

    @property
    def preferred_impersonation_label(self) -> str:
        return self.god_mode_target.username if self.god_mode_target is not None else ""

    @property
    def django_admin_available(self) -> bool:
        return self.admin_target is not None and self.admin_target.is_superuser and self.tenant.is_active


@dataclass(frozen=True)
class PlatformDashboardSummary:
    total_tenants: int
    active_tenants: int
    inactive_tenants: int
    pending_registrations: int
    recent_activity_tenants: int
    attention_tenants: int
    total_active_users: int
    total_orders_7d: int
    total_animals_7d: int
    attention_queue: tuple[TenantDashboardRow, ...] = field(default_factory=tuple)

    @property
    def healthy_tenants(self) -> int:
        return self.total_tenants - self.attention_tenants

    @property
    def active_recently(self) -> int:
        return self.recent_activity_tenants

    @property
    def need_attention(self) -> int:
        return self.attention_tenants

    @property
    def attention_rows(self) -> tuple[TenantDashboardRow, ...]:
        return self.attention_queue


def _latest_activity(*values):
    candidates = [value for value in values if value is not None]
    if not candidates:
        return None
    return max(candidates)


def _primary_domain_for(tenant: Client) -> str:
    primary = tenant.get_primary_domain() if hasattr(tenant, "get_primary_domain") else None
    return (getattr(primary, "domain", "") or "").strip()


def _impersonation_priority(user) -> tuple[int, int, str, int]:
    role = getattr(user, "role", "") or ""
    if getattr(user, "is_superuser", False):
        bucket = 0
    elif role == "OWNER":
        bucket = 1
    elif role == "ADMIN":
        bucket = 2
    elif role == "MANAGER":
        bucket = 3
    else:
        bucket = 4
    date_joined = getattr(user, "date_joined", None)
    timestamp = int(date_joined.timestamp()) if date_joined else 0
    return bucket, timestamp, getattr(user, "username", ""), getattr(user, "pk", 0)


def _build_impersonation_targets(users: list) -> tuple[TenantImpersonationTarget | None, ...]:
    active_users = [user for user in users if getattr(user, "is_active", False)]
    if not active_users:
        return None, None, None

    def as_target(mode: str, label: str, user) -> TenantImpersonationTarget | None:
        if user is None:
            return None
        return TenantImpersonationTarget(
            mode=mode,
            label=label,
            user_id=user.pk,
            username=user.username,
            email=getattr(user, "email", "") or "",
            role=getattr(user, "role", "") or "",
            is_superuser=bool(getattr(user, "is_superuser", False)),
        )

    ordered = sorted(active_users, key=_impersonation_priority)
    owner = next((user for user in ordered if user.role == "OWNER"), None)
    admin = next((user for user in ordered if getattr(user, "is_superuser", False) or user.role == "ADMIN"), None)
    god_mode = ordered[0]
    return (
        as_target("owner", _("Owner"), owner),
        as_target("admin", _("Admin"), admin),
        as_target("god_mode", _("God mode"), god_mode),
    )


def _collect_tenant_snapshot(
    tenant: Client,
) -> tuple[TenantOperationalSnapshot, tuple[TenantImpersonationTarget | None, ...]]:
    User = get_user_model()
    since = timezone.now() - timedelta(days=7)

    with tenant_context(tenant):
        users = list(
            User.objects.only(
                "id", "username", "email", "role", "is_active", "is_superuser", "last_login", "date_joined"
            )
        )
        user_agg = User.objects.aggregate(
            total_users=Count("id"),
            active_users=Count("id", filter=Q(is_active=True)),
            owner_count=Count("id", filter=Q(is_active=True, role=User.Role.OWNER)),
            admin_count=Count("id", filter=Q(is_active=True, role=User.Role.ADMIN)),
            manager_count=Count("id", filter=Q(is_active=True, role=User.Role.MANAGER)),
            operator_count=Count("id", filter=Q(is_active=True, role=User.Role.OPERATOR)),
            client_count=Count("id", filter=Q(is_active=True, role__in=[User.Role.CLIENT, User.Role.WALKIN])),
            django_superuser_count=Count("id", filter=Q(is_active=True, is_superuser=True)),
            recent_logins_7d=Count("id", filter=Q(is_active=True, last_login__gte=since)),
            latest_login_at=Max("last_login"),
        )
        order_agg = SlaughterOrder.objects.aggregate(
            total_orders=Count("id"),
            recent_orders_7d=Count("id", filter=Q(created_at__gte=since)),
            pending_orders=Count("id", filter=Q(status=SlaughterOrder.Status.PENDING)),
            in_progress_orders=Count("id", filter=Q(status=SlaughterOrder.Status.IN_PROGRESS)),
            completed_orders=Count("id", filter=Q(status=SlaughterOrder.Status.COMPLETED)),
            latest_order_at=Max("created_at"),
        )
        animal_agg = Animal.objects.aggregate(
            total_animals=Count("id"),
            recent_animals_7d=Count("id", filter=Q(created_at__gte=since)),
            carcass_ready_count=Count("id", filter=Q(status="carcass_ready")),
            disassembled_count=Count("id", filter=Q(status="disassembled")),
            delivered_count=Count("id", filter=Q(status="delivered")),
            latest_animal_at=Max("created_at"),
        )
        service_package_count = ServicePackage.objects.filter(is_active=True).count()

    snapshot = TenantOperationalSnapshot(
        total_users=user_agg["total_users"] or 0,
        active_users=user_agg["active_users"] or 0,
        owner_count=user_agg["owner_count"] or 0,
        admin_count=user_agg["admin_count"] or 0,
        manager_count=user_agg["manager_count"] or 0,
        operator_count=user_agg["operator_count"] or 0,
        client_count=user_agg["client_count"] or 0,
        django_superuser_count=user_agg["django_superuser_count"] or 0,
        recent_logins_7d=user_agg["recent_logins_7d"] or 0,
        total_orders=order_agg["total_orders"] or 0,
        recent_orders_7d=order_agg["recent_orders_7d"] or 0,
        pending_orders=order_agg["pending_orders"] or 0,
        in_progress_orders=order_agg["in_progress_orders"] or 0,
        completed_orders=order_agg["completed_orders"] or 0,
        total_animals=animal_agg["total_animals"] or 0,
        recent_animals_7d=animal_agg["recent_animals_7d"] or 0,
        carcass_ready_count=animal_agg["carcass_ready_count"] or 0,
        disassembled_count=animal_agg["disassembled_count"] or 0,
        delivered_count=animal_agg["delivered_count"] or 0,
        latest_login_at=user_agg["latest_login_at"],
        latest_order_at=order_agg["latest_order_at"],
        latest_animal_at=animal_agg["latest_animal_at"],
        latest_activity_at=_latest_activity(
            user_agg["latest_login_at"],
            order_agg["latest_order_at"],
            animal_agg["latest_animal_at"],
        ),
        service_package_count=service_package_count,
    )
    return snapshot, _build_impersonation_targets(users)


def _build_health(
    tenant: Client, primary_domain: str, stats: TenantOperationalSnapshot, query_error: str = ""
) -> tuple[TenantHealthSnapshot, tuple[str, ...]]:
    now = timezone.now()
    stale_cutoff = now - timedelta(days=30)
    flags: list[str] = []

    if query_error:
        flags.append(query_error)
    if not tenant.is_active:
        flags.append(_("Tenant is deactivated."))
    if not primary_domain:
        flags.append(_("Primary domain is missing."))
    if stats.active_users == 0:
        flags.append(_("No active tenant users."))
    if (stats.owner_count + stats.admin_count + stats.django_superuser_count) == 0:
        flags.append(_("No owner/admin access user exists."))
    if stats.service_package_count == 0:
        flags.append(_("No service packages configured."))
    if stats.latest_activity_at is None:
        flags.append(_("No tenant activity yet."))
    elif stats.latest_activity_at < stale_cutoff:
        flags.append(_("No activity in the last 30 days."))

    if query_error:
        return TenantHealthSnapshot(tone="error", label=_("Data issue"), reasons=tuple(flags)), tuple(flags)
    if not tenant.is_active:
        return TenantHealthSnapshot(tone="inactive", label=_("Inactive"), reasons=tuple(flags)), tuple(flags)
    if (
        not primary_domain
        or stats.service_package_count == 0
        or (stats.owner_count + stats.admin_count + stats.django_superuser_count) == 0
    ):
        return TenantHealthSnapshot(tone="setup", label=_("Needs setup"), reasons=tuple(flags)), tuple(flags)
    if stats.latest_activity_at is None or stats.latest_activity_at < stale_cutoff:
        return TenantHealthSnapshot(tone="attention", label=_("Attention"), reasons=tuple(flags)), tuple(flags)
    return TenantHealthSnapshot(tone="healthy", label=_("Healthy"), reasons=tuple(flags)), tuple(flags)


def build_tenant_dashboard_row(tenant: Client) -> TenantDashboardRow:
    primary_domain = _primary_domain_for(tenant)
    app_url = build_tenant_api_base_url(tenant)
    dashboard_url = build_post_login_redirect_url(tenant, use_api_host=True)
    web_url = build_tenant_web_app_base_url(tenant)
    admin_url = f"{app_url.rstrip('/')}/admin/"

    try:
        stats, targets = _collect_tenant_snapshot(tenant)
        query_error = ""
    except DatabaseError as exc:
        stats = TenantOperationalSnapshot()
        targets = (None, None, None)
        query_error = str(exc)

    health, flags = _build_health(tenant, primary_domain, stats, query_error=query_error)
    owner_target, admin_target, god_mode_target = targets
    return TenantDashboardRow(
        tenant=tenant,
        app_url=app_url,
        dashboard_url=dashboard_url,
        web_url=web_url,
        admin_url=admin_url,
        primary_domain=primary_domain,
        domain_count=len(list(tenant.domains.all())) if hasattr(tenant, "domains") else 0,
        stats=stats,
        health=health,
        owner_target=owner_target,
        admin_target=admin_target,
        god_mode_target=god_mode_target,
        attention_flags=flags[:3],
        query_error=query_error,
    )


def build_platform_dashboard_summary(
    *, tenant_rows: list[TenantDashboardRow], pending_registrations: int
) -> PlatformDashboardSummary:
    recent_cutoff = timezone.now() - timedelta(days=7)
    attention_queue = tuple(row for row in tenant_rows if row.health.tone != "healthy")
    return PlatformDashboardSummary(
        total_tenants=len(tenant_rows),
        active_tenants=sum(1 for row in tenant_rows if row.tenant.is_active),
        inactive_tenants=sum(1 for row in tenant_rows if not row.tenant.is_active),
        pending_registrations=pending_registrations,
        recent_activity_tenants=sum(
            1
            for row in tenant_rows
            if row.stats.latest_activity_at is not None and row.stats.latest_activity_at >= recent_cutoff
        ),
        attention_tenants=len(attention_queue),
        total_active_users=sum(row.stats.active_users for row in tenant_rows),
        total_orders_7d=sum(row.stats.recent_orders_7d for row in tenant_rows),
        total_animals_7d=sum(row.stats.recent_animals_7d for row in tenant_rows),
        attention_queue=attention_queue[:6],
    )


def get_impersonation_target_for_mode(tenant: Client, mode: str) -> TenantImpersonationTarget:
    row = build_tenant_dashboard_row(tenant)
    target_map = {
        "owner": row.owner_target,
        "admin": row.admin_target,
        "god_mode": row.god_mode_target,
    }
    target = target_map.get(mode)
    if target is None:
        raise ValueError(f"No impersonation target available for mode={mode!r}")
    return target


def start_platform_impersonation(request: HttpRequest, *, tenant: Client, platform_admin, mode: str):
    if mode not in {"owner", "admin", "god_mode"}:
        raise ValueError(f"Unsupported impersonation mode: {mode}")

    target = get_impersonation_target_for_mode(tenant, mode)
    with schema_context(get_public_schema_name()):
        event = PlatformImpersonationEvent.objects.create(
            platform_admin=platform_admin,
            tenant=tenant,
            mode=mode,
            target_user_id=target.user_id,
            target_username=target.username,
            target_email=target.email,
            target_role=target.role,
            target_is_superuser=target.is_superuser,
        )

    from users.views import _bootstrap_token_cache_set

    token = secrets.token_urlsafe(32)
    return_url = request.build_absolute_uri("/platform-admin/")
    dashboard_url = build_post_login_redirect_url(tenant, use_api_host=True)
    _bootstrap_token_cache_set(
        token=token,
        payload={
            "user_id": target.user_id,
            "schema": tenant.schema_name,
            "platform_impersonation": {
                "event_id": str(event.id),
                "mode": mode,
                "platform_admin_email": getattr(platform_admin, "email", "") or "",
                "platform_admin_name": getattr(platform_admin, "name", "") or "",
                "target_username": target.username,
                "target_role": target.role,
                "target_email": target.email,
                "return_url": return_url,
            },
        },
    )
    bootstrap_url = f"{build_tenant_api_base_url(tenant).rstrip('/')}/api/v1/auth/session-bootstrap/?{urlencode({'token': token, 'next': dashboard_url})}"
    return redirect(bootstrap_url)
