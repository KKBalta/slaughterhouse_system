"""
Tests for the labeling app.

Tests cover label template and print job functionality.
"""
import pytest
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import IntegrityError
import uuid

from labeling.models import LabelTemplate, PrintJob


User = get_user_model()


class LabelTemplateTest(TestCase):
    """Tests for LabelTemplate model."""
    
    def test_create_template(self):
        """Test creating a label template."""
        template = LabelTemplate.objects.create(
            name='Test Carcass Template',
            template_data={'field1': 'value1'},
            target_item_type='carcass'
        )
        
        self.assertEqual(template.name, 'Test Carcass Template')
        self.assertEqual(template.target_item_type, 'carcass')
    
    def test_template_data_json(self):
        """Test that template data is stored as JSON."""
        template_data = {
            'fields': ['weight', 'date', 'tag'],
            'format': 'standard',
            'size': {'width': 100, 'height': 50}
        }
        
        template = LabelTemplate.objects.create(
            name='JSON Test Template',
            template_data=template_data,
            target_item_type='meat_cut'
        )
        
        self.assertEqual(template.template_data['fields'], ['weight', 'date', 'tag'])
    
    def test_template_name_unique(self):
        """Test that template names must be unique."""
        LabelTemplate.objects.create(
            name='Unique Template',
            template_data={},
            target_item_type='carcass'
        )
        
        with self.assertRaises(IntegrityError):
            LabelTemplate.objects.create(
                name='Unique Template',
                template_data={},
                target_item_type='meat_cut'
            )
    
    def test_all_target_item_types(self):
        """Test all valid target item types."""
        target_types = ['carcass', 'meat_cut', 'offal', 'by_product']
        
        for i, target_type in enumerate(target_types):
            template = LabelTemplate.objects.create(
                name=f'Template {i}',
                template_data={},
                target_item_type=target_type
            )
            self.assertEqual(template.target_item_type, target_type)


class PrintJobTest(TestCase):
    """Tests for PrintJob model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='print_test_user',
            password='testpass123'
        )
        self.template = LabelTemplate.objects.create(
            name='Print Job Template',
            template_data={},
            target_item_type='carcass'
        )
    
    def test_create_print_job(self):
        """Test creating a print job."""
        item_id = uuid.uuid4()
        job = PrintJob.objects.create(
            label_template=self.template,
            item_type='carcass',
            item_id=item_id,
            printed_by=self.user
        )
        
        self.assertEqual(job.status, 'pending')
        self.assertEqual(job.item_type, 'carcass')
        self.assertEqual(job.item_id, item_id)
    
    def test_print_job_status_transitions(self):
        """Test print job status transitions."""
        job = PrintJob.objects.create(
            label_template=self.template,
            item_type='carcass',
            item_id=uuid.uuid4(),
            printed_by=self.user
        )
        
        self.assertEqual(job.status, 'pending')
        
        job.status = 'completed'
        job.save()
        
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
    
    def test_print_job_without_user(self):
        """Test creating print job without user."""
        job = PrintJob.objects.create(
            label_template=self.template,
            item_type='carcass',
            item_id=uuid.uuid4()
        )
        
        self.assertIsNone(job.printed_by)
    
    def test_print_job_template_deletion(self):
        """Test print job when template is deleted."""
        job = PrintJob.objects.create(
            label_template=self.template,
            item_type='carcass',
            item_id=uuid.uuid4()
        )
        
        self.template.delete()
        job.refresh_from_db()
        
        self.assertIsNone(job.label_template)


class PrintJobStatusTest(TestCase):
    """Tests for print job status handling."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='status_test_user',
            password='testpass123'
        )
        self.template = LabelTemplate.objects.create(
            name='Status Test Template',
            template_data={},
            target_item_type='meat_cut'
        )
    
    def test_all_status_values(self):
        """Test all valid status values."""
        statuses = ['pending', 'printing', 'completed', 'failed']
        
        for status in statuses:
            job = PrintJob.objects.create(
                label_template=self.template,
                item_type='meat_cut',
                item_id=uuid.uuid4()
            )
            job.status = status
            job.save()
            
            job.refresh_from_db()
            self.assertEqual(job.status, status)


# ============================================================================
# Pytest-style tests
# ============================================================================

@pytest.mark.django_db
class TestLabelTemplatePytest:
    """Pytest-style tests for label templates."""
    
    def test_template_creation(self):
        """Test creating a template."""
        template = LabelTemplate.objects.create(
            name='Pytest Template',
            template_data={'key': 'value'},
            target_item_type='carcass'
        )
        
        assert template.name == 'Pytest Template'
        assert template.template_data['key'] == 'value'
    
    def test_template_str_representation(self):
        """Test string representation of template."""
        template = LabelTemplate.objects.create(
            name='Str Test Template',
            template_data={},
            target_item_type='carcass'
        )
        
        # Should include the name
        assert 'Str Test Template' in str(template)


@pytest.mark.django_db
class TestPrintJobWorkflow:
    """Tests for print job workflow."""
    
    def test_print_job_lifecycle(self, admin_user):
        """Test complete print job lifecycle."""
        template = LabelTemplate.objects.create(
            name='Lifecycle Template',
            template_data={},
            target_item_type='carcass'
        )
        
        # Create job
        job = PrintJob.objects.create(
            label_template=template,
            item_type='carcass',
            item_id=uuid.uuid4(),
            printed_by=admin_user
        )
        assert job.status == 'pending'
        
        # Start printing
        job.status = 'printing'
        job.save()
        
        # Complete
        job.status = 'completed'
        job.save()
        
        job.refresh_from_db()
        assert job.status == 'completed'
    
    def test_print_job_failure_handling(self, admin_user):
        """Test handling print job failures."""
        template = LabelTemplate.objects.create(
            name='Failure Template',
            template_data={},
            target_item_type='carcass'
        )
        
        job = PrintJob.objects.create(
            label_template=template,
            item_type='carcass',
            item_id=uuid.uuid4(),
            printed_by=admin_user
        )
        
        # Simulate failure
        job.status = 'failed'
        job.save()
        
        job.refresh_from_db()
        assert job.status == 'failed'
