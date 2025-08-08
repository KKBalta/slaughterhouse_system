from django.contrib import admin
from .models import Report, GeneratedReport

@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('name', 'report_type', 'is_active')
    list_filter = ('report_type', 'is_active')
    search_fields = ('name', 'description')

@admin.register(GeneratedReport)
class GeneratedReportAdmin(admin.ModelAdmin):
    list_display = ('report_definition', 'generated_by', 'generated_at', 'status')
    list_filter = ('status', 'report_definition__report_type')
    search_fields = ('report_definition__name', 'generated_by__username')
    raw_id_fields = ('report_definition', 'generated_by')