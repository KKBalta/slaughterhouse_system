from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from core.views import set_language as set_language_view
from tenants.api_views_edge import public_edge_activate
from tenants.views import platform_admin_impersonation_consume, platform_admin_impersonation_stop

# Non-translatable URLs (admin, API endpoints, etc.)
urlpatterns = [
    # Redirect root favicon requests to static favicon (browsers request these automatically)
    path("favicon.ico", RedirectView.as_view(url=settings.STATIC_URL + "theme/img/favicon.png", permanent=False)),
    path(
        "apple-touch-icon.png", RedirectView.as_view(url=settings.STATIC_URL + "theme/img/favicon.png", permanent=False)
    ),
    path(
        "apple-touch-icon-precomposed.png",
        RedirectView.as_view(url=settings.STATIC_URL + "theme/img/favicon.png", permanent=False),
    ),
    path("admin/", admin.site.urls),
    path("i18n/setlang/", set_language_view, name="set_language"),
    path("reporting/", include("reporting.urls")),  # Add reporting URLs here temporarily
    path("api/v1/activate", public_edge_activate, name="public-edge-activate"),  # Public Edge activation
    path("api/v1/edge/", include("scales.api_urls")),  # CarniTrack Edge API (tenant-scoped)
    path("api/v1/auth/", include("users.api_urls")),  # Session auth endpoints for external frontend
    path("api/v1/clients/", include("users.client_api_urls")),  # Staff: client profiles (list + detail/PATCH)
    path(
        "api/v1/tenant-registration/", include("tenants.api_urls")
    ),  # Public tenant signup (same routes as urls_public)
    path(
        "platform-admin/impersonate/consume/",
        platform_admin_impersonation_consume,
        name="platform_admin_impersonation_consume",
    ),
    path(
        "platform-admin/impersonate/stop/",
        platform_admin_impersonation_stop,
        name="platform_admin_impersonation_stop",
    ),
]

# Translatable URLs
urlpatterns += i18n_patterns(
    path("reception/", include("reception.urls")),
    path("processing/", include("processing.urls")),
    path("labeling/", include("labeling.urls")),
    path("scales/", include("scales.urls")),  # Scale operations / session management
    path("portal/", include("portal.urls")),  # Client-facing order portal
    path("", include("users.urls")),  # Include user authentication URLs at the root
    prefix_default_language=True,  # Add language prefix for all languages for consistency
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
