import json
import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from processing.models import Animal, CattleDetails, WeightLog
from reception.models import ServicePackage, SlaughterOrder
from reporting.models import GeneratedReport, Report
from reporting.services import ExcelReportGenerator, PDFReportGenerator, ReportDataAggregator
from users.models import User

pytestmark = pytest.mark.django_db


class _BinaryWorkbook:
    def __init__(self, payload):
        self.payload = payload

    def save(self, path):
        with open(path, "wb") as handle:
            handle.write(self.payload)


class _ImmediateThread:
    def __init__(self, target=None, **kwargs):
        self.target = target
        self.daemon = False

    def start(self):
        if self.target is not None:
            self.target()


def _request(method, user=None, path="/", data=None, content_type=None):
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    factory = RequestFactory()
    request_factory_method = getattr(factory, method.lower())
    if content_type is None:
        request = request_factory_method(path, data=data or {})
    else:
        request = request_factory_method(path, data=data or {}, content_type=content_type)
    request.user = user if user is not None else AnonymousUser()
    return request


class TestReportModel:
    """Test the Report model"""

    @pytest.fixture(autouse=True)
    def _setup(self):
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
        assert self.report.name == "Daily Slaughter Report"
        assert self.report.report_type == "daily_slaughter"
        assert self.report.frequency == "daily"
        assert self.report.is_active

    def test_report_str(self):
        """Test report string representation"""
        assert str(self.report) == "Daily Slaughter Report"

    def test_report_choices(self):
        """Test report type choices"""
        valid_types = [choice[0] for choice in Report.REPORT_TYPE_CHOICES]
        assert "daily_slaughter" in valid_types
        assert "monthly_operations" in valid_types
        assert "yearly_operations" in valid_types


