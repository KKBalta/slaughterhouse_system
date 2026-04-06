"""Discover-tenants API smoke tests (SQLite / settings_test)."""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import django_tenants.utils as tenant_utils
import pytest
from django.core.cache import cache
from django.test import Client, RequestFactory, override_settings

import users.views as user_views
from tenants import email_index
from users.models import User


class _FakeQuery(list):
    def select_related(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self


class _FakeMembershipManager:
    def __init__(self, memberships):
        self.memberships = memberships
        self.calls = []

    def filter(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return _FakeQuery(self.memberships)


def _fake_tenant(pk=1, schema_name="pomet", name="Pomet", slug="pomet", domain="pomet.localhost"):
    return SimpleNamespace(
        pk=pk,
        schema_name=schema_name,
        name=name,
        slug=slug,
        get_primary_domain=lambda: SimpleNamespace(domain=domain),
    )


def _patch_discovery_context(monkeypatch):
    monkeypatch.setattr(tenant_utils, "get_public_schema_name", lambda: "public")
    monkeypatch.setattr(tenant_utils, "schema_context", lambda _schema: nullcontext())
    monkeypatch.setattr(email_index, "build_tenant_api_base_url", lambda tenant: f"http://{tenant.slug}.localhost:8000")
    monkeypatch.setattr(
        email_index, "build_tenant_web_app_base_url", lambda tenant: f"http://{tenant.slug}.localhost:3000"
    )
    monkeypatch.setattr(
        email_index,
        "build_post_login_redirect_url",
        lambda tenant, use_api_host=None: f"http://{tenant.slug}.localhost:3000/dashboard",
    )


def _json_body(response):
    return json.loads(response.content)


@pytest.mark.django_db
def test_discover_tenants_not_multitenant_returns_400():
    """When USE_MULTITENANT is false, discovery returns 400 without importing tenant models."""
    client = Client()
    response = client.post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({"email": "a@b.com"}),
        content_type="application/json",
    )
    assert response.status_code == 400
    body = response.json()
    assert "detail" in body


@pytest.mark.django_db
@override_settings(USE_MULTITENANT=True, ALLOWED_HOSTS=["testserver"])
def test_discover_tenants_phone_returns_role_and_deduplicates_tenants(monkeypatch):
    import tenants.models as tenant_models

    cache.clear()
    _patch_discovery_context(monkeypatch)

    fake_tenant = _fake_tenant()
    memberships = [
        SimpleNamespace(tenant=fake_tenant, role=User.Role.CLIENT),
        SimpleNamespace(tenant=fake_tenant, role=User.Role.CLIENT),
    ]
    manager = _FakeMembershipManager(memberships)
    monkeypatch.setattr(tenant_models, "EmailTenantMembership", SimpleNamespace(objects=manager))

    request = RequestFactory().post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({"phone": "+1 (555) 123-4567"}),
        content_type="application/json",
    )

    response = user_views.discover_tenants_api(request)

    assert response.status_code == 200
    assert len(manager.calls) == 1
    assert _json_body(response) == {
        "tenants": [
            {
                "schema_name": "pomet",
                "name": "Pomet",
                "slug": "pomet",
                "primary_domain": "pomet.localhost",
                "api_base_url": "http://pomet.localhost:8000",
                "auth_login_url": "http://pomet.localhost:8000/api/v1/auth/login/",
                "web_app_base_url": "http://pomet.localhost:3000",
                "post_login_redirect_url": "http://pomet.localhost:3000/dashboard",
                "role": User.Role.CLIENT,
            }
        ]
    }


