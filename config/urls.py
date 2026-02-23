from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.views.i18n import set_language

# Non-translatable URLs (admin, API endpoints, etc.)
urlpatterns = [
    path('admin/', admin.site.urls),
    path('i18n/', include('django.conf.urls.i18n')),  # Include the i18n URLs for set_language
    path('reporting/', include('reporting.urls')),  # Add reporting URLs here temporarily
    path('api/v1/edge/', include('scales.api_urls')),  # CarniTrack Edge API
]

# Translatable URLs
urlpatterns += i18n_patterns(
    path('reception/', include('reception.urls')),
    path('processing/', include('processing.urls')),
    path('labeling/', include('labeling.urls')),
    path('scales/', include('scales.urls')),  # Scale operations / session management
    path('', include('users.urls')), # Include user authentication URLs at the root
    prefix_default_language=True,  # Add language prefix for all languages for consistency
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
