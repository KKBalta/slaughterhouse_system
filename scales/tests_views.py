"""
Tests for scales template-based views: dashboard, session list/detail/create/close/cancel,
edge management, orphaned batches; and pure helpers is_edge_online, is_device_online, _age_seconds.
"""

from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from processing.models import Animal, WeightLog
from reception.models import ServicePackage, SlaughterOrder
from scales.models import DisassemblySession, EdgeDevice, OrphanedBatch, ScaleDevice, Site, WeighingEvent
from scales.views import _age_seconds, is_device_online, is_edge_online
from users.models import ClientProfile, User


def _make_eligible_animal(slaughter_order, tag="TAG-1", animal_type="cattle"):
    """Create an animal eligible for scale session (carcass_ready with hot weight)."""
    a = Animal.objects.create(
        slaughter_order=slaughter_order,
        animal_type=animal_type,
        identification_tag=tag,
    )
    a.perform_slaughter()
    a.save()
    a.prepare_carcass()
    a.save()
    WeightLog.objects.create(
        animal=a,
        slaughter_order=slaughter_order,
        weight=120.5,
        weight_type="hot_carcass_weight",
        is_group_weight=False,
    )
    return a


# ---------- Pure functions ----------


@pytest.mark.django_db
class TestConnectivityHelpers:
    def test_is_edge_online_none_last_seen(self):
        site = Site.objects.create(name="S")
        edge = EdgeDevice.objects.create(site=site, name="E", last_seen_at=None)
        assert is_edge_online(edge) is False

    def test_is_edge_online_recent_seen(self):
        site = Site.objects.create(name="S")
        edge = EdgeDevice.objects.create(site=site, name="E", last_seen_at=timezone.now())
        assert is_edge_online(edge) is True

    def test_is_edge_online_stale_seen(self):
        site = Site.objects.create(name="S")
        edge = EdgeDevice.objects.create(
            site=site,
            name="E",
            last_seen_at=timezone.now() - timedelta(seconds=120),
        )
        assert is_edge_online(edge) is False

    def test_is_edge_online_custom_timeout(self):
        site = Site.objects.create(name="S")
        edge = EdgeDevice.objects.create(
            site=site,
            name="E",
            last_seen_at=timezone.now() - timedelta(seconds=30),
        )
        assert is_edge_online(edge, timeout_seconds=20) is False
        assert is_edge_online(edge, timeout_seconds=60) is True

    def test_is_device_online_none_heartbeat(self):
        site = Site.objects.create(name="S")
        edge = EdgeDevice.objects.create(site=site, name="E")
        device = ScaleDevice.objects.create(
            edge=edge,
            device_id="D1",
            global_device_id="g1",
            last_heartbeat_at=None,
        )
        assert is_device_online(device) is False

    def test_is_device_online_recent_heartbeat(self):
        site = Site.objects.create(name="S")
        edge = EdgeDevice.objects.create(site=site, name="E")
        device = ScaleDevice.objects.create(
            edge=edge,
            device_id="D1",
            global_device_id="g1",
            last_heartbeat_at=timezone.now(),
        )
        assert is_device_online(device) is True

    def test_is_device_online_stale_heartbeat(self):
        site = Site.objects.create(name="S")
        edge = EdgeDevice.objects.create(site=site, name="E")
        device = ScaleDevice.objects.create(
            edge=edge,
            device_id="D1",
            global_device_id="g1",
            last_heartbeat_at=timezone.now() - timedelta(seconds=120),
        )
        assert is_device_online(device) is False

    def test_age_seconds_none(self):
        assert _age_seconds(None) is None

    def test_age_seconds_recent(self):
        past = timezone.now() - timedelta(seconds=10)
        age = _age_seconds(past)
        assert age is not None
        assert 9 <= age <= 11


# ---------- Fixtures for view tests ----------


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="scales_admin",
        password="testpass123",
        role=User.Role.ADMIN,
        is_staff=True,
    )


@pytest.fixture
def operator_user(db):
    return User.objects.create_user(
        username="scales_operator",
        password="testpass123",
        role=User.Role.OPERATOR,
    )


@pytest.fixture
def auth_client(db, admin_user):
    client = Client()
    client.force_login(admin_user)
    return client


@pytest.fixture
def site(db):
    return Site.objects.create(name="Test Site", address="")


