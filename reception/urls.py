from django.urls import path
from .views import (
    CreateSlaughterOrderView,
    SlaughterOrderListView,
    SlaughterOrderDetailView,
    SlaughterOrderUpdateView,
    CancelSlaughterOrderView,
    BillOrderView,
    AddAnimalToOrderView,
    EditAnimalInOrderView,
    RemoveAnimalFromOrderView,
)

app_name = 'reception'

urlpatterns = [
    path('create_order/', CreateSlaughterOrderView.as_view(), name='create_slaughter_order'),
    path('orders/', SlaughterOrderListView.as_view(), name='slaughter_order_list'),
    path('orders/<int:pk>/', SlaughterOrderDetailView.as_view(), name='slaughter_order_detail'),
    path('orders/<int:pk>/edit/', SlaughterOrderUpdateView.as_view(), name='slaughter_order_update'),
    path('orders/<int:pk>/cancel/', CancelSlaughterOrderView.as_view(), name='slaughter_order_cancel'),
    path('orders/<int:pk>/bill/', BillOrderView.as_view(), name='slaughter_order_bill'),
    path('orders/<int:order_pk>/add_animal/', AddAnimalToOrderView.as_view(), name='add_animal_to_order'),
    path('orders/<int:order_pk>/edit_animal/<uuid:animal_pk>/', EditAnimalInOrderView.as_view(), name='edit_animal_in_order'),
    path('orders/<int:order_pk>/remove_animal/<uuid:animal_pk>/', RemoveAnimalFromOrderView.as_view(), name='remove_animal_from_order'),
]