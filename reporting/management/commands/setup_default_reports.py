from django.core.management.base import BaseCommand

from reporting.models import Report


class Command(BaseCommand):
    help = "Create default report definitions"

    def handle(self, *args, **options):
        # Daily Reports
        daily_reports = [
            {
                "name": "Daily Slaughter Summary",
                "description": "Daily report showing all animals slaughtered with weights, offal status, and summary totals by animal type.",
                "report_type": "daily_slaughter",
                "frequency": "daily",
                "output_format": "excel",
                "is_active": True,
                "requires_date_range": True,
                "default_filters": {
                    "animal_types": ["cattle", "sheep", "goat", "lamb", "oglak", "calf", "heifer", "beef"],
                    "include_weights": True,
                    "include_offal_status": True,
                    "include_bowels_status": True,
                },
            },
            {
                "name": "Daily Throughput Report",
                "description": "Daily report showing processing throughput and efficiency metrics.",
                "report_type": "daily_throughput",
                "frequency": "daily",
                "output_format": "excel",
                "is_active": True,
                "requires_date_range": True,
                "default_filters": {"include_efficiency_metrics": True, "include_processing_times": True},
            },
        ]

        # Monthly Reports
        monthly_reports = [
            {
                "name": "Monthly Operations Summary",
                "description": "Monthly report summarizing all operations, yields, and performance metrics.",
                "report_type": "monthly_operations",
                "frequency": "monthly",
                "output_format": "both",
                "is_active": True,
                "requires_date_range": True,
                "default_filters": {
                    "include_financial_summary": True,
                    "include_yield_analysis": True,
                    "include_client_activity": True,
                },
            },
            {
                "name": "Monthly Yield Analysis",
                "description": "Detailed monthly analysis of meat yields and quality metrics.",
                "report_type": "monthly_yield",
                "frequency": "monthly",
                "output_format": "excel",
                "is_active": True,
                "requires_date_range": True,
                "default_filters": {"include_quality_metrics": True, "include_yield_trends": True},
            },
        ]

        # Yearly Reports
        yearly_reports = [
            {
                "name": "Annual Operations Report",
                "description": "Comprehensive annual report covering all aspects of slaughterhouse operations.",
                "report_type": "yearly_operations",
                "frequency": "yearly",
                "output_format": "both",
                "is_active": True,
                "requires_date_range": True,
                "default_filters": {
                    "include_financial_analysis": True,
                    "include_trend_analysis": True,
                    "include_compliance_summary": True,
                },
            },
            {
                "name": "Annual Yield Trends",
                "description": "Yearly analysis of yield trends and performance improvements.",
                "report_type": "yearly_yield",
                "frequency": "yearly",
                "output_format": "excel",
                "is_active": True,
                "requires_date_range": True,
                "default_filters": {"include_trend_analysis": True, "include_benchmarking": True},
            },
        ]

        # Create reports
        all_reports = daily_reports + monthly_reports + yearly_reports

        created_count = 0
        for report_data in all_reports:
            report, created = Report.objects.get_or_create(name=report_data["name"], defaults=report_data)
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Created report: {report.name}"))
            else:
                self.stdout.write(self.style.WARNING(f"Report already exists: {report.name}"))

        self.stdout.write(self.style.SUCCESS(f"Successfully created {created_count} new reports"))
