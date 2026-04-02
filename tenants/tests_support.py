from __future__ import annotations

import builtins
import sys
from contextlib import nullcontext
from io import StringIO
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.backends import ModelBackend
from django.core.management import call_command
from django.db import connection

from core.models import ServicePackage
from scales.models import Site
from tenants.auth_backends import PlatformAdminBackend, PublicSchemaSafeModelBackend
from tenants.context_processors import tenant_context
from tenants.models import PlatformAdmin
from tenants.redis_support import atomic_rate_incr, is_redis_reachable
from tenants.signals import ensure_default_scales_site, ensure_default_service_packages_signal
from tenants.storage import TenantGCSStorage
from tenants.tenant_helpers import get_tenant_site_url
from users.models import User

pytestmark = pytest.mark.django_db


class _FakeDomainQuery:
    def __init__(self, domains):
        self.domains = domains

    def first(self):
        return self.domains[0] if self.domains else None


class _FakeDomains:
    def __init__(self, domains):
        self.domains = domains

    def filter(self, **kwargs):
        is_primary = kwargs.get("is_primary")
        filtered = [domain for domain in self.domains if domain.is_primary == is_primary]
        return _FakeDomainQuery(filtered)

    def first(self):
        return self.domains[0] if self.domains else None


def test_tenant_context_returns_tenant_or_none():
    assert tenant_context(SimpleNamespace(tenant="tenant-a")) == {"tenant": "tenant-a"}
    assert tenant_context(SimpleNamespace()) == {"tenant": None}


def test_get_tenant_site_url_returns_fallback_when_multitenant_disabled(settings):
    settings.USE_MULTITENANT = False
    settings.SITE_URL_FALLBACK = "http://fallback.test"

    assert get_tenant_site_url() == "http://fallback.test"


def test_get_tenant_site_url_returns_fallback_without_tenant(monkeypatch, settings):
    settings.USE_MULTITENANT = True
    settings.SITE_URL_FALLBACK = "http://fallback.test"
    monkeypatch.setattr(connection, "tenant", None, raising=False)

    with patch("django_tenants.utils.get_public_schema_name", return_value="public"):
        assert get_tenant_site_url() == "http://fallback.test"


def test_get_tenant_site_url_returns_fallback_for_public_schema(monkeypatch, settings):
    settings.USE_MULTITENANT = True
    settings.SITE_URL_FALLBACK = "http://fallback.test"
    tenant = SimpleNamespace(schema_name="public")
    monkeypatch.setattr(connection, "tenant", tenant, raising=False)

    with patch("django_tenants.utils.get_public_schema_name", return_value="public"):
        assert get_tenant_site_url() == "http://fallback.test"


def test_get_tenant_site_url_uses_primary_domain(monkeypatch, settings):
    settings.USE_MULTITENANT = True
    settings.DEBUG = False
    tenant = SimpleNamespace(
        schema_name="acme",
        domains=_FakeDomains([SimpleNamespace(domain="acme.example.com", is_primary=True)]),
    )
    monkeypatch.setattr(connection, "tenant", tenant, raising=False)

    with patch("django_tenants.utils.get_public_schema_name", return_value="public"):
        assert get_tenant_site_url() == "https://acme.example.com"


def test_get_tenant_site_url_falls_back_to_schema_subdomain(monkeypatch, settings):
    settings.USE_MULTITENANT = True
    settings.DEBUG = True
    settings.TENANT_BASE_DOMAIN = "example.local"
    tenant = SimpleNamespace(schema_name="acme", domains=_FakeDomains([]))
    monkeypatch.setattr(connection, "tenant", tenant, raising=False)

    with patch("django_tenants.utils.get_public_schema_name", return_value="public"):
        assert get_tenant_site_url() == "http://acme.example.local"


def test_get_tenant_site_url_falls_back_to_schema_subdomain_without_domains_attr(monkeypatch, settings):
    settings.USE_MULTITENANT = True
    settings.DEBUG = False
    settings.TENANT_BASE_DOMAIN = "example.com"
    tenant = SimpleNamespace(schema_name="acme")
    monkeypatch.setattr(connection, "tenant", tenant, raising=False)

    with patch("django_tenants.utils.get_public_schema_name", return_value="public"):
        assert get_tenant_site_url() == "https://acme.example.com"


def test_platform_admin_backend_authenticates_public_schema(monkeypatch):
    admin = PlatformAdmin.objects.create(email="admin@example.com", name="Admin")
    admin.set_password("secretpass123")
    admin.save()
    monkeypatch.setattr(connection, "schema_name", "public", raising=False)

    with patch("tenants.auth_backends.get_public_schema_name", return_value="public"):
        result = PlatformAdminBackend().authenticate(None, username="ADMIN@example.com", password="secretpass123")

    assert result == admin


