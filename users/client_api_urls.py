from django.urls import path

from .client_api import client_profile_detail_api, client_profile_list_api

urlpatterns = [
    path("", client_profile_list_api, name="api_client_profile_list"),
    path("<uuid:pk>/", client_profile_detail_api, name="api_client_profile_detail"),
]
