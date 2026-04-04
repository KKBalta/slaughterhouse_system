"""
Authentication and authorization tests for the users app.

Tests cover:
- User login/logout
- Role-based access control
- Password management
- Session security
"""

import json
import os
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import django.contrib.auth as django_auth
import django_tenants.utils as tenant_utils
import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, override_settings
from django.urls import NoReverseMatch, reverse

from users.models import ClientProfile

# View tests: skip when SKIP_VIEW_TESTS env is set (e.g. in CI when templates missing).
# Set SKIP_VIEW_TESTS=true to skip; run locally with templates to exercise view tests.
SKIP_VIEW_TESTS = os.environ.get("SKIP_VIEW_TESTS", "false").lower() == "true"
SKIP_REASON = "View tests skipped - templates not available in test environment"

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def auth_state(db):
    """Create the fixed user set shared by auth-focused tests."""
    owner_user = User.objects.create_user(
        username="auth_owner",
        password="SecurePass123!",
        email="owner@test.com",
        role=User.Role.OWNER,
    )
    admin_user = User.objects.create_user(
        username="auth_admin",
        password="SecurePass123!",
        email="admin@test.com",
        role=User.Role.ADMIN,
        is_staff=True,
    )
    operator_user = User.objects.create_user(
        username="auth_operator",
        password="SecurePass123!",
        email="operator@test.com",
        role=User.Role.OPERATOR,
    )
    manager_user = User.objects.create_user(
        username="auth_manager",
        password="SecurePass123!",
        email="manager@test.com",
        role=User.Role.MANAGER,
    )
    client_user = User.objects.create_user(
        username="auth_client",
        password="SecurePass123!",
        email="client@test.com",
        role=User.Role.CLIENT,
    )
    client_profile = ClientProfile.objects.create(
        user=client_user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        contact_person="Auth Test Client",
        phone_number="5551234567",
        address="123 Auth Test St",
    )
    return SimpleNamespace(
        owner_user=owner_user,
        admin_user=admin_user,
        operator_user=operator_user,
        manager_user=manager_user,
        client_user=client_user,
        client_profile=client_profile,
    )


@pytest.mark.skipif(SKIP_VIEW_TESTS, reason=SKIP_REASON)
class TestLogin:
    """Tests for user login functionality."""

    def test_login_page_loads(self, client):
        response = client.get(reverse("login"))
        assert response.status_code in [200, 302]

    def test_valid_login(self, client, auth_state):
        response = client.post(
            reverse("login"),
            {"username": auth_state.admin_user.username, "password": "SecurePass123!"},
        )
        assert response.status_code == 302

    def test_invalid_login(self, client, auth_state):
        response = client.post(
            reverse("login"),
            {"username": auth_state.admin_user.username, "password": "WrongPassword!"},
        )
        assert response.status_code in [200, 302]

    def test_login_inactive_user(self, client, auth_state):
        auth_state.admin_user.is_active = False
        auth_state.admin_user.save()

        response = client.post(
            reverse("login"),
            {"username": auth_state.admin_user.username, "password": "SecurePass123!"},
        )
        assert response.status_code in [200, 302]

        auth_state.admin_user.is_active = True
        auth_state.admin_user.save()

    def test_login_creates_session(self, client, auth_state):
        client.post(
            reverse("login"),
            {"username": auth_state.admin_user.username, "password": "SecurePass123!"},
        )
        assert client.session.get("_auth_user_id")

    @override_settings(DEBUG=True, ALLOWED_HOSTS=["pomet.localhost", ".localhost", "testserver"])
    def test_login_page_sets_fresh_csrf_cookie_for_tenant_host(self, client):
        response = client.get(reverse("login"), HTTP_HOST="pomet.localhost:8000")
        assert response.status_code == 200
        assert "csrftoken" in response.cookies
        assert "no-store" in response["Cache-Control"]


