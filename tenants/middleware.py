"""
Tenant app middleware hooks (shared with multitenant routing).
"""

from django.conf import settings


class ClearLegacyMessagesCookieMiddleware:
    """
    Django's default FallbackStorage tries a signed ``messages`` cookie before the
    session. That cookie can survive when delete_cookie does not match how the
    cookie was set (domain / SameSite / Secure), so flash alerts reappear on
    later pages (often login). We use session-only MESSAGE_STORAGE; remove any
    stray legacy cookie so it cannot replay.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Match CookieStorage._update_cookie (django.contrib.messages) delete semantics.
        response.delete_cookie(
            "messages",
            path="/",
            domain=settings.SESSION_COOKIE_DOMAIN,
            samesite=settings.SESSION_COOKIE_SAMESITE,
        )
        return response
