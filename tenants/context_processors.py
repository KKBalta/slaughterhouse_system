from django.urls import NoReverseMatch, reverse


def tenant_context(request):
    """Expose current tenant and impersonation banner payload."""
    state = getattr(request, "session", {}).get("platform_impersonation")
    payload = None
    if isinstance(state, dict):
        payload = dict(state)
        payload["active"] = True
        try:
            payload["stop_url"] = reverse("stop_impersonation")
        except NoReverseMatch:
            payload["stop_url"] = "/impersonation/stop/"
    return {
        "tenant": getattr(request, "tenant", None),
        "platform_impersonation": payload,
    }
