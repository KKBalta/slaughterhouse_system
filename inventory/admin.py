from django.contrib import admin
from .models import Carcass, MeatCut, Offal, ByProduct, StorageLocation

@admin.register(StorageLocation)
class StorageLocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'location_type', 'capacity_kg', 'is_active')
    list_filter = ('location_type', 'is_active')
    search_fields = ('name',)

@admin.register(Carcass)
class CarcassAdmin(admin.ModelAdmin):
    list_display = ('animal', 'hot_carcass_weight', 'cold_carcass_weight', 'status', 'disposition', 'storage_location')
    list_filter = ('status', 'disposition', 'storage_location')
    search_fields = ('animal__identification_tag',)
    raw_id_fields = ('animal', 'storage_location')

@admin.register(MeatCut)
class MeatCutAdmin(admin.ModelAdmin):
    list_display = ('carcass', 'cut_type', 'weight', 'disposition', 'label_id', 'storage_location')
    list_filter = ('cut_type', 'disposition', 'storage_location')
    search_fields = ('carcass__animal__identification_tag', 'label_id')
    raw_id_fields = ('carcass', 'storage_location')

@admin.register(Offal)
class OffalAdmin(admin.ModelAdmin):
    list_display = ('animal', 'offal_type', 'weight', 'disposition', 'label_id', 'storage_location')
    list_filter = ('offal_type', 'disposition', 'storage_location')
    search_fields = ('animal__identification_tag', 'label_id')
    raw_id_fields = ('animal', 'storage_location')

@admin.register(ByProduct)
class ByProductAdmin(admin.ModelAdmin):
    list_display = ('animal', 'byproduct_type', 'weight', 'disposition', 'label_id', 'storage_location')
    list_filter = ('byproduct_type', 'disposition', 'storage_location')
    search_fields = ('animal__identification_tag', 'label_id')
    raw_id_fields = ('animal', 'storage_location')
