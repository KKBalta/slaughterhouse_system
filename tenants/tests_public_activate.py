"""Tests for POST /api/v1/activate — public-schema Edge activation endpoint."""

from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import Client as HttpClient
from django.utils import timezone

from scales.models import EdgeDevice, EdgeSetupCode, Site
from tenants.models import Client as TenantClient
from tenants.models import Domain, EdgeDeviceIndex, EdgeSetupCodeIndex


def _pub_activate_url():
    return "/api/v1/activate"


@pytest.fixture
def http_client():
    return HttpClient()


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr("tenants.redis_support.atomic_rate_incr", lambda _k, _w: 0)


@pytest.fixture
def tenant(db):
    """Create a tenant Client in the public schema for FK references."""
    t = TenantClient.objects.create(
        schema_name="test_farm",
        name="Test Farm",
    )
    Domain.objects.create(domain="test-farm.localhost", tenant=t, is_primary=True)
    return t


@pytest.fixture
def site(db):
    return Site.objects.create(name="Test Plant", address="")


@pytest.fixture
def setup_code(db, site):
    return EdgeSetupCode.objects.create(
        site=site,
        edge_name="Test Edge",
        printers_config=[
            {
                "localPrinterId": "carcass-01",
                "host": "192.168.1.220",
                "port": 9100,
                "role": "carcass",
                "displayName": "Carcass Line",
            },
        ],
        expires_at=timezone.now() + timedelta(hours=48),
    )


@pytest.fixture
def index_entry(db, tenant, setup_code):
    """Create a public-schema index entry mapping code -> tenant."""
    return EdgeSetupCodeIndex.objects.create(
        code=setup_code.code,
        tenant=tenant,
        tenant_schema=tenant.schema_name,
        setup_code_id=setup_code.pk,
        expires_at=setup_code.expires_at,
        is_consumed=False,
    )


def _noop_schema_context(schema):
    """In test env all models live in the same schema; skip schema switch."""
    return nullcontext()


@pytest.fixture(autouse=True)
def _patch_schema_context_for_views(monkeypatch):
    """Patch schema_context in the view module so it's a no-op in tests."""
    import tenants.api_views_edge as view_mod

    monkeypatch.setattr(view_mod, "schema_context", _noop_schema_context)


# ==========================================================================
# Happy path
# ==========================================================================


@pytest.mark.django_db
class TestPublicActivateSuccess:
    def test_activate_returns_200_with_full_payload(self, http_client, setup_code, index_entry, tenant):
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": setup_code.code, "version": "0.3.0", "capabilities": ["weighing", "printing"]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "edgeId" in data
        assert "siteId" in data
        assert data["siteName"] == "Test Plant"
        assert "config" in data
        assert "baseUrl" in data["config"]
        assert data["config"]["timezone"] == "Europe/Istanbul"
        assert len(data["printers"]) == 1
        assert data["printers"][0]["localPrinterId"] == "carcass-01"
        assert data["printers"][0]["host"] == "192.168.1.220"

    def test_activate_creates_edge_device(self, http_client, setup_code, index_entry, site):
        assert EdgeDevice.objects.count() == 0
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": setup_code.code, "version": "1.0.0"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert EdgeDevice.objects.count() == 1
        edge = EdgeDevice.objects.first()
        assert edge.name == "Test Edge"
        assert edge.site == site
        assert edge.is_online is True
        assert edge.version == "1.0.0"
        idx = EdgeDeviceIndex.objects.get(edge_id=edge.id)
        assert idx.tenant_id == index_entry.tenant_id
        assert idx.tenant_schema == index_entry.tenant_schema
        assert idx.is_active is True

    def test_activate_marks_setup_code_as_used(self, http_client, setup_code, index_entry):
        http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": setup_code.code}),
            content_type="application/json",
        )
        setup_code.refresh_from_db()
        assert setup_code.used_at is not None
        assert setup_code.used_by_edge is not None

    def test_activate_case_insensitive(self, http_client, setup_code, index_entry):
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": setup_code.code.lower()}),
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_activate_edge_name_falls_back_to_site_name(self, http_client, tenant, site, db):
        code = EdgeSetupCode.objects.create(
            site=site,
            edge_name="",
            expires_at=timezone.now() + timedelta(hours=48),
        )
        EdgeSetupCodeIndex.objects.create(
            code=code.code,
            tenant=tenant,
            tenant_schema=tenant.schema_name,
            setup_code_id=code.pk,
            expires_at=code.expires_at,
            is_consumed=False,
        )
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": code.code}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        edge = EdgeDevice.objects.first()
        assert edge.name == "Test Plant"

    def test_activate_no_printers_returns_empty_list(self, http_client, tenant, site, db):
        code = EdgeSetupCode.objects.create(
            site=site,
            edge_name="Bare Edge",
            expires_at=timezone.now() + timedelta(hours=48),
        )
        EdgeSetupCodeIndex.objects.create(
            code=code.code,
            tenant=tenant,
            tenant_schema=tenant.schema_name,
            setup_code_id=code.pk,
            expires_at=code.expires_at,
            is_consumed=False,
        )
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": code.code}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["printers"] == []

    def test_activate_multi_printer_config(self, http_client, tenant, site, db):
        code = EdgeSetupCode.objects.create(
            site=site,
            printers_config=[
                {"localPrinterId": "carcass-01", "host": "10.0.0.1", "port": 9100, "role": "carcass"},
                {"localPrinterId": "product-01", "host": "10.0.0.2", "port": 9100, "role": "meat_cut"},
            ],
            expires_at=timezone.now() + timedelta(hours=48),
        )
        EdgeSetupCodeIndex.objects.create(
            code=code.code,
            tenant=tenant,
            tenant_schema=tenant.schema_name,
            setup_code_id=code.pk,
            expires_at=code.expires_at,
            is_consumed=False,
        )
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": code.code}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        printers = resp.json()["printers"]
        assert len(printers) == 2
        assert printers[0]["role"] == "carcass"
        assert printers[1]["role"] == "meat_cut"

    def test_response_config_includes_tenant_base_url(self, http_client, setup_code, index_entry, tenant, monkeypatch):
        import tenants.api_views_edge as view_mod

        monkeypatch.setattr(view_mod, "build_tenant_api_base_url", lambda t: "https://test-farm.carnitrack.com")
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": setup_code.code}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["config"]["baseUrl"] == "https://test-farm.carnitrack.com"


