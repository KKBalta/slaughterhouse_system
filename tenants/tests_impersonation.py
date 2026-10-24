import hashlib
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone

from tenants.impersonation import (
    IMPERSONATION_DESTINATION_DASHBOARD,
    IMPERSONATION_DESTINATION_DJANGO_ADMIN,
    _impersonation_ttl_seconds,
    build_impersonation_consume_url,
    consume_platform_impersonation_session,
    create_platform_impersonation_session,
    get_impersonation_redirect_url,
    get_impersonation_stop_payload,
    get_platform_admin_dashboard_url,
    hash_impersonation_token,
    stop_platform_impersonation_session,
)
from tenants.models import Client, PlatformAdmin, PlatformImpersonationSession
from users.models import User

pytestmark = pytest.mark.django_db


def _make_base_objects():
    platform_admin = PlatformAdmin.objects.create(email="platform@example.com", name="Platform Admin")
    tenant = Client.objects.create(schema_name="acme", name="Acme", is_active=True)
    target_user = User.objects.create_user(
        username="target-user",
        email="target@example.com",
        password="testpass123",
        role=User.Role.ADMIN,
        is_active=True,
    )
    return platform_admin, tenant, target_user


@override_settings(PLATFORM_IMPERSONATION_TTL_SECONDS="15")
def test_impersonation_ttl_has_minimum_of_30_seconds():
    assert _impersonation_ttl_seconds() == 30


@override_settings(PLATFORM_IMPERSONATION_TTL_SECONDS="invalid")
def test_impersonation_ttl_falls_back_to_default_on_invalid_setting():
    assert _impersonation_ttl_seconds() == 180


def test_hash_impersonation_token_hashes_empty_string():
    assert hash_impersonation_token("") == hashlib.sha256(b"").hexdigest()


@override_settings(SITE_URL_FALLBACK="https://platform.example.com/")
def test_get_platform_admin_dashboard_url_uses_fallback_setting():
    assert get_platform_admin_dashboard_url() == "https://platform.example.com/platform-admin/"


