"""Edge API URL configuration (no i18n prefix)."""

from django.urls import path

from . import api_views

urlpatterns = [
    path("register", api_views.edge_register, name="edge-register"),
    path("sessions", api_views.edge_sessions, name="edge-sessions"),
    path("events", api_views.edge_post_event, name="edge-post-event"),
    path("events/batch", api_views.edge_post_event_batch, name="edge-post-event-batch"),
    path("offline-batches/ack", api_views.edge_offline_batch_ack, name="edge-offline-batch-ack"),
    path("config", api_views.edge_config, name="edge-config"),
    path("devices/status", api_views.edge_device_status, name="edge-device-status"),
    path("heartbeat", api_views.edge_heartbeat, name="edge-heartbeat"),
]