# ==========================================================================
# Error cases
# ==========================================================================


@pytest.mark.django_db
class TestPublicActivateErrors:
    def test_empty_code_returns_400(self, http_client):
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "code is required" in resp.json()["error"]

    def test_unknown_code_returns_404(self, http_client):
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": "CT-XXXX-XXXX"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_already_consumed_returns_409(self, http_client, setup_code, index_entry):
        index_entry.is_consumed = True
        index_entry.save(update_fields=["is_consumed"])
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": setup_code.code}),
            content_type="application/json",
        )
        assert resp.status_code == 409

    def test_expired_index_returns_410(self, http_client, tenant, site, db):
        code = EdgeSetupCode.objects.create(
            site=site,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        EdgeSetupCodeIndex.objects.create(
            code=code.code,
            tenant=tenant,
            tenant_schema=tenant.schema_name,
            setup_code_id=code.pk,
            expires_at=code.expires_at,
            is_consumed=False,
        )
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": code.code}),
            content_type="application/json",
        )
        assert resp.status_code == 410

    def test_inactive_tenant_returns_403(self, http_client, setup_code, index_entry, tenant):
        tenant.is_active = False
        tenant.save(update_fields=["is_active"])
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": setup_code.code}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_method_not_allowed(self, http_client):
        resp = http_client.get(_pub_activate_url())
        assert resp.status_code == 405

    def test_rate_limit_returns_429(self, http_client, monkeypatch):
        monkeypatch.setattr("tenants.redis_support.atomic_rate_incr", lambda _k, _w: 11)
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": "CT-TEST-CODE"}),
            content_type="application/json",
        )
        assert resp.status_code == 429

    def test_revoked_setup_code_returns_404_at_tenant_level(self, http_client, setup_code, index_entry):
        """If the setup code is revoked (is_active=False) in the tenant schema,
        even though the index entry exists, the tenant-level lookup fails with 404."""
        setup_code.is_active = False
        setup_code.save(update_fields=["is_active"])
        resp = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": setup_code.code}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_double_activation_returns_409_at_tenant_level(self, http_client, setup_code, index_entry):
        """Second activation attempt after first success returns 409."""
        resp1 = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": setup_code.code}),
            content_type="application/json",
        )
        assert resp1.status_code == 200

        index_entry.refresh_from_db()

        resp2 = http_client.post(
            _pub_activate_url(),
            data=json.dumps({"code": setup_code.code}),
            content_type="application/json",
        )
        assert resp2.status_code == 409

    def test_invalid_json_returns_400(self, http_client):
        resp = http_client.post(
            _pub_activate_url(),
            data="not json",
            content_type="application/json",
        )
        assert resp.status_code == 400


# ==========================================================================
# EdgeSetupCodeIndex model
# ==========================================================================


@pytest.mark.django_db
class TestEdgeSetupCodeIndexModel:
    def test_create_and_str(self, tenant, setup_code):
        entry = EdgeSetupCodeIndex.objects.create(
            code=setup_code.code,
            tenant=tenant,
            tenant_schema="test_farm",
            setup_code_id=setup_code.pk,
            expires_at=setup_code.expires_at,
        )
        assert "test_farm" in str(entry)
        assert setup_code.code in str(entry)

    def test_unique_code_constraint(self, tenant, setup_code):
        from django.db import IntegrityError

        EdgeSetupCodeIndex.objects.create(
            code=setup_code.code,
            tenant=tenant,
            tenant_schema="test_farm",
            setup_code_id=setup_code.pk,
            expires_at=setup_code.expires_at,
        )
        with pytest.raises(IntegrityError):
            EdgeSetupCodeIndex.objects.create(
                code=setup_code.code,
                tenant=tenant,
                tenant_schema="test_farm",
                setup_code_id=setup_code.pk,
                expires_at=setup_code.expires_at,
            )


