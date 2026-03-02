from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from processing.models import Animal, CattleDetails, WeightLog
from reception.models import ServicePackage, SlaughterOrder
from reporting.models import GeneratedReport, Report
from reporting.services import ExcelReportGenerator, ReportDataAggregator
from users.models import User


class ReportModelTest(TestCase):
    """Test the Report model"""

    def setUp(self):
        self.report = Report.objects.create(
            name="Daily Slaughter Report",
            description="Daily slaughter operations report",
            report_type="daily_slaughter",
            frequency="daily",
            output_format="excel",
            is_active=True,
        )

    def test_report_creation(self):
        """Test report creation"""
        self.assertEqual(self.report.name, "Daily Slaughter Report")
        self.assertEqual(self.report.report_type, "daily_slaughter")
        self.assertEqual(self.report.frequency, "daily")
        self.assertTrue(self.report.is_active)

    def test_report_str(self):
        """Test report string representation"""
        self.assertEqual(str(self.report), "Daily Slaughter Report")

    def test_report_choices(self):
        """Test report type choices"""
        valid_types = [choice[0] for choice in Report.REPORT_TYPE_CHOICES]
        self.assertIn("daily_slaughter", valid_types)
        self.assertIn("monthly_operations", valid_types)
        self.assertIn("yearly_operations", valid_types)


class GeneratedReportModelTest(TestCase):
    """Test the GeneratedReport model"""

    def setUp(self):
        self.report = Report.objects.create(name="Test Report", report_type="daily_slaughter", frequency="daily")
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")

    def test_generated_report_creation(self):
        """Test generated report creation"""
        generated_report = GeneratedReport.objects.create(
            report_definition=self.report,
            generated_by=self.user,
            start_date=date.today(),
            end_date=date.today(),
            status="success",
        )

        self.assertEqual(generated_report.report_definition, self.report)
        self.assertEqual(generated_report.generated_by, self.user)
        self.assertEqual(generated_report.status, "success")

    def test_generated_report_str(self):
        """Test generated report string representation"""
        generated_report = GeneratedReport.objects.create(
            report_definition=self.report, generated_by=self.user, start_date=date.today(), end_date=date.today()
        )

        expected_str = (
            f"Generated Report: {self.report.name} on {generated_report.generated_at.strftime('%Y-%m-%d %H:%M')}"
        )
        self.assertEqual(str(generated_report), expected_str)


