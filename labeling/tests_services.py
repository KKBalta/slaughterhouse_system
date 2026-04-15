"""
Tests for the labeling app.

Tests cover label template and print job functionality.
"""

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from processing.models import DisassemblyCut

from scales.models import EdgeDevice, Printer, Site

from labeling.models import AnimalLabel, CustomLabel, LabelTemplate, PrintJob
from labeling.services import (
    archive_destination_sensitive_order_labels,
    cancel_pending_edge_print_job,
    enqueue_print_job,
    printers_for_role,
    resolve_target_role,
)

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_create_template():
    template = LabelTemplate.objects.create(
        name="Test Carcass Template", template_data={"field1": "value1"}, target_item_type="carcass"
    )

    assert template.name == "Test Carcass Template"
    assert template.target_item_type == "carcass"


def test_template_data_json():
    template_data = {
        "fields": ["weight", "date", "tag"],
        "format": "standard",
        "size": {"width": 100, "height": 50},
    }

    template = LabelTemplate.objects.create(
        name="JSON Test Template", template_data=template_data, target_item_type="meat_cut"
    )

    assert template.template_data["fields"] == ["weight", "date", "tag"]


def test_template_name_unique():
    LabelTemplate.objects.create(name="Unique Template", template_data={}, target_item_type="carcass")

    with pytest.raises(IntegrityError):
        LabelTemplate.objects.create(name="Unique Template", template_data={}, target_item_type="meat_cut")


def test_all_target_item_types():
    target_types = ["carcass", "meat_cut", "offal", "by_product"]

    for i, target_type in enumerate(target_types):
        template = LabelTemplate.objects.create(name=f"Template {i}", template_data={}, target_item_type=target_type)
        assert template.target_item_type == target_type


def test_create_print_job():
    user = User.objects.create_user(username="print_test_user", password="testpass123", role=User.Role.ADMIN)
    template = LabelTemplate.objects.create(name="Print Job Template", template_data={}, target_item_type="carcass")

    item_id = uuid.uuid4()
    job = PrintJob.objects.create(label_template=template, item_type="carcass", item_id=item_id, printed_by=user)

    assert job.status == "pending"
    assert job.item_type == "carcass"
    assert job.item_id == item_id


def test_cancel_pending_edge_print_job():
    site = Site.objects.create(name="Cancel Site", address="")
    job = PrintJob.objects.create(
        site=site,
        status="pending",
        dispatch_mode="edge",
        prn_content="p",
        target_role="carcass",
    )
    assert cancel_pending_edge_print_job(job) is True
    job.refresh_from_db()
    assert job.status == "cancelled"
    assert "queue" in job.error_text.lower()


def test_cancel_pending_edge_print_job_noop_when_not_pending():
    site = Site.objects.create(name="Cancel Site 2", address="")
    job = PrintJob.objects.create(
        site=site,
        status="dispatched",
        dispatch_mode="edge",
        prn_content="p",
    )
    assert cancel_pending_edge_print_job(job) is False
    job.refresh_from_db()
    assert job.status == "dispatched"


def test_enqueue_print_job_edge_minimal():
    site = Site.objects.create(name="Enqueue Site", address="")
    job = enqueue_print_job(site=site, prn_content="TSPL", target_role="carcass")
    assert job.status == "pending"
    assert job.dispatch_mode == "edge"
    assert job.site_id == site.id
    assert job.target_role == "carcass"
    assert job.item_id is None
    assert job.item_type == ""


def test_enqueue_print_job_maps_animal_label_type_to_role(admin_user, animal_factory):
    site = Site.objects.create(name="S", address="")
    animal = animal_factory()
    label = AnimalLabel.objects.create(
        animal=animal,
        label_type="final",
        printed_by=admin_user,
        prn_content="P",
        bat_content="B",
    )
    job = enqueue_print_job(site=site, prn_content="X", animal_label=label)
    assert job.target_role == "meat_cut"
    assert job.item_id == animal.id
    assert job.item_type == "meat_cut"


def test_enqueue_print_job_custom_label_sets_animal_item_type(admin_user):
    site = Site.objects.create(name="S2", address="")
    custom = CustomLabel.objects.create(
        uretici="U",
        kupe_no="K1",
        kesim_tarihi=date(2026, 1, 1),
        stt=date(2026, 1, 11),
        cinsi="SIGIR",
        weight="12.5",
        printed_by=admin_user,
        prn_content="C",
        bat_content="C",
    )
    job = enqueue_print_job(site=site, prn_content="Y", custom_label=custom)
    assert job.item_type == "animal"
    assert job.item_id == custom.id
    assert job.target_role == "carcass"