def test_build_impersonation_consume_url_uses_tenant_api_base(mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme")
    mocker.patch("tenants.impersonation.build_tenant_api_base_url", return_value="https://acme.example.com/")

    url = build_impersonation_consume_url(tenant, "raw-token")

    assert url == "https://acme.example.com/platform-admin/impersonate/consume/?token=raw-token"


def test_create_platform_impersonation_session_rejects_inactive_tenant():
    platform_admin, tenant, target_user = _make_base_objects()
    tenant.is_active = False
    tenant.save(update_fields=["is_active"])

    with pytest.raises(ValidationError, match="inactive tenant"):
        create_platform_impersonation_session(platform_admin=platform_admin, tenant=tenant, target_user=target_user)


def test_create_platform_impersonation_session_rejects_inactive_target_user():
    platform_admin, tenant, target_user = _make_base_objects()
    target_user.is_active = False
    target_user.save(update_fields=["is_active"])

    with pytest.raises(ValidationError, match="inactive user"):
        create_platform_impersonation_session(platform_admin=platform_admin, tenant=tenant, target_user=target_user)


def test_create_platform_impersonation_session_rejects_django_admin_destination_without_access():
    platform_admin, tenant, target_user = _make_base_objects()
    target_user.is_staff = False
    target_user.is_superuser = False
    target_user.save(update_fields=["is_staff", "is_superuser"])

    with pytest.raises(ValidationError, match="Django admin access"):
        create_platform_impersonation_session(
            platform_admin=platform_admin,
            tenant=tenant,
            target_user=target_user,
            destination=IMPERSONATION_DESTINATION_DJANGO_ADMIN,
        )


def test_create_platform_impersonation_session_rejects_unknown_destination():
    platform_admin, tenant, target_user = _make_base_objects()

    with pytest.raises(ValidationError, match="Unknown impersonation destination"):
        create_platform_impersonation_session(
            platform_admin=platform_admin,
            tenant=tenant,
            target_user=target_user,
            destination="unknown",
        )


@override_settings(PLATFORM_IMPERSONATION_TTL_SECONDS=300)
def test_create_platform_impersonation_session_creates_record_and_truncates_fields(mocker):
    platform_admin, tenant, target_user = _make_base_objects()
    target_user.email = "x" * 300
    target_user.role = "R" * 80
    target_user.save(update_fields=["email", "role"])
    mocker.patch("secrets.token_urlsafe", return_value="deterministic-token")
    now = timezone.now()

    session, raw_token = create_platform_impersonation_session(
        platform_admin=platform_admin,
        tenant=tenant,
        target_user=target_user,
        destination=IMPERSONATION_DESTINATION_DASHBOARD,
        created_from_ip="1" * 100,
    )

    assert raw_token == "deterministic-token"
    assert session.token_hash == hash_impersonation_token("deterministic-token")
    assert session.target_email == ("x" * 254)
    assert session.target_role == ("R" * 50)
    assert session.created_from_ip == ("1" * 64)
    assert session.destination == IMPERSONATION_DESTINATION_DASHBOARD
    assert session.expires_at >= now + timedelta(seconds=300)


def test_consume_platform_impersonation_session_rejects_invalid_token():
    tenant = Client.objects.create(schema_name="acme", name="Acme")

    with pytest.raises(ValidationError, match="invalid"):
        consume_platform_impersonation_session(raw_token="missing-token", tenant=tenant)


def test_consume_platform_impersonation_session_rejects_session_from_another_tenant(mocker):
    platform_admin, tenant, target_user = _make_base_objects()
    other_tenant = Client.objects.create(schema_name="other", name="Other")
    mocker.patch("secrets.token_urlsafe", return_value="cross-tenant-token")
    _session, raw_token = create_platform_impersonation_session(
        platform_admin=platform_admin,
        tenant=tenant,
        target_user=target_user,
    )

    with pytest.raises(ValidationError, match="does not belong to this tenant"):
        consume_platform_impersonation_session(raw_token=raw_token, tenant=other_tenant)


def test_consume_platform_impersonation_session_rejects_already_used_link(mocker):
    platform_admin, tenant, target_user = _make_base_objects()
    mocker.patch("secrets.token_urlsafe", return_value="already-used-token")
    session, raw_token = create_platform_impersonation_session(
        platform_admin=platform_admin,
        tenant=tenant,
        target_user=target_user,
    )
    session.consumed_at = timezone.now()
    session.save(update_fields=["consumed_at"])

    with pytest.raises(ValidationError, match="already used"):
        consume_platform_impersonation_session(raw_token=raw_token, tenant=tenant)


def test_consume_platform_impersonation_session_rejects_expired_link(mocker):
    platform_admin, tenant, target_user = _make_base_objects()
    mocker.patch("secrets.token_urlsafe", return_value="expired-token")
    session, raw_token = create_platform_impersonation_session(
        platform_admin=platform_admin,
        tenant=tenant,
        target_user=target_user,
    )
    session.expires_at = timezone.now() - timedelta(seconds=1)
    session.save(update_fields=["expires_at"])

    with pytest.raises(ValidationError, match="expired"):
        consume_platform_impersonation_session(raw_token=raw_token, tenant=tenant)


def test_consume_platform_impersonation_session_marks_session_consumed_and_truncates_host(mocker):
    platform_admin, tenant, target_user = _make_base_objects()
    mocker.patch("secrets.token_urlsafe", return_value="valid-consume-token")
    session, raw_token = create_platform_impersonation_session(
        platform_admin=platform_admin,
        tenant=tenant,
        target_user=target_user,
    )

    consumed = consume_platform_impersonation_session(raw_token=raw_token, tenant=tenant, consumed_host="h" * 500)

    consumed.refresh_from_db()
    assert consumed.pk == session.pk
    assert consumed.consumed_at is not None
    assert consumed.consumed_host == ("h" * 255)


def test_stop_platform_impersonation_session_is_noop_for_empty_session_id():
    stop_platform_impersonation_session(None)

    assert PlatformImpersonationSession.objects.count() == 0


def test_stop_platform_impersonation_session_sets_stopped_at_once(mocker):
    platform_admin, tenant, target_user = _make_base_objects()
    mocker.patch("secrets.token_urlsafe", return_value="stop-token")
    session, _raw_token = create_platform_impersonation_session(
        platform_admin=platform_admin,
        tenant=tenant,
        target_user=target_user,
    )

    stop_platform_impersonation_session(session.pk)
    first_stopped_at = PlatformImpersonationSession.objects.get(pk=session.pk).stopped_at
    stop_platform_impersonation_session(session.pk)
    second_stopped_at = PlatformImpersonationSession.objects.get(pk=session.pk).stopped_at

    assert first_stopped_at is not None
    assert second_stopped_at == first_stopped_at


def test_get_impersonation_redirect_url_returns_admin_url_for_admin_destination():
    session = SimpleNamespace(destination=IMPERSONATION_DESTINATION_DJANGO_ADMIN, tenant=None)

    assert get_impersonation_redirect_url(session) == "/admin/"


def test_get_impersonation_redirect_url_builds_dashboard_redirect_for_default_destination(mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme")
    session = SimpleNamespace(destination=IMPERSONATION_DESTINATION_DASHBOARD, tenant=tenant)
    mock_redirect = mocker.patch(
        "tenants.impersonation.build_post_login_redirect_url", return_value="https://acme.example.com/en/dashboard/"
    )

    url = get_impersonation_redirect_url(session)

    assert url == "https://acme.example.com/en/dashboard/"
    mock_redirect.assert_called_once_with(tenant, use_api_host=True)


def test_get_impersonation_stop_payload_returns_none_when_not_active():
    request = SimpleNamespace(session={})

    assert get_impersonation_stop_payload(request) is None


@override_settings(SITE_URL_FALLBACK="https://platform.example.com")
def test_get_impersonation_stop_payload_returns_full_payload_when_active():
    request = SimpleNamespace(
        session={
            "platform_impersonation_active": True,
            "platform_impersonation_session_id": 77,
            "platform_impersonation_admin_email": "admin@example.com",
            "platform_impersonation_admin_name": "Platform Admin",
            "platform_impersonation_target_username": "target-user",
            "platform_impersonation_target_role": "ADMIN",
            "platform_impersonation_started_at": "2026-01-01T00:00:00Z",
        }
    )

    payload = get_impersonation_stop_payload(request)

    assert payload == {
        "active": True,
        "session_id": 77,
        "platform_admin_email": "admin@example.com",
        "platform_admin_name": "Platform Admin",
        "target_username": "target-user",
        "target_role": "ADMIN",
        "started_at": "2026-01-01T00:00:00Z",
        "stop_url": "/platform-admin/impersonate/stop/",
        "return_url": "https://platform.example.com/platform-admin/",
    }
