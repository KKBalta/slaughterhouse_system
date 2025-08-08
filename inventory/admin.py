from django.contrib import admin
from .models import Carcass, MeatCut, Offal, ByProduct, Label

@admin.register(Carcass)
class CarcassAdmin(admin.ModelAdmin):
    list_display = ('animal', 'weight', 'status', 'disposition')
    list_filter = ('status', 'disposition')
    search_fields = ('animal__identification_tag',)
    raw_id_fields = ('animal',)

@admin.register(MeatCut)
class MeatCutAdmin(admin.ModelAdmin):
    list_display = ('carcass', 'cut_type', 'weight', 'disposition', 'label_id')
    list_filter = ('cut_type', 'disposition')
    search_fields = ('carcass__animal__identification_tag', 'label_id')
    raw_id_fields = ('carcass',)

@admin.register(Offal)
class OffalAdmin(admin.ModelAdmin):
    list_display = ('animal', 'offal_type', 'weight', 'disposition', 'label_id')
    list_filter = ('offal_type', 'disposition')
    search_fields = ('animal__identification_tag', 'label_id')
    raw_id_fields = ('animal',)

@admin.register(ByProduct)
class ByProductAdmin(admin.ModelAdmin):
    list_display = ('animal', 'byproduct_type', 'weight', 'disposition', 'label_id')
    list_filter = ('byproduct_type', 'disposition')
    search_fields = ('animal__identification_tag', 'label_id')
    raw_id_fields = ('animal',)

@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ('label_code', 'item_type', 'item_id', 'print_date', 'printed_by')
    list_filter = ('item_type', 'print_date')
    search_fields = ('label_code', 'item_id')
    raw_id_fields = ('printed_by',)