def test_enqueue_print_job_explicit_target_role_overrides_label_type(admin_user, animal_factory):
    site = Site.objects.create(name="S-override", address="")
    animal = animal_factory()
    label = AnimalLabel.objects.create(
        animal=animal,
        label_type="final",
        printed_by=admin_user,
        prn_content="P",
        bat_content="B",
    )
    job = enqueue_print_job(
        site=site, prn_content="Z", animal_label=label, target_role="offal"
    )
    assert job.target_role == "offal"
    assert job.item_type == "offal"


def test_resolve_target_role_hot_and_cold_carcass():
    for lt in ("hot_carcass", "cold_carcass"):
        assert resolve_target_role(animal_label=SimpleNamespace(label_type=lt)) == "carcass"


def test_resolve_target_role_final_and_cut():
    for lt in ("final", "cut"):
        assert resolve_target_role(animal_label=SimpleNamespace(label_type=lt)) == "meat_cut"


def test_resolve_target_role_unknown_label_type_defaults_carcass():
    assert resolve_target_role(animal_label=SimpleNamespace(label_type="unknown_x")) == "carcass"


def test_resolve_target_role_custom_label():
    assert resolve_target_role(custom_label=SimpleNamespace()) == "carcass"


def test_resolve_target_role_explicit_beats_auto():
    assert (
        resolve_target_role(
            animal_label=SimpleNamespace(label_type="final"),
            target_role="offal",
        )
        == "offal"
    )


def test_printers_for_role_filters_site_role_active_enabled_orders_by_priority():
    site = Site.objects.create(name="PF Role Site", address="")
    edge = EdgeDevice.objects.create(site=site, name="E-pf", is_active=True)
    Printer.objects.create(
        edge=edge,
        site=site,
        local_printer_id="m1",
        host="10.0.0.1",
        port=9100,
        role="meat_cut",
        priority=50,
        enabled=True,
        is_active=True,
    )
    Printer.objects.create(
        edge=edge,
        site=site,
        local_printer_id="c2",
        host="10.0.0.2",
        port=9100,
        role="carcass",
        priority=200,
        enabled=True,
        is_active=True,
        display_name="B",
    )
    Printer.objects.create(
        edge=edge,
        site=site,
        local_printer_id="c1",
        host="10.0.0.3",
        port=9100,
        role="carcass",
        priority=100,
        enabled=True,
        is_active=True,
        display_name="A",
    )
    Printer.objects.create(
        edge=edge,
        site=site,
        local_printer_id="c3",
        host="10.0.0.4",
        port=9100,
        role="carcass",
        priority=10,
        enabled=False,
        is_active=True,
    )
    qs = printers_for_role(site, "carcass")
    assert list(qs.values_list("local_printer_id", flat=True)) == ["c1", "c2"]


def test_printjob_admin_reenqueue_failed_bumps_edge_cache_per_site(mocker, admin_user):
    from django.contrib.admin.sites import AdminSite
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.test import RequestFactory

    from labeling.admin import PrintJobAdmin

    site_a = Site.objects.create(name="Reenqueue A", address="")
    site_b = Site.objects.create(name="Reenqueue B", address="")
    j1 = PrintJob.objects.create(
        site=site_a,
        status="failed",
        dispatch_mode="edge",
        prn_content="p",
        attempts=3,
        error_text="e",
    )
    PrintJob.objects.create(
        site=site_a,
        status="failed",
        dispatch_mode="edge",
        prn_content="q",
    )
    PrintJob.objects.create(
        site=site_b,
        status="failed",
        dispatch_mode="edge",
        prn_content="r",
    )
    bump = mocker.patch("scales.api_views._bump_edge_print_jobs_version")

    factory = RequestFactory()
    request = factory.post("/admin/")
    request.user = admin_user
    request.session = {}
    request._messages = FallbackStorage(request)

    modeladmin = PrintJobAdmin(PrintJob, AdminSite())
    qs = PrintJob.objects.filter(
        pk__in=PrintJob.objects.filter(site__in=[site_a, site_b]).values_list("pk", flat=True)
    )
    modeladmin.reenqueue_failed_jobs(request, qs)

    assert bump.call_count == 2
    bump.assert_any_call(site_a.id)
    bump.assert_any_call(site_b.id)
    for job in PrintJob.objects.filter(site__in=[site_a, site_b]):
        assert job.status == "pending"
        assert job.attempts == 0
        assert job.error_text == ""


def test_printjob_admin_reenqueue_does_not_bump_for_legacy_dispatch(mocker, admin_user):
    from django.contrib.admin.sites import AdminSite
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.test import RequestFactory

    from labeling.admin import PrintJobAdmin

    site = Site.objects.create(name="Legacy site", address="")
    PrintJob.objects.create(
        site=site,
        status="failed",
        dispatch_mode="legacy_bat",
        prn_content="p",
    )
    bump = mocker.patch("scales.api_views._bump_edge_print_jobs_version")

    factory = RequestFactory()
    request = factory.post("/admin/")
    request.user = admin_user
    request.session = {}
    request._messages = FallbackStorage(request)

    modeladmin = PrintJobAdmin(PrintJob, AdminSite())
    modeladmin.reenqueue_failed_jobs(request, PrintJob.objects.all())

    bump.assert_not_called()


