from django.urls import path

from .views import (
    ClientProfileRegisterView,
    CustomLoginView,
    CustomLogoutView,
    RegisterView,
    dashboard_view,
    home_view,
    logged_out_view,
)

urlpatterns = [
    path("", home_view, name="home"),  # Set new landing page as the home page
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", CustomLoginView.as_view(), name="login"),
    path("logout/", CustomLogoutView.as_view(), name="logout"),
    path("logged-out/", logged_out_view, name="logged_out"),  # Page shown after logout
    path("dashboard/", dashboard_view, name="dashboard"),
    path("client-register/", ClientProfileRegisterView.as_view(), name="client_register"),
]