def test_platform_admin_backend_rejects_inactive_or_wrong_schema(monkeypatch):
    admin = PlatformAdmin.objects.create(email="inactive@example.com", name="Inactive", is_active=False)
    admin.set_password("secretpass123")
    admin.save()

    backend = PlatformAdminBackend()
    monkeypatch.setattr(connection, "schema_name", "tenant-a", raising=False)
    with patch("tenants.auth_backends.get_public_schema_name", return_value="public"):
        assert backend.authenticate(None, username="inactive@example.com", password="secretpass123") is None

    monkeypatch.setattr(connection, "schema_name", "public", raising=False)
    with patch("tenants.auth_backends.get_public_schema_name", return_value="public"):
        assert backend.authenticate(None, username="inactive@example.com", password="secretpass123") is None
        assert backend.authenticate(None, username="inactive@example.com", password="wrongpass") is None
        assert backend.get_user(admin.pk) == admin


def test_public_schema_safe_model_backend_returns_none_on_public_schema(monkeypatch):
    monkeypatch.setattr(connection, "schema_name", "public", raising=False)

    with patch("tenants.auth_backends.get_public_schema_name", return_value="public"):
        assert PublicSchemaSafeModelBackend().authenticate(None, username="user", password="password123") is None
        assert PublicSchemaSafeModelBackend().get_user(1) is None


def test_public_schema_safe_model_backend_falls_back_to_case_insensitive_username(monkeypatch):
    user = User.objects.create_user(username="CaseUser", email="case@example.com", password="secretpass123")
    monkeypatch.setattr(connection, "schema_name", "tenant-a", raising=False)

    with (
        patch("tenants.auth_backends.get_public_schema_name", return_value="public"),
        patch.object(ModelBackend, "authenticate", return_value=None),
    ):
        result = PublicSchemaSafeModelBackend().authenticate(None, username="caseuser", password="secretpass123")

    assert result == user


def test_public_schema_safe_model_backend_falls_back_to_email(monkeypatch):
    user = User.objects.create_user(username="mailuser", email="mail@example.com", password="secretpass123")
    monkeypatch.setattr(connection, "schema_name", "tenant-a", raising=False)

    with (
        patch("tenants.auth_backends.get_public_schema_name", return_value="public"),
        patch.object(ModelBackend, "authenticate", return_value=None),
    ):
        result = PublicSchemaSafeModelBackend().authenticate(
            None, username="MAIL@example.com", password="secretpass123"
        )

    assert result == user
    with patch("tenants.auth_backends.get_public_schema_name", return_value="public"):
        assert PublicSchemaSafeModelBackend().get_user(user.pk) == user


def test_public_schema_safe_model_backend_falls_back_to_phone(monkeypatch):
    user = User.objects.create_user(
        username="phoneuser",
        phone_number="+15551234567",
        password="secretpass123",
    )
    monkeypatch.setattr(connection, "schema_name", "tenant-a", raising=False)

    with (
        patch("tenants.auth_backends.get_public_schema_name", return_value="public"),
        patch.object(ModelBackend, "authenticate", return_value=None),
    ):
        result = PublicSchemaSafeModelBackend().authenticate(
            None, username="+1 (555) 123-4567", password="secretpass123"
        )

    assert result == user


def test_atomic_rate_incr_returns_eval_result(monkeypatch):
    class _FakeConn:
        def eval(self, script, key_count, key, window):
            assert key_count == 1
            assert key == "rate:key"
            assert window == 30
            return 7

    fake_module = ModuleType("django_redis")
    fake_module.get_redis_connection = lambda alias: _FakeConn()
    monkeypatch.setitem(sys.modules, "django_redis", fake_module)

    assert atomic_rate_incr("rate:key", 30) == 7


def test_atomic_rate_incr_fails_open(monkeypatch):
    def _raise(_alias):
        raise RuntimeError("redis down")

    fake_module = ModuleType("django_redis")
    fake_module.get_redis_connection = _raise
    monkeypatch.setitem(sys.modules, "django_redis", fake_module)

    assert atomic_rate_incr("rate:key", 30) == 0


def test_is_redis_reachable_returns_false_without_package(monkeypatch):
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "redis":
            raise ImportError("missing redis")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    assert is_redis_reachable("redis://localhost") is False


