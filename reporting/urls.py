from django.urls import path

from . import views

urlpatterns = [
    # Main dashboard
    path("", views.report_dashboard, name="report_dashboard"),
    # Report generation
    path("generate/", views.generate_report, name="generate_report"),
    path("test/", views.test_report_generation, name="test_report_generation"),
    path("list/", views.report_list, name="report_list"),
    # API endpoints for Google Scheduler
    path("api/generate-daily/", views.generate_daily_reports_api, name="api_generate_daily_reports"),
]