@pytest.mark.django_db
@override_settings(USE_MULTITENANT=True, ALLOWED_HOSTS=["testserver"])
def test_discover_tenants_uses_normalized_phone_cache_key(monkeypatch):
    import tenants.models as tenant_models

    cache.clear()
    _patch_discovery_context(monkeypatch)

    cached_payload = {
        "tenants": [
            {
                "schema_name": "cached",
                "name": "Cached Farm",
                "slug": "cached",
                "primary_domain": "cached.localhost",
                "api_base_url": "http://cached.localhost:8000",
                "auth_login_url": "http://cached.localhost:8000/api/v1/auth/login/",
                "web_app_base_url": "http://cached.localhost:3000",
                "post_login_redirect_url": "http://cached.localhost:3000/dashboard",
                "role": User.Role.CLIENT,
            }
        ]
    }
    cache.set("tenant_discovery_phone:+15551234567", cached_payload, timeout=300)

    class _FailingManager:
        def filter(self, *args, **kwargs):
            raise AssertionError("DB lookup should not run when the normalized phone cache key is populated.")

    monkeypatch.setattr(tenant_models, "EmailTenantMembership", SimpleNamespace(objects=_FailingManager()))

    request = RequestFactory().post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({"phone": "+1 (555) 123-4567"}),
        content_type="application/json",
    )

    response = user_views.discover_tenants_api(request)

    assert response.status_code == 200
    assert _json_body(response) == cached_payload


@pytest.mark.django_db
@override_settings(USE_MULTITENANT=True, ALLOWED_HOSTS=["testserver"])
def test_discover_tenants_empty_result_includes_hint(monkeypatch):
    import tenants.models as tenant_models

    cache.clear()
    _patch_discovery_context(monkeypatch)

    manager = _FakeMembershipManager([])
    monkeypatch.setattr(tenant_models, "EmailTenantMembership", SimpleNamespace(objects=manager))

    request = RequestFactory().post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({"email": "missing@example.com"}),
        content_type="application/json",
    )

    response = user_views.discover_tenants_api(request)

    assert response.status_code == 200
    assert _json_body(response) == {
        "tenants": [],
        "discovery_hint": (
            "No tenants are indexed for this email or phone number. Each tenant user needs at least one "
            "contact identifier and a public EmailTenantMembership row (created automatically on save, or run: "
            "python manage.py backfill_email_tenant_membership)."
        ),
    }


@pytest.mark.django_db
@override_settings(USE_MULTITENANT=True, DEBUG=True, TENANT_BASE_DOMAIN="localhost", ALLOWED_HOSTS=["testserver"])
def test_discover_tenants_prefers_localhost_hosts_in_debug_for_imported_remote_domains(monkeypatch):
    import tenants.models as tenant_models

    cache.clear()
    monkeypatch.setattr(tenant_utils, "get_public_schema_name", lambda: "public")
    monkeypatch.setattr(tenant_utils, "schema_context", lambda _schema: nullcontext())
    monkeypatch.setattr(
        email_index,
        "build_post_login_redirect_url",
        lambda tenant, use_api_host=None: "http://pomet.localhost:3000/dashboard",
    )

    fake_tenant = _fake_tenant(domain="pomet.carnitrack.com")
    memberships = [SimpleNamespace(tenant=fake_tenant, role=User.Role.CLIENT)]
    manager = _FakeMembershipManager(memberships)
    monkeypatch.setattr(tenant_models, "EmailTenantMembership", SimpleNamespace(objects=manager))

    request = RequestFactory().post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({"email": "user@example.com"}),
        content_type="application/json",
    )

    response = user_views.discover_tenants_api(request)

    assert response.status_code == 200
    assert _json_body(response) == {
        "tenants": [
            {
                "schema_name": "pomet",
                "name": "Pomet",
                "slug": "pomet",
                "primary_domain": "pomet.localhost",
                "api_base_url": "http://pomet.localhost:8000",
                "auth_login_url": "http://pomet.localhost:8000/api/v1/auth/login/",
                "web_app_base_url": "http://pomet.localhost:3000",
                "post_login_redirect_url": "http://pomet.localhost:3000/dashboard",
                "role": User.Role.CLIENT,
            }
        ]
    }


