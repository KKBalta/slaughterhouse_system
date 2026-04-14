"""Tests for POST /api/v1/edge/activate, setup-code dashboard views, and edge management."""

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from scales.models import EdgeDevice, EdgeSetupCode, Printer, ScaleDevice, Site
from users.models import User


def _edge_url(path):
    return f"/api/v1/edge/{path}"


@pytest.fixture
def api_client():
    return Client()


@pytest.fixture(autouse=True)
def _no_activate_rate_limit(monkeypatch):
    def _noop(_key, _window):
        return 0

    monkeypatch.setattr("tenants.redis_support.atomic_rate_incr", _noop)


# ---------- Fixtures for dashboard view tests ----------


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="setup_admin",
        password="testpass123",
        role=User.Role.ADMIN,
        is_staff=True,
    )


@pytest.fixture
def auth_client(db, admin_user):
    client = Client()
    client.force_login(admin_user)
    return client


@pytest.fixture
def site(db):
    return Site.objects.create(name="Test Site", address="")


# ==========================================================================
# POST /api/v1/edge/activate
# ==========================================================================


@pytest.mark.django_db
class TestEdgeActivate:
    def test_activate_success(self, api_client):
        site = Site.objects.create(name="Test Site", address="")
        valid_code = EdgeSetupCode.objects.create(
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
        resp = api_client.post(
            _edge_url("activate"),
            data=json.dumps({"code": valid_code.code, "version": "0.1.0"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "edgeId" in data
        assert "siteId" in data
        assert data["siteName"] == "Test Site"
        assert "config" in data
        assert "baseUrl" in data["config"]

        # Verify all printer fields are present and correct
        assert len(data["printers"]) == 1
        p = data["printers"][0]
        assert p["localPrinterId"] == "carcass-01"
        assert p["host"] == "192.168.1.220"
        assert p["port"] == 9100
        assert p["role"] == "carcass"
        assert p["displayName"] == "Carcass Line"
        assert p["transport"] == "tcp"
        assert p["model"] == ""
        assert p["priority"] == 100

        valid_code.refresh_from_db()
        assert valid_code.used_at is not None
        assert valid_code.used_by_edge is not None

    def test_activate_already_used(self, api_client):
        site = Site.objects.create(name="Test Site", address="")
        valid_code = EdgeSetupCode.objects.create(
            site=site,
            edge_name="Test Edge",
            expires_at=timezone.now() + timedelta(hours=48),
        )
        api_client.post(
            _edge_url("activate"),
            data=json.dumps({"code": valid_code.code, "version": "0.1.0"}),
            content_type="application/json",
        )
        resp = api_client.post(
            _edge_url("activate"),
            data=json.dumps({"code": valid_code.code, "version": "0.1.0"}),
            content_type="application/json",
        )
        assert resp.status_code == 409

    def test_activate_expired(self, api_client):
        site = Site.objects.create(name="Test Site", address="")
        expired_code = EdgeSetupCode.objects.create(
            site=site,
            edge_name="Expired Edge",
            expires_at=timezone.now() - timedelta(hours=1),
        )
        resp = api_client.post(
            _edge_url("activate"),
            data=json.dumps({"code": expired_code.code, "version": "0.1.0"}),
            content_type="application/json",
        )
        assert resp.status_code == 410

    def test_activate_unknown_code(self, api_client):
        Site.objects.create(name="Test Site", address="")
        resp = api_client.post(
            _edge_url("activate"),
            data=json.dumps({"code": "CT-XXXX-XXXX", "version": "0.1.0"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_activate_case_insensitive(self, api_client):
        site = Site.objects.create(name="Test Site", address="")
        valid_code = EdgeSetupCode.objects.create(
            site=site,
            edge_name="Test Edge",
            expires_at=timezone.now() + timedelta(hours=48),
        )
        resp = api_client.post(
            _edge_url("activate"),
            data=json.dumps({"code": valid_code.code.lower(), "version": "0.1.0"}),
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_activate_creates_edge_device(self, api_client):
        site = Site.objects.create(name="Test Site", address="")
        valid_code = EdgeSetupCode.objects.create(
            site=site,
            edge_name="Test Edge",
            expires_at=timezone.now() + timedelta(hours=48),
        )
        assert EdgeDevice.objects.count() == 0
        api_client.post(
            _edge_url("activate"),
            data=json.dumps({"code": valid_code.code, "version": "0.1.0"}),
            content_type="application/json",
        )
        assert EdgeDevice.objects.count() == 1
        edge = EdgeDevice.objects.first()
        assert edge.site == site
        assert edge.name == "Test Edge"
        assert edge.is_online

    def test_activate_edge_name_falls_back_to_site_name(self, api_client):
        """When edge_name is blank, the created EdgeDevice uses the site name."""
        site = Site.objects.create(name="Ankara Main Plant", address="")
        code = EdgeSetupCode.objects.create(
            site=site,
            edge_name="",
            expires_at=timezone.now() + timedelta(hours=48),
        )
        resp = api_client.post(
            _edge_url("activate"),
            data=json.dumps({"code": code.code, "version": "0.1.0"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        edge = EdgeDevice.objects.first()
        assert edge.name == "Ankara Main Plant"

    def test_activate_stores_version(self, api_client):
        site = Site.objects.create(name="Test Site", address="")
        code = EdgeSetupCode.objects.create(
            site=site,
            expires_at=timezone.now() + timedelta(hours=48),
        )
        api_client.post(
            _edge_url("activate"),
            data=json.dumps({"code": code.code, "version": "2.3.1"}),
            content_type="application/json",
        )
        edge = EdgeDevice.objects.first()
        assert edge.version == "2.3.1"

    def test_activate_empty_code(self, api_client):
        Site.objects.create(name="Test Site", address="")
        resp = api_client.post(
            _edge_url("activate"),
            data=json.dumps({"code": "", "version": "0.1.0"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_activate_revoked_code_returns_404(self, api_client):
        site = Site.objects.create(name="Test Site", address="")
        valid_code = EdgeSetupCode.objects.create(
            site=site,
            edge_name="Test Edge",
            expires_at=timezone.now() + timedelta(hours=48),
        )
        valid_code.soft_delete()
        resp = api_client.post(
            _edge_url("activate"),
            data=json.dumps({"code": valid_code.code, "version": "0.1.0"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_activate_no_printers_returns_empty_list(self, api_client):
        site = Site.objects.create(name="Test Site", address="")
        code = EdgeSetupCode.objects.create(
            site=site,
            edge_name="No Printers Edge",
            expires_at=timezone.now() + timedelta(hours=48),
        )
        resp = api_client.post(
            _edge_url("activate"),
            data=json.dumps({"code": code.code, "version": "0.1.0"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["printers"] == []

    def test_activate_multi_printer_config(self, api_client):
        """Setup code with multiple printers returns all of them."""
        site = Site.objects.create(name="Test Site", address="")
        code = EdgeSetupCode.objects.create(
            site=site,
            printers_config=[
                {"localPrinterId": "carcass-01", "host": "10.0.0.1", "port": 9100, "role": "carcass"},
                {"localPrinterId": "product-01", "host": "10.0.0.2", "port": 9100, "role": "meat_cut"},
            ],
            expires_at=timezone.now() + timedelta(hours=48),
        )
        resp = api_client.post(
            _edge_url("activate"),
            data=json.dumps({"code": code.code, "version": "0.1.0"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        printers = resp.json()["printers"]
        assert len(printers) == 2
        assert printers[0]["localPrinterId"] == "carcass-01"
        assert printers[1]["localPrinterId"] == "product-01"

    def test_method_not_allowed(self, api_client):
        resp = api_client.get(_edge_url("activate"))
        assert resp.status_code == 405


# ==========================================================================
# EdgeSetupCode model
# ==========================================================================


@pytest.mark.django_db
class TestEdgeSetupCodeModel:
    def test_generate_code_format(self):
        site = Site.objects.create(name="S", address="")
        code = EdgeSetupCode.objects.create(
            site=site, expires_at=timezone.now() + timedelta(hours=1)
        )
        assert code.code.startswith("CT-")
        parts = code.code.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4

    def test_is_valid_active(self):
        site = Site.objects.create(name="S", address="")
        code = EdgeSetupCode.objects.create(
            site=site, expires_at=timezone.now() + timedelta(hours=1)
        )
        assert code.is_valid() is True

    def test_is_valid_expired(self):
        site = Site.objects.create(name="S", address="")
        code = EdgeSetupCode.objects.create(
            site=site, expires_at=timezone.now() - timedelta(hours=1)
        )
        assert code.is_valid() is False

    def test_is_valid_used(self):
        site = Site.objects.create(name="S", address="")
        code = EdgeSetupCode.objects.create(
            site=site,
            expires_at=timezone.now() + timedelta(hours=1),
            used_at=timezone.now(),
        )
        assert code.is_valid() is False

    def test_str_active(self):
        site = Site.objects.create(name="MySite", address="")
        code = EdgeSetupCode.objects.create(
            site=site, expires_at=timezone.now() + timedelta(hours=1)
        )
        assert "(active)" in str(code)
        assert "MySite" in str(code)

    def test_str_used(self):
        site = Site.objects.create(name="MySite", address="")
        code = EdgeSetupCode.objects.create(
            site=site,
            expires_at=timezone.now() + timedelta(hours=1),
            used_at=timezone.now(),
        )
        assert "(used)" in str(code)

    def test_unique_code(self):
        from django.db import IntegrityError

        site = Site.objects.create(name="S", address="")
        code = EdgeSetupCode.objects.create(
            site=site, expires_at=timezone.now() + timedelta(hours=1)
        )
        with pytest.raises(IntegrityError):
            EdgeSetupCode.objects.create(
                site=site,
                code=code.code,
                expires_at=timezone.now() + timedelta(hours=1),
            )


# ==========================================================================
# Dashboard views: list, create, detail, revoke
# ==========================================================================


@pytest.mark.django_db
class TestEdgeSetupCodeListView:
    def test_list_requires_login(self, api_client):
        resp = api_client.get(reverse("scales:edge_setup_code_list"))
        assert resp.status_code == 302
        assert "/login" in resp.url or "/accounts/login" in resp.url

    def test_list_renders_for_admin(self, auth_client, site):
        EdgeSetupCode.objects.create(
            site=site, edge_name="E1", expires_at=timezone.now() + timedelta(hours=24)
        )
        resp = auth_client.get(reverse("scales:edge_setup_code_list"))
        assert resp.status_code == 200
        assert b"E1" in resp.content

    def test_list_excludes_soft_deleted(self, auth_client, site):
        code = EdgeSetupCode.objects.create(
            site=site, edge_name="Deleted", expires_at=timezone.now() + timedelta(hours=24)
        )
        code.soft_delete()
        resp = auth_client.get(reverse("scales:edge_setup_code_list"))
        assert resp.status_code == 200
        assert b"Deleted" not in resp.content


@pytest.mark.django_db
class TestEdgeSetupCodeCreateView:
    def test_create_get_renders_form(self, auth_client, site):
        resp = auth_client.get(reverse("scales:edge_setup_code_create"))
        assert resp.status_code == 200
        assert b"Add Edge Device" in resp.content

    def test_create_post_creates_code(self, auth_client, site):
        resp = auth_client.post(
            reverse("scales:edge_setup_code_create"),
            data={
                "site_id": str(site.id),
                "edge_name": "My Edge",
                "expiry_hours": "24",
            },
        )
        assert resp.status_code == 302
        assert EdgeSetupCode.objects.count() == 1
        code = EdgeSetupCode.objects.first()
        assert code.site == site
        assert code.edge_name == "My Edge"

    def test_create_post_with_manual_printers(self, auth_client, site):
        resp = auth_client.post(
            reverse("scales:edge_setup_code_create"),
            data={
                "site_id": str(site.id),
                "edge_name": "Printer Edge",
                "expiry_hours": "48",
                "manual_printer_host": ["192.168.1.100", "192.168.1.101"],
                "manual_printer_role": ["carcass", "meat_cut"],
                "manual_printer_name": ["Main", "Product"],
            },
        )
        assert resp.status_code == 302
        code = EdgeSetupCode.objects.first()
        assert len(code.printers_config) == 2
        assert code.printers_config[0]["host"] == "192.168.1.100"
        assert code.printers_config[0]["role"] == "carcass"
        assert code.printers_config[1]["host"] == "192.168.1.101"

    def test_create_post_skips_empty_printer_hosts(self, auth_client, site):
        resp = auth_client.post(
            reverse("scales:edge_setup_code_create"),
            data={
                "site_id": str(site.id),
                "edge_name": "",
                "expiry_hours": "48",
                "manual_printer_host": ["", "192.168.1.200"],
                "manual_printer_role": ["generic", "carcass"],
                "manual_printer_name": ["", "Real"],
            },
        )
        assert resp.status_code == 302
        code = EdgeSetupCode.objects.first()
        assert len(code.printers_config) == 1
        assert code.printers_config[0]["host"] == "192.168.1.200"

    def test_create_post_missing_site_shows_error(self, auth_client):
        resp = auth_client.post(
            reverse("scales:edge_setup_code_create"),
            data={"site_id": "", "edge_name": "", "expiry_hours": "48"},
        )
        assert resp.status_code == 302  # redirect back to form

    def test_create_post_invalid_expiry_uses_default(self, auth_client, site):
        auth_client.post(
            reverse("scales:edge_setup_code_create"),
            data={
                "site_id": str(site.id),
                "edge_name": "",
                "expiry_hours": "garbage",
            },
        )
        code = EdgeSetupCode.objects.first()
        hours_diff = (code.expires_at - code.created_at).total_seconds() / 3600
        assert 47 < hours_diff < 49  # ~48 hours default

    def test_create_requires_login(self, api_client):
        resp = api_client.get(reverse("scales:edge_setup_code_create"))
        assert resp.status_code == 302


@pytest.mark.django_db
class TestEdgeSetupCodeDetailView:
    def test_detail_renders(self, auth_client, site):
        code = EdgeSetupCode.objects.create(
            site=site,
            edge_name="Detail Edge",
            printers_config=[{"localPrinterId": "p1", "host": "10.0.0.1", "port": 9100, "role": "carcass"}],
            expires_at=timezone.now() + timedelta(hours=48),
        )
        resp = auth_client.get(reverse("scales:edge_setup_code_detail", kwargs={"pk": code.pk}))
        assert resp.status_code == 200
        assert code.code.encode() in resp.content
        assert b"10.0.0.1" in resp.content

    def test_detail_shows_tenant_url(self, auth_client, site):
        code = EdgeSetupCode.objects.create(
            site=site, expires_at=timezone.now() + timedelta(hours=48)
        )
        resp = auth_client.get(reverse("scales:edge_setup_code_detail", kwargs={"pk": code.pk}))
        assert resp.status_code == 200
        assert b"Cloud API URL" in resp.content

    def test_detail_404_for_soft_deleted(self, auth_client, site):
        code = EdgeSetupCode.objects.create(
            site=site, expires_at=timezone.now() + timedelta(hours=48)
        )
        code.soft_delete()
        resp = auth_client.get(reverse("scales:edge_setup_code_detail", kwargs={"pk": code.pk}))
        assert resp.status_code == 404

    def test_detail_requires_login(self, api_client, site):
        code = EdgeSetupCode.objects.create(
            site=site, expires_at=timezone.now() + timedelta(hours=48)
        )
        resp = api_client.get(reverse("scales:edge_setup_code_detail", kwargs={"pk": code.pk}))
        assert resp.status_code == 302


@pytest.mark.django_db
class TestEdgeSetupCodeRevokeView:
    def test_revoke_soft_deletes(self, auth_client, site):
        code = EdgeSetupCode.objects.create(
            site=site, expires_at=timezone.now() + timedelta(hours=48)
        )
        resp = auth_client.post(reverse("scales:edge_setup_code_revoke", kwargs={"pk": code.pk}))
        assert resp.status_code == 302
        code.refresh_from_db()
        assert code.is_active is False

    def test_revoke_already_used_fails(self, auth_client, site):
        code = EdgeSetupCode.objects.create(
            site=site,
            expires_at=timezone.now() + timedelta(hours=48),
            used_at=timezone.now(),
        )
        resp = auth_client.post(reverse("scales:edge_setup_code_revoke", kwargs={"pk": code.pk}))
        assert resp.status_code == 302
        code.refresh_from_db()
        assert code.is_active is True  # should NOT have been revoked

    def test_revoke_requires_post(self, auth_client, site):
        code = EdgeSetupCode.objects.create(
            site=site, expires_at=timezone.now() + timedelta(hours=48)
        )
        resp = auth_client.get(reverse("scales:edge_setup_code_revoke", kwargs={"pk": code.pk}))
        assert resp.status_code == 405

    def test_revoke_requires_login(self, api_client, site):
        code = EdgeSetupCode.objects.create(
            site=site, expires_at=timezone.now() + timedelta(hours=48)
        )
        resp = api_client.post(reverse("scales:edge_setup_code_revoke", kwargs={"pk": code.pk}))
        assert resp.status_code == 302
        assert "/login" in resp.url or "/accounts/login" in resp.url


# ==========================================================================
# Edge device removal from Edge Management
# ==========================================================================


@pytest.mark.django_db
class TestEdgeDeviceRemoveView:
    def test_remove_soft_deletes_edge(self, auth_client, site):
        edge = EdgeDevice.objects.create(site=site, name="Test Edge", is_online=False)
        resp = auth_client.post(reverse("scales:edge_device_remove", kwargs={"pk": edge.pk}))
        assert resp.status_code == 302
        edge.refresh_from_db()
        assert edge.is_active is False

    def test_remove_also_deactivates_scale_devices(self, auth_client, site):
        edge = EdgeDevice.objects.create(site=site, name="Test Edge")
        sd = ScaleDevice.objects.create(
            edge=edge,
            device_id="SCALE-01",
            global_device_id="TEST-SCALE-01",
        )
        resp = auth_client.post(reverse("scales:edge_device_remove", kwargs={"pk": edge.pk}))
        assert resp.status_code == 302
        sd.refresh_from_db()
        assert sd.is_active is False

    def test_remove_also_deactivates_printers(self, auth_client, site):
        edge = EdgeDevice.objects.create(site=site, name="Test Edge")
        printer = Printer.objects.create(
            edge=edge,
            site=site,
            local_printer_id="printer-01",
            host="192.168.1.100",
            port=9100,
        )
        resp = auth_client.post(reverse("scales:edge_device_remove", kwargs={"pk": edge.pk}))
        assert resp.status_code == 302
        printer.refresh_from_db()
        assert printer.is_active is False
        assert printer.enabled is False

    def test_remove_blocked_by_active_sessions(self, auth_client, site):
        from scales.models import DisassemblySession

        edge = EdgeDevice.objects.create(site=site, name="Busy Edge")
        sd = ScaleDevice.objects.create(
            edge=edge,
            device_id="SCALE-01",
            global_device_id="BUSY-SCALE-01",
        )
        DisassemblySession.objects.create(
            site=site,
            device=sd,
            operator="test",
            started_at=timezone.now(),
            status="active",
        )
        resp = auth_client.post(reverse("scales:edge_device_remove", kwargs={"pk": edge.pk}))
        assert resp.status_code == 302
        edge.refresh_from_db()
        assert edge.is_active is True  # NOT removed

    def test_remove_nonexistent_edge_shows_error(self, auth_client):
        import uuid

        fake_pk = uuid.uuid4()
        resp = auth_client.post(reverse("scales:edge_device_remove", kwargs={"pk": fake_pk}))
        assert resp.status_code == 302

    def test_remove_already_deleted_edge_shows_error(self, auth_client, site):
        edge = EdgeDevice.objects.create(site=site, name="Deleted Edge", is_active=False)
        resp = auth_client.post(reverse("scales:edge_device_remove", kwargs={"pk": edge.pk}))
        assert resp.status_code == 302
        # Should still be inactive
        edge.refresh_from_db()
        assert edge.is_active is False

    def test_remove_requires_login(self, api_client, site):
        edge = EdgeDevice.objects.create(site=site, name="Test Edge")
        resp = api_client.post(reverse("scales:edge_device_remove", kwargs={"pk": edge.pk}))
        assert resp.status_code == 302
        assert "/login" in resp.url or "/accounts/login" in resp.url

    def test_remove_requires_post(self, auth_client, site):
        edge = EdgeDevice.objects.create(site=site, name="Test Edge")
        resp = auth_client.get(reverse("scales:edge_device_remove", kwargs={"pk": edge.pk}))
        assert resp.status_code == 405
