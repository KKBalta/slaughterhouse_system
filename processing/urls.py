from django.urls import path

from . import views

app_name = "processing"

urlpatterns = [
    # Dashboard
    path("", views.ProcessingDashboardView.as_view(), name="dashboard"),
    # Animal Management
    path("animals/", views.AnimalListView.as_view(), name="animal_list"),
    path("animals/search/", views.AnimalSearchView.as_view(), name="animal_search"),
    path("animals/search/debug/", views.AnimalSearchDebugView.as_view(), name="animal_search_debug"),
    path("animals/<uuid:pk>/", views.AnimalDetailView.as_view(), name="animal_detail"),
    # Workflow Operations
    path("animals/<uuid:pk>/slaughter/", views.MarkAnimalSlaughteredView.as_view(), name="mark_slaughtered"),
    path("animals/<uuid:pk>/weights/", views.AnimalWeightLogView.as_view(), name="animal_weights"),
    path("animals/<uuid:pk>/leather-weight/", views.LeatherWeightLogView.as_view(), name="leather_weight"),
    path("animals/<uuid:pk>/details/", views.AnimalDetailsUpdateView.as_view(), name="animal_details"),
    # Batch Operations
    path("batch/slaughter/", views.BatchSlaughterView.as_view(), name="batch_slaughter"),
    path("batch/weights/", views.BatchWeightLogView.as_view(), name="batch_weights"),
    path("batch/weights/reports/", views.BatchWeightReportsView.as_view(), name="batch_weight_reports"),
    # Status Updates
    path("orders/<uuid:order_pk>/status/", views.OrderStatusUpdateView.as_view(), name="order_status_update"),
    # Disassembly
    path("disassembly/", views.DisassemblyDashboardView.as_view(), name="disassembly_dashboard"),
    path("animals/<uuid:pk>/disassembly/", views.DisassemblyDetailView.as_view(), name="disassembly_detail"),
    path("animals/<uuid:pk>/disassembly/add/", views.AddDisassemblyCutView.as_view(), name="add_disassembly_cut"),
    path(
        "animals/<uuid:pk>/disassembly/cuts/<uuid:cut_pk>/edit/",
        views.EditDisassemblyCutView.as_view(),
        name="edit_disassembly_cut",
    ),
    path(
        "animals/<uuid:pk>/disassembly/cuts/<uuid:cut_pk>/delete/",
        views.DeleteDisassemblyCutView.as_view(),
        name="delete_disassembly_cut",
    ),
]