@pytest.mark.django_db
@override_settings(USE_MULTITENANT=True, ALLOWED_HOSTS=["testserver"])
def test_discover_tenants_without_identifier_returns_empty_list(monkeypatch):
    cache.clear()
    _patch_discovery_context(monkeypatch)

    request = RequestFactory().post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({}),
        content_type="application/json",
    )

    response = user_views.discover_tenants_api(request)

    assert response.status_code == 200
    assert _json_body(response) == {"tenants": []}


# ---------------------------------------------------------------------------
# Rate-limiting tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(USE_MULTITENANT=True, ALLOWED_HOSTS=["testserver"])
def test_discover_tenants_returns_429_when_ip_rate_limit_exceeded(monkeypatch):
    """Tier 1: per-IP rate limit returns 429."""
    import tenants.models as tenant_models

    cache.clear()
    _patch_discovery_context(monkeypatch)

    manager = _FakeMembershipManager([])
    monkeypatch.setattr(tenant_models, "EmailTenantMembership", SimpleNamespace(objects=manager))

    call_count = 0

    def fake_rate_incr(key, window):
        nonlocal call_count
        call_count += 1
        # First call is IP check — return over limit
        if call_count == 1:
            return user_views._DISCOVERY_RATE_IP_LIMIT + 1
        return 1

    monkeypatch.setattr("tenants.redis_support.atomic_rate_incr", fake_rate_incr)

    request = RequestFactory().post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({"email": "user@example.com"}),
        content_type="application/json",
    )

    response = user_views.discover_tenants_api(request)

    assert response.status_code == 429
    body = _json_body(response)
    assert "Too many requests" in body["detail"]
    # DB should never be hit
    assert len(manager.calls) == 0


@pytest.mark.django_db
@override_settings(USE_MULTITENANT=True, ALLOWED_HOSTS=["testserver"])
def test_discover_tenants_returns_429_when_identifier_rate_limit_exceeded(monkeypatch):
    """Tier 2: per-identifier rate limit returns 429."""
    import tenants.models as tenant_models

    cache.clear()
    _patch_discovery_context(monkeypatch)

    manager = _FakeMembershipManager([])
    monkeypatch.setattr(tenant_models, "EmailTenantMembership", SimpleNamespace(objects=manager))

    call_count = 0

    def fake_rate_incr(key, window):
        nonlocal call_count
        call_count += 1
        # First call is IP check — under limit
        if call_count == 1:
            return 1
        # Second call is identifier check — over limit
        return user_views._DISCOVERY_RATE_ID_LIMIT + 1

    monkeypatch.setattr("tenants.redis_support.atomic_rate_incr", fake_rate_incr)

    request = RequestFactory().post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({"phone": "+905551234567"}),
        content_type="application/json",
    )

    response = user_views.discover_tenants_api(request)

    assert response.status_code == 429
    assert len(manager.calls) == 0


@pytest.mark.django_db
@override_settings(USE_MULTITENANT=True, ALLOWED_HOSTS=["testserver"])
def test_discover_tenants_passes_when_under_rate_limits(monkeypatch):
    """Requests under both limits proceed normally."""
    import tenants.models as tenant_models

    cache.clear()
    _patch_discovery_context(monkeypatch)

    fake_tenant = _fake_tenant()
    memberships = [SimpleNamespace(tenant=fake_tenant, role=User.Role.CLIENT)]
    manager = _FakeMembershipManager(memberships)
    monkeypatch.setattr(tenant_models, "EmailTenantMembership", SimpleNamespace(objects=manager))

    def fake_rate_incr(key, window):
        return 1  # always under limit

    monkeypatch.setattr("tenants.redis_support.atomic_rate_incr", fake_rate_incr)

    request = RequestFactory().post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({"email": "user@example.com"}),
        content_type="application/json",
    )

    response = user_views.discover_tenants_api(request)

    assert response.status_code == 200
    body = _json_body(response)
    assert len(body["tenants"]) == 1


