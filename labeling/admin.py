from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from .models import LabelTemplate, PrintJob, Label, AnimalLabel

@admin.register(LabelTemplate)
class LabelTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'target_item_type', 'label_format', 'created_at')
    list_filter = ('target_item_type', 'label_format', 'created_at')
    search_fields = ('name', 'template_data')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display = ('item_type', 'item_id', 'quantity', 'status', 'printed_by', 'print_date')
    list_filter = ('item_type', 'status', 'print_date')
    search_fields = ('item_id', 'printed_by__username')
    readonly_fields = ('print_date',)
    raw_id_fields = ('printed_by', 'label_template')

@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ('label_code', 'item_type', 'item_id', 'printed_by', 'print_date')
    list_filter = ('item_type', 'print_date')
    search_fields = ('label_code', 'item_id', 'printed_by__username')
    readonly_fields = ('print_date',)
    raw_id_fields = ('printed_by',)

@admin.register(AnimalLabel)
class AnimalLabelAdmin(admin.ModelAdmin):
    list_display = (
        'label_code', 'animal_identification', 'label_type', 'printed_by', 
        'print_date', 'has_pdf', 'zpl_preview'
    )
    list_filter = ('label_type', 'print_date', 'created_at')
    search_fields = ('label_code', 'animal__identification_tag', 'printed_by__username')
    readonly_fields = ('label_code', 'print_date', 'created_at', 'updated_at', 'zpl_content_preview', 'pdf_preview')
    raw_id_fields = ('animal', 'printed_by')
    date_hierarchy = 'print_date'
    
    def animal_identification(self, obj):
        """Display animal identification tag"""
        return obj.animal.identification_tag if obj.animal else "N/A"
    animal_identification.short_description = _("Animal ID")
    animal_identification.admin_order_field = 'animal__identification_tag'
    
    def has_pdf(self, obj):
        """Show if PDF file exists"""
        return "✅" if obj.pdf_file else "❌"
    has_pdf.short_description = _("PDF")
    
    def zpl_preview(self, obj):
        """Show truncated ZPL content"""
        if obj.zpl_content:
            preview = obj.zpl_content[:50] + "..." if len(obj.zpl_content) > 50 else obj.zpl_content
            return format_html('<code style="font-size: 10px;">{}</code>', preview)
        return "No ZPL content"
    zpl_preview.short_description = _("ZPL Preview")
    
    def zpl_content_preview(self, obj):
        """Show full ZPL content in readonly field"""
        if obj.zpl_content:
            return format_html('<pre style="background: #f5f5f5; padding: 10px; border-radius: 4px; font-size: 12px;">{}</pre>', obj.zpl_content)
        return "No ZPL content"
    zpl_content_preview.short_description = _("ZPL Content")
    
    def pdf_preview(self, obj):
        """Show PDF file link"""
        if obj.pdf_file:
            return format_html(
                '<a href="{}" target="_blank" class="button">View PDF</a>',
                obj.pdf_file.url
            )
        return "No PDF file"
    pdf_preview.short_description = _("PDF File")
    
    actions = ['regenerate_pdf', 'delete_pdf_files']
    
    def regenerate_pdf(self, request, queryset):
        """Regenerate PDF files for selected labels"""
        from .utils import generate_pdf_label
        from django.core.files.base import ContentFile
        
        updated_count = 0
        for animal_label in queryset:
            try:
                # Generate new PDF
                pdf_buffer = generate_pdf_label(animal_label.animal, animal_label.label_type)
                
                # Save new PDF file
                pdf_filename = f"animal_label_{animal_label.animal.identification_tag}_{animal_label.label_type}_{animal_label.id}.pdf"
                animal_label.pdf_file.save(pdf_filename, ContentFile(pdf_buffer.getvalue()), save=True)
                updated_count += 1
                
            except Exception as e:
                self.message_user(request, f"Error regenerating PDF for {animal_label}: {str(e)}", level='ERROR')
        
        self.message_user(request, f"Successfully regenerated {updated_count} PDF files.")
    regenerate_pdf.short_description = _("Regenerate PDF files")
    
    def delete_pdf_files(self, request, queryset):
        """Delete PDF files for selected labels"""
        from django.core.files.storage import default_storage
        
        deleted_count = 0
        for animal_label in queryset:
            if animal_label.pdf_file:
                try:
                    if default_storage.exists(animal_label.pdf_file.name):
                        default_storage.delete(animal_label.pdf_file.name)
                    animal_label.pdf_file = None
                    animal_label.save()
                    deleted_count += 1
                except Exception as e:
                    self.message_user(request, f"Error deleting PDF for {animal_label}: {str(e)}", level='ERROR')
        
        self.message_user(request, f"Successfully deleted {deleted_count} PDF files.")
    delete_pdf_files.short_description = _("Delete PDF files")
