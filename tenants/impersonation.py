from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from tenants.email_index import build_post_login_redirect_url, build_tenant_api_base_url
from tenants.models import PlatformImpersonationSession
from users.models import User

IMPERSONATION_DESTINATION_DASHBOARD = "dashboard"
IMPERSONATION_DESTINATION_DJANGO_ADMIN = "django_admin"


def _impersonation_ttl_seconds() -> int:
    try:
        value = int(getattr(settings, "PLATFORM_IMPERSONATION_TTL_SECONDS", 180) or 180)
    except (TypeError, ValueError):
        value = 180
    return max(value, 30)


def hash_impersonation_token(raw_token: str) -> str:
    return hashlib.sha256((raw_token or "").encode("utf-8")).hexdigest()


def get_platform_admin_dashboard_url() -> str:
    base = (getattr(settings, "SITE_URL_FALLBACK", "") or "http://localhost:8000").rstrip("/")
    return f"{base}/platform-admin/"


def build_impersonation_consume_url(tenant, raw_token: str) -> str:
    base = build_tenant_api_base_url(tenant).rstrip("/")
    return f"{base}/platform-admin/impersonate/consume/?token={raw_token}"


def create_platform_impersonation_session(
    *,
    platform_admin,
    tenant,
    target_user,
    destination: str = IMPERSONATION_DESTINATION_DASHBOARD,
    created_from_ip: str = "",
):
    if not tenant.is_active:
        raise ValidationError("Cannot impersonate an inactive tenant.")
    if not getattr(target_user, "is_active", False):
        raise ValidationError("Cannot impersonate an inactive user.")
    if destination == IMPERSONATION_DESTINATION_DJANGO_ADMIN and not (
        getattr(target_user, "is_staff", False) or getattr(target_user, "is_superuser", False)
    ):
        raise ValidationError("Selected user does not have Django admin access.")
    if destination not in {
        IMPERSONATION_DESTINATION_DASHBOARD,
        IMPERSONATION_DESTINATION_DJANGO_ADMIN,
    }:
        raise ValidationError("Unknown impersonation destination.")

    raw_token = secrets.token_urlsafe(32)
    session = PlatformImpersonationSession.objects.create(
        platform_admin=platform_admin,
        tenant=tenant,
        target_user_id=target_user.pk,
        target_username=target_user.get_username(),
        target_email=(getattr(target_user, "email", "") or "")[:254],
        target_role=(getattr(target_user, "role", "") or "")[:50],
        token_hash=hash_impersonation_token(raw_token),
        destination=destination,
        created_from_ip=(created_from_ip or "")[:64],
        expires_at=timezone.now() + timedelta(seconds=_impersonation_ttl_seconds()),
    )
    return session, raw_token


def consume_platform_impersonation_session(*, raw_token: str, tenant, consumed_host: str = ""):
    token_hash = hash_impersonation_token(raw_token)
    if not token_hash:
        raise ValidationError("Missing impersonation token.")

    with transaction.atomic():
        session = (
            PlatformImpersonationSession.objects.select_for_update()
            .select_related("platform_admin", "tenant")
            .filter(token_hash=token_hash)
            .first()
        )
        if session is None:
            raise ValidationError("Impersonation link is invalid.")
        if session.tenant_id != tenant.pk:
            raise ValidationError("Impersonation link does not belong to this tenant.")
        if session.consumed_at is not None:
            raise ValidationError("Impersonation link was already used.")
        if session.expires_at <= timezone.now():
            raise ValidationError("Impersonation link expired.")

        session.consumed_at = timezone.now()
        session.consumed_host = (consumed_host or "")[:255]
        session.save(update_fields=["consumed_at", "consumed_host"])
        return session


def stop_platform_impersonation_session(session_id) -> None:
    if not session_id:
        return
    PlatformImpersonationSession.objects.filter(pk=session_id, stopped_at__isnull=True).update(stopped_at=timezone.now())


def get_impersonation_redirect_url(session) -> str:
    if session.destination == IMPERSONATION_DESTINATION_DJANGO_ADMIN:
        return "/admin/"
    return build_post_login_redirect_url(session.tenant, use_api_host=True)


def get_impersonation_stop_payload(request) -> dict | None:
    if not request.session.get("platform_impersonation_active"):
        return None
    return {
        "active": True,
        "session_id": request.session.get("platform_impersonation_session_id"),
        "platform_admin_email": request.session.get("platform_impersonation_admin_email", ""),
        "platform_admin_name": request.session.get("platform_impersonation_admin_name", ""),
        "target_username": request.session.get("platform_impersonation_target_username", ""),
        "target_role": request.session.get("platform_impersonation_target_role", ""),
        "started_at": request.session.get("platform_impersonation_started_at", ""),
        "stop_url": "/platform-admin/impersonate/stop/",
        "return_url": get_platform_admin_dashboard_url(),
    }
