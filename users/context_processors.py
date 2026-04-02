from __future__ import annotations

from users.policies import dashboard_capabilities


def role_capabilities(request):
    return {
        "role_caps": dashboard_capabilities(getattr(request, "user", None)),
    }
