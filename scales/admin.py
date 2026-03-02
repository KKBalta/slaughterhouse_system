from django.contrib import admin

from .models import (
    DisassemblySession,
    EdgeActivityLog,
    EdgeDevice,
    OfflineBatchAck,
    OrphanedBatch,
    PLUItem,
    ScaleDevice,
    Site,
    WeighingEvent,
)


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "api_key")
    search_fields = ("name",)


@admin.register(EdgeDevice)
class EdgeDeviceAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "site", "is_online", "last_seen_at", "version")
    list_filter = ("is_online", "site")
    search_fields = ("name",)
    raw_id_fields = ("site",)


@admin.register(ScaleDevice)
class ScaleDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "device_id",
        "global_device_id",
        "edge",
        "device_type",
        "status",
        "last_heartbeat_at",
        "last_event_at",
    )
    list_filter = ("status", "device_type", "edge")
    search_fields = ("device_id", "global_device_id")
    raw_id_fields = ("edge",)


@admin.register(PLUItem)
class PLUItemAdmin(admin.ModelAdmin):
    list_display = ("plu_code", "name", "category", "is_active", "site")
    list_filter = ("category", "is_active", "site")
    search_fields = ("plu_code", "name")


@admin.register(DisassemblySession)
class DisassemblySessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "animal",
        "device",
        "operator",
        "status",
        "started_at",
        "ended_at",
        "event_count",
        "total_weight_grams",
    )
    list_filter = ("status", "site", "device")
    search_fields = ("operator",)
    raw_id_fields = ("animal", "device", "site")
    readonly_fields = ("last_event_at", "event_count", "total_weight_grams")


@admin.register(WeighingEvent)
class WeighingEventAdmin(admin.ModelAdmin):
    list_display = (
        "edge_event_id",
        "plu_code",
        "product_name",
        "weight_grams",
        "device",
        "session",
        "scale_timestamp",
    )
    list_filter = ("site", "session")
    search_fields = ("edge_event_id", "plu_code", "product_name")
    raw_id_fields = ("session", "device", "animal", "site")
    readonly_fields = ("cloud_received_at",)


@admin.register(OfflineBatchAck)
class OfflineBatchAckAdmin(admin.ModelAdmin):
    list_display = (
        "batch_id",
        "received_at",
        "edge",
        "site",
        "device_id",
        "event_count",
        "total_weight_grams",
    )
    list_filter = ("edge", "site")
    search_fields = ("batch_id", "device_id")
    raw_id_fields = ("edge", "site")
    readonly_fields = ("received_at", "created_at", "updated_at")


@admin.register(OrphanedBatch)
class OrphanedBatchAdmin(admin.ModelAdmin):
    list_display = (
        "batch_id",
        "edge",
        "device",
        "status",
        "event_count",
        "total_weight_grams",
        "started_at",
        "reconciled_to_session",
    )
    list_filter = ("status", "edge")
    raw_id_fields = ("edge", "device", "site", "reconciled_to_session")


@admin.register(EdgeActivityLog)
class EdgeActivityLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "level",
        "action",
        "site",
        "edge",
        "device",
        "message",
    )
    list_filter = ("level", "action", "site", "edge")
    search_fields = ("message", "request_path", "action")
    raw_id_fields = ("site", "edge", "device")
    readonly_fields = ("created_at", "updated_at")
