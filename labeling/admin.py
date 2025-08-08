from django.contrib import admin
from .models import LabelTemplate, PrintJob

@admin.register(LabelTemplate)
class LabelTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'target_item_type', 'is_active')
    list_filter = ('target_item_type', 'is_active')
    search_fields = ('name',)

@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display = ('label_template', 'item_type', 'item_id', 'quantity', 'print_date', 'printed_by', 'status')
    list_filter = ('item_type', 'status', 'print_date')
    search_fields = ('label_template__name', 'item_id')
    raw_id_fields = ('label_template', 'printed_by')