class TestGeneratedReportModel:
    """Test the GeneratedReport model"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.report = Report.objects.create(name="Test Report", report_type="daily_slaughter", frequency="daily")
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            role=User.Role.ADMIN,
        )

    def test_generated_report_creation(self):
        """Test generated report creation"""
        generated_report = GeneratedReport.objects.create(
            report_definition=self.report,
            generated_by=self.user,
            start_date=date.today(),
            end_date=date.today(),
            status="success",
        )

        assert generated_report.report_definition == self.report
        assert generated_report.generated_by == self.user
        assert generated_report.status == "success"

    def test_generated_report_str(self):
        """Test generated report string representation"""
        generated_report = GeneratedReport.objects.create(
            report_definition=self.report, generated_by=self.user, start_date=date.today(), end_date=date.today()
        )

        expected_str = (
            f"Generated Report: {self.report.name} on {generated_report.generated_at.strftime('%Y-%m-%d %H:%M')}"
        )
        assert str(generated_report) == expected_str


class TestReportDataAggregator:
    """Test the ReportDataAggregator service"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            role=User.Role.ADMIN,
        )
        self.service_package = ServicePackage.objects.create(
            name="Test Package", includes_disassembly=True, includes_delivery=True
        )
        self.slaughter_order = SlaughterOrder.objects.create(
            client_name="Test Client",
            service_package=self.service_package,
            order_datetime=timezone.now(),
            status="PENDING",
        )
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
        WeightLog.objects.create(
            animal=self.animal1, weight=Decimal("500.00"), weight_type="live_weight", is_group_weight=False
        )
        WeightLog.objects.create(
            animal=self.animal1, weight=Decimal("300.00"), weight_type="hot_carcass_weight", is_group_weight=False
        )
        CattleDetails.objects.create(
            animal=self.animal1,
            breed="Holstein",
            sakatat_status=1.0,
            bowels_status=1.0,
        )
        self.test_date = date.today()
        self.animal1.slaughter_date = timezone.make_aware(datetime.combine(self.test_date, datetime.min.time()))
        self.animal1.save()
        self.animal2.slaughter_date = timezone.make_aware(datetime.combine(self.test_date, datetime.min.time()))
        self.animal2.save()

    def test_aggregator_initialization(self):
        """Test aggregator initialization"""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        assert aggregator.start_date == self.test_date
        assert aggregator.end_date == self.test_date

    def test_get_daily_slaughter_data(self):
        """Test getting daily slaughter data"""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        data = aggregator.get_daily_slaughter_data()

        assert len(data) == 2
        animal1_data = data[0]
        assert animal1_data["client_name"] == "Test Client"
        assert animal1_data["animal_type"] == "SIGIR"
        assert animal1_data["quantity"] == 1
        assert animal1_data["offal_status"] == "SAĞLAM"
        assert animal1_data["bowels_status"] == "SAĞLAM"

    def test_get_daily_summary_totals(self):
        """Test getting daily summary totals"""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        summary = aggregator.get_daily_summary_totals()

        assert "buyukbas" in summary
        assert "kuzu" in summary
        assert "oglak" in summary
        assert "koyun" in summary
        assert "keci" in summary

        for category in summary.values():
            assert "kesim" in category
            assert "deri" in category
            assert "bagirsak" in category

    def test_get_all_data(self):
        """Test getting all data for report"""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        all_data = aggregator.get_all_data()

        assert "date" in all_data
        assert "daily_data" in all_data
        assert "summary" in all_data
        assert "total_animals" in all_data
        assert "total_hot_carcass_weight" in all_data
        assert "total_leather_weight" in all_data
        assert all_data["total_animals"] == 2

    def test_get_daily_slaughter_data_applies_animal_type_filters(self):
        """Test report filters narrow the queryset."""
        aggregator = ReportDataAggregator(self.test_date, self.test_date, filters={"animal_types": ["cattle"]})
        data = aggregator.get_daily_slaughter_data()

        assert len(data) == 1
        assert data[0]["animal_type"] == "SIGIR"

    def test_turkish_animal_type_mapping(self):
        """Test Turkish animal type mapping"""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)

        assert aggregator._get_turkish_animal_type("cattle") == "SIGIR"
        assert aggregator._get_turkish_animal_type("sheep") == "KOYUN"
        assert aggregator._get_turkish_animal_type("goat") == "KECI"
        assert aggregator._get_turkish_animal_type("lamb") == "KUZU"
        assert aggregator._get_turkish_animal_type("heifer") == "DUVE"
        assert aggregator._get_turkish_animal_type("beef") == "DANA"

    def test_offal_bowels_status_mapping(self):
        """Test offal and bowels status mapping"""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)

        offal_status, bowels_status = aggregator._get_offal_bowels_status(self.animal1)
        assert offal_status == "SAĞLAM"
        assert bowels_status == "SAĞLAM"

        self.animal1.cattle_details.sakatat_status = 0.0
        self.animal1.cattle_details.bowels_status = 0.0
        self.animal1.cattle_details.save()

        offal_status, bowels_status = aggregator._get_offal_bowels_status(self.animal1)
        assert offal_status == "ATIK"
        assert bowels_status == "BOZUK"

        self.animal1.cattle_details.sakatat_status = 0.5
        self.animal1.cattle_details.save()

        offal_status, bowels_status = aggregator._get_offal_bowels_status(self.animal1)
        assert offal_status == "YARIM"

    def _make_aggregation_record(
        self,
        client_name="Client A",
        animal_type="KUZU",
        quantity=1,
        live_weight=40.0,
        hot_carcass_weight=20.0,
        offal_status="SAĞLAM",
        bowels_status="SAĞLAM",
        leather_weight=3.0,
        sakatat_weight=1.0,
        destination="Dest",
        description="",
        identification_tag="",
    ):
        """Build a record in the shape expected by _aggregate_identical_records."""
        return {
            "client_name": client_name,
            "animal_type": animal_type,
            "quantity": quantity,
            "live_weight": live_weight,
            "hot_carcass_weight": hot_carcass_weight,
            "offal_status": offal_status,
            "bowels_status": bowels_status,
            "leather_weight": leather_weight,
            "sakatat_weight": sakatat_weight,
            "destination": destination,
            "description": description,
            "identification_tag": identification_tag,
        }

    def test_aggregate_identical_records_empty(self):
        """_aggregate_identical_records returns empty list for empty input."""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        result = aggregator._aggregate_identical_records([])
        assert result == []

    def test_aggregate_identical_records_merges_small_animal_identical(self):
        """Identical small-animal records (KUZU) are merged and quantity summed; weights multiplied by quantity."""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        rec = self._make_aggregation_record(animal_type="KUZU", quantity=1)
        daily_data = [rec, rec.copy()]
        result = aggregator._aggregate_identical_records(daily_data)
        assert len(result) == 1
        assert result[0]["quantity"] == 2
        assert result[0]["live_weight"] == 80.0
        assert result[0]["hot_carcass_weight"] == 40.0
        assert result[0]["leather_weight"] == 6.0

    def test_aggregate_identical_records_keeps_different_animal_types_separate(self):
        """Records with different animal_type stay as separate rows."""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        daily_data = [
            self._make_aggregation_record(animal_type="KUZU"),
            self._make_aggregation_record(animal_type="DANA"),
        ]
        result = aggregator._aggregate_identical_records(daily_data)
        assert len(result) == 2
        assert result[0]["animal_type"] == "KUZU"
        assert result[1]["animal_type"] == "DANA"

    def test_aggregate_identical_records_keeps_different_weights_separate(self):
        """Records differing in hot_carcass_weight stay as separate rows."""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        daily_data = [
            self._make_aggregation_record(animal_type="KUZU", hot_carcass_weight=20.0),
            self._make_aggregation_record(animal_type="KUZU", hot_carcass_weight=22.0),
        ]
        result = aggregator._aggregate_identical_records(daily_data)
        assert len(result) == 2

    def test_aggregate_identical_records_large_animal_uses_identification_tag(self):
        """For non-small animals (e.g. SIGIR), identification_tag is part of key so same type different tag = 2 rows."""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        daily_data = [
            self._make_aggregation_record(animal_type="SIGIR", identification_tag="T1"),
            self._make_aggregation_record(animal_type="SIGIR", identification_tag="T2"),
        ]
        result = aggregator._aggregate_identical_records(daily_data)
        assert len(result) == 2

    def test_aggregate_identical_records_single_record_unchanged(self):
        """Single record is returned unchanged; weights not multiplied when quantity is 1."""
        aggregator = ReportDataAggregator(self.test_date, self.test_date)
        rec = self._make_aggregation_record(quantity=1, live_weight=50.0, hot_carcass_weight=25.0, leather_weight=4.0)
        result = aggregator._aggregate_identical_records([rec])
        assert len(result) == 1
        assert result[0]["quantity"] == 1
        assert result[0]["live_weight"] == 50.0
        assert result[0]["hot_carcass_weight"] == 25.0
        assert result[0]["leather_weight"] == 4.0


