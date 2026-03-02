from django.contrib import admin

from .models import ServicePackage


@admin.register(ServicePackage)
class ServicePackageAdmin(admin.ModelAdmin):
    list_display = ("name", "includes_disassembly", "includes_delivery", "is_active", "created_at")
    list_filter = ("is_active", "includes_disassembly", "includes_delivery", "created_at")
    search_fields = ("name", "description")

    fieldsets = (
        ("Basic Information", {"fields": ("name", "description")}),
        (
            "Services Included",
            {
                "fields": ("includes_disassembly", "includes_delivery"),
                "description": 'Select which services are included in this package. For disassembly, use "boneless" in the package name for boneless-only service.',
            },
        ),
        (
            "Status",
            {
                "fields": ("is_active",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    readonly_fields = ("created_at", "updated_at")