@pytest.mark.django_db
@override_settings(USE_MULTITENANT=True, ALLOWED_HOSTS=["testserver"])
def test_discover_tenants_rate_limit_fail_open_when_redis_down(monkeypatch):
    """When atomic_rate_incr returns 0 (Redis down), requests pass through."""
    import tenants.models as tenant_models

    cache.clear()
    _patch_discovery_context(monkeypatch)

    fake_tenant = _fake_tenant()
    memberships = [SimpleNamespace(tenant=fake_tenant, role=User.Role.CLIENT)]
    manager = _FakeMembershipManager(memberships)
    monkeypatch.setattr(tenant_models, "EmailTenantMembership", SimpleNamespace(objects=manager))

    def fake_rate_incr(key, window):
        return 0  # Redis unreachable

    monkeypatch.setattr("tenants.redis_support.atomic_rate_incr", fake_rate_incr)

    request = RequestFactory().post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({"email": "user@example.com"}),
        content_type="application/json",
    )

    response = user_views.discover_tenants_api(request)

    assert response.status_code == 200
    body = _json_body(response)
    assert len(body["tenants"]) == 1


@pytest.mark.django_db
@override_settings(USE_MULTITENANT=True, ALLOWED_HOSTS=["testserver"])
def test_discover_tenants_no_rate_limit_without_identifier(monkeypatch):
    """Requests without email/phone skip rate limiting entirely."""
    cache.clear()
    _patch_discovery_context(monkeypatch)

    rate_calls = []

    def fake_rate_incr(key, window):
        rate_calls.append(key)
        return 1

    monkeypatch.setattr("tenants.redis_support.atomic_rate_incr", fake_rate_incr)

    request = RequestFactory().post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({}),
        content_type="application/json",
    )

    response = user_views.discover_tenants_api(request)

    assert response.status_code == 200
    assert _json_body(response) == {"tenants": []}
    assert len(rate_calls) == 0


@pytest.mark.django_db
@override_settings(USE_MULTITENANT=True, ALLOWED_HOSTS=["testserver"])
def test_discover_tenants_rate_limit_uses_correct_keys(monkeypatch):
    """Verify the IP and identifier keys passed to atomic_rate_incr."""
    import tenants.models as tenant_models

    cache.clear()
    _patch_discovery_context(monkeypatch)

    manager = _FakeMembershipManager([])
    monkeypatch.setattr(tenant_models, "EmailTenantMembership", SimpleNamespace(objects=manager))

    rate_calls = []

    def fake_rate_incr(key, window):
        rate_calls.append((key, window))
        return 1

    monkeypatch.setattr("tenants.redis_support.atomic_rate_incr", fake_rate_incr)

    request = RequestFactory().post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({"email": "Test@Example.COM"}),
        content_type="application/json",
    )
    request.META["REMOTE_ADDR"] = "192.168.1.42"

    user_views.discover_tenants_api(request)

    assert len(rate_calls) == 2
    ip_key, ip_window = rate_calls[0]
    id_key, id_window = rate_calls[1]
    assert ip_key == "disc_ip:192.168.1.42"
    assert ip_window == 60
    assert id_key == "disc_id:test@example.com"  # normalized
    assert id_window == 300


@pytest.mark.django_db
@override_settings(USE_MULTITENANT=True, ALLOWED_HOSTS=["testserver"])
def test_discover_tenants_rate_limit_uses_xff_header(monkeypatch):
    """X-Forwarded-For header is used for IP extraction."""
    import tenants.models as tenant_models

    cache.clear()
    _patch_discovery_context(monkeypatch)

    manager = _FakeMembershipManager([])
    monkeypatch.setattr(tenant_models, "EmailTenantMembership", SimpleNamespace(objects=manager))

    rate_calls = []

    def fake_rate_incr(key, window):
        rate_calls.append(key)
        return 1

    monkeypatch.setattr("tenants.redis_support.atomic_rate_incr", fake_rate_incr)

    request = RequestFactory().post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({"email": "a@b.com"}),
        content_type="application/json",
        HTTP_X_FORWARDED_FOR="10.0.0.1, 10.0.0.2",
    )

    user_views.discover_tenants_api(request)

    assert rate_calls[0] == "disc_ip:10.0.0.1"
