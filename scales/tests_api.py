"""
Tests for scales Edge API endpoints (api_views).
All 8 endpoints: register, sessions, events, events/batch, offline-batches/ack, config, devices/status, heartbeat.
"""

import json
import uuid

import pytest
from django.test import Client
from django.utils import timezone

from scales.models import DisassemblySession, EdgeDevice, OfflineBatchAck, ScaleDevice, Site, WeighingEvent


# Base path for edge API (no named URL in api_urls; mounted at api/v1/edge/)
def _edge_url(path):
    return f"/api/v1/edge/{path}"


@pytest.fixture
def site(db):
    return Site.objects.create(name="Test Site", address="")


@pytest.fixture
def edge_device(db, site):
    return EdgeDevice.objects.create(
        site=site,
        name="Test Edge",
        is_active=True,
        is_online=False,
        last_seen_at=None,
        version="",
    )


@pytest.fixture
def scale_device(db, edge_device):
    return ScaleDevice.objects.create(
        edge=edge_device,
        device_id="SCALE-01",
        global_device_id=f"{edge_device.id}-SCALE-01",
        device_type="disassembly",
        status="online",
    )


@pytest.fixture
def api_client():
    return Client()


# ---------- edge_register ----------


@pytest.mark.django_db
class TestEdgeRegister:
    def test_post_first_registration_creates_site_and_edge(self, api_client):
        """First registration (no edgeId) creates site and edge, returns edgeId and config."""
        resp = api_client.post(
            _edge_url("register"),
            data=json.dumps({"siteName": "New Plant", "version": "1.0.0"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "edgeId" in data
        assert "siteId" in data
        assert data["siteName"] == "New Plant"
        assert "config" in data
        assert data["config"]["timezone"] == "Europe/Istanbul"

        edge_uuid = uuid.UUID(data["edgeId"])
        edge = EdgeDevice.objects.get(id=edge_uuid)
        assert edge.is_active
        assert edge.is_online
        assert edge.version == "1.0.0"
        assert edge.site.name == "New Plant"

    def test_post_first_registration_reuses_existing_site_by_name(self, api_client, site):
        """First registration with existing site name reuses that site."""
        resp = api_client.post(
            _edge_url("register"),
            data=json.dumps({"siteName": site.name}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["siteId"] == str(site.id)
        assert data["siteName"] == site.name
        EdgeDevice.objects.get(id=data["edgeId"], site=site)

    def test_post_reregister_updates_edge(self, api_client, edge_device):
        """Re-registration with valid edgeId updates edge (online, last_seen, version)."""
        resp = api_client.post(
            _edge_url("register"),
            data=json.dumps(
                {
                    "edgeId": str(edge_device.id),
                    "siteId": str(edge_device.site_id),
                    "siteName": "Updated Name",
                    "version": "2.0.0",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["edgeId"] == str(edge_device.id)
        edge_device.refresh_from_db()
        assert edge_device.is_online is True
        assert edge_device.version == "2.0.0"

    def test_post_register_invalid_edge_id_returns_400(self, api_client):
        resp = api_client.post(
            _edge_url("register"),
            data=json.dumps({"edgeId": "not-a-uuid"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_post_register_unknown_edge_returns_404(self, api_client, site):
        unknown_uuid = uuid.uuid4()
        resp = api_client.post(
            _edge_url("register"),
            data=json.dumps({"edgeId": str(unknown_uuid), "siteId": str(site.id)}),
            content_type="application/json",
        )
        assert resp.status_code == 404
        assert "error" in resp.json()

    def test_register_method_not_allowed(self, api_client):
        resp = api_client.get(_edge_url("register"))
        assert resp.status_code == 405


# ---------- edge_sessions (requires X-Edge-Id) ----------


@pytest.mark.django_db
class TestEdgeSessions:
    def test_get_without_edge_id_returns_401(self, api_client):
        resp = api_client.get(_edge_url("sessions"))
        assert resp.status_code == 401
        assert "X-Edge-Id" in resp.json().get("error", "")

    def test_get_with_invalid_edge_id_returns_401(self, api_client):
        resp = api_client.get(_edge_url("sessions"), HTTP_X_EDGE_ID="not-a-uuid")
        assert resp.status_code == 401

    def test_get_empty_device_ids_returns_empty_sessions(self, api_client, edge_device):
        resp = api_client.get(_edge_url("sessions"), HTTP_X_EDGE_ID=str(edge_device.id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []
        assert "ETag" in resp

    def test_get_with_device_ids_returns_matching_sessions(self, api_client, edge_device, scale_device):
        from processing.models import Animal
        from reception.models import ServicePackage, SlaughterOrder
        from users.models import ClientProfile, User

        user = User.objects.create_user(username="u", password="p", role=User.Role.CLIENT)
        cp = ClientProfile.objects.create(
            user=user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number="1",
            address="a",
        )
        pkg = ServicePackage.objects.create(name="P", includes_disassembly=True)
        order = SlaughterOrder.objects.create(
            client=cp,
            order_datetime=timezone.now(),
            service_package=pkg,
        )
        animal = Animal.objects.create(
            slaughter_order=order,
            animal_type="cattle",
            identification_tag="T1",
        )
        animal.perform_slaughter()
        animal.save()
        animal.prepare_carcass()
        animal.save()

        session = DisassemblySession.objects.create(
            site=edge_device.site,
            device=scale_device,
            animal=animal,
            operator="op",
            started_at=timezone.now(),
            status="pending",
            is_active=True,
        )
        session.animals.set([animal])

        resp = api_client.get(
            _edge_url("sessions"),
            {"device_ids": scale_device.device_id},
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["cloudSessionId"] == str(session.id)
        assert data["sessions"][0]["deviceId"] == scale_device.device_id
        assert data["sessions"][0]["animalTag"] == "T1"

    def test_get_sessions_etag_304(self, api_client, edge_device):
        resp1 = api_client.get(_edge_url("sessions"), HTTP_X_EDGE_ID=str(edge_device.id))
        assert resp1.status_code == 200
        etag = resp1.get("ETag")
        assert etag
        resp2 = api_client.get(
            _edge_url("sessions"),
            HTTP_X_EDGE_ID=str(edge_device.id),
            HTTP_IF_NONE_MATCH=etag,
        )
        assert resp2.status_code == 304

    def test_sessions_method_not_allowed(self, api_client, edge_device):
        resp = api_client.post(_edge_url("sessions"), HTTP_X_EDGE_ID=str(edge_device.id))
        assert resp.status_code == 405


# ---------- edge_post_event ----------


@pytest.mark.django_db
class TestEdgePostEvent:
    def test_post_without_edge_id_returns_401(self, api_client):
        resp = api_client.post(
            _edge_url("events"),
            data=json.dumps({"localEventId": "e1", "deviceId": "d1", "weightGrams": 100}),
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_post_missing_local_event_id_returns_400(self, api_client, edge_device):
        resp = api_client.post(
            _edge_url("events"),
            data=json.dumps({"deviceId": "d1", "weightGrams": 100}),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 400
        assert "localEventId" in resp.json().get("error", "")

    def test_post_creates_event_and_scale_device(self, api_client, edge_device):
        resp = api_client.post(
            _edge_url("events"),
            data=json.dumps(
                {
                    "localEventId": "ev-001",
                    "deviceId": "SCALE-A",
                    "weightGrams": 1500,
                    "pluCode": "101",
                    "productName": "Test Product",
                }
            ),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert "cloudEventId" in data

        event = WeighingEvent.objects.get(edge_event_id="ev-001")
        assert event.weight_grams == 1500
        assert event.plu_code == "101"
        device = ScaleDevice.objects.get(edge=edge_device, device_id="SCALE-A")
        assert device

    def test_post_duplicate_returns_duplicate_status(self, api_client, edge_device, scale_device):
        WeighingEvent.objects.create(
            site=edge_device.site,
            device=scale_device,
            plu_code="1",
            product_name="P",
            weight_grams=100,
            barcode="",
            scale_timestamp=timezone.now(),
            edge_received_at=timezone.now(),
            edge_event_id="dup-1",
        )
        resp = api_client.post(
            _edge_url("events"),
            data=json.dumps(
                {
                    "localEventId": "dup-1",
                    "deviceId": scale_device.device_id,
                    "weightGrams": 200,
                }
            ),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "duplicate"
        assert WeighingEvent.objects.filter(edge_event_id="dup-1").count() == 1

    def test_events_method_not_allowed(self, api_client, edge_device):
        resp = api_client.get(_edge_url("events"), HTTP_X_EDGE_ID=str(edge_device.id))
        assert resp.status_code == 405


# ---------- edge_post_event_batch ----------


@pytest.mark.django_db
class TestEdgePostEventBatch:
    def test_post_batch_accepts_events(self, api_client, edge_device):
        resp = api_client.post(
            _edge_url("events/batch"),
            data=json.dumps(
                {
                    "events": [
                        {"localEventId": "b1", "deviceId": "D1", "weightGrams": 100},
                        {"localEventId": "b2", "deviceId": "D1", "weightGrams": 200},
                    ],
                }
            ),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 2
        assert all(r["status"] == "accepted" for r in results)
        assert WeighingEvent.objects.filter(edge_event_id__in=["b1", "b2"]).count() == 2

    def test_post_batch_missing_local_event_id_fails_item(self, api_client, edge_device):
        resp = api_client.post(
            _edge_url("events/batch"),
            data=json.dumps(
                {
                    "events": [
                        {"localEventId": "", "deviceId": "D1", "weightGrams": 100},
                    ],
                }
            ),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        assert resp.json()["results"][0]["status"] == "failed"
        assert "localEventId" in resp.json()["results"][0].get("error", "")

    def test_post_batch_duplicate_returns_duplicate_per_item(self, api_client, edge_device, scale_device):
        WeighingEvent.objects.create(
            site=edge_device.site,
            device=scale_device,
            plu_code="1",
            product_name="P",
            weight_grams=100,
            barcode="",
            scale_timestamp=timezone.now(),
            edge_received_at=timezone.now(),
            edge_event_id="batch-dup",
        )
        resp = api_client.post(
            _edge_url("events/batch"),
            data=json.dumps(
                {
                    "events": [
                        {"localEventId": "batch-dup", "deviceId": scale_device.device_id, "weightGrams": 99},
                    ],
                }
            ),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        assert resp.json()["results"][0]["status"] == "duplicate"

    def test_batch_method_not_allowed(self, api_client, edge_device):
        resp = api_client.get(_edge_url("events/batch"), HTTP_X_EDGE_ID=str(edge_device.id))
        assert resp.status_code == 405


# ---------- edge_offline_batch_ack ----------


@pytest.mark.django_db
class TestEdgeOfflineBatchAck:
    def test_post_ack_creates_record(self, api_client, edge_device):
        resp = api_client.post(
            _edge_url("offline-batches/ack"),
            data=json.dumps(
                {
                    "batchId": "batch-123",
                    "deviceId": "D1",
                    "eventCount": 5,
                    "totalWeightGrams": 10000,
                }
            ),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "received"
        assert data["batchId"] == "batch-123"
        assert "receivedAt" in data
        ack = OfflineBatchAck.objects.get(batch_id="batch-123")
        assert ack.edge_id == edge_device.id
        assert ack.event_count == 5
        assert ack.total_weight_grams == 10000

    def test_post_ack_missing_batch_id_returns_400(self, api_client, edge_device):
        resp = api_client.post(
            _edge_url("offline-batches/ack"),
            data=json.dumps({"deviceId": "D1"}),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 400
        assert "batchId" in resp.json().get("error", "")

    def test_post_ack_idempotent_returns_already_received(self, api_client, edge_device):
        OfflineBatchAck.objects.create(
            batch_id="idem-batch",
            received_at=timezone.now(),
            edge=edge_device,
            site=edge_device.site,
        )
        resp = api_client.post(
            _edge_url("offline-batches/ack"),
            data=json.dumps({"batchId": "idem-batch", "deviceId": "D1"}),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_received"
        assert OfflineBatchAck.objects.filter(batch_id="idem-batch").count() == 1

    def test_offline_batch_ack_method_not_allowed(self, api_client, edge_device):
        resp = api_client.get(
            _edge_url("offline-batches/ack"),
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 405


# ---------- edge_config ----------


@pytest.mark.django_db
class TestEdgeConfig:
    def test_get_returns_config(self, api_client, edge_device):
        resp = api_client.get(_edge_url("config"), HTTP_X_EDGE_ID=str(edge_device.id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["edgeId"] == str(edge_device.id)
        assert "sessionPollIntervalMs" in data
        assert data["timezone"] == "Europe/Istanbul"

    def test_config_method_not_allowed(self, api_client, edge_device):
        resp = api_client.post(_edge_url("config"), HTTP_X_EDGE_ID=str(edge_device.id))
        assert resp.status_code == 405


# ---------- edge_device_status ----------


@pytest.mark.django_db
class TestEdgeDeviceStatus:
    def test_post_creates_or_updates_device(self, api_client, edge_device):
        resp = api_client.post(
            _edge_url("devices/status"),
            data=json.dumps(
                {
                    "deviceId": "PRINTER-01",
                    "status": "online",
                    "deviceType": "disassembly",
                }
            ),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        dev = ScaleDevice.objects.get(edge=edge_device, device_id="PRINTER-01")
        assert dev.status == "online"
        assert dev.device_type == "disassembly"

    def test_post_update_existing_device(self, api_client, edge_device, scale_device):
        resp = api_client.post(
            _edge_url("devices/status"),
            data=json.dumps(
                {
                    "deviceId": scale_device.device_id,
                    "status": "idle",
                }
            ),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        scale_device.refresh_from_db()
        assert scale_device.status == "idle"

    def test_post_missing_device_id_returns_400(self, api_client, edge_device):
        resp = api_client.post(
            _edge_url("devices/status"),
            data=json.dumps({"status": "online"}),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 400
        assert "deviceId" in resp.json().get("error", "")

    def test_device_status_method_not_allowed(self, api_client, edge_device):
        resp = api_client.get(
            _edge_url("devices/status"),
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 405


# ---------- edge_heartbeat ----------


@pytest.mark.django_db
class TestEdgeHeartbeat:
    def test_post_updates_edge_and_devices(self, api_client, edge_device):
        resp = api_client.post(
            _edge_url("heartbeat"),
            data=json.dumps(
                {
                    "version": "3.0",
                    "devices": [
                        {"deviceId": "D1", "status": "online"},
                        {"deviceId": "D2", "status": "idle"},
                    ],
                }
            ),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "serverTime" in data
        edge_device.refresh_from_db()
        assert edge_device.is_online is True
        assert edge_device.version == "3.0"
        assert ScaleDevice.objects.filter(edge=edge_device).count() == 2

    def test_heartbeat_method_not_allowed(self, api_client, edge_device):
        resp = api_client.get(_edge_url("heartbeat"), HTTP_X_EDGE_ID=str(edge_device.id))
        assert resp.status_code == 405
