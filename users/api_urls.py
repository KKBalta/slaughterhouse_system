from django.urls import path

from .views import csrf_token_api, session_login_api, session_logout_api, session_me_api

urlpatterns = [
    path("csrf/", csrf_token_api, name="api_csrf"),
    path("login/", session_login_api, name="api_login"),
    path("logout/", session_logout_api, name="api_logout"),
    path("me/", session_me_api, name="api_me"),
]