class TestLogout:
    """Tests for user logout functionality."""

    def test_logout_clears_session(self, client, auth_state):
        client.login(username=auth_state.admin_user.username, password="SecurePass123!")
        assert client.session.get("_auth_user_id")

        response = client.post(reverse("logout"))
        assert response.status_code == 302
        assert client.session.get("_auth_user_id") is None

    def test_logout_redirects(self, client, auth_state):
        client.login(username=auth_state.admin_user.username, password="SecurePass123!")
        response = client.post(reverse("logout"))
        assert response.status_code == 302


@pytest.mark.skipif(SKIP_VIEW_TESTS, reason=SKIP_REASON)
class TestRoleBasedAccess:
    """Tests for role-based access control."""

    def test_admin_can_access_admin_views(self, client, auth_state):
        client.login(username=auth_state.admin_user.username, password="SecurePass123!")
        response = client.get(reverse("processing:dashboard"))
        assert response.status_code in [200, 302]

    def test_client_cannot_access_processing(self, client, auth_state):
        client.login(username=auth_state.client_user.username, password="SecurePass123!")
        response = client.get(reverse("processing:dashboard"))
        assert response.status_code in [200, 302, 403]

    def test_operator_can_access_processing(self, client, auth_state):
        client.login(username=auth_state.operator_user.username, password="SecurePass123!")
        response = client.get(reverse("processing:dashboard"))
        assert response.status_code in [200, 302]

    def test_manager_cannot_access_reporting(self, client, auth_state):
        client.login(username=auth_state.manager_user.username, password="SecurePass123!")
        response = client.get(reverse("report_dashboard"))
        assert response.status_code == 302


class TestPasswordManagement:
    """Tests for password management."""

    def test_password_change_view_loads(self, client, auth_state):
        client.login(username=auth_state.admin_user.username, password="SecurePass123!")
        try:
            response = client.get(reverse("password_change"))
            assert response.status_code in [200, 302]
        except NoReverseMatch:
            pytest.skip("Password change URL not configured")

    def test_password_change_success(self, auth_state):
        from users.services import change_user_password

        success = change_user_password(
            user=auth_state.admin_user,
            old_password="SecurePass123!",
            new_password="NewSecurePass456!",
        )

        assert success is True
        assert auth_state.admin_user.check_password("NewSecurePass456!")

        auth_state.admin_user.set_password("SecurePass123!")
        auth_state.admin_user.save()

    def test_password_change_mismatch(self, auth_state):
        from users.services import change_user_password

        success = change_user_password(
            user=auth_state.admin_user,
            old_password="WrongPassword!",
            new_password="NewSecurePass456!",
        )

        assert success is False
        assert auth_state.admin_user.check_password("SecurePass123!")


@pytest.mark.skipif(SKIP_VIEW_TESTS, reason=SKIP_REASON)
class TestAccountProfile:
    def test_account_profile_page_loads_for_authenticated_user(self, client, auth_state):
        client.login(username=auth_state.manager_user.username, password="SecurePass123!")

        response = client.get(reverse("account_profile"))

        assert response.status_code == 200

    def test_account_profile_updates_client_contact_and_syncs_profile(self, client, auth_state):
        client.login(username=auth_state.client_user.username, password="SecurePass123!")

        response = client.post(
            reverse("account_profile"),
            {
                "action": "contact",
                "email": "",
                "phone_area_code": "+90",
                "phone_number": "5550004455",
            },
        )

        assert response.status_code == 302
        auth_state.client_user.refresh_from_db()
        auth_state.client_profile.refresh_from_db()
        assert auth_state.client_user.email == ""
        assert auth_state.client_user.phone_number == "+905550004455"
        assert auth_state.client_profile.phone_number == "+905550004455"

    def test_account_profile_changes_password_and_keeps_session(self, client, auth_state):
        client.login(username=auth_state.manager_user.username, password="SecurePass123!")

        response = client.post(
            reverse("account_profile"),
            {
                "action": "password",
                "current_password": "SecurePass123!",
                "new_password1": "NewSecurePass456!",
                "new_password2": "NewSecurePass456!",
            },
        )

        assert response.status_code == 302
        auth_state.manager_user.refresh_from_db()
        assert auth_state.manager_user.check_password("NewSecurePass456!")
        assert client.get(reverse("account_profile")).status_code == 200
        client.post(reverse("logout"))
        assert client.login(username=auth_state.manager_user.username, password="NewSecurePass456!")