def test_print_job_status_transitions():
    user = User.objects.create_user(username="status_test_user", password="testpass123", role=User.Role.ADMIN)
    template = LabelTemplate.objects.create(name="Status Test Template", template_data={}, target_item_type="carcass")

    job = PrintJob.objects.create(label_template=template, item_type="carcass", item_id=uuid.uuid4(), printed_by=user)

    assert job.status == "pending"

    job.status = "completed"
    job.save()

    job.refresh_from_db()
    assert job.status == "completed"


def test_print_job_without_user():
    template = LabelTemplate.objects.create(name="Print Job Template", template_data={}, target_item_type="carcass")

    job = PrintJob.objects.create(label_template=template, item_type="carcass", item_id=uuid.uuid4())

    assert job.printed_by is None


def test_print_job_template_deletion():
    template = LabelTemplate.objects.create(name="Another Template", template_data={}, target_item_type="by_product")
    job = PrintJob.objects.create(label_template=template, item_type="by_product", item_id=uuid.uuid4())

    template.delete()
    job.refresh_from_db()

    assert job.label_template is None


def test_all_status_values():
    user = User.objects.create_user(username="status_test_user_2", password="testpass123", role=User.Role.ADMIN)
    template = LabelTemplate.objects.create(
        name="Status Test Template 2", template_data={}, target_item_type="meat_cut"
    )

    for status in ["pending", "printing", "completed", "failed"]:
        job = PrintJob.objects.create(label_template=template, item_type="meat_cut", item_id=uuid.uuid4())
        job.status = status
        job.save()

        job.refresh_from_db()
        assert job.status == status


class TestLabelTemplatePytest:
    def test_template_creation(self):
        template = LabelTemplate.objects.create(
            name="Pytest Template",
            template_data={"key": "value"},
            target_item_type="carcass",
        )

        assert template.name == "Pytest Template"
        assert template.template_data["key"] == "value"

    def test_template_str_representation(self):
        template = LabelTemplate.objects.create(
            name="Str Test Template",
            template_data={},
            target_item_type="carcass",
        )

        assert "Str Test Template" in str(template)


class TestPrintJobWorkflow:
    def test_print_job_lifecycle(self, admin_user):
        template = LabelTemplate.objects.create(
            name="Lifecycle Template",
            template_data={},
            target_item_type="carcass",
        )

        job = PrintJob.objects.create(
            label_template=template,
            item_type="carcass",
            item_id=uuid.uuid4(),
            printed_by=admin_user,
        )
        assert job.status == "pending"

        job.status = "printing"
        job.save()

        job.status = "completed"
        job.save()

        job.refresh_from_db()
        assert job.status == "completed"

    def test_print_job_failure_handling(self, admin_user):
        template = LabelTemplate.objects.create(
            name="Failure Template",
            template_data={},
            target_item_type="carcass",
        )

        job = PrintJob.objects.create(
            label_template=template,
            item_type="carcass",
            item_id=uuid.uuid4(),
            printed_by=admin_user,
        )

        job.status = "failed"
        job.save()

        job.refresh_from_db()
        assert job.status == "failed"


def test_archive_destination_sensitive_order_labels_hides_active_labels_but_keeps_cut_labels(
    admin_user,
    animal_factory,
    slaughter_order_factory,
):
    order = slaughter_order_factory(destination="Old Route")
    animal = animal_factory(slaughter_order=order, status="slaughtered")
    hot_label = AnimalLabel.objects.create(
        animal=animal,
        label_type="hot_carcass",
        printed_by=admin_user,
        prn_content="HOT",
        bat_content="HOT",
    )
    hot_label.pdf_file = "animal_labels/pdf/stale-hot-label.pdf"
    hot_label.save(update_fields=["pdf_file"])

    cut = DisassemblyCut.objects.create(animal=animal, cut_name="ANTREKOT", weight_kg="5.00")
    cut_label = AnimalLabel.objects.create(
        animal=animal,
        cut=cut,
        label_type="cut",
        printed_by=admin_user,
        prn_content="CUT",
        bat_content="CUT",
    )
    cut_label.pdf_file = "animal_labels/pdf/cut-label.pdf"
    cut_label.save(update_fields=["pdf_file"])

    archived_count = archive_destination_sensitive_order_labels(order)

    assert archived_count == 1
    hot_label.refresh_from_db()
    cut_label.refresh_from_db()
    assert hot_label.is_active is False
    assert hot_label.pdf_file.name == "animal_labels/pdf/stale-hot-label.pdf"
    assert cut_label.is_active is True
