from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from .models import Report, GeneratedReport
from datetime import date

User = get_user_model()

class ReportingModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='password123'
        )

    def test_create_report_definition(self):
        report = Report.objects.create(
            name="Daily Slaughter Report",
            report_type='operational',
            configuration={'filter': 'all'}
        )
        self.assertEqual(report.name, "Daily Slaughter Report")
        self.assertEqual(report.report_type, 'operational')

    def test_report_definition_name_uniqueness(self):
        Report.objects.create(name="Unique Report", report_type='financial')
        with self.assertRaises(IntegrityError):
            Report.objects.create(name="Unique Report", report_type='financial')

    def test_create_generated_report(self):
        report_def = Report.objects.create(
            name="Test Report",
            report_type='analytics'
        )
        gen_report = GeneratedReport.objects.create(
            report_definition=report_def,
            generated_by=self.user,
            start_date=date(2023, 1, 1),
            end_date=date(2023, 1, 31)
        )
        self.assertEqual(gen_report.report_definition, report_def)
        self.assertEqual(gen_report.status, 'pending')

    def test_generated_report_definition_deletion(self):
        report_def = Report.objects.create(
            name="Another Report",
            report_type='operational'
        )
        gen_report = GeneratedReport.objects.create(
            report_definition=report_def
        )
        report_def.delete()
        self.assertFalse(GeneratedReport.objects.filter(pk=gen_report.pk).exists())