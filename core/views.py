import logging
from urllib.parse import unquote, urlsplit

from django.utils import translation
from django.utils.translation import get_language_from_path
from django.views.i18n import set_language as django_set_language

logger = logging.getLogger(__name__)


def set_language(request):
    """
    Wrap Django's set_language so translate_url() can resolve the ``next`` URL.

    LocalePrefixPattern matches only the language prefix that matches
    ``get_language()``. POSTs to ``/i18n/setlang/`` have no language segment,
    so the middleware often activates the cookie language (e.g. ``tr``) while
    the user is viewing ``/en/...``. Then resolve() fails for ``/en/...``,
    translate_url returns the same URL, and the UI language appears stuck.

    Activating the language taken from ``next`` or the Referer path before
    delegating fixes resolution and the redirect to the correct prefix.
    """
    next_url = request.POST.get("next", request.GET.get("next"))
    referer = request.META.get("HTTP_REFERER")
    for candidate in (next_url, referer):
        if not candidate:
            continue
        parsed = urlsplit(candidate)
        path_lang = get_language_from_path(unquote(parsed.path))
        if path_lang:
            translation.activate(path_lang)
            break
    return django_set_language(request)
