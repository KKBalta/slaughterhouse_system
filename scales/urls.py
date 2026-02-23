from django.urls import path
from . import views

app_name = "scales"

urlpatterns = [
    path("", views.ScalesDashboardView.as_view(), name="dashboard"),
    path("edge-management/", views.EdgeManagementView.as_view(), name="edge_management"),
    path("edge-management/edges/", views.EdgeBySiteJsonView.as_view(), name="edge_by_site_json"),
    path("edge-management/printers/", views.PrintersByEdgeJsonView.as_view(), name="printers_by_edge_json"),
    path("sessions/", views.SessionListView.as_view(), name="session_list"),
    path("sessions/create/", views.SessionCreateView.as_view(), name="session_create"),
    path("sessions/<uuid:pk>/", views.SessionDetailView.as_view(), name="session_detail"),
    path("sessions/<uuid:pk>/events-json/", views.SessionEventsJsonView.as_view(), name="session_events_json"),
    path("sessions/<uuid:pk>/close/", views.SessionCloseView.as_view(), name="session_close"),
    path("sessions/<uuid:pk>/cancel/", views.SessionCancelView.as_view(), name="session_cancel"),
    path("plu/", views.PLUListView.as_view(), name="plu_list"),
    path("orphaned-batches/", views.OrphanedBatchListView.as_view(), name="orphaned_batch_list"),
    path(
        "orphaned-batches/<uuid:pk>/reconcile/",
        views.OrphanedBatchReconcileView.as_view(),
        name="orphaned_batch_reconcile",
    ),
]
