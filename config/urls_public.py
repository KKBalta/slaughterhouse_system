"""URLconf for the public schema (e.g. marketing / landing when no tenant hostname matches)."""

from django.urls import include, path, re_path
from django.views.generic import RedirectView

from tenants.views import (
    PlatformAdminLoginView,
    PlatformAdminLogoutView,
    platform_admin_dashboard,
    platform_admin_setup,
    public_landing,
    public_setup,
    public_setup_status,
    public_signin,
    tenant_impersonate,
    tenant_create_superuser,
    tenant_hard_delete,
    tenant_registration_approve,
    tenant_registration_reject,
    toggle_tenant_active,
)

urlpatterns = [
    # Keep auth API reachable on public hosts (e.g. api.carnitrack.localhost in dev).
    path("api/v1/auth/", include("users.api_urls")),
    path("api/v1/tenant-registration/", include("tenants.api_urls")),
    path("", public_landing, name="public_landing"),
    path("signin/", public_signin, name="public_signin"),
    path("setup/", public_setup, name="public_setup"),
    path("setup/status/<uuid:registration_id>/", public_setup_status, name="public_setup_status"),
    path("platform-admin/setup/", platform_admin_setup, name="platform_admin_setup"),
    path("platform-admin/login/", PlatformAdminLoginView.as_view(), name="platform_admin_login"),
    path("platform-admin/logout/", PlatformAdminLogoutView.as_view(), name="platform_admin_logout"),
    path("platform-admin/", platform_admin_dashboard, name="platform_admin_dashboard"),
    path(
        "platform-admin/registrations/<uuid:registration_id>/approve/",
        tenant_registration_approve,
        name="tenant_registration_approve",
    ),
    path(
        "platform-admin/registrations/<uuid:registration_id>/reject/",
        tenant_registration_reject,
        name="tenant_registration_reject",
    ),
    path(
        "platform-admin/tenants/<slug:schema_name>/superuser/",
        tenant_create_superuser,
        name="tenant_create_superuser",
    ),
    path(
        "platform-admin/tenants/<slug:schema_name>/impersonate/<slug:mode>/",
        tenant_impersonate,
        name="tenant_impersonate",
    ),
    path("platform-admin/tenants/<slug:schema_name>/toggle/", toggle_tenant_active, name="toggle_tenant_active"),
    path("platform-admin/tenants/<slug:schema_name>/delete/", tenant_hard_delete, name="tenant_hard_delete"),
    # Any other path on the public schema redirects to the landing page.
    re_path(r"^.+$", RedirectView.as_view(pattern_name="public_landing", permanent=False)),
]
