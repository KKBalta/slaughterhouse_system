from django.contrib import admin
from .models import ServicePackage

@admin.register(ServicePackage)
class ServicePackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'includes_disassembly', 'includes_delivery', 'is_active')
    list_filter = ('is_active', 'includes_disassembly', 'includes_delivery')
    search_fields = ('name', 'description')