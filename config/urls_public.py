"""URLconf for the public schema (e.g. marketing / landing when no tenant hostname matches)."""

from django.urls import include
from django.urls import path, re_path
from django.views.generic import RedirectView

from tenants.views import (
    PlatformAdminLoginView,
    PlatformAdminLogoutView,
    platform_admin_dashboard,
    platform_admin_setup,
    public_landing,
    tenant_create_superuser,
    toggle_tenant_active,
)

urlpatterns = [
    # Keep auth API reachable on public hosts (e.g. api.carnitrack.localhost in dev).
    path("api/v1/auth/", include("users.api_urls")),
    path("", public_landing, name="public_landing"),
    path("platform-admin/setup/", platform_admin_setup, name="platform_admin_setup"),
    path("platform-admin/login/", PlatformAdminLoginView.as_view(), name="platform_admin_login"),
    path("platform-admin/logout/", PlatformAdminLogoutView.as_view(), name="platform_admin_logout"),
    path("platform-admin/", platform_admin_dashboard, name="platform_admin_dashboard"),
    path(
        "platform-admin/tenants/<slug:schema_name>/superuser/",
        tenant_create_superuser,
        name="tenant_create_superuser",
    ),
    path("platform-admin/tenants/<slug:schema_name>/toggle/", toggle_tenant_active, name="toggle_tenant_active"),
    # Any other path on the public schema redirects to the landing page.
    re_path(r"^.+$", RedirectView.as_view(pattern_name="public_landing", permanent=False)),
]