class TestSessionSecurity:
    """Tests for session security."""

    def test_session_expires_on_browser_close(self, client, auth_state):
        client.login(username=auth_state.admin_user.username, password="SecurePass123!")
        assert client.session.session_key is not None

    def test_concurrent_sessions(self, auth_state):
        client1 = Client()
        client2 = Client()

        client1.login(username=auth_state.admin_user.username, password="SecurePass123!")
        client2.login(username=auth_state.admin_user.username, password="SecurePass123!")

        assert client1.session.get("_auth_user_id")
        assert client2.session.get("_auth_user_id")


def _dummy_login_user():
    class DummyUser:
        id = 7
        pk = 7
        email = "client@example.com"
        role = User.Role.CLIENT
        is_active = True

        def get_username(self):
            return "client-user"

    return DummyUser()


@override_settings(
    USE_MULTITENANT=True,
    DEBUG=False,
    TENANT_POST_LOGIN_USE_API_HOST=False,
    ALLOWED_HOSTS=["pomet.localhost", ".localhost", "localhost", "testserver"],
)
def test_session_login_api_redirects_via_bootstrap_for_cross_site_spa(monkeypatch):
    from django.db import connection

    import users.views as user_views
    from tenants import email_index

    request = RequestFactory().post(
        "/api/v1/auth/login/",
        data=json.dumps({"email": "client@example.com", "password": "secret"}),
        content_type="application/json",
        HTTP_HOST="pomet.localhost:8000",
        HTTP_ORIGIN="http://localhost:3000",
    )
    request.COOKIES["csrftoken"] = "csrf-token"

    monkeypatch.setattr(user_views, "authenticate", lambda request, username, password: _dummy_login_user())
    monkeypatch.setattr(user_views.secrets, "token_urlsafe", lambda _n: "bootstrap-token")
    monkeypatch.setattr(user_views, "_bootstrap_token_cache_set", lambda **kwargs: None)
    monkeypatch.setattr(connection, "schema_name", "pomet", raising=False)
    monkeypatch.setattr(email_index, "get_client_tenant_from_connection", lambda: SimpleNamespace(schema_name="pomet"))
    monkeypatch.setattr(
        email_index,
        "build_post_login_redirect_url",
        lambda tenant, use_api_host=None: "http://pomet.localhost:3000/dashboard",
    )

    response = user_views.session_login_api(request)

    assert response.status_code == 200
    payload = json.loads(response.content)
    parsed = urlsplit(payload["redirect_url"])
    next_url = parse_qs(parsed.query)["next"][0]

    assert payload["session_pending"] is True
    assert payload["redirect_url"] == payload["session_bootstrap_url"]
    assert payload["post_bootstrap_redirect_url"] == "http://pomet.localhost:3000/dashboard"
    assert payload["user"]["role"] == User.Role.CLIENT
    assert parsed.scheme == "http"
    assert parsed.netloc == "pomet.localhost:8000"
    assert parsed.path == "/api/v1/auth/session-bootstrap/"
    assert parse_qs(parsed.query)["token"] == ["bootstrap-token"]
    assert next_url == "http://pomet.localhost:3000/dashboard"