class ReportDataAggregatorTest(TestCase):
    """Test the ReportDataAggregator service"""

    def setUp(self):
        # Create test data
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")

        # Create service package
        self.service_package = ServicePackage.objects.create(
            name="Test Package", includes_disassembly=True, includes_delivery=True
        )

        # Create slaughter order
        self.slaughter_order = SlaughterOrder.objects.create(
            client_name="Test Client",
            service_package=self.service_package,
            order_datetime=timezone.now(),
            status="PENDING",
        )

        # Create animals
        self.animal1 = Animal.objects.create(
            slaughter_order=self.slaughter_order,
            animal_type="cattle",
            identification_tag="TEST-001",
            received_date=timezone.now(),
            status="carcass_ready",
        )

        self.animal2 = Animal.objects.create(
            slaughter_order=self.slaughter_order,
            animal_type="sheep",
            identification_tag="TEST-002",
            received_date=timezone.now(),
            status="carcass_ready",
        )

        # Create weight logs
        WeightLog.objects.create(
            animal=self.animal1, weight=Decimal("500.00"), weight_type="live_weight", is_group_weight=False
        )

        WeightLog.objects.create(
            animal=self.animal1, weight=Decimal("300.00"), weight_type="hot_carcass_weight", is_group_weight=False
        )

        # Create cattle details
        CattleDetails.objects.create(
            animal=self.animal1,
            breed="Holstein",
            sakatat_status=1.0,  # Good
            bowels_status=1.0,  # Good
        )

        # Set slaughter dates
        self.test_date = date.today()
        self.animal1.slaughter_date = timezone.make_aware(datetime.combine(self.test_date, datetime.min.time()))
        self.animal1.save()

        self.animal2.slaughter_date = timezone.make_aware(datetime.combine(self.test_date, datetime.min.time()))
        self.animal2.save()

    def test_aggregator_initialization(self):
        """Test aggregator initialization"""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        self.assertEqual(aggregator.start_date, self.test_date)
        self.assertEqual(aggregator.end_date, self.test_date)

    def test_get_daily_slaughter_data(self):
        """Test getting daily slaughter data"""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        data = aggregator.get_daily_slaughter_data()

        self.assertEqual(len(data), 2)  # Two animals

        # Check first animal data
        animal1_data = data[0]
        self.assertEqual(animal1_data["client_name"], "Test Client")
        self.assertEqual(animal1_data["animal_type"], "SIGIR")  # Turkish for cattle
        self.assertEqual(animal1_data["quantity"], 1)
        self.assertEqual(animal1_data["offal_status"], "SAĞLAM")
        self.assertEqual(animal1_data["bowels_status"], "SAĞLAM")

    def test_get_daily_summary_totals(self):
        """Test getting daily summary totals"""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        summary = aggregator.get_daily_summary_totals()

        # Check that summary has expected structure
        self.assertIn("buyukbas", summary)
        self.assertIn("kuzu", summary)
        self.assertIn("oglak", summary)
        self.assertIn("koyun", summary)
        self.assertIn("keci", summary)

        # Check that each category has expected keys
        for category in summary.values():
            self.assertIn("kesim", category)
            self.assertIn("deri", category)
            self.assertIn("bagirsak", category)

    def test_get_all_data(self):
        """Test getting all data for report"""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        all_data = aggregator.get_all_data()

        self.assertIn("date", all_data)
        self.assertIn("daily_data", all_data)
        self.assertIn("summary", all_data)
        self.assertIn("total_animals", all_data)
        self.assertIn("total_hot_carcass_weight", all_data)
        self.assertIn("total_leather_weight", all_data)

        self.assertEqual(all_data["total_animals"], 2)  # Two animals, each with quantity 1

    def test_turkish_animal_type_mapping(self):
        """Test Turkish animal type mapping"""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)

        # Test various animal types
        self.assertEqual(aggregator._get_turkish_animal_type("cattle"), "SIGIR")
        self.assertEqual(aggregator._get_turkish_animal_type("sheep"), "KOYUN")
        self.assertEqual(aggregator._get_turkish_animal_type("goat"), "KECI")
        self.assertEqual(aggregator._get_turkish_animal_type("lamb"), "KUZU")
        self.assertEqual(aggregator._get_turkish_animal_type("heifer"), "DUVE")
        self.assertEqual(aggregator._get_turkish_animal_type("beef"), "DANA")

    def test_offal_bowels_status_mapping(self):
        """Test offal and bowels status mapping"""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)

        # Test with good status
        offal_status, bowels_status = aggregator._get_offal_bowels_status(self.animal1)
        self.assertEqual(offal_status, "SAĞLAM")
        self.assertEqual(bowels_status, "SAĞLAM")

        # Test with bad status
        self.animal1.cattle_details.sakatat_status = 0.0  # Not usable
        self.animal1.cattle_details.bowels_status = 0.0  # Not usable
        self.animal1.cattle_details.save()

        offal_status, bowels_status = aggregator._get_offal_bowels_status(self.animal1)
        self.assertEqual(offal_status, "ATIK")
        self.assertEqual(bowels_status, "BOZUK")

        # Test with half status
        self.animal1.cattle_details.sakatat_status = 0.5  # Not bad
        self.animal1.cattle_details.save()

        offal_status, bowels_status = aggregator._get_offal_bowels_status(self.animal1)
        self.assertEqual(offal_status, "YARIM")


