"""URLconf for the public schema (e.g. marketing / landing when no tenant hostname matches)."""

from django.urls import path

from tenants.views import public_landing

urlpatterns = [
    path("", public_landing, name="public_landing"),
]