# ==========================================================================
# Signal: EdgeSetupCode post_save -> EdgeSetupCodeIndex sync
# ==========================================================================


@pytest.mark.django_db
class TestSetupCodeSignalSync:
    def test_sync_creates_index_entry(self, tenant, site, monkeypatch):
        """When USE_MULTITENANT=True and a tenant context exists, saving an
        EdgeSetupCode should upsert an EdgeSetupCodeIndex row."""
        import scales.signals as sig_mod

        from django.db import connection

        monkeypatch.setattr("django.conf.settings.USE_MULTITENANT", True)
        monkeypatch.setattr(connection, "tenant", SimpleNamespace(schema_name="test_farm"), raising=False)
        monkeypatch.setattr(sig_mod, "get_public_schema_name", lambda: "public")
        monkeypatch.setattr(sig_mod, "schema_context", _noop_schema_context)

        code = EdgeSetupCode.objects.create(
            site=site,
            edge_name="Signal Edge",
            expires_at=timezone.now() + timedelta(hours=24),
        )

        sig_mod.sync_setup_code_to_public_index(code)

        entry = EdgeSetupCodeIndex.objects.get(code=code.code)
        assert entry.tenant == tenant
        assert entry.tenant_schema == "test_farm"
        assert entry.setup_code_id == code.pk
        assert entry.is_consumed is False

    def test_sync_marks_consumed_when_used(self, tenant, site, monkeypatch):
        import scales.signals as sig_mod

        from django.db import connection

        monkeypatch.setattr("django.conf.settings.USE_MULTITENANT", True)
        monkeypatch.setattr(connection, "tenant", SimpleNamespace(schema_name="test_farm"), raising=False)
        monkeypatch.setattr(sig_mod, "get_public_schema_name", lambda: "public")
        monkeypatch.setattr(sig_mod, "schema_context", _noop_schema_context)

        code = EdgeSetupCode.objects.create(
            site=site,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        sig_mod.sync_setup_code_to_public_index(code)

        code.used_at = timezone.now()
        code.save(update_fields=["used_at"])
        sig_mod.sync_setup_code_to_public_index(code)

        entry = EdgeSetupCodeIndex.objects.get(code=code.code)
        assert entry.is_consumed is True

    def test_sync_marks_consumed_when_soft_deleted(self, tenant, site, monkeypatch):
        import scales.signals as sig_mod

        from django.db import connection

        monkeypatch.setattr("django.conf.settings.USE_MULTITENANT", True)
        monkeypatch.setattr(connection, "tenant", SimpleNamespace(schema_name="test_farm"), raising=False)
        monkeypatch.setattr(sig_mod, "get_public_schema_name", lambda: "public")
        monkeypatch.setattr(sig_mod, "schema_context", _noop_schema_context)

        code = EdgeSetupCode.objects.create(
            site=site,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        sig_mod.sync_setup_code_to_public_index(code)

        code.is_active = False
        code.save(update_fields=["is_active"])
        sig_mod.sync_setup_code_to_public_index(code)

        entry = EdgeSetupCodeIndex.objects.get(code=code.code)
        assert entry.is_consumed is True

    def test_remove_deletes_index_entry(self, tenant, site, monkeypatch):
        import scales.signals as sig_mod

        monkeypatch.setattr("django.conf.settings.USE_MULTITENANT", True)
        monkeypatch.setattr(sig_mod, "get_public_schema_name", lambda: "public")
        monkeypatch.setattr(sig_mod, "schema_context", _noop_schema_context)

        EdgeSetupCodeIndex.objects.create(
            code="CT-TEST-XXXX",
            tenant=tenant,
            tenant_schema="test_farm",
            setup_code_id="00000000-0000-0000-0000-000000000000",
            expires_at=timezone.now() + timedelta(hours=24),
        )
        assert EdgeSetupCodeIndex.objects.filter(code="CT-TEST-XXXX").exists()

        sig_mod.remove_setup_code_from_public_index("CT-TEST-XXXX")

        assert not EdgeSetupCodeIndex.objects.filter(code="CT-TEST-XXXX").exists()

    def test_sync_noop_when_multitenant_disabled(self, site, monkeypatch):
        import scales.signals as sig_mod

        monkeypatch.setattr("django.conf.settings.USE_MULTITENANT", False)

        code = EdgeSetupCode.objects.create(
            site=site,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        sig_mod.sync_setup_code_to_public_index(code)
        assert EdgeSetupCodeIndex.objects.count() == 0
