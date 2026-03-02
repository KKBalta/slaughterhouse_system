from django.urls import path

from .views import (
    AddAnimalToOrderView,
    BatchAddAnimalsToOrderView,
    BillOrderView,
    CancelSlaughterOrderView,
    ClientSearchView,
    CreateSlaughterOrderView,
    EditAnimalInOrderView,
    RemoveAnimalFromOrderView,
    SlaughterOrderDetailView,
    SlaughterOrderListView,
    SlaughterOrderUpdateView,
)

app_name = "reception"

urlpatterns = [
    path("api/search-clients/", ClientSearchView.as_view(), name="client_search"),
    path("create_order/", CreateSlaughterOrderView.as_view(), name="create_slaughter_order"),
    path("orders/", SlaughterOrderListView.as_view(), name="slaughter_order_list"),
    path("orders/<uuid:pk>/", SlaughterOrderDetailView.as_view(), name="slaughter_order_detail"),
    path("orders/<uuid:pk>/edit/", SlaughterOrderUpdateView.as_view(), name="slaughter_order_update"),
    path("orders/<uuid:pk>/cancel/", CancelSlaughterOrderView.as_view(), name="slaughter_order_cancel"),
    path("orders/<uuid:pk>/bill/", BillOrderView.as_view(), name="slaughter_order_bill"),
    path("orders/<uuid:order_pk>/add_animal/", AddAnimalToOrderView.as_view(), name="add_animal_to_order"),
    path(
        "orders/<uuid:order_pk>/batch_add_animals/",
        BatchAddAnimalsToOrderView.as_view(),
        name="batch_add_animals_to_order",
    ),
    path(
        "orders/<uuid:order_pk>/edit_animal/<uuid:animal_pk>/",
        EditAnimalInOrderView.as_view(),
        name="edit_animal_in_order",
    ),
    path(
        "orders/<uuid:order_pk>/remove_animal/<uuid:animal_pk>/",
        RemoveAnimalFromOrderView.as_view(),
        name="remove_animal_from_order",
    ),
]