class ExcelReportGeneratorTest(TestCase):
    """Test the ExcelReportGenerator service"""

    def setUp(self):
        self.report_data = {
            "date": "2024-01-15",
            "daily_data": [
                {
                    "client_name": "Test Client",
                    "quantity": 1,
                    "animal_type": "SIGIR",
                    "hot_carcass_weight": 200.0,
                    "offal_status": "SAĞLAM",
                    "bowels_status": "SAĞLAM",
                    "leather_weight": 25.0,
                    "destination": "Test Destination",
                    "description": "",
                }
            ],
            "summary": {
                "buyukbas": {"kesim": 1, "deri": 25.0, "bagirsak": 1},
                "kuzu": {"kesim": 0, "deri": 0, "bagirsak": 0},
                "oglak": {"kesim": 0, "deri": 0, "bagirsak": 0},
                "koyun": {"kesim": 0, "deri": 0, "bagirsak": 0},
                "keci": {"kesim": 0, "deri": 0, "bagirsak": 0},
            },
            "total_animals": 1,
            "total_hot_carcass_weight": 200.0,
            "total_leather_weight": 25.0,
        }

    def test_excel_generator_initialization(self):
        """Test Excel generator initialization"""
        generator = ExcelReportGenerator(self.report_data)
        self.assertEqual(generator.report_data, self.report_data)

    def test_generate_daily_slaughter_excel(self):
        """Test generating daily slaughter Excel report"""
        generator = ExcelReportGenerator(self.report_data)
        workbook = generator.generate_daily_slaughter_excel()

        # Check that workbook was created
        self.assertIsNotNone(workbook)

        # Check worksheet
        ws = workbook.active
        self.assertEqual(ws.title, "Daily Slaughter Report")

        # Check title
        self.assertEqual(ws["A1"].value, "GÜNLÜK KESİM RAPORU - 2024-01-15")

        # Check headers
        headers = [
            "FİRMA ÜNVANI",
            "ADET",
            "CİNSİ",
            "SICAK KARKAS",
            "HAYVAN KİMLİK NO",
            "SAKATAT",
            "BAĞIRSAK",
            "DERİ",
            "ALINAN MÜŞTERİ",
            "AÇIKLAMA",
        ]
        for i, header in enumerate(headers, 1):
            self.assertEqual(ws.cell(row=3, column=i).value, header)

        # Check data
        self.assertEqual(ws.cell(row=4, column=1).value, "Test Destination")  # ALINAN MÜŞTERİ
        self.assertEqual(ws.cell(row=4, column=2).value, 1)  # ADET
        self.assertEqual(ws.cell(row=4, column=3).value, "SIGIR")  # CİNSİ
        self.assertEqual(ws.cell(row=4, column=4).value, 200.0)  # SICAK KARKAS
        self.assertEqual(ws.cell(row=4, column=5).value, "")  # HAYVAN KİMLİK NO (empty in test data)
        self.assertEqual(ws.cell(row=4, column=6).value, "SAĞLAM")  # SAKATAT
        self.assertEqual(ws.cell(row=4, column=7).value, "SAĞLAM")  # BAĞIRSAK
        self.assertEqual(ws.cell(row=4, column=8).value, 25.0)  # DERİ
        self.assertEqual(ws.cell(row=4, column=9).value, "Test Client")  # FİRMA ÜNVANI
        self.assertEqual(ws.cell(row=4, column=10).value, "")  # AÇIKLAMA

        # Check summary section
        summary_start_row = 7  # After data and spacing
        self.assertEqual(ws.cell(row=summary_start_row, column=1).value, "ÖZET")

        # Check summary headers
        summary_headers = ["", "KESİM", "DERİ", "BAĞIRSAK"]
        for i, header in enumerate(summary_headers, 1):
            self.assertEqual(ws.cell(row=summary_start_row + 1, column=i).value, header)

        # Check summary data
        self.assertEqual(ws.cell(row=summary_start_row + 2, column=1).value, "BÜYÜKBAŞ")
        self.assertEqual(ws.cell(row=summary_start_row + 2, column=2).value, 1)
        self.assertEqual(ws.cell(row=summary_start_row + 2, column=3).value, 25.0)
        self.assertEqual(ws.cell(row=summary_start_row + 2, column=4).value, 1)