def test_is_redis_reachable_returns_true_when_ping_succeeds(monkeypatch):
    class _FakeClient:
        def ping(self):
            return True

    fake_module = ModuleType("redis")
    fake_module.from_url = lambda url, socket_connect_timeout, socket_timeout: _FakeClient()
    monkeypatch.setitem(sys.modules, "redis", fake_module)

    assert is_redis_reachable("redis://localhost") is True


def test_is_redis_reachable_returns_false_when_ping_fails(monkeypatch):
    class _FakeClient:
        def ping(self):
            raise RuntimeError("no ping")

    fake_module = ModuleType("redis")
    fake_module.from_url = lambda url, socket_connect_timeout, socket_timeout: _FakeClient()
    monkeypatch.setitem(sys.modules, "redis", fake_module)

    assert is_redis_reachable("redis://localhost") is False


def test_ensure_default_scales_site_skips_public_tenant():
    Site.objects.all().delete()

    with patch("tenants.signals.get_public_schema_name", return_value="public"):
        ensure_default_scales_site(sender=None, tenant=SimpleNamespace(schema_name="public", name="Public"))

    assert Site.objects.count() == 0


def test_ensure_default_scales_site_creates_default_site_with_fallback_name():
    Site.objects.all().delete()
    tenant = SimpleNamespace(schema_name="acme", name=" ")

    with (
        patch("tenants.signals.get_public_schema_name", return_value="public"),
        patch("tenants.signals.schema_context", side_effect=lambda schema: nullcontext()),
    ):
        ensure_default_scales_site(sender=None, tenant=tenant)
        ensure_default_scales_site(sender=None, tenant=tenant)

    site = Site.objects.get()
    assert site.name == "acme"
    assert Site.objects.count() == 1


def test_ensure_default_service_packages_signal_seeds_defaults():
    ServicePackage.objects.all().delete()

    with (
        patch("tenants.signals.get_public_schema_name", return_value="public"),
        patch("tenants.signals.schema_context", side_effect=lambda schema: nullcontext()),
    ):
        ensure_default_service_packages_signal(sender=None, tenant=SimpleNamespace(schema_name="acme"))

    assert ServicePackage.objects.count() == 3


def test_ensure_default_service_packages_signal_skips_public_tenant():
    ServicePackage.objects.all().delete()

    with patch("tenants.signals.get_public_schema_name", return_value="public"):
        ensure_default_service_packages_signal(sender=None, tenant=SimpleNamespace(schema_name="public"))

    assert ServicePackage.objects.count() == 0


def test_create_platform_admin_command_creates_and_updates_user():
    PlatformAdmin.objects.all().delete()

    with (
        patch("tenants.management.commands.create_platform_admin.get_public_schema_name", return_value="public"),
        patch(
            "tenants.management.commands.create_platform_admin.schema_context",
            side_effect=lambda schema: nullcontext(),
        ),
    ):
        call_command(
            "create_platform_admin",
            "--email=ADMIN@EXAMPLE.COM",
            "--name=Admin User",
            "--password=secretpass123",
            stdout=StringIO(),
        )

        created = PlatformAdmin.objects.get(email="admin@example.com")
        assert created.name == "Admin User"
        assert created.is_active is True
        assert created.check_password("secretpass123")

        call_command(
            "create_platform_admin",
            "--email=ADMIN@EXAMPLE.COM",
            "--name=Updated Admin",
            "--password=newsecret123",
            stdout=StringIO(),
        )

    updated = PlatformAdmin.objects.get(email="admin@example.com")
    assert updated.name == "Updated Admin"
    assert updated.check_password("newsecret123")


def test_tenant_gcs_storage_prefixes_names(monkeypatch, settings):
    storage = object.__new__(TenantGCSStorage)

    settings.USE_MULTITENANT = False
    assert storage._with_tenant_prefix("logo.png") == "logo.png"

    settings.USE_MULTITENANT = True
    monkeypatch.setattr(connection, "schema_name", "", raising=False)
    assert storage._with_tenant_prefix("logo.png") == "logo.png"

    monkeypatch.setattr(connection, "schema_name", "acme", raising=False)
    assert storage._with_tenant_prefix("logo.png") == "acme/logo.png"
    assert storage._with_tenant_prefix("acme/logo.png") == "acme/logo.png"


def test_tenant_gcs_storage_normalize_name_uses_prefixed_value(monkeypatch, settings):
    storage = object.__new__(TenantGCSStorage)
    settings.USE_MULTITENANT = True
    monkeypatch.setattr(connection, "schema_name", "acme", raising=False)

    with patch("tenants.storage.GoogleCloudStorage._normalize_name", return_value="normalized") as mock_normalize:
        assert storage._normalize_name("logo.png") == "normalized"

    mock_normalize.assert_called_once_with("acme/logo.png")
