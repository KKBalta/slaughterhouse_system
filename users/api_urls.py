from django.urls import path

from .views import (
    csrf_token_api,
    discover_tenants_api,
    session_bootstrap_api,
    session_login_api,
    session_logout_api,
    session_me_api,
)

urlpatterns = [
    path("csrf/", csrf_token_api, name="api_csrf"),
    path("discover-tenants/", discover_tenants_api, name="api_discover_tenants"),
    path("login/", session_login_api, name="api_login"),
    path("session-bootstrap/", session_bootstrap_api, name="api_session_bootstrap"),
    path("logout/", session_logout_api, name="api_logout"),
    path("me/", session_me_api, name="api_me"),
]