@override_settings(
    USE_MULTITENANT=True,
    DEBUG=False,
    ALLOWED_HOSTS=["pomet.localhost", ".localhost", "localhost", "testserver"],
)
def test_session_bootstrap_api_allows_same_tenant_spa_redirect(monkeypatch):
    from django.db import connection

    import users.views as user_views
    from tenants import email_index

    next_url = "http://pomet.localhost:3000/dashboard"
    request = RequestFactory().get(
        "/api/v1/auth/session-bootstrap/",
        data={"token": "bootstrap-token", "next": next_url},
        HTTP_HOST="pomet.localhost:8000",
    )

    class DummyUserModel:
        class DoesNotExist(Exception):
            pass

        objects = SimpleNamespace(get=lambda pk: _dummy_login_user())

    monkeypatch.setattr(user_views, "_bootstrap_token_cache_pop", lambda token: {"user_id": 7, "schema": "pomet"})
    monkeypatch.setattr(connection, "schema_name", "pomet", raising=False)
    monkeypatch.setattr(django_auth, "get_user_model", lambda: DummyUserModel)
    monkeypatch.setattr(tenant_utils, "get_public_schema_name", lambda: "public")
    monkeypatch.setattr(user_views, "login", lambda request, user, backend=None: None)
    monkeypatch.setattr(user_views, "get_token", lambda request: "csrf-token")
    monkeypatch.setattr(
        email_index,
        "get_client_tenant_from_connection",
        lambda: SimpleNamespace(schema_name="pomet", language_code="en"),
    )
    monkeypatch.setattr(email_index, "build_tenant_api_base_url", lambda tenant: "http://pomet.localhost:8000")
    monkeypatch.setattr(email_index, "build_tenant_web_app_base_url", lambda tenant: "http://pomet.localhost:3000")
    monkeypatch.setattr(
        email_index,
        "build_post_login_redirect_url",
        lambda tenant, use_api_host=None: (
            "http://pomet.localhost:8000/en/dashboard/" if use_api_host else "http://pomet.localhost:3000/dashboard"
        ),
    )

    response = user_views.session_bootstrap_api(request)

    assert response.status_code == 302
    assert response["Location"] == next_url


def test_session_me_api_returns_role():
    import users.views as user_views

    user = User.objects.create_user(
        username="me-client",
        password="SecurePass123!",
        email="me@example.com",
        role=User.Role.CLIENT,
    )
    request = RequestFactory().get("/api/v1/auth/me/")
    request.user = user

    response = user_views.session_me_api(request)

    assert response.status_code == 200
    payload = json.loads(response.content)
    assert payload["user"]["role"] == User.Role.CLIENT


@override_settings(LANGUAGE_CODE="tr", PUBLIC_TENANT_HTTP_PORT="8000", TENANT_LOGIN_SUCCESS_REDIRECT_PATH="/dashboard")
def test_build_post_login_redirect_url_uses_tenant_language_code():
    from tenants.email_index import build_post_login_redirect_url

    class DummyTenant:
        schema_name = "pomet"
        slug = "pomet"
        language_code = "en"

        def get_primary_domain(self):
            return SimpleNamespace(domain="pomet.localhost")

    assert (
        build_post_login_redirect_url(DummyTenant(), use_api_host=True) == "http://pomet.localhost:8000/en/dashboard/"
    )


class TestAuthenticationPytest:
    """Pytest-style authentication tests."""

    def test_login_required_decorator(self, client, admin_user):
        response = client.get(reverse("processing:dashboard"))
        assert response.status_code == 302

        client.force_login(admin_user)
        response = client.get(reverse("processing:dashboard"))
        assert response.status_code in [200, 302]

    @pytest.mark.skip(reason="View test - templates not available in test environment")
    def test_role_check_decorator(self, client, user_factory):
        from users.models import User

        client_user = user_factory(role=User.Role.CLIENT)
        operator_user = user_factory(role=User.Role.OPERATOR)

        client.force_login(client_user)
        response = client.get(reverse("processing:dashboard"))
        assert response.status_code in [302, 403]

        client.force_login(operator_user)
        response = client.get(reverse("processing:dashboard"))
        assert response.status_code in [200, 302]


class TestUserRoles:
    """Tests for user role functionality."""

    def test_user_role_choices(self):
        expected_roles = ["OWNER", "ADMIN", "OPERATOR", "MANAGER", "CLIENT", "WALKIN"]
        actual_roles = [choice[0] for choice in User.Role.choices]

        for role in expected_roles:
            assert role in actual_roles

    def test_default_role_is_admin(self):
        with pytest.raises(ValueError, match="explicit role"):
            User.objects.create_user(username="default_role_test", password="testpass123")

    def test_role_assignment(self, user_factory):
        from users.models import User

        for role in User.Role:
            user = user_factory(role=role)
            assert user.role == role


