"""Discover-tenants API smoke tests (SQLite / settings_test)."""

import json
from contextlib import nullcontext
from types import SimpleNamespace

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
    monkeypatch.setattr(email_index, "build_tenant_web_app_base_url", lambda tenant: f"http://{tenant.slug}.localhost:3000")
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
