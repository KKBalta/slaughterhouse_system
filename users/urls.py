from django.urls import path

from tenants.views import tenant_company_settings_view

from .views import (
    CustomLoginView,
    CustomLogoutView,
    account_profile_view,
    client_profile_activate_view,
    client_profile_add_view,
    client_profile_delete_view,
    client_profile_detail_view,
    client_profile_edit_view,
    client_profile_list_view,
    dashboard_view,
    home_view,
    logged_out_view,
    stop_impersonation_view,
    tenant_user_create_view,
    tenant_user_edit_view,
    tenant_user_list_view,
)

urlpatterns = [
    path("", home_view, name="home"),  # Set new landing page as the home page
    path("login/", CustomLoginView.as_view(), name="login"),
    path("signin/", CustomLoginView.as_view(), name="signin"),
    path("logout/", CustomLogoutView.as_view(), name="logout"),
    path("logged-out/", logged_out_view, name="logged_out"),  # Page shown after logout
    path("dashboard/", dashboard_view, name="dashboard"),
    path("impersonation/stop/", stop_impersonation_view, name="stop_impersonation"),
    path("account/", account_profile_view, name="account_profile"),
    path(
        "tenant-company-settings/",
        tenant_company_settings_view,
        name="tenant_company_settings",
    ),
    path("users/", tenant_user_list_view, name="tenant_user_list"),
    path("users/create/<str:role>/", tenant_user_create_view, name="tenant_user_create"),
    path("users/<int:pk>/edit/", tenant_user_edit_view, name="tenant_user_edit"),
    path("clients/add/", client_profile_add_view, name="client_profile_add"),
    path("clients/<uuid:pk>/edit/", client_profile_edit_view, name="client_profile_edit"),
    path("clients/<uuid:pk>/activate/", client_profile_activate_view, name="client_profile_activate"),
    path("clients/<uuid:pk>/delete/", client_profile_delete_view, name="client_profile_delete"),
    path("clients/<uuid:pk>/", client_profile_detail_view, name="client_profile_detail"),
    path("clients/", client_profile_list_view, name="client_profile_list"),
]
