from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

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
    path("i18n/", include("django.conf.urls.i18n")),  # Include the i18n URLs for set_language
    path("reporting/", include("reporting.urls")),  # Add reporting URLs here temporarily
    path("api/v1/edge/", include("scales.api_urls")),  # CarniTrack Edge API
    path("api/v1/auth/", include("users.api_urls")),  # Session auth endpoints for external frontend
    path("api/v1/clients/", include("users.client_api_urls")),  # Staff: client profiles (list + detail/PATCH)
    path(
        "api/v1/tenant-registration/", include("tenants.api_urls")
    ),  # Public tenant signup (same routes as urls_public)
]

# Translatable URLs
urlpatterns += i18n_patterns(
    path("reception/", include("reception.urls")),
    path("processing/", include("processing.urls")),
    path("labeling/", include("labeling.urls")),
    path("scales/", include("scales.urls")),  # Scale operations / session management
    path("", include("users.urls")),  # Include user authentication URLs at the root
    prefix_default_language=True,  # Add language prefix for all languages for consistency
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
