import os
from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from reporting.models import GeneratedReport, Report
from reporting.services import ExcelReportGenerator, ReportDataAggregator
from tenants.models import Client
from users.models import User


class Command(BaseCommand):
    help = "Generate daily reports for the previous day"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Specific date to generate reports for (YYYY-MM-DD). Defaults to yesterday.",
        )
        parser.add_argument(
            "--report-types",
            nargs="+",
            default=["daily_slaughter"],
            help="List of report types to generate",
        )
        parser.add_argument(
            "--output-format",
            choices=["pdf", "excel", "both"],
            default="excel",
            help="Output format for reports",
        )
        parser.add_argument(
            "--system-user",
            type=str,
            default="system",
            help="Username for system-generated reports",
        )
        parser.add_argument(
            "--schema",
            type=str,
            help="Tenant schema name to generate reports for.",
        )
        parser.add_argument(
            "--all-tenants",
            action="store_true",
            help="Generate reports for every active tenant schema.",
        )

    def handle(self, *args, **options):
        # Determine report date
        if options["date"]:
            try:
                report_date = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError:
                self.stdout.write(self.style.ERROR(f"Invalid date format: {options['date']}. Use YYYY-MM-DD format."))
                return
        else:
            report_date = (timezone.now() - timedelta(days=1)).date()

        if options["schema"] and options["all_tenants"]:
            self.stdout.write(self.style.ERROR("Use either --schema or --all-tenants, not both."))
            return

        if options["all_tenants"]:
            for schema_name in self._iter_active_tenant_schemas():
                self._run_for_schema(schema_name, report_date, options)
            return

        if options["schema"]:
            self._run_for_schema(options["schema"], report_date, options)
            return

        self._run_for_current_schema(report_date, options)

    def _schema_label(self, schema_name=None):
        value = schema_name or getattr(connection, "schema_name", None) or "default"
        return f"[{value}]"

    def _iter_active_tenant_schemas(self):
        if not getattr(settings, "USE_MULTITENANT", False):
            current = getattr(connection, "schema_name", None)
            return [current] if current else []

        public_schema = get_public_schema_name()
        with schema_context(public_schema):
            return list(
                Client.objects.filter(is_active=True)
                .exclude(schema_name=public_schema)
                .order_by("schema_name")
                .values_list("schema_name", flat=True)
            )

    def _run_for_schema(self, schema_name, report_date, options):
        with schema_context(schema_name):
            self._run_for_current_schema(report_date, options, schema_name=schema_name)

    def _run_for_current_schema(self, report_date, options, schema_name=None):
        current_schema = schema_name or getattr(connection, "schema_name", None)

        # Get system user inside the active tenant schema.
        try:
            system_user = User.objects.get(username=options["system_user"])
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'{self._schema_label(current_schema)} System user "{options["system_user"]}" not found')
            )
            return

        # Generate reports
        for report_type in options["report_types"]:
            self.generate_report(report_type, report_date, options["output_format"], system_user)

    def _report_output_dir(self, report_date):
        parts = [settings.MEDIA_ROOT, "reports"]
        if getattr(settings, "USE_MULTITENANT", False):
            schema_name = getattr(connection, "schema_name", None) or "default"
            parts.append(schema_name)
        parts.extend(["daily", str(report_date.year), str(report_date.month).zfill(2)])
        return os.path.join(*parts)

    def generate_report(self, report_type, date, output_format, user):
        """Generate a specific report type for a given date"""
        current_schema = getattr(connection, "schema_name", None)
        try:
            # Get report definition
            report = Report.objects.get(report_type=report_type, frequency="daily", is_active=True)

            # Calculate date range (daily reports typically cover one day)
            start_date = date
            end_date = date

            # Aggregate data
            aggregator = ReportDataAggregator(start_date, end_date)
            report_data = aggregator.get_all_data()

            # Create generated report record
            generated_report = GeneratedReport.objects.create(
                report_definition=report, generated_by=user, start_date=start_date, end_date=end_date, status="pending"
            )

            # Generate files
            file_paths = []

            if output_format in ["excel", "both"]:
                excel_generator = ExcelReportGenerator(report_data, report.configuration)
                excel_wb = excel_generator.generate_daily_slaughter_excel()

                # Save Excel file
                excel_filename = f"{report_type}_{date.strftime('%Y-%m-%d')}.xlsx"
                excel_path = self._report_output_dir(date)
                os.makedirs(excel_path, exist_ok=True)
                excel_full_path = os.path.join(excel_path, excel_filename)
                excel_wb.save(excel_full_path)
                file_paths.append(excel_full_path)

            # Update generated report
            generated_report.file_path = file_paths[0] if file_paths else None
            generated_report.status = "success"
            generated_report.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"{self._schema_label(current_schema)} Successfully generated {report_type} report for {date}"
                )
            )

            if file_paths:
                self.stdout.write(f"{self._schema_label(current_schema)} Files saved to: {', '.join(file_paths)}")

        except Report.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f"{self._schema_label(current_schema)} Report definition not found for type: {report_type}")
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(
                    f"{self._schema_label(current_schema)} Failed to generate {report_type} report for {date}: {str(e)}"
                )
            )
