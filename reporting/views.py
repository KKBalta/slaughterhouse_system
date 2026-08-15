import json
import logging
import os
import threading
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from users.views import client_required, manager_or_admin_required

from .models import GeneratedReport
from .services import ExcelReportGenerator, OperationsInsightService, PDFReportGenerator, ReportDataAggregator

logger = logging.getLogger(__name__)


@login_required
@manager_or_admin_required
def report_dashboard(request):
    """Simple dashboard for report generation"""
    return render(request, "reporting/simple_dashboard.html")


@login_required
@manager_or_admin_required
@require_http_methods(["GET"])
def api_ops_kpis(request):
    """JSON feed for the live Ops panel on /reporting/ (Idea 1)."""
    try:
        data = OperationsInsightService().get_live_ops_kpis()
        return JsonResponse(data)
    except Exception:
        logger.exception("api_ops_kpis failed")
        return JsonResponse({"error": "ops_kpis_failed"}, status=500)


@login_required
@manager_or_admin_required
@require_http_methods(["GET"])
def api_quality_insight(request):
    """JSON feed for the Quality & Loss panel on /reporting/ (Idea 2)."""
    from datetime import datetime as dt

    def _parse_date(s):
        if not s:
            return None
        try:
            return dt.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None

    try:
        window_days = int(request.GET.get("window_days", 90))
    except (TypeError, ValueError):
        window_days = 90
    try:
        sigma = float(request.GET.get("sigma", 2.0))
    except (TypeError, ValueError):
        sigma = 2.0
    start = _parse_date(request.GET.get("start"))
    end = _parse_date(request.GET.get("end"))

    try:
        data = OperationsInsightService().get_quality_insight(
            window_days=window_days, start=start, end=end, sigma=sigma
        )
        return JsonResponse(data)
    except Exception:
        logger.exception("api_quality_insight failed")
        return JsonResponse({"error": "quality_insight_failed"}, status=500)


@login_required
@manager_or_admin_required
def generate_report(request):
    """Generate report based on form data"""
    if request.method == "POST":
        try:
            start_date = request.POST.get("start_date")
            end_date = request.POST.get("end_date")
            output_format = request.POST.get("output_format", "excel")

            # Convert string dates to date objects
            from datetime import datetime

            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()

            report_type = request.POST.get("report_type", "daily_slaughter")

            # Generate report data
            aggregator = ReportDataAggregator(start_date_obj, end_date_obj, filters={"report_type": report_type})
            report_data = aggregator.get_all_data()

            logger.debug(
                "Report data for %s to %s: report_type=%s, daily_data count=%s, summary=%s",
                start_date,
                end_date,
                report_type,
                len(report_data.get("daily_data", [])),
                report_data.get("summary", {}),
            )
            if not report_data.get("daily_data"):
                logger.debug("No data found for the selected date range - generating empty report")

            if output_format == "excel":
                try:
                    excel_generator = ExcelReportGenerator(report_data)
                    _excel_dispatch = {
                        "daily_slaughter": excel_generator.generate_daily_slaughter_excel,
                        "cold_shrinkage": excel_generator.generate_cold_shrinkage_excel,
                        "cut_yield_analysis": excel_generator.generate_cut_yield_excel,
                        "pipeline_time_analysis": excel_generator.generate_pipeline_time_excel,
                        "byproduct_offal_summary": excel_generator.generate_byproduct_offal_excel,
                        "client_activity_summary": excel_generator.generate_client_activity_excel,
                    }
                    generate_fn = _excel_dispatch.get(report_type, excel_generator.generate_daily_slaughter_excel)
                    workbook = generate_fn()

                    import tempfile

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
                        workbook.save(tmp_file.name)
                        with open(tmp_file.name, "rb") as f:
                            response = HttpResponse(
                                f.read(),
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )
                            response["Content-Disposition"] = (
                                f'attachment; filename="{report_type}_{start_date}_to_{end_date}.xlsx"'
                            )
                        os.unlink(tmp_file.name)
                        return response
                except Exception:
                    logger.exception("Excel generation failed")
                    return HttpResponse("An error occurred processing your request.", status=500)
            elif output_format == "pdf":
                try:
                    pdf_generator = PDFReportGenerator(report_data)
                    _pdf_dispatch = {
                        "daily_slaughter": pdf_generator.generate_daily_slaughter_pdf,
                    }
                    pdf_fn = _pdf_dispatch.get(report_type, pdf_generator.generate_daily_slaughter_pdf)
                    pdf_path = pdf_fn()
                    with open(pdf_path, "rb") as f:
                        response = HttpResponse(f.read(), content_type="application/pdf")
                        response["Content-Disposition"] = (
                            f'attachment; filename="{report_type}_{start_date}_to_{end_date}.pdf"'
                        )
                    os.unlink(pdf_path)
                    return response
                except Exception:
                    logger.exception("PDF generation failed")
                    return HttpResponse("An error occurred processing your request.", status=500)
            else:
                return HttpResponse("Invalid output format. Please select Excel or PDF.", status=400)

        except Exception:
            logger.exception("Error generating report")
            return HttpResponse("An error occurred processing your request.", status=500)

    return HttpResponse("Method not allowed", status=405)