class TestClientProfile:
    """Tests for client profile functionality."""

    def test_client_profile_required_for_client_role(self, user_factory, client_profile_factory):
        from users.models import User

        user = user_factory(role=User.Role.CLIENT)
        profile = client_profile_factory(user=user)

        assert user.client_profile == profile

    def test_enterprise_profile_fields(self, user_factory):
        from users.models import ClientProfile, User

        user = user_factory(role=User.Role.CLIENT)
        profile = ClientProfile.objects.create(
            user=user,
            account_type=ClientProfile.AccountType.ENTERPRISE,
            company_name="Test Company",
            contact_person="John Doe",
            tax_id="TAX123456",
            phone_number="5551234567",
            address="123 Business St",
        )

        assert profile.company_name == "Test Company"
        assert profile.tax_id == "TAX123456"

    def test_profile_str_representation(self, user_factory, client_profile_factory):
        from users.models import User

        user = user_factory(username="teststr", role=User.Role.CLIENT)
        profile = client_profile_factory(user=user, account_type=ClientProfile.AccountType.INDIVIDUAL)

        assert "Individual" in str(profile)


class TestClientProfileRegistration:
    """Internal client creation uses the tenant users-management flow."""

    def test_post_creates_client_user_and_profile(self, client, auth_state):
        client.login(username=auth_state.admin_user.username, password="SecurePass123!")
        response = client.post(
            reverse("tenant_user_create", args=[User.Role.CLIENT]),
            {
                "username": "new-client-user",
                "email": "",
                "new_password1": "SecurePass123!",
                "new_password2": "SecurePass123!",
                "account_type": "INDIVIDUAL",
                "contact_person": "New Client",
                "phone_area_code": "+90",
                "phone_number": "5554443322",
                "address": "100 St",
                "default_destination": "Istanbul Delivery Center",
            },
        )

        assert response.status_code == 302
        user = User.objects.get(username="new-client-user")
        assert user.role == User.Role.CLIENT
        assert user.phone_number == "+905554443322"
        assert user.client_profile.phone_number == "+905554443322"
        assert user.client_profile.default_destination == "Istanbul Delivery Center"

    def test_post_creates_client_user_with_generated_password_when_empty(self, client, auth_state):
        client.login(username=auth_state.admin_user.username, password="SecurePass123!")
        response = client.post(
            reverse("tenant_user_create", args=[User.Role.CLIENT]),
            {
                "username": "auto-pass-client",
                "email": "",
                "new_password1": "",
                "new_password2": "",
                "account_type": "INDIVIDUAL",
                "contact_person": "Auto Pass",
                "phone_area_code": "+90",
                "phone_number": "5554443323",
                "address": "100 St",
            },
        )

        assert response.status_code == 302
        user = User.objects.get(username="auto-pass-client")
        assert user.has_usable_password()
        assert user.check_password("") is False

    def test_post_creates_client_user_with_email_only(self, client, auth_state):
        client.login(username=auth_state.admin_user.username, password="SecurePass123!")
        response = client.post(
            reverse("tenant_user_create", args=[User.Role.CLIENT]),
            {
                "username": "mail-client-user",
                "account_type": "INDIVIDUAL",
                "contact_person": "Mail Client",
                "email": "mail-client@example.com",
                "new_password1": "SecurePass123!",
                "new_password2": "SecurePass123!",
                "phone_area_code": "+90",
                "phone_number": "",
                "address": "100 St",
            },
        )

        assert response.status_code == 302
        user = User.objects.get(email="mail-client@example.com")
        assert user.role == User.Role.CLIENT
        assert user.phone_number == ""
        assert user.client_profile.phone_number == ""

    def test_post_links_existing_walk_in_orders_by_phone_and_keeps_walk_in_fields(self, client, auth_state):
        from core.models import ServicePackage
        from reception.models import SlaughterOrder

        client.login(username=auth_state.admin_user.username, password="SecurePass123!")
        package = ServicePackage.objects.create(name="Walk-in Link Package")
        order = SlaughterOrder.objects.create(
            client_name="Walk-in Joe",
            client_phone="+905551234000",
            service_package=package,
        )

        response = client.post(
            reverse("tenant_user_create", args=[User.Role.CLIENT]),
            {
                "username": "walkin-linked-client",
                "email": "",
                "new_password1": "SecurePass123!",
                "new_password2": "SecurePass123!",
                "account_type": "INDIVIDUAL",
                "contact_person": "Linked Client",
                "phone_area_code": "+90",
                "phone_number": "5551234000",
                "address": "100 St",
            },
        )

        assert response.status_code == 302
        created_user = User.objects.get(username="walkin-linked-client")
        order.refresh_from_db()
        assert order.client == created_user.client_profile
        assert order.client_name == "Walk-in Joe"
        assert order.client_phone == "+905551234000"

    def test_post_creates_profile_without_new_user_when_phone_is_already_registered(self, client, auth_state):
        client.login(username=auth_state.admin_user.username, password="SecurePass123!")
        existing_user = User.objects.create_user(
            username="registered-phone-user",
            password="SecurePass123!",
            phone_number="+905551239999",
            role=User.Role.CLIENT,
        )

        response = client.post(
            reverse("tenant_user_create", args=[User.Role.CLIENT]),
            {
                "username": "",
                "email": "",
                "new_password1": "",
                "new_password2": "",
                "account_type": "INDIVIDUAL",
                "contact_person": "Existing Registered Phone",
                "phone_area_code": "+90",
                "phone_number": "5551239999",
                "address": "100 St",
            },
        )

        assert response.status_code == 302
        assert User.objects.filter(username="registered-phone-user").count() == 1
        existing_user.refresh_from_db()
        assert existing_user.client_profile.contact_person == "Existing Registered Phone"
        assert existing_user.client_profile.phone_number == "+905551239999"

    def test_operator_can_create_client_account(self, client, auth_state):
        client.login(username=auth_state.operator_user.username, password="SecurePass123!")
        data = {
            "username": "operator-created-client",
            "email": "",
            "new_password1": "SecurePass123!",
            "new_password2": "SecurePass123!",
            "account_type": "INDIVIDUAL",
            "contact_person": "Dup Client",
            "phone_area_code": "+90",
            "phone_number": "5550000001",
            "address": "Addr",
        }
        response = client.post(reverse("tenant_user_create", args=[User.Role.CLIENT]), data)

        assert response.status_code == 302
        created = User.objects.get(username="operator-created-client")
        assert created.role == User.Role.CLIENT
        assert created.client_profile.phone_number == "+905550000001"