class TestExcelReportGenerator:
    """Test the ExcelReportGenerator service"""

    @pytest.fixture(autouse=True)
    def _setup(self):
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
        assert generator.report_data == self.report_data

    def test_generate_daily_slaughter_excel(self):
        """Test generating daily slaughter Excel report"""
        generator = ExcelReportGenerator(self.report_data)
        workbook = generator.generate_daily_slaughter_excel()

        assert workbook is not None
        ws = workbook.active
        assert ws.title == "Daily Slaughter Report"
        assert ws["A1"].value == "GÜNLÜK KESİM RAPORU - 2024-01-15"
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
            assert ws.cell(row=3, column=i).value == header

        assert ws.cell(row=4, column=1).value == "Test Destination"
        assert ws.cell(row=4, column=2).value == 1
        assert ws.cell(row=4, column=3).value == "SIGIR"
        assert ws.cell(row=4, column=4).value == 200.0
        assert ws.cell(row=4, column=5).value == ""
        assert ws.cell(row=4, column=6).value == "SAĞLAM"
        assert ws.cell(row=4, column=7).value == "SAĞLAM"
        assert ws.cell(row=4, column=8).value == 25.0
        assert ws.cell(row=4, column=9).value == "Test Client"
        assert ws.cell(row=4, column=10).value == ""

        summary_start_row = 7
        assert ws.cell(row=summary_start_row, column=1).value == "ÖZET"
        summary_headers = ["", "KESİM", "DERİ", "BAĞIRSAK"]
        for i, header in enumerate(summary_headers, 1):
            assert ws.cell(row=summary_start_row + 1, column=i).value == header

        assert ws.cell(row=summary_start_row + 2, column=1).value == "BÜYÜKBAŞ"
        assert ws.cell(row=summary_start_row + 2, column=2).value == 1
        assert ws.cell(row=summary_start_row + 2, column=3).value == 25.0
        assert ws.cell(row=summary_start_row + 2, column=4).value == 1


