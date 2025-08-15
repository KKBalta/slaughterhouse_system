from django.urls import path
from . import views

app_name = 'processing'

urlpatterns = [
    # Dashboard
    path('', views.ProcessingDashboardView.as_view(), name='dashboard'),
    
    # Animal Management
    path('animals/', views.AnimalListView.as_view(), name='animal_list'),
    path('animals/search/', views.AnimalSearchView.as_view(), name='animal_search'),
    path('animals/<uuid:pk>/', views.AnimalDetailView.as_view(), name='animal_detail'),
    
    # Workflow Operations
    path('animals/<uuid:pk>/slaughter/', views.MarkAnimalSlaughteredView.as_view(), name='mark_slaughtered'),
    path('animals/<uuid:pk>/weights/', views.AnimalWeightLogView.as_view(), name='animal_weights'),
    path('animals/<uuid:pk>/leather-weight/', views.LeatherWeightLogView.as_view(), name='leather_weight'),
    
    # Batch Operations
    path('batch/slaughter/', views.BatchSlaughterView.as_view(), name='batch_slaughter'),
    path('batch/weights/', views.BatchWeightLogView.as_view(), name='batch_weights'),
    
    # Status Updates
    path('orders/<uuid:order_pk>/status/', views.OrderStatusUpdateView.as_view(), name='order_status_update'),
]
