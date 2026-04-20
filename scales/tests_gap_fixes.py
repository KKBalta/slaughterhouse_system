"""
Tests for printer flow gap fixes: A, E, F, G and Activation Feedback.

Gap A — Terminal state guard in edge_ack_print_job
Gap E — labelCount uses j.quantity instead of hardcoded 1
Gap F — Pending jobs filtered by claimed_by_edge for multi-edge safety
Gap G — cleanup_stale_print_jobs management command
Activation Feedback — EdgeSetupCodeDetailView context with edge status
"""

import json
import uuid
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from labeling.models import PrintJob
from labeling.services import enqueue_print_job
from scales.models import EdgeDevice, EdgeSetupCode, Printer, Site
from users.models import User


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
        is_online=True,
        last_seen_at=timezone.now(),
        version="1.0.0",
    )


@pytest.fixture
def api_client():
    return Client()


@pytest.fixture(autouse=True)
def _no_edge_rate_limit(monkeypatch):
    def _noop(_key, _window):
        return 0

    monkeypatch.setattr("tenants.redis_support.atomic_rate_incr", _noop)


# ==========================================================================
# Gap A — Terminal state guard in edge_ack_print_job
# ==========================================================================


@pytest.mark.django_db
class TestGapA_TerminalStateGuard:
    def test_ack_on_cancelled_job_returns_ignored(self, api_client, edge_device):
        """ACK on a cancelled job returns 200 with ignored=True, does not change status."""
        job = enqueue_print_job(
            site=edge_device.site,
            prn_content="SIZE 1 mm, 1 mm\r\nPRINT 1,1\r\n",
            target_role="carcass",
        )
        job.status = "cancelled"
        job.save(update_fields=["status", "updated_at"])

        resp = api_client.post(
            _edge_url(f"print-jobs/{job.id}/ack"),
            data=json.dumps({"status": "completed", "attempts": 1}),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["ignored"] is True
        assert "already cancelled" in data["reason"]

        job.refresh_from_db()
        assert job.status == "cancelled"

    def test_ack_on_completed_job_returns_ignored(self, api_client, edge_device):
        """ACK on a completed job returns 200 with ignored=True, does not change status."""
        job = enqueue_print_job(site=edge_device.site, prn_content="X", target_role="carcass")
        job.status = "completed"
        job.printed_at = timezone.now()
        job.save(update_fields=["status", "printed_at", "updated_at"])

        resp = api_client.post(
            _edge_url(f"print-jobs/{job.id}/ack"),
            data=json.dumps({"status": "failed", "errorText": "paper jam"}),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ignored"] is True
        assert "already completed" in data["reason"]

        job.refresh_from_db()
        assert job.status == "completed"

    def test_ack_on_pending_job_still_works(self, api_client, edge_device):
        """Normal ACK on a pending job still processes correctly."""
        job = enqueue_print_job(site=edge_device.site, prn_content="X", target_role="carcass")
        resp = api_client.post(
            _edge_url(f"print-jobs/{job.id}/ack"),
            data=json.dumps({"status": "completed", "attempts": 1}),
            content_type="application/json",
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json().get("ignored") is not True

        job.refresh_from_db()
        assert job.status == "completed"


# ==========================================================================
# Gap E — labelCount from j.quantity
# ==========================================================================


@pytest.mark.django_db
class TestGapE_LabelCount:
    def test_pending_returns_quantity_as_label_count(self, api_client, edge_device):
        """Pending jobs endpoint returns j.quantity as labelCount."""
        job = enqueue_print_job(site=edge_device.site, prn_content="X", target_role="carcass")
        job.quantity = 5
        job.save(update_fields=["quantity", "updated_at"])

        resp = api_client.get(
            _edge_url("print-jobs/pending"),
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        assert len(jobs) == 1
        assert jobs[0]["labelCount"] == 5

    def test_pending_default_quantity_is_1(self, api_client, edge_device):
        """Default quantity=1 still returns labelCount=1."""
        enqueue_print_job(site=edge_device.site, prn_content="X", target_role="carcass")
        resp = api_client.get(
            _edge_url("print-jobs/pending"),
            HTTP_X_EDGE_ID=str(edge_device.id),
        )
        assert resp.status_code == 200
        assert resp.json()["jobs"][0]["labelCount"] == 1


# ==========================================================================
# Gap F — Multi-edge claimed_by_edge filter
# ==========================================================================


@pytest.mark.django_db
class TestGapF_MultiEdgeClaim:
    def test_pending_excludes_jobs_claimed_by_other_edge(self, api_client, site):
        """Jobs claimed by another edge are not visible to this edge."""
        edge_a = EdgeDevice.objects.create(site=site, name="Edge A", is_active=True, is_online=True)
        edge_b = EdgeDevice.objects.create(site=site, name="Edge B", is_active=True, is_online=True)
        job = enqueue_print_job(site=site, prn_content="X", target_role="carcass")
        job.claimed_by_edge = edge_a
        job.status = "pending"
        job.save(update_fields=["claimed_by_edge", "status", "updated_at"])

        resp = api_client.get(
            _edge_url("print-jobs/pending"),
            HTTP_X_EDGE_ID=str(edge_b.id),
        )
        assert resp.status_code == 200
        assert len(resp.json()["jobs"]) == 0

    def test_pending_includes_unclaimed_jobs(self, api_client, site):
        """Unclaimed jobs (claimed_by_edge=NULL) are visible to any edge."""
        edge_a = EdgeDevice.objects.create(site=site, name="Edge A", is_active=True, is_online=True)
        enqueue_print_job(site=site, prn_content="X", target_role="carcass")

        resp = api_client.get(
            _edge_url("print-jobs/pending"),
            HTTP_X_EDGE_ID=str(edge_a.id),
        )
        assert resp.status_code == 200
        assert len(resp.json()["jobs"]) == 1

    def test_pending_includes_jobs_claimed_by_self(self, api_client, site):
        """Jobs claimed by this edge are still visible to it."""
        edge_a = EdgeDevice.objects.create(site=site, name="Edge A", is_active=True, is_online=True)
        job = enqueue_print_job(site=site, prn_content="X", target_role="carcass")
        job.claimed_by_edge = edge_a
        job.status = "pending"
        job.save(update_fields=["claimed_by_edge", "status", "updated_at"])

        resp = api_client.get(
            _edge_url("print-jobs/pending"),
            HTTP_X_EDGE_ID=str(edge_a.id),
        )
        assert resp.status_code == 200
        assert len(resp.json()["jobs"]) == 1


# ==========================================================================
# Gap G — cleanup_stale_print_jobs management command
# ==========================================================================


@pytest.mark.django_db
class TestGapG_StaleCleanupCommand:
    def test_fails_stale_dispatched_jobs(self, site, edge_device):
        """Jobs dispatched >30min ago are marked failed by the command."""
        job = PrintJob.objects.create(
            site=site,
            item_type="carcass",
            item_id=uuid.uuid4(),
            prn_content="X",
            dispatch_mode="edge",
            status="dispatched",
            target_role="carcass",
        )
        PrintJob.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=45))

        out = StringIO()
        call_command("cleanup_stale_print_jobs", "--minutes", "30", stdout=out)

        job.refresh_from_db()
        assert job.status == "failed"
        assert "stuck in dispatched" in job.error_text
        assert "1" in out.getvalue()

    def test_does_not_fail_recent_dispatched_jobs(self, site, edge_device):
        """Jobs dispatched recently are not affected."""
        job = PrintJob.objects.create(
            site=site,
            item_type="carcass",
            item_id=uuid.uuid4(),
            prn_content="X",
            dispatch_mode="edge",
            status="dispatched",
            target_role="carcass",
        )

        out = StringIO()
        call_command("cleanup_stale_print_jobs", "--minutes", "30", stdout=out)

        job.refresh_from_db()
        assert job.status == "dispatched"
        assert "0" in out.getvalue()

    def test_does_not_affect_pending_jobs(self, site):
        """Pending jobs are never touched, even if old."""
        job = enqueue_print_job(site=site, prn_content="X", target_role="carcass")
        PrintJob.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=60))

        out = StringIO()
        call_command("cleanup_stale_print_jobs", "--minutes", "30", stdout=out)

        job.refresh_from_db()
        assert job.status == "pending"

    def test_custom_minutes_parameter(self, site):
        """The --minutes flag controls the cutoff."""
        job = PrintJob.objects.create(
            site=site,
            item_type="carcass",
            item_id=uuid.uuid4(),
            prn_content="X",
            dispatch_mode="edge",
            status="dispatched",
            target_role="carcass",
        )
        PrintJob.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=15))

        out = StringIO()
        call_command("cleanup_stale_print_jobs", "--minutes", "10", stdout=out)

        job.refresh_from_db()
        assert job.status == "failed"


