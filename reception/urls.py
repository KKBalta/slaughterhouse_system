from django.urls import path
from .views import CreateSlaughterOrderView

app_name = 'reception'

urlpatterns = [
    path('create_order/', CreateSlaughterOrderView.as_view(), name='create_slaughter_order'),
]