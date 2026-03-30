from django.contrib import admin

from .models import ServicePackage


@admin.register(ServicePackage)
class ServicePackageAdmin(admin.ModelAdmin):
    list_display = ("name", "name_tr", "includes_disassembly", "includes_delivery", "is_active", "created_at")
    list_filter = ("is_active", "includes_disassembly", "includes_delivery", "created_at")
    search_fields = ("name", "name_tr", "description", "description_tr")

    fieldsets = (
        ("Basic Information", {"fields": ("name", "description")}),
        ("Turkish (optional)", {"fields": ("name_tr", "description_tr")}),
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