# ==========================================================================
# Activation Feedback — EdgeSetupCodeDetailView context
# ==========================================================================


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="gaptest_admin",
        password="testpass123",
        role=User.Role.ADMIN,
        is_staff=True,
    )


@pytest.fixture
def auth_client(db, admin_user):
    client = Client()
    client.force_login(admin_user)
    return client


@pytest.mark.django_db
class TestActivationFeedback:
    def test_unused_code_shows_not_connected(self, auth_client, site):
        """An unused setup code context has edge_connected=False."""
        sc = EdgeSetupCode.objects.create(
            site=site,
            edge_name="Test Edge",
            expires_at=timezone.now() + timedelta(hours=48),
        )
        resp = auth_client.get(reverse("scales:edge_setup_code_detail", kwargs={"pk": sc.pk}))
        assert resp.status_code == 200
        assert resp.context["edge_connected"] is False

    def test_unused_code_has_meta_refresh(self, auth_client, site):
        """Unused code page should have meta refresh for auto-polling."""
        sc = EdgeSetupCode.objects.create(
            site=site,
            edge_name="Test Edge",
            expires_at=timezone.now() + timedelta(hours=48),
        )
        resp = auth_client.get(reverse("scales:edge_setup_code_detail", kwargs={"pk": sc.pk}))
        assert resp.status_code == 200
        assert b'http-equiv="refresh"' in resp.content

    def test_used_code_with_online_edge_shows_connected(self, auth_client, site):
        """A used setup code with an online edge shows edge_connected + edge_online."""
        edge = EdgeDevice.objects.create(
            site=site,
            name="Online Edge",
            is_active=True,
            is_online=True,
            last_seen_at=timezone.now(),
            version="2.0.0",
            health="ok",
        )
        sc = EdgeSetupCode.objects.create(
            site=site,
            edge_name="Online Edge",
            expires_at=timezone.now() + timedelta(hours=48),
            used_at=timezone.now(),
            used_by_edge=edge,
        )
        resp = auth_client.get(reverse("scales:edge_setup_code_detail", kwargs={"pk": sc.pk}))
        assert resp.status_code == 200
        assert resp.context["edge_connected"] is True
        assert resp.context["edge_online"] is True
        assert resp.context["edge_name"] == "Online Edge"
        assert resp.context["edge_version"] == "2.0.0"
        assert resp.context["edge_health"] == "ok"
        assert b'http-equiv="refresh"' not in resp.content

    def test_used_code_with_offline_edge_shows_not_online(self, auth_client, site):
        """A used setup code with an offline edge shows edge_connected but not edge_online."""
        edge = EdgeDevice.objects.create(
            site=site,
            name="Offline Edge",
            is_active=True,
            is_online=False,
            last_seen_at=timezone.now() - timedelta(minutes=10),
            version="1.0.0",
        )
        sc = EdgeSetupCode.objects.create(
            site=site,
            edge_name="Offline Edge",
            expires_at=timezone.now() + timedelta(hours=48),
            used_at=timezone.now(),
            used_by_edge=edge,
        )
        resp = auth_client.get(reverse("scales:edge_setup_code_detail", kwargs={"pk": sc.pk}))
        assert resp.status_code == 200
        assert resp.context["edge_connected"] is True
        assert resp.context["edge_online"] is False

    def test_used_code_shows_printer_count(self, auth_client, site):
        """The context includes the count of active printers for the connected edge."""
        edge = EdgeDevice.objects.create(
            site=site,
            name="Printer Edge",
            is_active=True,
            is_online=True,
            last_seen_at=timezone.now(),
        )
        Printer.objects.create(
            site=site,
            edge=edge,
            local_printer_id="p1",
            host="192.168.1.10",
            role="carcass",
            is_active=True,
        )
        Printer.objects.create(
            site=site,
            edge=edge,
            local_printer_id="p2",
            host="192.168.1.11",
            role="meat_cut",
            is_active=True,
        )
        Printer.objects.create(
            site=site,
            edge=edge,
            local_printer_id="p3",
            host="192.168.1.12",
            role="offal",
            is_active=False,
        )
        sc = EdgeSetupCode.objects.create(
            site=site,
            edge_name="Printer Edge",
            expires_at=timezone.now() + timedelta(hours=48),
            used_at=timezone.now(),
            used_by_edge=edge,
        )
        resp = auth_client.get(reverse("scales:edge_setup_code_detail", kwargs={"pk": sc.pk}))
        assert resp.status_code == 200
        assert resp.context["edge_printer_count"] == 2
