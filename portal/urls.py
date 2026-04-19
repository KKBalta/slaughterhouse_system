from django.urls import path

from .views import ClientOrderDetailView, ClientOrderListView

app_name = "portal"

urlpatterns = [
    path("orders/", ClientOrderListView.as_view(), name="order_list"),
    path("orders/<uuid:pk>/", ClientOrderDetailView.as_view(), name="order_detail"),
]
