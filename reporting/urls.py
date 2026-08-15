from django.urls import path

from . import views

urlpatterns = [
    # Main dashboard (manager/admin)
    path("", views.report_dashboard, name="report_dashboard"),
    # Report generation (manager/admin)
    path("generate/", views.generate_report, name="generate_report"),
    path("test/", views.test_report_generation, name="test_report_generation"),
    path("<uuid:report_id>/download/", views.download_report, name="download_report"),
    path("list/", views.report_list, name="report_list"),
    # Customer portal
    path("portal/", views.client_report_portal, name="client_report_portal"),
    path("portal/generate/", views.client_generate_report, name="client_generate_report"),
    # API endpoints for Google Scheduler
    path("api/generate-daily/", views.generate_daily_reports_api, name="api_generate_daily_reports"),
    # Live operations & quality insight feeds for the dashboard panels
    path("api/ops-kpis/", views.api_ops_kpis, name="api_ops_kpis"),
    path("api/quality-insight/", views.api_quality_insight, name="api_quality_insight"),
]