@pytest.fixture
def edge_device(db, site):
    return EdgeDevice.objects.create(
        site=site,
        name="Test Edge",
        is_active=True,
        last_seen_at=timezone.now(),
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
def eligible_animal(db, site):
    user = User.objects.create_user(
        username="c",
        password="p",
        role=User.Role.CLIENT,
    )
    cp = ClientProfile.objects.create(
        user=user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        phone_number="1",
        address="a",
    )
    pkg = ServicePackage.objects.create(name="Pkg", includes_disassembly=True)
    order = SlaughterOrder.objects.create(
        client=cp,
        order_datetime=timezone.now(),
        service_package=pkg,
    )
    return _make_eligible_animal(order, "ELIG-1")


@pytest.fixture
def active_session(db, site, scale_device, eligible_animal):
    session = DisassemblySession.objects.create(
        site=site,
        device=scale_device,
        animal=eligible_animal,
        operator="op",
        started_at=timezone.now(),
        status="active",
        is_active=True,
    )
    session.animals.set([eligible_animal])
    return session


# ---------- ScalesDashboardView ----------


@pytest.mark.django_db
class TestScalesDashboardView:
    def test_dashboard_requires_login(self, client):
        resp = client.get(reverse("scales:dashboard"))
        assert resp.status_code == 302
        assert "login" in resp.url

    def test_dashboard_200_with_context(self, auth_client, site, edge_device):
        resp = auth_client.get(reverse("scales:dashboard"))
        assert resp.status_code == 200
        assert "sites" in resp.context
        assert "edges" in resp.context
        assert "active_sessions" in resp.context
        assert "pending_batches" in resp.context
        assert list(resp.context["sites"]) == [site]
        assert list(resp.context["edges"]) == [edge_device]
        assert resp.context["pending_batches"] == 0


# ---------- SessionListView ----------


@pytest.mark.django_db
class TestSessionListView:
    def test_session_list_requires_login(self, client):
        resp = client.get(reverse("scales:session_list"))
        assert resp.status_code == 302

    def test_session_list_200_with_sessions(self, auth_client, active_session):
        resp = auth_client.get(reverse("scales:session_list"))
        assert resp.status_code == 200
        assert "sessions" in resp.context
        assert resp.context["object_list"].count() >= 1
        assert "status_filter" in resp.context
        assert "status_choices" in resp.context

    def test_session_list_filter_by_status(self, auth_client, active_session):
        resp = auth_client.get(
            reverse("scales:session_list"),
            {"status": "active"},
        )
        assert resp.status_code == 200
        assert resp.context["status_filter"] == "active"


# ---------- SessionDetailView ----------


@pytest.mark.django_db
class TestSessionDetailView:
    def test_session_detail_requires_login(self, client, active_session):
        resp = client.get(
            reverse("scales:session_detail", kwargs={"pk": active_session.pk}),
        )
        assert resp.status_code == 302

    def test_session_detail_200_with_events(self, auth_client, active_session, site, scale_device):
        WeighingEvent.objects.create(
            site=site,
            session=active_session,
            device=scale_device,
            animal=active_session.animal,
            plu_code="1",
            product_name="P",
            weight_grams=1000,
            barcode="",
            scale_timestamp=timezone.now(),
            edge_received_at=timezone.now(),
            edge_event_id="ev-detail-1",
        )
        resp = auth_client.get(
            reverse("scales:session_detail", kwargs={"pk": active_session.pk}),
        )
        assert resp.status_code == 200
        assert resp.context["session"] == active_session
        assert "events" in resp.context
        assert len(resp.context["events"]) == 1


# ---------- SessionEventsJsonView ----------


@pytest.mark.django_db
class TestSessionEventsJsonView:
    def test_events_json_returns_session_data(self, auth_client, active_session, site, scale_device):
        WeighingEvent.objects.create(
            site=site,
            session=active_session,
            device=scale_device,
            animal=active_session.animal,
            plu_code="101",
            product_name="Product",
            weight_grams=500,
            barcode="",
            scale_timestamp=timezone.now(),
            edge_received_at=timezone.now(),
            edge_event_id="ev-json-1",
        )
        resp = auth_client.get(
            reverse(
                "scales:session_events_json",
                kwargs={"pk": active_session.pk},
            ),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == str(active_session.id)
        assert data["status"] == "active"
        # events list is from DB; session.event_count/total_weight_grams are denormalized (updated by Edge API)
        assert len(data["events"]) == 1
        assert data["events"][0]["plu_code"] == "101"
        assert data["events"][0]["weight_grams"] == 500


# ---------- SessionCloseView ----------


@pytest.mark.django_db
class TestSessionCloseView:
    def test_close_session_redirects_and_updates_status(self, auth_client, active_session):
        url = reverse(
            "scales:session_close",
            kwargs={"pk": active_session.pk},
        )
        resp = auth_client.post(url, {"close_reason": "Done"})
        assert resp.status_code == 302
        active_session.refresh_from_db()
        assert active_session.status == "completed"
        assert active_session.ended_at is not None
        assert active_session.close_reason == "Done"

    def test_close_already_closed_session_warning(self, auth_client, active_session):
        active_session.status = "completed"
        active_session.ended_at = timezone.now()
        active_session.save()
        url = reverse(
            "scales:session_close",
            kwargs={"pk": active_session.pk},
        )
        resp = auth_client.post(url)
        assert resp.status_code == 302
        assert active_session.status == "completed"


# ---------- SessionCancelView ----------


@pytest.mark.django_db
class TestSessionCancelView:
    def test_cancel_session_redirects_and_updates_status(self, auth_client, active_session):
        url = reverse(
            "scales:session_cancel",
            kwargs={"pk": active_session.pk},
        )
        resp = auth_client.post(url, {"close_reason": "Mistake"})
        assert resp.status_code == 302
        active_session.refresh_from_db()
        assert active_session.status == "cancelled"
        assert active_session.ended_at is not None
        assert active_session.close_reason == "Mistake"


# ---------- SessionCreateView ----------


@pytest.mark.django_db
class TestSessionCreateView:
    def test_session_create_get_200_with_form(self, auth_client, site, edge_device, scale_device):
        resp = auth_client.get(reverse("scales:session_create"))
        assert resp.status_code == 200
        assert "form" in resp.context
        assert "sites" in resp.context
        assert "initial_animals" in resp.context

    def test_session_create_post_creates_session_and_redirects(
        self, auth_client, site, edge_device, scale_device, eligible_animal
    ):
        url = reverse("scales:session_create")
        resp = auth_client.post(
            url,
            {
                "site_id": str(site.id),
                "device": str(scale_device.id),
                "animal_ids": [str(eligible_animal.id)],
            },
        )
        assert resp.status_code == 302
        assert "/scales/sessions/" in resp.url
        session = DisassemblySession.objects.filter(
            device=scale_device,
            status="pending",
            is_active=True,
        ).first()
        assert session is not None
        assert session.animal_id == eligible_animal.id
        assert list(session.animals.values_list("id", flat=True)) == [eligible_animal.id]


# ---------- EdgeManagementView (admin only) ----------


@pytest.mark.django_db
class TestEdgeManagementView:
    def test_edge_management_requires_admin(self, db, operator_user, client):
        client.force_login(operator_user)
        resp = client.get(reverse("scales:edge_management"))
        assert resp.status_code == 403

    def test_edge_management_200_for_admin(self, auth_client, site, edge_device, scale_device):
        resp = auth_client.get(reverse("scales:edge_management"))
        assert resp.status_code == 200
        assert "sites" in resp.context
        assert "edges" in resp.context
        assert "printers" in resp.context
        assert "recent_logs" in resp.context

    def test_edge_management_filter_by_site(self, auth_client, site, edge_device):
        resp = auth_client.get(
            reverse("scales:edge_management"),
            {"site_id": str(site.id)},
        )
        assert resp.status_code == 200
        assert len(resp.context["edges"]) >= 1
        assert resp.context["selected_site_id"] == str(site.id)


# ---------- EdgeBySiteJsonView, PrintersByEdgeJsonView ----------


@pytest.mark.django_db
class TestEdgeBySiteJsonView:
    def test_edge_by_site_json_requires_admin(self, db, operator_user, client, site):
        client.force_login(operator_user)
        resp = client.get(
            reverse("scales:edge_by_site_json"),
            {"site_id": str(site.id)},
        )
        assert resp.status_code == 403

    def test_edge_by_site_json_returns_edges(self, auth_client, site, edge_device):
        edge_device.last_seen_at = timezone.now()
        edge_device.save()
        resp = auth_client.get(
            reverse("scales:edge_by_site_json"),
            {"site_id": str(site.id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "edges" in data
        assert len(data["edges"]) == 1
        assert data["edges"][0]["id"] == str(edge_device.id)
        assert "is_online" in data["edges"][0]

    def test_edge_by_site_json_empty_without_site_id(self, auth_client):
        resp = auth_client.get(reverse("scales:edge_by_site_json"))
        assert resp.status_code == 200
        assert resp.json()["edges"] == []


@pytest.mark.django_db
class TestPrintersByEdgeJsonView:
    def test_printers_by_edge_json_returns_devices(self, auth_client, edge_device, scale_device):
        resp = auth_client.get(
            reverse("scales:printers_by_edge_json"),
            {"edge_id": str(edge_device.id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "printers" in data
        assert len(data["printers"]) == 1
        assert data["printers"][0]["device_id"] == scale_device.device_id
        assert "is_online" in data["printers"][0]

    def test_printers_by_edge_json_empty_without_edge_id(self, auth_client):
        resp = auth_client.get(reverse("scales:printers_by_edge_json"))
        assert resp.status_code == 200
        assert resp.json()["printers"] == []


# ---------- OrphanedBatchListView ----------


@pytest.mark.django_db
class TestOrphanedBatchListView:
    def test_orphaned_batch_list_200(self, auth_client):
        resp = auth_client.get(reverse("scales:orphaned_batch_list"))
        assert resp.status_code == 200
        assert "batches" in resp.context
        assert resp.context["object_list"].count() == 0

    def test_orphaned_batch_list_shows_pending(self, auth_client, site, edge_device, scale_device):
        OrphanedBatch.objects.create(
            site=site,
            edge=edge_device,
            device=scale_device,
            batch_id="batch-1",
            started_at=timezone.now(),
            status="pending",
            is_active=True,
        )
        resp = auth_client.get(reverse("scales:orphaned_batch_list"))
        assert resp.status_code == 200
        assert resp.context["object_list"].count() == 1