class TestPDFReportGenerator:
    """Test the PDFReportGenerator service"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.report_data = {
            "start_date": "01.01.2024",
            "end_date": "01.01.2024",
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
                    "identification_tag": "TAG-001",
                }
            ],
            "summary": {
                "buyukbas": {"kesim": 1, "deri": 25.0, "bagirsak": 1, "sakatat": 1},
                "kuzu": {"kesim": 0, "deri": 0, "bagirsak": 0, "sakatat": 0},
                "oglak": {"kesim": 0, "deri": 0, "bagirsak": 0, "sakatat": 0},
                "koyun": {"kesim": 0, "deri": 0, "bagirsak": 0, "sakatat": 0},
                "keci": {"kesim": 0, "deri": 0, "bagirsak": 0, "sakatat": 0},
            },
        }

    def test_pdf_generator_initialization(self):
        """Test PDF generator initialization."""
        generator = PDFReportGenerator(self.report_data)
        assert generator.report_data == self.report_data

    def test_convert_turkish_chars_empty(self):
        """_convert_turkish_chars returns empty string for empty input."""
        generator = PDFReportGenerator(self.report_data)
        assert generator._convert_turkish_chars("") == ""
        assert generator._convert_turkish_chars(None) is None

    def test_convert_turkish_chars_converts_all(self):
        """_convert_turkish_chars converts Turkish letters to ASCII."""
        generator = PDFReportGenerator(self.report_data)
        assert generator._convert_turkish_chars("ĞÜŞİÖÇ ğüşışöç") == "GUSIOC gusisoc"
        assert generator._convert_turkish_chars("SAĞLAM") == "SAGLAM"
        assert generator._convert_turkish_chars("İzmir") == "Izmir"

    def test_convert_turkish_chars_plain_unchanged(self):
        """_convert_turkish_chars leaves ASCII text unchanged."""
        generator = PDFReportGenerator(self.report_data)
        assert generator._convert_turkish_chars("Hello World") == "Hello World"

    def test_truncate_text_empty(self):
        """_truncate_text returns empty string for empty/None."""
        generator = PDFReportGenerator(self.report_data)
        assert generator._truncate_text("") == ""
        assert generator._truncate_text(None) == ""

    def test_truncate_text_short_unchanged(self):
        """_truncate_text leaves short text unchanged."""
        generator = PDFReportGenerator(self.report_data)
        assert generator._truncate_text("Short", max_length=20) == "Short"

    def test_truncate_text_long_truncated(self):
        """_truncate_text truncates long text with ellipsis."""
        generator = PDFReportGenerator(self.report_data)
        assert generator._truncate_text("This is a long text", max_length=15) == "This is a lo..."

    def test_truncate_text_non_string(self):
        """_truncate_text converts non-string to str then truncates."""
        generator = PDFReportGenerator(self.report_data)
        assert generator._truncate_text(12345, max_length=4) == "1..."

    def test_wrap_text_empty(self):
        """_wrap_text returns empty string for empty/None."""
        generator = PDFReportGenerator(self.report_data)
        assert generator._wrap_text("") == ""
        assert generator._wrap_text(None) == ""

    def test_wrap_text_short_unchanged(self):
        """_wrap_text leaves short text as single line."""
        generator = PDFReportGenerator(self.report_data)
        assert generator._wrap_text("Short", max_chars_per_line=15) == "Short"

    def test_wrap_text_wraps_long_line(self):
        """_wrap_text wraps at word boundaries."""
        generator = PDFReportGenerator(self.report_data)
        text = "One Two Three Four Five"
        result = generator._wrap_text(text, max_chars_per_line=10)
        assert "\n" in result
        lines = result.split("\n")
        for line in lines:
            assert len(line) <= 10

    def test_wrap_text_long_single_word_truncated(self):
        """_wrap_text truncates a single word longer than max_chars_per_line."""
        generator = PDFReportGenerator(self.report_data)
        result = generator._wrap_text("VeryLongWordWithoutSpaces", max_chars_per_line=8)
        assert result == "VeryL..."

    def test_generate_daily_slaughter_pdf_returns_path(self):
        """generate_daily_slaughter_pdf returns a file path."""
        generator = PDFReportGenerator(self.report_data)
        path = generator.generate_daily_slaughter_pdf()
        assert isinstance(path, str)
        assert path.endswith(".pdf")

    def test_generate_daily_slaughter_pdf_file_exists(self):
        """generate_daily_slaughter_pdf creates a file that exists."""
        import os

        generator = PDFReportGenerator(self.report_data)
        path = generator.generate_daily_slaughter_pdf()
        assert os.path.isfile(path)

    def test_generate_daily_slaughter_pdf_valid_pdf(self):
        """generate_daily_slaughter_pdf produces valid PDF (magic bytes)."""
        generator = PDFReportGenerator(self.report_data)
        path = generator.generate_daily_slaughter_pdf()
        with open(path, "rb") as f:
            header = f.read(5)
        assert header == b"%PDF-"

    def test_generate_daily_slaughter_pdf_empty_daily_data(self):
        """generate_daily_slaughter_pdf works with empty daily_data."""
        data = {"start_date": "01.01.2024", "end_date": "01.01.2024", "daily_data": [], "summary": {}}
        generator = PDFReportGenerator(data)
        path = generator.generate_daily_slaughter_pdf()
        assert isinstance(path, str)
        assert path.endswith(".pdf")


class TestManagementCommands:
    """Test management commands"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.system_user = User.objects.create_user(
            username="system",
            email="system@slaughterhouse.local",
            password="systempass123",
            role="ADMIN",
            is_staff=True,
        )
        self.report = Report.objects.create(
            name="Daily Slaughter Report",
            report_type="daily_slaughter",
            frequency="daily",
            output_format="excel",
            is_active=True,
        )

    def test_setup_system_user_command(self):
        """Test setup system user command"""
        User.objects.filter(username="system").delete()
        call_command("setup_system_user")
        system_user = User.objects.get(username="system")
        assert system_user.email == "system@slaughterhouse.local"
        assert system_user.role == "ADMIN"
        assert system_user.is_staff

    def test_setup_system_user_already_exists(self):
        """Test setup system user when user already exists"""
        call_command("setup_system_user")
        system_user = User.objects.get(username="system")
        assert system_user.username == "system"

    @patch("reporting.services.ReportDataAggregator")
    @patch("reporting.services.ExcelReportGenerator")
    def test_generate_daily_reports_command(self, mock_excel_generator, mock_aggregator):
        """Test generate daily reports command"""
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

        with patch("os.makedirs"), patch("os.path.join", return_value="/tmp/test.xlsx"):
            call_command("generate_daily_reports", "--date=2024-01-15")

        generated_report = GeneratedReport.objects.get(report_definition=self.report, generated_by=self.system_user)
        assert generated_report.status == "success"
        assert generated_report.start_date == date(2024, 1, 15)
        assert generated_report.end_date == date(2024, 1, 15)

    def test_generate_daily_reports_invalid_date(self):
        """Test generate daily reports with invalid date"""
        call_command("generate_daily_reports", "--date=invalid-date")
        assert GeneratedReport.objects.count() == 0

    def test_generate_daily_reports_system_user_not_found(self):
        """Test generate daily reports when system user doesn't exist"""
        User.objects.filter(username="system").delete()
        call_command("generate_daily_reports", "--system-user=nonexistent")
        assert GeneratedReport.objects.count() == 0

    def test_generate_daily_reports_report_definition_not_found(self):
        """Test generate daily reports when no active report definition exists."""
        self.report.delete()
        stdout = StringIO()

        call_command("generate_daily_reports", "--date=2024-01-15", stdout=stdout)

        assert "Report definition not found for type: daily_slaughter" in stdout.getvalue()
        assert GeneratedReport.objects.count() == 0

    @patch("reporting.management.commands.generate_daily_reports.os.makedirs")
    @patch("reporting.management.commands.generate_daily_reports.ExcelReportGenerator")
    @patch("reporting.management.commands.generate_daily_reports.ReportDataAggregator")
    def test_generate_daily_reports_handles_generation_failure(
        self,
        mock_aggregator,
        mock_excel_generator,
        _mock_makedirs,
    ):
        """Test generate daily reports when workbook generation fails."""
        stdout = StringIO()
        mock_aggregator.return_value.get_all_data.return_value = {
            "date": "2024-01-15",
            "daily_data": [],
            "summary": {},
            "total_animals": 0,
            "total_weight": 0,
            "total_leather_weight": 0,
        }
        mock_workbook = MagicMock()
        mock_workbook.save.side_effect = RuntimeError("disk full")
        mock_excel_generator.return_value.generate_daily_slaughter_excel.return_value = mock_workbook

        call_command("generate_daily_reports", "--date=2024-01-15", stdout=stdout)

        generated_report = GeneratedReport.objects.get(report_definition=self.report, generated_by=self.system_user)
        assert generated_report.status == "pending"
        assert "Failed to generate daily_slaughter report for 2024-01-15: disk full" in stdout.getvalue()

    def test_generate_daily_reports_pdf_output_skips_file_save(self):
        """Test generate daily reports when output format does not create Excel files."""
        stdout = StringIO()

        call_command("generate_daily_reports", "--date=2024-01-15", "--output-format=pdf", stdout=stdout)

        generated_report = GeneratedReport.objects.get(report_definition=self.report, generated_by=self.system_user)
        assert generated_report.status == "success"
        assert generated_report.file_path is None
        assert "Files saved to:" not in stdout.getvalue()

    @override_settings(USE_MULTITENANT=True)
    @patch("reporting.management.commands.generate_daily_reports.schema_context")
    def test_generate_daily_reports_single_schema_uses_schema_context(self, mock_schema_context):
        """Test generate daily reports runs inside the requested tenant schema."""

        @contextmanager
        def _switch_schema(schema_name):
            previous = getattr(connection, "schema_name", None)
            connection.schema_name = schema_name
            try:
                yield
            finally:
                connection.schema_name = previous

        mock_schema_context.side_effect = _switch_schema

        with patch(
            "reporting.management.commands.generate_daily_reports.Command._run_for_current_schema"
        ) as mock_runner:
            call_command("generate_daily_reports", "--date=2024-01-15", "--schema=acme")

        mock_schema_context.assert_called_once_with("acme")
        mock_runner.assert_called_once()

    @override_settings(USE_MULTITENANT=True)
    @patch("reporting.management.commands.generate_daily_reports.Command._iter_active_tenant_schemas")
    @patch("reporting.management.commands.generate_daily_reports.schema_context")
    @patch("reporting.management.commands.generate_daily_reports.ExcelReportGenerator")
    @patch("reporting.management.commands.generate_daily_reports.ReportDataAggregator")
    def test_generate_daily_reports_creates_report_for_each_tenant(
        self,
        mock_aggregator,
        mock_excel_generator,
        mock_schema_context,
        mock_iter_schemas,
        tmp_path,
    ):
        """Test multitenant runs create one report record per tenant schema."""
        mock_iter_schemas.return_value = ["acme", "bravo"]
        mock_aggregator.return_value.get_all_data.return_value = {
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
            "total_live_weight": 0,
            "total_hot_carcass_weight": 0,
            "total_leather_weight": 0,
        }
        mock_excel_generator.return_value.generate_daily_slaughter_excel.return_value = _BinaryWorkbook(b"tenant-xlsx")

        @contextmanager
        def _switch_schema(schema_name):
            previous = getattr(connection, "schema_name", None)
            connection.schema_name = schema_name
            try:
                yield
            finally:
                connection.schema_name = previous

        mock_schema_context.side_effect = _switch_schema

        with override_settings(MEDIA_ROOT=str(tmp_path), USE_MULTITENANT=True):
            call_command("generate_daily_reports", "--date=2024-01-15", "--all-tenants")

        assert GeneratedReport.objects.count() == 2
        file_paths = sorted(GeneratedReport.objects.values_list("file_path", flat=True))
        assert any(os.path.join("reports", "acme", "daily", "2024", "01") in path for path in file_paths)
        assert any(os.path.join("reports", "bravo", "daily", "2024", "01") in path for path in file_paths)


