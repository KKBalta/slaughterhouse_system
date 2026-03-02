import os
from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from reporting.models import GeneratedReport, Report
from reporting.services import ExcelReportGenerator, ReportDataAggregator
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

        # Get system user
        try:
            system_user = User.objects.get(username=options["system_user"])
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'System user "{options["system_user"]}" not found'))
            return

        # Generate reports
        for report_type in options["report_types"]:
            self.generate_report(report_type, report_date, options["output_format"], system_user)

    def generate_report(self, report_type, date, output_format, user):
        """Generate a specific report type for a given date"""
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
                excel_filename = f"daily_slaughter_{date.strftime('%Y-%m-%d')}.xlsx"
                excel_path = os.path.join(
                    settings.MEDIA_ROOT, "reports", "daily", str(date.year), str(date.month).zfill(2)
                )
                os.makedirs(excel_path, exist_ok=True)
                excel_full_path = os.path.join(excel_path, excel_filename)
                excel_wb.save(excel_full_path)
                file_paths.append(excel_full_path)

            # Update generated report
            generated_report.file_path = file_paths[0] if file_paths else None
            generated_report.status = "success"
            generated_report.save()

            self.stdout.write(self.style.SUCCESS(f"Successfully generated {report_type} report for {date}"))

            if file_paths:
                self.stdout.write(f"Files saved to: {', '.join(file_paths)}")

        except Report.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Report definition not found for type: {report_type}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to generate {report_type} report for {date}: {str(e)}"))
