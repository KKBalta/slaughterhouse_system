import uuid

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from .models import LabelTemplate, PrintJob

User = get_user_model()


class LabelingModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password123")

    def test_create_label_template(self):
        template = LabelTemplate.objects.create(
            name="Carcass Template", template_data={"field": "value"}, target_item_type="carcass"
        )
        self.assertEqual(template.name, "Carcass Template")
        self.assertEqual(template.target_item_type, "carcass")

    def test_label_template_name_uniqueness(self):
        LabelTemplate.objects.create(name="Unique Template", template_data={}, target_item_type="meat_cut")
        with self.assertRaises(IntegrityError):
            LabelTemplate.objects.create(name="Unique Template", template_data={}, target_item_type="meat_cut")

    def test_create_print_job(self):
        template = LabelTemplate.objects.create(name="Test Template", template_data={}, target_item_type="offal")
        item_id = uuid.uuid4()
        job = PrintJob.objects.create(label_template=template, item_type="offal", item_id=item_id, printed_by=self.user)
        self.assertEqual(job.label_template, template)
        self.assertEqual(job.item_id, item_id)
        self.assertEqual(job.status, "pending")

    def test_print_job_template_deletion(self):
        template = LabelTemplate.objects.create(
            name="Another Template", template_data={}, target_item_type="by_product"
        )
        item_id = uuid.uuid4()
        job = PrintJob.objects.create(label_template=template, item_type="by_product", item_id=item_id)
        template.delete()
        job.refresh_from_db()
        self.assertIsNone(job.label_template)
