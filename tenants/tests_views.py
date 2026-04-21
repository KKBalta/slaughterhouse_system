from contextlib import nullcontext

import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import Http404, HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import reverse

from tenants.models import Client, Domain, PlatformAdmin, TenantRegistrationRequest
from tenants.views import (
    PlatformAdminLoginView,
    platform_admin_dashboard,
    tenant_company_settings_view,
    tenant_create_superuser,
    tenant_hard_delete,
    tenant_impersonate,
    tenant_impersonate_identifier,
    tenant_impersonate_user,
    tenant_registration_approve,
    tenant_registration_reject,
    toggle_tenant_active,
)
from users.models import User

pytestmark = pytest.mark.django_db


def _request(method, path, user, data=None):
    factory = RequestFactory()
    request = getattr(factory, method.lower())(path, data or {})
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def _capture_render(mocker, target="tenants.views.render"):
    captured = {}

    def fake_render(request, template_name, context=None, *args, **kwargs):
        captured["template_name"] = template_name
        captured["context"] = context or {}
        return HttpResponse(status=kwargs.get("status") or 200)

    mocker.patch(target, side_effect=fake_render)
    return captured


@pytest.fixture
def platform_admin():
    admin = PlatformAdmin.objects.create(email="platform@example.com", name="Platform Admin")
    admin.set_password("testpass123")
    admin.save()
    return admin


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_platform_admin_setup_redirects_when_setup_is_complete(client):
    PlatformAdmin.objects.create(email="existing@example.com", name="Existing Admin")

    response = client.get(reverse("platform_admin_setup"))

    assert response.status_code == 302
    assert response.url == reverse("platform_admin_login")


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_platform_admin_setup_creates_account_and_redirects(client):
    response = client.post(
        reverse("platform_admin_setup"),
        data={
            "name": "First Admin",
            "email": "first@example.com",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("platform_admin_login")
    created = PlatformAdmin.objects.get(email="first@example.com")
    assert created.name == "First Admin"
    assert created.check_password("StrongPass123!") is True


@override_settings(
    ROOT_URLCONF="config.urls_public",
    USE_MULTITENANT=True,
    TENANT_BASE_DOMAIN="localhost",
    SITE_URL_FALLBACK="http://fallback.test",
)
def test_platform_admin_login_redirects_authenticated_platform_admin(platform_admin):
    request = _request("get", "/platform-admin/login/", platform_admin)

    response = PlatformAdminLoginView.as_view()(request)

    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")


@override_settings(
    ROOT_URLCONF="config.urls_public",
    USE_MULTITENANT=True,
    TENANT_BASE_DOMAIN="localhost",
    SITE_URL_FALLBACK="http://fallback.test",
)
def test_platform_admin_dashboard_renders_tenants_and_pending_registrations(platform_admin, mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme")
    Domain.objects.create(domain="acme.localhost", tenant=tenant, is_primary=True)
    pending = TenantRegistrationRequest.objects.create(
        company_name="Pending Co",
        derived_schema_name="pending-co",
        owner_email="pending@example.com",
        owner_password_hash="hashed-password",
    )
    captured = _capture_render(mocker)
    row = type(
        "TenantRow",
        (),
        {
            "tenant": tenant,
            "app_url": "http://acme.localhost:8000",
            "stats": type(
                "Stats",
                (),
                {"active_users": 2, "recent_orders_7d": 1, "recent_animals_7d": 3, "latest_activity_at": None},
            )(),
            "health": type("Health", (), {"tone": "healthy"})(),
        },
    )()
    summary = type("Summary", (), {"total_tenants": 1, "pending_registrations": 1})()
    mocker.patch("tenants.views.build_tenant_dashboard_row", return_value=row)
    mocker.patch("tenants.views.build_platform_dashboard_summary", return_value=summary)
    request = _request("get", "/platform-admin/", platform_admin)

    response = platform_admin_dashboard(request)

    assert response.status_code == 200
    assert captured["template_name"] == "tenants/platform_admin/dashboard.html"
    assert list(captured["context"]["pending_registrations"]) == [pending]
    tenant_rows = captured["context"]["tenant_rows"]
    assert len(tenant_rows) == 1
    assert tenant_rows[0].tenant == tenant
    assert tenant_rows[0].app_url == "http://acme.localhost:8000"
    assert captured["context"]["dashboard_summary"] == summary


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_platform_admin_dashboard_post_provisions_tenant(platform_admin, mocker):
    mock_provision = mocker.patch("tenants.views.provision_tenant")
    request = _request(
        "post",
        "/platform-admin/",
        platform_admin,
        {
            "_action": "create_tenant",
            "schema_name": "acme",
            "name": "Acme",
            "company_name": "Acme Meat",
            "contact_email": "owner@example.com",
        },
    )

    response = platform_admin_dashboard(request)

    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")
    mock_provision.assert_called_once_with(
        schema_name="acme",
        name="Acme",
        company_name="Acme Meat",
        contact_email="owner@example.com",
        domain_name="acme.localhost",
    )


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_tenant_registration_approve_handles_success_and_validation_error(platform_admin, mocker):
    registration = TenantRegistrationRequest.objects.create(
        company_name="Approve Me",
        derived_schema_name="approve-me",
        owner_email="approve@example.com",
        owner_password_hash="hashed-password",
    )

    mock_approve = mocker.patch("tenants.views.approve_registration")
    request = _request("post", "/platform-admin/registrations/approve/", platform_admin)
    response = tenant_registration_approve(request, registration.id)
    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")
    mock_approve.assert_called_once_with(registration, platform_admin)

    mock_approve.side_effect = ValidationError("boom")
    request = _request("post", "/platform-admin/registrations/approve/", platform_admin)
    response = tenant_registration_approve(request, registration.id)

    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")
    assert mock_approve.call_count == 2


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_tenant_registration_reject_handles_success_and_validation_error(platform_admin, mocker):
    registration = TenantRegistrationRequest.objects.create(
        company_name="Reject Me",
        derived_schema_name="reject-me",
        owner_email="reject@example.com",
        owner_password_hash="hashed-password",
    )
    mock_reject = mocker.patch("tenants.views.reject_registration")

    request = _request(
        "post",
        "/platform-admin/registrations/reject/",
        platform_admin,
        {"rejection_reason": "Missing documents"},
    )
    response = tenant_registration_reject(request, registration.id)
    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")
    mock_reject.assert_called_once_with(registration, platform_admin, reason="Missing documents")

    registration = TenantRegistrationRequest.objects.create(
        company_name="Reject Error",
        derived_schema_name="reject-error",
        owner_email="reject-error@example.com",
        owner_password_hash="hashed-password",
    )
    mock_reject.side_effect = ValidationError("boom")
    request = _request("post", "/platform-admin/registrations/reject/", platform_admin, {"rejection_reason": "Nope"})
    response = tenant_registration_reject(request, registration.id)

    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")
    assert mock_reject.call_count == 2


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_tenant_create_superuser_get_renders_existing_users(platform_admin, mocker, admin_user):
    tenant = Client.objects.create(schema_name="acme", name="Acme")
    Domain.objects.create(domain="acme.localhost", tenant=tenant, is_primary=True)
    captured = _capture_render(mocker)
    mocker.patch("tenants.views.tenant_context", return_value=nullcontext())
    request = _request("get", "/platform-admin/tenants/acme/superuser/", platform_admin)

    response = tenant_create_superuser(request, tenant.schema_name)

    assert response.status_code == 200
    assert captured["template_name"] == "tenants/platform_admin/tenant_superuser.html"
    assert captured["context"]["tenant"] == tenant
    assert captured["context"]["domain_hint"] == "acme.localhost"
    assert captured["context"]["tenant_login_url"] == "http://acme.localhost:8000/en/login/"
    assert any(row["username"] == admin_user.username for row in captured["context"]["existing_users"])


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_tenant_create_superuser_post_duplicate_username_and_email(platform_admin, mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme")
    Domain.objects.create(domain="acme.localhost", tenant=tenant, is_primary=True)
    existing = User.objects.create_user(
        username="duplicate",
        email="duplicate@example.com",
        password="testpass123",
        role=User.Role.ADMIN,
    )
    mocker.patch("tenants.views.tenant_context", return_value=nullcontext())

    captured = _capture_render(mocker)
    request = _request(
        "post",
        "/platform-admin/tenants/acme/superuser/",
        platform_admin,
        {
            "username": existing.username,
            "email": "new@example.com",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
            "account_kind": "app_admin",
        },
    )
    response = tenant_create_superuser(request, tenant.schema_name)
    assert response.status_code == 200
    assert "username" in captured["context"]["form"].errors

    captured = _capture_render(mocker)
    request = _request(
        "post",
        "/platform-admin/tenants/acme/superuser/",
        platform_admin,
        {
            "username": "unique-user",
            "email": existing.email,
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
            "account_kind": "app_admin",
        },
    )
    response = tenant_create_superuser(request, tenant.schema_name)
    assert response.status_code == 200
    assert "email" in captured["context"]["form"].errors


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_tenant_create_superuser_post_handles_integrity_error(platform_admin, mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme")
    Domain.objects.create(domain="acme.localhost", tenant=tenant, is_primary=True)
    captured = _capture_render(mocker)
    mocker.patch("tenants.views.tenant_context", return_value=nullcontext())
    mocker.patch.object(User.objects, "create_user", side_effect=IntegrityError("duplicate"))
    request = _request(
        "post",
        "/platform-admin/tenants/acme/superuser/",
        platform_admin,
        {
            "username": "fresh-user",
            "email": "fresh@example.com",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
            "account_kind": "app_admin",
        },
    )

    response = tenant_create_superuser(request, tenant.schema_name)

    assert response.status_code == 200
    assert captured["context"]["form"].non_field_errors()


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_tenant_create_superuser_post_success_creates_user_and_redirects(platform_admin, mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme")
    Domain.objects.create(domain="acme.localhost", tenant=tenant, is_primary=True)
    mocker.patch("tenants.views.tenant_context", return_value=nullcontext())
    request = _request(
        "post",
        "/platform-admin/tenants/acme/superuser/",
        platform_admin,
        {
            "username": "tenant-admin",
            "email": "tenant-admin@example.com",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
            "account_kind": "django_superuser",
        },
    )

    response = tenant_create_superuser(request, tenant.schema_name)

    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")
    created = User.objects.get(username="tenant-admin")
    assert created.role == User.Role.ADMIN
    assert created.is_staff is True
    assert created.is_superuser is True


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_tenant_hard_delete_handles_confirmation_validation_and_success(platform_admin, mocker):
    request = _request("post", "/platform-admin/tenants/acme/delete/", platform_admin, {"confirm_schema": "wrong"})
    response = tenant_hard_delete(request, "acme")
    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")

    mock_delete = mocker.patch("tenants.views.hard_delete_tenant", side_effect=ValidationError("nope"))
    request = _request("post", "/platform-admin/tenants/acme/delete/", platform_admin, {"confirm_schema": "acme"})
    response = tenant_hard_delete(request, "acme")
    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")
    mock_delete.assert_called_once_with(schema_name="acme")

    mock_delete = mocker.patch("tenants.views.hard_delete_tenant")
    request = _request("post", "/platform-admin/tenants/acme/delete/", platform_admin, {"confirm_schema": "acme"})
    response = tenant_hard_delete(request, "acme")
    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")
    mock_delete.assert_called_once_with(schema_name="acme")


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_toggle_tenant_active_flips_state(platform_admin, mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme", is_active=True)
    request = _request("post", "/platform-admin/tenants/acme/toggle/", platform_admin)
    mocker.patch("django_tenants.models.schema_exists", return_value=True)

    response = toggle_tenant_active(request, tenant.schema_name)

    tenant.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")
    assert tenant.is_active is False


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_tenant_impersonate_redirects_to_bootstrap(platform_admin, mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme")
    redirect_response = HttpResponse(status=302)
    redirect_response["Location"] = "http://acme.localhost:8000/api/v1/auth/session-bootstrap/?token=test"
    mock_start = mocker.patch("tenants.views.start_platform_impersonation", return_value=redirect_response)
    request = _request("post", "/platform-admin/tenants/acme/impersonate/god_mode/", platform_admin)

    response = tenant_impersonate(request, tenant.schema_name, "god_mode")

    assert response.status_code == 302
    assert response["Location"].startswith("http://acme.localhost:8000/api/v1/auth/session-bootstrap/")
    mock_start.assert_called_once_with(
        request,
        tenant=tenant,
        platform_admin=platform_admin,
        mode="god_mode",
    )


@override_settings(USE_MULTITENANT=False)
def test_tenant_company_settings_view_404s_when_multitenant_disabled(admin_user):
    request = _request("get", "/en/company-settings/", admin_user)
    request.tenant = Client.objects.create(schema_name="acme", name="Acme")

    with pytest.raises(Http404):
        tenant_company_settings_view(request)


@override_settings(USE_MULTITENANT=True)
def test_tenant_company_settings_view_enforces_tenant_and_permissions(admin_user, user_factory):
    request = _request("get", "/en/company-settings/", admin_user)
    request.tenant = None

    with pytest.raises(Http404):
        tenant_company_settings_view(request)

    request = _request("get", "/en/company-settings/", user_factory(role=User.Role.CLIENT))
    request.tenant = Client.objects.create(schema_name="acme", name="Acme")
    with pytest.raises(PermissionDenied):
        tenant_company_settings_view(request)


@override_settings(USE_MULTITENANT=True)
def test_tenant_company_settings_view_get_and_post(admin_user, mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme", company_name="Old Co")
    captured = _capture_render(mocker)
    mocker.patch("django_tenants.utils.get_public_schema_name", return_value="public")
    mocker.patch("django_tenants.utils.schema_context", return_value=nullcontext())
    mocker.patch("django_tenants.models.schema_exists", return_value=True)

    request = _request("get", reverse("tenant_company_settings"), admin_user)
    request.tenant = tenant
    response = tenant_company_settings_view(request)

    assert response.status_code == 200
    assert captured["template_name"] == "tenants/tenant_company_settings.html"
    assert captured["context"]["form"].instance == tenant

    request = _request(
        "post",
        reverse("tenant_company_settings"),
        admin_user,
        {
            "name": "Acme",
            "company_name": "New Co",
            "company_full_name": "New Co Ltd",
            "company_address": "123 New Street",
            "registered_province_plaka": "06",
            "license_no": "L-1",
            "operation_no": "O-1",
            "contact_email": "info@example.com",
            "contact_phone_area_code": "+90",
            "contact_phone": "5551112233",
            "printer_turkish_mode": "unicode",
        },
    )
    request.tenant = tenant
    response = tenant_company_settings_view(request)

    tenant.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("tenant_company_settings")
    assert tenant.company_name == "New Co"
    assert tenant.registered_province_plaka == "06"
    assert tenant.contact_email == "info@example.com"
    assert tenant.contact_phone == "+905551112233"


# --- Impersonation: view + service tests ---------------------------------


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_tenant_impersonate_user_rejects_non_integer_user_id(platform_admin, mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme")
    mock_start = mocker.patch("tenants.views.start_platform_impersonation_for_user")
    request = _request(
        "post",
        "/platform-admin/tenants/acme/impersonate-user/",
        platform_admin,
        {"user_id": "not-a-number"},
    )

    response = tenant_impersonate_user(request, tenant.schema_name)

    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")
    mock_start.assert_not_called()


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_tenant_impersonate_user_handles_unresolved_user(platform_admin, mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme")
    mocker.patch(
        "tenants.views.start_platform_impersonation_for_user",
        side_effect=ValueError("No active tenant user matched the selection."),
    )
    request = _request(
        "post",
        "/platform-admin/tenants/acme/impersonate-user/",
        platform_admin,
        {"user_id": "999"},
    )

    response = tenant_impersonate_user(request, tenant.schema_name)

    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_tenant_impersonate_user_requires_platform_admin(user_factory, mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme")
    mock_start = mocker.patch("tenants.views.start_platform_impersonation_for_user")
    mocker.patch("tenants.views.logout")
    non_admin = user_factory(role=User.Role.ADMIN)
    request = _request(
        "post",
        "/platform-admin/tenants/acme/impersonate-user/",
        non_admin,
        {"user_id": "1"},
    )

    response = tenant_impersonate_user(request, tenant.schema_name)

    assert response.status_code == 302
    assert response.url == "/platform-admin/login/"
    mock_start.assert_not_called()


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_tenant_impersonate_identifier_rejects_empty_input(platform_admin, mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme")
    mock_start = mocker.patch("tenants.views.start_platform_impersonation_for_identifier")
    request = _request(
        "post",
        "/platform-admin/tenants/acme/impersonate-lookup/",
        platform_admin,
        {"identifier": "   "},
    )

    response = tenant_impersonate_identifier(request, tenant.schema_name)

    assert response.status_code == 302
    assert response.url == reverse("platform_admin_dashboard")
    mock_start.assert_not_called()


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True, TENANT_BASE_DOMAIN="localhost")
def test_tenant_impersonate_identifier_forwards_trimmed_value(platform_admin, mocker):
    tenant = Client.objects.create(schema_name="acme", name="Acme")
    redirect_response = HttpResponse(status=302)
    redirect_response["Location"] = "http://acme.localhost:8000/api/v1/auth/session-bootstrap/?token=test"
    mock_start = mocker.patch(
        "tenants.views.start_platform_impersonation_for_identifier",
        return_value=redirect_response,
    )
    request = _request(
        "post",
        "/platform-admin/tenants/acme/impersonate-lookup/",
        platform_admin,
        {"identifier": "  customer@example.com  "},
    )

    response = tenant_impersonate_identifier(request, tenant.schema_name)

    assert response.status_code == 302
    mock_start.assert_called_once_with(
        request,
        tenant=tenant,
        platform_admin=platform_admin,
        identifier="customer@example.com",
    )


def test_build_impersonation_targets_excludes_non_staff_from_staff_targets(user_factory):
    from tenants.dashboard_services import _build_impersonation_targets

    owner = user_factory(role=User.Role.OWNER, is_active=True)
    manager = user_factory(role=User.Role.MANAGER, is_active=True)
    client_user = user_factory(role=User.Role.CLIENT, is_active=True)
    walkin = user_factory(role=User.Role.WALKIN, is_active=True)
    inactive_admin = user_factory(role=User.Role.ADMIN, is_active=False)

    _, staff_targets = _build_impersonation_targets([owner, manager, client_user, walkin, inactive_admin])

    roles = {t.role for t in staff_targets}
    assert "CLIENT" not in roles
    assert "WALKIN" not in roles
    assert roles <= {"OWNER", "ADMIN", "MANAGER", "OPERATOR"}
    assert {t.user_id for t in staff_targets} == {owner.pk, manager.pk}


def test_as_target_derives_client_mode_for_client_role(user_factory):
    from tenants.dashboard_services import _as_target

    client_user = user_factory(role=User.Role.CLIENT, is_active=True)

    target = _as_target(client_user)

    assert target is not None
    assert target.mode == "client"
    assert target.role == "CLIENT"
    assert target.user_id == client_user.pk


def test_fetch_active_tenant_user_normalizes_phone_needle(user_factory, mocker):
    from tenants.dashboard_services import _fetch_active_tenant_user

    tenant = Client.objects.create(schema_name="acme-phone", name="Acme Phone")
    client_user = user_factory(
        role=User.Role.WALKIN,
        is_active=True,
        phone_number="+905551234567",
    )
    mocker.patch("tenants.dashboard_services.tenant_context", return_value=nullcontext())

    found = _fetch_active_tenant_user(tenant, identifier="05551234567")

    assert found is not None
    assert found.pk == client_user.pk


def test_fetch_active_tenant_user_returns_none_for_inactive_user(user_factory, mocker):
    from tenants.dashboard_services import _fetch_active_tenant_user

    tenant = Client.objects.create(schema_name="acme-inactive", name="Acme Inactive")
    inactive = user_factory(role=User.Role.CLIENT, is_active=False, email="gone@example.com")
    mocker.patch("tenants.dashboard_services.tenant_context", return_value=nullcontext())

    found = _fetch_active_tenant_user(tenant, user_id=inactive.pk)
    assert found is None

    found_by_email = _fetch_active_tenant_user(tenant, identifier="gone@example.com")
    assert found_by_email is None
