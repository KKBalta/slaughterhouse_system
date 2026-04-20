"""
Tests for the labeling app.

Tests cover label template and print job functionality.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from labeling.models import AnimalLabel, LabelTemplate, PrintJob
from labeling.services import archive_destination_sensitive_order_labels
from processing.models import DisassemblyCut

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
