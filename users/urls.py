from django.urls import path

from tenants.views import tenant_company_settings_view

from .views import (
    ClientProfileRegisterView,
    CustomLoginView,
    CustomLogoutView,
    RegisterView,
    client_profile_activate_view,
    client_profile_add_view,
    client_profile_delete_view,
    client_profile_detail_view,
    client_profile_edit_view,
    client_profile_list_view,
    client_register_done_view,
    dashboard_view,
    home_view,
    logged_out_view,
)

urlpatterns = [
    path("", home_view, name="home"),  # Set new landing page as the home page
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", CustomLoginView.as_view(), name="login"),
    path("signin/", CustomLoginView.as_view(), name="signin"),
    path("logout/", CustomLogoutView.as_view(), name="logout"),
    path("logged-out/", logged_out_view, name="logged_out"),  # Page shown after logout
    path("dashboard/", dashboard_view, name="dashboard"),
    path(
        "tenant-company-settings/",
        tenant_company_settings_view,
        name="tenant_company_settings",
    ),
    path("client-register/", ClientProfileRegisterView.as_view(), name="client_register"),
    path("client-register/done/", client_register_done_view, name="client_register_done"),
    path("clients/add/", client_profile_add_view, name="client_profile_add"),
    path("clients/<uuid:pk>/edit/", client_profile_edit_view, name="client_profile_edit"),
    path("clients/<uuid:pk>/activate/", client_profile_activate_view, name="client_profile_activate"),
    path("clients/<uuid:pk>/delete/", client_profile_delete_view, name="client_profile_delete"),
    path("clients/<uuid:pk>/", client_profile_detail_view, name="client_profile_detail"),
    path("clients/", client_profile_list_view, name="client_profile_list"),
]
