from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from .models import (
    Animal, CattleDetails, SheepDetails, GoatDetails, LambDetails, 
    OglakDetails, CalfDetails, HeiferDetails, WeightLog
)

class CattleDetailsInline(admin.StackedInline):
    model = CattleDetails
    can_delete = False
    verbose_name_plural = _('Cattle Details')

class SheepDetailsInline(admin.StackedInline):
    model = SheepDetails
    can_delete = False
    verbose_name_plural = _('Sheep Details')

class GoatDetailsInline(admin.StackedInline):
    model = GoatDetails
    can_delete = False
    verbose_name_plural = _('Goat Details')

class LambDetailsInline(admin.StackedInline):
    model = LambDetails
    can_delete = False
    verbose_name_plural = _('Lamb Details')

class OglakDetailsInline(admin.StackedInline):
    model = OglakDetails
    can_delete = False
    verbose_name_plural = _('Oglak Details')

class CalfDetailsInline(admin.StackedInline):
    model = CalfDetails
    can_delete = False
    verbose_name_plural = _('Calf Details')

class HeiferDetailsInline(admin.StackedInline):
    model = HeiferDetails
    can_delete = False
    verbose_name_plural = _('Heifer Details')

@admin.register(Animal)
class AnimalAdmin(admin.ModelAdmin):
    list_display = (
        'identification_tag', 'animal_type', 'slaughter_order', 'status', 
        'received_date', 'slaughter_date', 'get_leather_weight', 'get_picture_status', 'get_scale_receipt_picture'
    )
    list_filter = ('animal_type', 'status', 'slaughter_order__service_package', 'received_date')
    search_fields = ('identification_tag', 'slaughter_order__id', 'slaughter_order__customer__name')
    inlines = [
        CattleDetailsInline, SheepDetailsInline, GoatDetailsInline, 
        LambDetailsInline, OglakDetailsInline, CalfDetailsInline, HeiferDetailsInline
    ]
    raw_id_fields = ('slaughter_order',)
    readonly_fields = ('created_at', 'updated_at', 'scale_receipt_picture_preview')
    date_hierarchy = 'received_date'
    
    def get_leather_weight(self, obj):
        """Display leather weight if available"""
        if obj.leather_weight_kg:
            return f"{obj.leather_weight_kg} kg"
        return "-"
    get_leather_weight.short_description = _("Leather Weight")
    
    def get_picture_status(self, obj):
        """Show if pictures are uploaded"""
        status = []
        if obj.picture:
            status.append(_("📷 Photo"))
        if obj.passport_picture:
            status.append(_("📋 Passport"))
        # Convert each item to string before joining
        return " | ".join([str(s) for s in status]) if status else str(_("No photos"))
    get_picture_status.short_description = _("Pictures")
    
    def get_scale_receipt_picture(self, obj):
        if obj.scale_receipt_picture:
            return format_html('<a href="{}" target="_blank"><img src="{}" style="max-height:40px;max-width:60px;border-radius:4px;"/></a>', obj.scale_receipt_picture.url, obj.scale_receipt_picture.url)
        return "-"
    get_scale_receipt_picture.short_description = _("Scale Receipt")
    get_scale_receipt_picture.allow_tags = True

    def scale_receipt_picture_preview(self, obj):
        if obj.scale_receipt_picture:
            return format_html('<img src="{}" style="max-width:300px;max-height:300px;border-radius:8px;"/>', obj.scale_receipt_picture.url)
        return "-"
    scale_receipt_picture_preview.short_description = _("Scale Receipt Preview")
    
    def get_inline_instances(self, request, obj=None):
        """Only show relevant inline based on animal type"""
        if not obj:
            return []
        
        inline_mapping = {
            'cattle': [CattleDetailsInline],
            'sheep': [SheepDetailsInline],
            'goat': [GoatDetailsInline],
            'lamb': [LambDetailsInline],
            'oglak': [OglakDetailsInline],
            'calf': [CalfDetailsInline],
            'heifer': [HeiferDetailsInline],
            'beef': [CattleDetailsInline],  # Use cattle details for beef
        }
        
        relevant_inlines = inline_mapping.get(obj.animal_type, [])
        return [inline(self.model, self.admin_site) for inline in relevant_inlines]

@admin.register(WeightLog)
class WeightLogAdmin(admin.ModelAdmin):
    list_display = (
        'get_identifier', 'weight_type', 'weight', 'is_group_weight', 
        'group_quantity', 'group_total_weight', 'log_date'
    )
    list_filter = ('weight_type', 'is_group_weight', 'log_date')
    search_fields = ('animal__identification_tag', 'slaughter_order__id')
    raw_id_fields = ('animal', 'slaughter_order')
    readonly_fields = ('log_date',)
    date_hierarchy = 'log_date'
    
    def get_identifier(self, obj):
        """Show animal tag or slaughter order ID"""
        if obj.animal:
            return f"🐄 {obj.animal.identification_tag}"
        elif obj.slaughter_order:
            return _("📋 Order #%(id)s") % {'id': obj.slaughter_order.id}
        return _("Unknown")
    get_identifier.short_description = _("Animal/Order")
    get_identifier.admin_order_field = 'animal__identification_tag'

# Register individual detail models for direct access
@admin.register(CattleDetails)
class CattleDetailsAdmin(admin.ModelAdmin):
    list_display = ('animal', 'breed', 'liver_status', 'bowels_status')
    list_filter = ('breed', 'liver_status', 'bowels_status')
    search_fields = ('animal__identification_tag', 'breed')
    raw_id_fields = ('animal',)

@admin.register(SheepDetails)
class SheepDetailsAdmin(admin.ModelAdmin):
    list_display = ('animal', 'breed', 'sakatat_status', 'bowels_status')
    list_filter = ('breed', 'sakatat_status', 'bowels_status')
    search_fields = ('animal__identification_tag', 'breed')
    raw_id_fields = ('animal',)

@admin.register(GoatDetails)
class GoatDetailsAdmin(admin.ModelAdmin):
    list_display = ('animal', 'breed', 'sakatat_status', 'bowels_status')
    list_filter = ('breed', 'sakatat_status', 'bowels_status')
    search_fields = ('animal__identification_tag', 'breed')
    raw_id_fields = ('animal',)

@admin.register(LambDetails)
class LambDetailsAdmin(admin.ModelAdmin):
    list_display = ('animal', 'sakatat_status', 'bowels_status')
    list_filter = ('sakatat_status', 'bowels_status')
    search_fields = ('animal__identification_tag',)
    raw_id_fields = ('animal',)

@admin.register(OglakDetails)
class OglakDetailsAdmin(admin.ModelAdmin):
    list_display = ('animal', 'sakatat_status', 'bowels_status')
    list_filter = ('sakatat_status', 'bowels_status')
    search_fields = ('animal__identification_tag',)
    raw_id_fields = ('animal',)

@admin.register(CalfDetails)
class CalfDetailsAdmin(admin.ModelAdmin):
    list_display = ('animal', 'breed', 'liver_status', 'bowels_status')
    list_filter = ('breed', 'liver_status', 'bowels_status')
    search_fields = ('animal__identification_tag', 'breed')
    raw_id_fields = ('animal',)

@admin.register(HeiferDetails)
class HeiferDetailsAdmin(admin.ModelAdmin):
    list_display = ('animal', 'breed', 'liver_status', 'bowels_status')
    list_filter = ('breed', 'liver_status', 'bowels_status')
    search_fields = ('animal__identification_tag', 'breed')
    raw_id_fields = ('animal',)