class ManagementCommandTest(TestCase):
    """Test management commands"""

    def setUp(self):
        # Create system user
        self.system_user = User.objects.create_user(
            username="system",
            email="system@slaughterhouse.local",
            password="systempass123",
            role="ADMIN",
            is_staff=True,
        )

        # Create report definition
        self.report = Report.objects.create(
            name="Daily Slaughter Report",
            report_type="daily_slaughter",
            frequency="daily",
            output_format="excel",
            is_active=True,
        )

    def test_setup_system_user_command(self):
        """Test setup system user command"""
        # Delete existing system user
        User.objects.filter(username="system").delete()

        # Run command
        call_command("setup_system_user")

        # Check that system user was created
        system_user = User.objects.get(username="system")
        self.assertEqual(system_user.email, "system@slaughterhouse.local")
        self.assertEqual(system_user.role, "ADMIN")
        self.assertTrue(system_user.is_staff)

    def test_setup_system_user_already_exists(self):
        """Test setup system user when user already exists"""
        # Run command (user already exists from setUp)
        call_command("setup_system_user")

        # Should not raise an error
        system_user = User.objects.get(username="system")
        self.assertEqual(system_user.username, "system")

    @patch("reporting.services.ReportDataAggregator")
    @patch("reporting.services.ExcelReportGenerator")
    def test_generate_daily_reports_command(self, mock_excel_generator, mock_aggregator):
        """Test generate daily reports command"""
        # Mock the services
        mock_aggregator_instance = MagicMock()
        mock_aggregator.return_value = mock_aggregator_instance
        mock_aggregator_instance.get_all_data.return_value = {
            "date": "2024-01-15",
            "daily_data": [],
            "summary": {
                "buyukbas": {"kesim": 0, "deri": 0, "bagirsak": 0},
                "kuzu": {"kesim": 0, "deri": 0, "bagirsak": 0},
                "oglak": {"kesim": 0, "deri": 0, "bagirsak": 0},
                "koyun": {"kesim": 0, "deri": 0, "bagirsak": 0},
                "keci": {"kesim": 0, "deri": 0, "bagirsak": 0},
            },
            "total_animals": 0,
            "total_weight": 0,
            "total_leather_weight": 0,
        }

        mock_excel_generator_instance = MagicMock()
        mock_excel_generator.return_value = mock_excel_generator_instance
        mock_workbook = MagicMock()
        mock_excel_generator_instance.generate_daily_slaughter_excel.return_value = mock_workbook

        # Run command
        with patch("os.makedirs"), patch("os.path.join", return_value="/tmp/test.xlsx"):
            call_command("generate_daily_reports", "--date=2024-01-15")

        # Check that GeneratedReport was created
        generated_report = GeneratedReport.objects.get(report_definition=self.report, generated_by=self.system_user)
        self.assertEqual(generated_report.status, "success")
        self.assertEqual(generated_report.start_date, date(2024, 1, 15))
        self.assertEqual(generated_report.end_date, date(2024, 1, 15))

    def test_generate_daily_reports_invalid_date(self):
        """Test generate daily reports with invalid date"""
        # Should not raise an error, but should handle gracefully
        call_command("generate_daily_reports", "--date=invalid-date")

        # Should not create any generated reports
        self.assertEqual(GeneratedReport.objects.count(), 0)

    def test_generate_daily_reports_system_user_not_found(self):
        """Test generate daily reports when system user doesn't exist"""
        # Delete system user
        User.objects.filter(username="system").delete()

        # Run command
        call_command("generate_daily_reports", "--system-user=nonexistent")

        # Should not create any generated reports
        self.assertEqual(GeneratedReport.objects.count(), 0)


