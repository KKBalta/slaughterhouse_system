"""Regression: language switch must redirect to the same page under the new prefix."""

from django.test import RequestFactory

from core.views import set_language


def test_set_language_redirects_next_url_when_cookie_language_mismatches_path_prefix():
    """
    POST /i18n/setlang/ has no language segment, so LocaleMiddleware uses the cookie.
    If the user is on /en/... but the cookie still says tr, translate_url() must still
    resolve /en/... — our view activates the language from ``next`` before delegating.
    """
    rf = RequestFactory()
    request = rf.post(
        "/i18n/setlang/",
        {"language": "tr", "next": "/en/dashboard/"},
        HTTP_HOST="testserver",
    )
    request.COOKIES["django_language"] = "tr"
    response = set_language(request)
    assert response.status_code == 302
    assert response.url == "/tr/dashboard/"
