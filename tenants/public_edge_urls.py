"""
Public-schema Edge API URL routes.

These are the same views as scales.api_urls, but wrapped with
public_require_edge_id which resolves the tenant from X-Edge-Id
via the public EdgeDeviceIndex table.

register / activate need tenant schema context without X-Edge-Id; see edge_middleware
and public_edge_activate.
"""

from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from scales import api_views
from tenants.api_views_edge import public_edge_activate
from tenants.edge_middleware import public_edge_register, public_require_edge_id


def _pub(view_func):
    """Wrap a tenant-scoped Edge view for public-schema use."""
    return csrf_exempt(public_require_edge_id(view_func))


urlpatterns = [
    path("register", public_edge_register, name="pub-edge-register"),
    path("activate", csrf_exempt(public_edge_activate), name="pub-edge-activate-v2"),
    path("sessions", _pub(api_views.edge_sessions), name="pub-edge-sessions"),
    path("events", _pub(api_views.edge_post_event), name="pub-edge-post-event"),
    path("events/batch", _pub(api_views.edge_post_event_batch), name="pub-edge-post-event-batch"),
    path("offline-batches/ack", _pub(api_views.edge_offline_batch_ack), name="pub-edge-offline-batch-ack"),
    path("config", _pub(api_views.edge_config), name="pub-edge-config"),
    path("devices/status", _pub(api_views.edge_device_status), name="pub-edge-device-status"),
    path("heartbeat", _pub(api_views.edge_heartbeat), name="pub-edge-heartbeat"),
    path("print-jobs/pending", _pub(api_views.edge_pending_print_jobs), name="pub-edge-pending-print-jobs"),
    path("print-jobs/<uuid:job_id>/ack", _pub(api_views.edge_ack_print_job), name="pub-edge-ack-print-job"),
    path("printers/inventory", _pub(api_views.edge_printer_inventory), name="pub-edge-printer-inventory"),
]