class IntegrationTest(TransactionTestCase):
    """Integration tests for the complete reporting workflow"""

    def setUp(self):
        # Create comprehensive test data
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")

        self.service_package = ServicePackage.objects.create(
            name="Test Package", includes_disassembly=True, includes_delivery=True
        )

        self.slaughter_order = SlaughterOrder.objects.create(
            client_name="Test Client",
            service_package=self.service_package,
            order_datetime=timezone.now(),
            status="PENDING",
        )

        # Create multiple animals
        self.animals = []
        animal_types = ["cattle", "sheep", "goat", "lamb"]

        for i, animal_type in enumerate(animal_types):
            animal = Animal.objects.create(
                slaughter_order=self.slaughter_order,
                animal_type=animal_type,
                identification_tag=f"TEST-{i + 1:03d}",
                received_date=timezone.now(),
                status="carcass_ready",
                slaughter_date=timezone.make_aware(datetime.combine(date.today(), datetime.min.time())),
                leather_weight_kg=Decimal(f"{20 + i * 5}.00"),
            )
            self.animals.append(animal)

            # Create weight logs
            WeightLog.objects.create(
                animal=animal, weight=Decimal(f"{400 + i * 100}.00"), weight_type="live_weight", is_group_weight=False
            )

            WeightLog.objects.create(
                animal=animal,
                weight=Decimal(f"{250 + i * 50}.00"),
                weight_type="hot_carcass_weight",
                is_group_weight=False,
            )

        # Create cattle details for first animal
        CattleDetails.objects.create(animal=self.animals[0], breed="Holstein", sakatat_status=1.0, bowels_status=1.0)

    def test_complete_report_generation_workflow(self):
        """Test the complete report generation workflow"""
        # Create report definition
        report = Report.objects.create(
            name="Daily Slaughter Report",
            report_type="daily_slaughter",
            frequency="daily",
            output_format="excel",
            is_active=True,
        )

        # Create system user
        system_user = User.objects.create_user(
            username="system",
            email="system@slaughterhouse.local",
            password="systempass123",
            role="ADMIN",
            is_staff=True,
        )

        # Generate report data
        aggregator = ReportDataAggregator(date.today(), date.today())
        report_data = aggregator.get_all_data()

        # Verify data structure
        self.assertIn("daily_data", report_data)
        self.assertIn("summary", report_data)
        self.assertEqual(len(report_data["daily_data"]), 4)  # Four animals

        # Generate Excel report
        excel_generator = ExcelReportGenerator(report_data)
        workbook = excel_generator.generate_daily_slaughter_excel()

        # Verify Excel structure
        ws = workbook.active
        self.assertEqual(ws.title, "Daily Slaughter Report")

        # Check that all animals are included
        data_start_row = 4
        for i in range(4):
            row = data_start_row + i
            self.assertIsNotNone(ws.cell(row=row, column=1).value)  # Client name
            self.assertIsNotNone(ws.cell(row=row, column=3).value)  # Animal type

        # Find the summary section by looking for "ÖZET"
        summary_start_row = None
        for row in range(1, 20):  # Search in first 20 rows
            if ws.cell(row=row, column=1).value == "ÖZET":
                summary_start_row = row
                break

        self.assertIsNotNone(summary_start_row, "ÖZET section not found in Excel file")

        # Verify that summary has data
        buyukbas_row = summary_start_row + 2
        self.assertEqual(ws.cell(row=buyukbas_row, column=1).value, "BÜYÜKBAŞ")
        self.assertEqual(ws.cell(row=buyukbas_row, column=2).value, 1)  # One cattle

    def test_report_data_accuracy(self):
        """Test that report data is accurate"""
        aggregator = ReportDataAggregator(date.today(), date.today())
        report_data = aggregator.get_all_data()

        # Check total animals (4 animals, each with quantity 1)
        self.assertEqual(report_data["total_animals"], 4)

        # Check that all animals have correct data
        for animal_data in report_data["daily_data"]:
            self.assertIn("client_name", animal_data)
            self.assertIn("animal_type", animal_data)
            self.assertIn("hot_carcass_weight", animal_data)
            self.assertIn("offal_status", animal_data)
            self.assertIn("bowels_status", animal_data)
            self.assertIn("leather_weight", animal_data)

        # Check summary totals
        summary = report_data["summary"]
        self.assertEqual(summary["buyukbas"]["kesim"], 1)  # One cattle
        self.assertEqual(summary["kuzu"]["kesim"], 1)  # One lamb
        self.assertEqual(summary["keci"]["kesim"], 1)  # One goat
        self.assertEqual(summary["koyun"]["kesim"], 1)  # One sheep