@csrf_exempt
@require_http_methods(["POST"])
def generate_daily_reports_api(request):
    """API endpoint for Google Scheduler to trigger daily report generation"""
    try:
        # Parse request body
        data = json.loads(request.body)
        report_types = data.get("report_types", ["daily_slaughter"])
        output_format = data.get("output_format", "excel")
        system_user = data.get("system_user", "system")
        schema_name = data.get("schema_name")
        all_tenants = bool(data.get("all_tenants", False))

        if schema_name and all_tenants:
            return JsonResponse(
                {"status": "error", "message": "Use either schema_name or all_tenants, not both."},
                status=400,
            )

        if getattr(settings, "USE_MULTITENANT", False):
            from django.db import connection
            from django_tenants.utils import get_public_schema_name

            public_schema = get_public_schema_name()
            if not all_tenants and not schema_name:
                schema_name = getattr(getattr(request, "tenant", None), "schema_name", None) or getattr(
                    connection, "schema_name", None
                )
            if not all_tenants and (not schema_name or schema_name == public_schema):
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "Tenant schema is required when generating reports from the public host.",
                    },
                    status=400,
                )

        # Run management command in background
        def run_command():
            try:
                kwargs = {
                    "report_types": report_types,
                    "output_format": output_format,
                    "system_user": system_user,
                }
                if all_tenants:
                    kwargs["all_tenants"] = True
                elif schema_name:
                    kwargs["schema"] = schema_name
                call_command("generate_daily_reports", **kwargs)
            except CommandError as e:
                logger.exception("Daily report generation failed: %s", e)

        # Start background thread
        thread = threading.Thread(target=run_command)
        thread.daemon = True
        thread.start()

        return JsonResponse(
            {"status": "success", "message": "Daily report generation started", "report_types": report_types}
        )

    except Exception:
        logger.exception("Daily reports API request failed")
        return JsonResponse({"status": "error", "message": "An error occurred processing your request."}, status=500)


@login_required
@manager_or_admin_required
def test_report_generation(request):
    """Test view for report generation (for development/testing)"""
    if request.method == "POST":
        try:
            # Get yesterday's date
            yesterday = (timezone.now() - timedelta(days=1)).date()

            # Generate report data
            aggregator = ReportDataAggregator(yesterday, yesterday)
            report_data = aggregator.get_all_data()

            # Generate Excel
            excel_generator = ExcelReportGenerator(report_data)
            workbook = excel_generator.generate_daily_slaughter_excel()

            # Save to temporary file
            import tempfile

            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
                workbook.save(tmp_file.name)

                # Read file and return as response
                with open(tmp_file.name, "rb") as f:
                    response = HttpResponse(
                        f.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    response["Content-Disposition"] = f'attachment; filename="test_report_{yesterday}.xlsx"'

                # Clean up
                os.unlink(tmp_file.name)
                return response

        except Exception:
            logger.exception("Test report generation failed")
            return JsonResponse(
                {"status": "error", "message": "An error occurred processing your request."}, status=500
            )

    return render(request, "reporting/test_report.html")


@login_required
@manager_or_admin_required
def download_report(request, report_id):
    """Download a generated report file for the current tenant."""
    report = get_object_or_404(GeneratedReport, pk=report_id)

    if report.status != "success" or not report.file_path:
        raise Http404("Report file not available.")
    if not os.path.exists(report.file_path):
        raise Http404("Report file not found.")

    filename = os.path.basename(report.file_path)
    return FileResponse(open(report.file_path, "rb"), as_attachment=True, filename=filename)


@login_required
@manager_or_admin_required
def report_list(request):
    """List all generated reports"""
    reports = GeneratedReport.objects.select_related("report_definition", "generated_by").order_by("-generated_at")
    context = {"reports": reports}
    return render(request, "reporting/report_list.html", context)


@login_required
@client_required
def client_report_portal(request):
    """Customer portal — date picker for client-scoped order receipts."""
    return render(request, "reporting/client_portal.html")


@login_required
@client_required
def client_generate_report(request):
    """Generate a report scoped to the authenticated client's own orders."""
    if request.method != "POST":
        return HttpResponse(status=405)

    client_profile = getattr(request.user, "client_profile", None)
    if not client_profile:
        return HttpResponse("No client profile associated with this account.", status=403)

    try:
        start_date = request.POST.get("start_date")
        end_date = request.POST.get("end_date")
        output_format = request.POST.get("output_format", "pdf")

        from datetime import datetime

        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()

        aggregator = ReportDataAggregator(
            start_date_obj, end_date_obj, filters={"report_type": "client_order_receipt"}
        )
        report_data = aggregator.get_all_data()
        report_data["client_orders"] = aggregator.get_client_order_data(client_profile.id)

        if output_format == "excel":
            try:
                excel_generator = ExcelReportGenerator(report_data)
                workbook = excel_generator.generate_client_order_receipt_excel()

                import tempfile

                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
                    workbook.save(tmp_file.name)
                    with open(tmp_file.name, "rb") as f:
                        response = HttpResponse(
                            f.read(),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                        response["Content-Disposition"] = (
                            f'attachment; filename="kesim_raporu_{start_date}_to_{end_date}.xlsx"'
                        )
                    os.unlink(tmp_file.name)
                    return response
            except Exception:
                logger.exception("Client Excel generation failed")
                return HttpResponse("An error occurred processing your request.", status=500)
        else:
            try:
                pdf_generator = PDFReportGenerator(report_data)
                pdf_path = pdf_generator.generate_client_order_receipt_pdf()
                with open(pdf_path, "rb") as f:
                    response = HttpResponse(f.read(), content_type="application/pdf")
                    response["Content-Disposition"] = (
                        f'attachment; filename="kesim_raporu_{start_date}_to_{end_date}.pdf"'
                    )
                os.unlink(pdf_path)
                return response
            except Exception:
                logger.exception("Client PDF generation failed")
                return HttpResponse("An error occurred processing your request.", status=500)

    except Exception:
        logger.exception("Client report generation failed")
        return HttpResponse("An error occurred processing your request.", status=500)