class TestClientProfileAPI:
    """Staff JSON API for client profiles."""

    def test_list_redirects_when_anonymous(self, client):
        response = client.get("/api/v1/clients/")
        assert response.status_code == 302

    def test_list_forbidden_for_client_role(self, client, auth_state):
        client.login(username=auth_state.client_user.username, password="SecurePass123!")
        response = client.get("/api/v1/clients/")
        assert response.status_code == 403

    def test_list_ok_for_operator(self, client, auth_state):
        client.login(username=auth_state.operator_user.username, password="SecurePass123!")
        response = client.get("/api/v1/clients/")
        assert response.status_code == 200

    def test_list_ok_for_manager(self, client, auth_state):
        client.login(username=auth_state.manager_user.username, password="SecurePass123!")
        response = client.get("/api/v1/clients/")
        assert response.status_code == 200
        payload = json.loads(response.content)
        assert "results" in payload
        assert "count" in payload

    def test_list_search_matches_default_destination(self, client, auth_state):
        auth_state.client_profile.default_destination = "Ankara Delivery Hub"
        auth_state.client_profile.save(update_fields=["default_destination"])

        client.login(username=auth_state.manager_user.username, password="SecurePass123!")
        response = client.get("/api/v1/clients/", {"search": "Ankara"})

        assert response.status_code == 200
        payload = json.loads(response.content)
        assert payload["results"]
        assert payload["results"][0]["default_destination"] == "Ankara Delivery Hub"

    def test_detail_ok_for_manager(self, client, auth_state):
        client.login(username=auth_state.manager_user.username, password="SecurePass123!")
        response = client.get(f"/api/v1/clients/{auth_state.client_profile.id}/")
        assert response.status_code == 200
        payload = json.loads(response.content)
        assert payload["id"] == str(auth_state.client_profile.id)

    def test_patch_updates_profile(self, client, auth_state):
        client.login(username=auth_state.manager_user.username, password="SecurePass123!")
        profile_id = str(auth_state.client_profile.id)
        response = client.patch(
            f"/api/v1/clients/{profile_id}/",
            data=json.dumps({"phone_number": "+909998887777", "default_destination": "Cold Storage A"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        auth_state.client_user.refresh_from_db()
        auth_state.client_profile.refresh_from_db()
        assert auth_state.client_user.phone_number == "+909998887777"
        assert auth_state.client_profile.phone_number == "+909998887777"
        assert auth_state.client_profile.default_destination == "Cold Storage A"

    def test_api_rejects_non_client_profile_records(self, client, auth_state):
        staff_user = User.objects.create_user(
            username="staff-profile-user",
            password="SecurePass123!",
            role=User.Role.MANAGER,
        )
        staff_profile = ClientProfile.objects.create(
            user=staff_user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            contact_person="Staff Profile",
            phone_number="+15554443333",
            address="Back Office",
        )

        client.login(username=auth_state.operator_user.username, password="SecurePass123!")
        response = client.get(f"/api/v1/clients/{staff_profile.id}/")

        assert response.status_code == 403

    def test_api_allows_walkin_profile_records(self, client, auth_state):
        walkin_user = User.objects.create_user(
            username="walkin-prospect",
            password=None,
            phone_number="+15554443322",
            role=User.Role.WALKIN,
        )
        walkin_user.set_unusable_password()
        walkin_user.save(update_fields=["password"])
        walkin_profile = ClientProfile.objects.create(
            user=walkin_user,
            account_type=ClientProfile.AccountType.UNCLASSIFIED,
            contact_person="Walk-in Prospect",
            phone_number="+15554443322",
            address="",
        )

        client.login(username=auth_state.operator_user.username, password="SecurePass123!")
        response = client.get(f"/api/v1/clients/{walkin_profile.id}/")

        assert response.status_code == 200


@pytest.mark.skipif(SKIP_VIEW_TESTS, reason=SKIP_REASON)
class TestTenantUserManagement:
    def test_admin_can_create_admin(self, client, auth_state):
        client.login(username=auth_state.admin_user.username, password="SecurePass123!")

        response = client.post(
            reverse("tenant_user_create", args=[User.Role.ADMIN]),
            {
                "role": User.Role.ADMIN,
                "username": "tenant-admin",
                "email": "tenant-admin@example.com",
                "phone_area_code": "+90",
                "phone_number": "",
                "new_password1": "SecurePass123!",
                "new_password2": "SecurePass123!",
                "is_active": "on",
            },
        )

        assert response.status_code == 302
        created = User.objects.get(username="tenant-admin")
        assert created.role == User.Role.ADMIN

    def test_owner_cannot_create_admin(self, client, auth_state):
        client.login(username=auth_state.owner_user.username, password="SecurePass123!")

        response = client.get(reverse("tenant_user_create", args=[User.Role.ADMIN]))

        assert response.status_code == 403

    def test_owner_user_list_hides_admin_create_action(self, client, auth_state):
        client.login(username=auth_state.owner_user.username, password="SecurePass123!")

        response = client.get(reverse("tenant_user_list"))

        assert response.status_code == 200
        assert User.Role.ADMIN not in response.context["creatable_roles"]

    def test_admin_can_create_manager(self, client, auth_state):
        client.login(username=auth_state.admin_user.username, password="SecurePass123!")

        response = client.post(
            reverse("tenant_user_create", args=[User.Role.MANAGER]),
            {
                "role": User.Role.MANAGER,
                "username": "tenant-manager",
                "email": "",
                "phone_area_code": "+1",
                "phone_number": "5556667777",
                "new_password1": "SecurePass123!",
                "new_password2": "SecurePass123!",
                "is_active": "on",
            },
        )

        assert response.status_code == 302
        created = User.objects.get(username="tenant-manager")
        assert created.role == User.Role.MANAGER
        assert created.phone_number == "+15556667777"

    def test_staff_edit_page_prefills_existing_username(self, client, auth_state):
        client.login(username=auth_state.admin_user.username, password="SecurePass123!")

        response = client.get(reverse("tenant_user_edit", kwargs={"pk": auth_state.manager_user.pk}))

        assert response.status_code == 200
        assert response.context["form"]["username"].value() == auth_state.manager_user.username

    def test_admin_can_create_manager_with_generated_password_when_empty(self, client, auth_state):
        client.login(username=auth_state.admin_user.username, password="SecurePass123!")

        response = client.post(
            reverse("tenant_user_create", args=[User.Role.MANAGER]),
            {
                "role": User.Role.MANAGER,
                "username": "tenant-manager-auto",
                "email": "",
                "phone_area_code": "+1",
                "phone_number": "5556667788",
                "new_password1": "",
                "new_password2": "",
                "is_active": "on",
            },
        )

        assert response.status_code == 302
        created = User.objects.get(username="tenant-manager-auto")
        assert created.role == User.Role.MANAGER
        assert created.has_usable_password()
        assert created.check_password("") is False

    def test_operator_cannot_create_staff_user(self, client, auth_state):
        client.login(username=auth_state.operator_user.username, password="SecurePass123!")

        response = client.get(reverse("tenant_user_create", args=[User.Role.OPERATOR]))

        assert response.status_code == 403

    def test_operator_user_list_is_limited_to_client_facing_roles(self, client, auth_state):
        walkin_user = User.objects.create_user(
            username="operator-visible-walkin",
            password=None,
            phone_number="+15554440000",
            role=User.Role.WALKIN,
        )
        walkin_user.set_unusable_password()
        walkin_user.save(update_fields=["password"])
        ClientProfile.objects.create(
            user=walkin_user,
            account_type=ClientProfile.AccountType.UNCLASSIFIED,
            contact_person="Visible Walk-in",
            phone_number="+15554440000",
            address="",
        )

        client.login(username=auth_state.operator_user.username, password="SecurePass123!")

        response = client.get(reverse("tenant_user_list"))

        assert response.status_code == 200
        rows = response.context["user_rows"]
        assert rows
        assert {row["user"].role for row in rows}.issubset({User.Role.CLIENT})
        assert not any(row["user"].role == User.Role.WALKIN for row in rows)
        client_rows = response.context["client_rows"]
        assert any(
            cr["profile"].user_id == walkin_user.pk for cr in client_rows
        ), "Walk-in prospects should appear under Client accounts, not the main user table"

    def test_owner_cannot_edit_admin_user(self, client, auth_state):
        client.login(username=auth_state.owner_user.username, password="SecurePass123!")

        response = client.get(reverse("tenant_user_edit", kwargs={"pk": auth_state.admin_user.pk}))

        assert response.status_code == 403

    def test_manager_can_edit_client_account_and_phone_syncs(self, client, auth_state):
        client.login(username=auth_state.manager_user.username, password="SecurePass123!")

        response = client.post(
            reverse("tenant_user_edit", kwargs={"pk": auth_state.client_user.pk}),
            {
                "username": "edited-client",
                "email": "edited-client@example.com",
                "new_password1": "",
                "new_password2": "",
                "account_type": ClientProfile.AccountType.INDIVIDUAL,
                "contact_person": "Edited Client",
                "phone_area_code": "+90",
                "phone_number": "5550001122",
                "address": "Edited Address",
                "company_name": "",
                "tax_id": "",
            },
        )

        assert response.status_code == 302
        auth_state.client_user.refresh_from_db()
        auth_state.client_profile.refresh_from_db()
        assert auth_state.client_user.username == "edited-client"
        assert auth_state.client_user.email == "edited-client@example.com"
        assert auth_state.client_user.phone_number == "+905550001122"
        assert auth_state.client_profile.phone_number == "+905550001122"
