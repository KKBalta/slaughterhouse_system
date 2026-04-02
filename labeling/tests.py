import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from .models import LabelTemplate, PrintJob

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_create_label_template():
    template = LabelTemplate.objects.create(
        name="Carcass Template", template_data={"field": "value"}, target_item_type="carcass"
    )
    assert template.name == "Carcass Template"
    assert template.target_item_type == "carcass"


def test_label_template_name_uniqueness():
    LabelTemplate.objects.create(name="Unique Template", template_data={}, target_item_type="meat_cut")
    with pytest.raises(IntegrityError):
        LabelTemplate.objects.create(name="Unique Template", template_data={}, target_item_type="meat_cut")


def test_create_print_job():
    user = User.objects.create_user(username="testuser", password="password123")
    template = LabelTemplate.objects.create(name="Test Template", template_data={}, target_item_type="offal")
    item_id = uuid.uuid4()
    job = PrintJob.objects.create(label_template=template, item_type="offal", item_id=item_id, printed_by=user)
    assert job.label_template == template
    assert job.item_id == item_id
    assert job.status == "pending"


def test_print_job_template_deletion():
    template = LabelTemplate.objects.create(name="Another Template", template_data={}, target_item_type="by_product")
    item_id = uuid.uuid4()
    job = PrintJob.objects.create(label_template=template, item_type="by_product", item_id=item_id)
    template.delete()
    job.refresh_from_db()
    assert job.label_template is None