@pytest.mark.django_db(transaction=True)
class TestIntegration:
    """Integration tests for the complete reporting workflow"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            role=User.Role.ADMIN,
        )
        self.service_package = ServicePackage.objects.create(
            name="Test Package", includes_disassembly=True, includes_delivery=True
        )
        self.slaughter_order = SlaughterOrder.objects.create(
            client_name="Test Client",
            service_package=self.service_package,
            order_datetime=timezone.now(),
            status="PENDING",
        )
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
            WeightLog.objects.create(
                animal=animal, weight=Decimal(f"{400 + i * 100}.00"), weight_type="live_weight", is_group_weight=False
            )
            WeightLog.objects.create(
                animal=animal,
                weight=Decimal(f"{250 + i * 50}.00"),
                weight_type="hot_carcass_weight",
                is_group_weight=False,
            )
        CattleDetails.objects.create(animal=self.animals[0], breed="Holstein", sakatat_status=1.0, bowels_status=1.0)

    def test_complete_report_generation_workflow(self):
        """Test the complete report generation workflow"""
        report = Report.objects.create(
            name="Daily Slaughter Report",
            report_type="daily_slaughter",
            frequency="daily",
            output_format="excel",
            is_active=True,
        )
        User.objects.create_user(
            username="system",
            email="system@slaughterhouse.local",
            password="systempass123",
            role="ADMIN",
            is_staff=True,
        )
        aggregator = ReportDataAggregator(date.today(), date.today())
        report_data = aggregator.get_all_data()
        assert "daily_data" in report_data
        assert "summary" in report_data
        assert len(report_data["daily_data"]) == 4
        excel_generator = ExcelReportGenerator(report_data)
        workbook = excel_generator.generate_daily_slaughter_excel()
        ws = workbook.active
        assert ws.title == "Daily Slaughter Report"
        data_start_row = 4
        for i in range(4):
            row = data_start_row + i
            assert ws.cell(row=row, column=1).value is not None
            assert ws.cell(row=row, column=3).value is not None
        summary_start_row = None
        for row in range(1, 20):
            if ws.cell(row=row, column=1).value == "ÖZET":
                summary_start_row = row
                break
        assert summary_start_row is not None, "ÖZET section not found in Excel file"
        buyukbas_row = summary_start_row + 2
        assert ws.cell(row=buyukbas_row, column=1).value == "BÜYÜKBAŞ"
        assert ws.cell(row=buyukbas_row, column=2).value == 1

    def test_report_data_accuracy(self):
        """Test that report data is accurate"""
        aggregator = ReportDataAggregator(date.today(), date.today())
        report_data = aggregator.get_all_data()

        assert report_data["total_animals"] == 4
        for animal_data in report_data["daily_data"]:
            assert "client_name" in animal_data
            assert "animal_type" in animal_data
            assert "hot_carcass_weight" in animal_data
            assert "offal_status" in animal_data
            assert "bowels_status" in animal_data
            assert "leather_weight" in animal_data

        summary = report_data["summary"]
        assert summary["buyukbas"]["kesim"] == 1
        assert summary["kuzu"]["kesim"] == 1
        assert summary["keci"]["kesim"] == 1
        assert summary["koyun"]["kesim"] == 1


class TestReportingViews:
    @pytest.fixture(autouse=True)
    def _setup(self, admin_user, operator_user):
        self.admin_user = admin_user
        self.operator_user = operator_user
        self.report_definition = Report.objects.create(
            name="Dashboard Report",
            report_type="daily_slaughter",
            frequency="daily",
            output_format="excel",
            is_active=True,
        )

    def test_report_dashboard_requires_login(self):
        from reporting.views import report_dashboard

        response = report_dashboard(_request("get"))

        assert response.status_code == 302
        assert "/login/" in response.url

    def test_report_dashboard_client_force_login_allows_manager(self, client, manager_user):
        from django.urls import reverse

        client.force_login(manager_user)

        response = client.get(reverse("report_dashboard"))

        assert response.status_code == 200

    def test_report_dashboard_client_force_login_allows_admin(self, client):
        from django.urls import reverse

        client.force_login(self.admin_user)

        response = client.get(reverse("report_dashboard"))

        assert response.status_code == 200

    def test_report_dashboard_renders_for_admin(self):
        from django.http import HttpResponse

        from reporting.views import report_dashboard

        captured = {}

        def _fake_render(_request, template_name, context=None):
            captured["template"] = template_name
            captured["context"] = context
            return HttpResponse("ok")

        with patch("reporting.views.render", side_effect=_fake_render):
            response = report_dashboard(_request("get", self.admin_user, "/reporting/"))

        assert response.status_code == 200
        assert captured["template"] == "reporting/simple_dashboard.html"

    def test_report_dashboard_rejects_operator(self):
        from reporting.views import report_dashboard

        response = report_dashboard(_request("get", self.operator_user, "/reporting/"))

        assert response.status_code == 302
        assert "/login/" in response.url

    @patch("reporting.views.ExcelReportGenerator")
    @patch("reporting.views.ReportDataAggregator")
    def test_generate_report_excel_success(self, mock_aggregator, mock_excel_generator):
        from reporting.views import generate_report

        mock_aggregator.return_value.get_all_data.return_value = {"daily_data": [], "summary": {}}
        mock_excel_generator.return_value.generate_daily_slaughter_excel.return_value = _BinaryWorkbook(b"excel-bytes")

        response = generate_report(
            _request(
                "post",
                self.admin_user,
                "/reporting/generate/",
                {"start_date": "2026-03-01", "end_date": "2026-03-02", "output_format": "excel"},
            )
        )

        assert response.status_code == 200
        assert response["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert response.content == b"excel-bytes"
        assert response["Content-Disposition"] == 'attachment; filename="report_2026-03-01_to_2026-03-02.xlsx"'

    @patch("reporting.views.ExcelReportGenerator")
    @patch("reporting.views.ReportDataAggregator")
    def test_generate_report_excel_failure_returns_500(self, mock_aggregator, mock_excel_generator):
        from reporting.views import generate_report

        mock_aggregator.return_value.get_all_data.return_value = {"daily_data": [], "summary": {}}
        mock_excel_generator.return_value.generate_daily_slaughter_excel.side_effect = RuntimeError("xlsx failed")

        response = generate_report(
            _request(
                "post",
                self.admin_user,
                "/reporting/generate/",
                {"start_date": "2026-03-01", "end_date": "2026-03-02", "output_format": "excel"},
            )
        )

        assert response.status_code == 500
        assert response.content == b"An error occurred processing your request."

    @patch("reporting.views.PDFReportGenerator")
    @patch("reporting.views.ReportDataAggregator")
    def test_generate_report_pdf_success(self, mock_aggregator, mock_pdf_generator, tmp_path):
        from reporting.views import generate_report

        pdf_path = tmp_path / "report.pdf"
        pdf_path.write_bytes(b"%PDF-test")
        mock_aggregator.return_value.get_all_data.return_value = {"daily_data": [], "summary": {}}
        mock_pdf_generator.return_value.generate_daily_slaughter_pdf.return_value = str(pdf_path)

        response = generate_report(
            _request(
                "post",
                self.admin_user,
                "/reporting/generate/",
                {"start_date": "2026-03-01", "end_date": "2026-03-02", "output_format": "pdf"},
            )
        )

        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert response.content == b"%PDF-test"
        assert response["Content-Disposition"] == 'attachment; filename="report_2026-03-01_to_2026-03-02.pdf"'
        assert not pdf_path.exists()

    @patch("reporting.views.PDFReportGenerator")
    @patch("reporting.views.ReportDataAggregator")
    def test_generate_report_pdf_failure_returns_500(self, mock_aggregator, mock_pdf_generator):
        from reporting.views import generate_report

        mock_aggregator.return_value.get_all_data.return_value = {"daily_data": [], "summary": {}}
        mock_pdf_generator.return_value.generate_daily_slaughter_pdf.side_effect = RuntimeError("pdf failed")

        response = generate_report(
            _request(
                "post",
                self.admin_user,
                "/reporting/generate/",
                {"start_date": "2026-03-01", "end_date": "2026-03-02", "output_format": "pdf"},
            )
        )

        assert response.status_code == 500
        assert response.content == b"An error occurred processing your request."

    @patch("reporting.views.ReportDataAggregator")
    def test_generate_report_invalid_output_format_returns_400(self, mock_aggregator):
        from reporting.views import generate_report

        mock_aggregator.return_value.get_all_data.return_value = {"daily_data": [], "summary": {}}

        response = generate_report(
            _request(
                "post",
                self.admin_user,
                "/reporting/generate/",
                {"start_date": "2026-03-01", "end_date": "2026-03-02", "output_format": "csv"},
            )
        )

        assert response.status_code == 400
        assert response.content == b"Invalid output format. Please select Excel or PDF."

    def test_generate_report_invalid_dates_return_500(self):
        from reporting.views import generate_report

        response = generate_report(
            _request(
                "post",
                self.admin_user,
                "/reporting/generate/",
                {"start_date": "invalid", "end_date": "2026-03-02", "output_format": "excel"},
            )
        )

        assert response.status_code == 500
        assert response.content == b"An error occurred processing your request."

    def test_generate_report_get_returns_405(self):
        from reporting.views import generate_report

        response = generate_report(_request("get", self.admin_user, "/reporting/generate/"))

        assert response.status_code == 405
        assert response.content == b"Method not allowed"

    @patch("reporting.views.call_command")
    @patch("reporting.views.threading.Thread", side_effect=lambda target: _ImmediateThread(target=target))
    def test_generate_daily_reports_api_starts_command(self, _mock_thread, mock_call_command, client):
        from django.urls import reverse

        response = client.post(
            reverse("api_generate_daily_reports"),
            data=json.dumps(
                {
                    "report_types": ["daily_slaughter", "daily_weights"],
                    "output_format": "pdf",
                    "system_user": "scheduler",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "message": "Daily report generation started",
            "report_types": ["daily_slaughter", "daily_weights"],
        }
        mock_call_command.assert_called_once_with(
            "generate_daily_reports",
            report_types=["daily_slaughter", "daily_weights"],
            output_format="pdf",
            system_user="scheduler",
        )

    @override_settings(USE_MULTITENANT=True)
    @patch("django_tenants.utils.get_public_schema_name")
    @patch("reporting.views.call_command")
    @patch("reporting.views.threading.Thread", side_effect=lambda target: _ImmediateThread(target=target))
    def test_generate_daily_reports_api_passes_request_tenant_schema(
        self,
        _mock_thread,
        mock_call_command,
        mock_public_schema_name,
    ):
        from reporting.views import generate_daily_reports_api

        mock_public_schema_name.return_value = "public"
        request = _request(
            "post",
            path="/reporting/api/generate-daily/",
            data=json.dumps({}),
            content_type="application/json",
        )
        request.tenant = SimpleNamespace(schema_name="acme")

        response = generate_daily_reports_api(request)

        assert response.status_code == 200
        mock_call_command.assert_called_once_with(
            "generate_daily_reports",
            report_types=["daily_slaughter"],
            output_format="excel",
            system_user="system",
            schema="acme",
        )

    @override_settings(USE_MULTITENANT=True)
    @patch("django_tenants.utils.get_public_schema_name")
    def test_generate_daily_reports_api_rejects_public_schema_without_explicit_target(self, mock_public_schema_name):
        from reporting.views import generate_daily_reports_api

        mock_public_schema_name.return_value = "public"
        request = _request(
            "post",
            path="/reporting/api/generate-daily/",
            data=json.dumps({}),
            content_type="application/json",
        )
        request.tenant = SimpleNamespace(schema_name="public")

        response = generate_daily_reports_api(request)

        assert response.status_code == 400
        assert json.loads(response.content) == {
            "status": "error",
            "message": "Tenant schema is required when generating reports from the public host.",
        }

    @patch("reporting.views.call_command", side_effect=CommandError("scheduler failed"))
    @patch("reporting.views.threading.Thread", side_effect=lambda target: _ImmediateThread(target=target))
    def test_generate_daily_reports_api_swallows_command_error(self, _mock_thread, _mock_call_command, client):
        from django.urls import reverse

        response = client.post(
            reverse("api_generate_daily_reports"),
            data=json.dumps({}),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert response.json()["report_types"] == ["daily_slaughter"]

    def test_generate_daily_reports_api_invalid_json_returns_500(self, client):
        from django.urls import reverse

        response = client.post(
            reverse("api_generate_daily_reports"),
            data="{not-json",
            content_type="application/json",
        )

        assert response.status_code == 500
        assert response.json() == {
            "status": "error",
            "message": "An error occurred processing your request.",
        }

    def test_test_report_generation_get_renders_template(self):
        from django.http import HttpResponse

        from reporting.views import test_report_generation

        captured = {}

        def _fake_render(_request, template_name, context=None):
            captured["template"] = template_name
            captured["context"] = context
            return HttpResponse("ok")

        with patch("reporting.views.render", side_effect=_fake_render):
            response = test_report_generation(_request("get", self.admin_user, "/reporting/test/"))

        assert response.status_code == 200
        assert captured["template"] == "reporting/test_report.html"

    @patch("reporting.views.ExcelReportGenerator")
    @patch("reporting.views.ReportDataAggregator")
    def test_test_report_generation_post_returns_excel(self, mock_aggregator, mock_excel_generator):
        from reporting.views import test_report_generation

        expected_date = (timezone.now() - timedelta(days=1)).date()
        mock_aggregator.return_value.get_all_data.return_value = {"daily_data": [], "summary": {}}
        mock_excel_generator.return_value.generate_daily_slaughter_excel.return_value = _BinaryWorkbook(b"test-xlsx")

        response = test_report_generation(_request("post", self.admin_user, "/reporting/test/"))

        assert response.status_code == 200
        assert response["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert response.content == b"test-xlsx"
        assert response["Content-Disposition"] == f'attachment; filename="test_report_{expected_date}.xlsx"'

    @patch("reporting.views.ReportDataAggregator", side_effect=RuntimeError("aggregate failed"))
    def test_test_report_generation_post_failure_returns_json(self, _mock_aggregator):
        from reporting.views import test_report_generation

        response = test_report_generation(_request("post", self.admin_user, "/reporting/test/"))

        assert response.status_code == 500
        assert json.loads(response.content) == {
            "status": "error",
            "message": "An error occurred processing your request.",
        }

    def test_report_list_orders_reports_newest_first(self):
        from django.http import HttpResponse

        from reporting.views import report_list

        older = GeneratedReport.objects.create(
            report_definition=self.report_definition,
            generated_by=self.admin_user,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 1),
            status="success",
        )
        newer = GeneratedReport.objects.create(
            report_definition=self.report_definition,
            generated_by=self.admin_user,
            start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 2),
            status="success",
        )
        GeneratedReport.objects.filter(pk=older.pk).update(generated_at=timezone.now() - timedelta(days=2))
        GeneratedReport.objects.filter(pk=newer.pk).update(generated_at=timezone.now() - timedelta(days=1))

        captured = {}

        def _fake_render(_request, template_name, context=None):
            captured["template"] = template_name
            captured["context"] = context or {}
            return HttpResponse("ok")

        with patch("reporting.views.render", side_effect=_fake_render):
            response = report_list(_request("get", self.admin_user, "/reporting/list/"))

        reports = list(captured["context"]["reports"])

        assert response.status_code == 200
        assert captured["template"] == "reporting/report_list.html"
        assert [report.pk for report in reports[:2]] == [newer.pk, older.pk]
