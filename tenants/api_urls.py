from importlib import import_module

from django.urls import path


def _import_view(qualified: str):
    """Resolve view at request time so django check / URL load does not import tenants.models."""

    def view(request, *args, **kwargs):
        mod_path, name = qualified.rsplit(".", 1)
        fn = getattr(import_module(mod_path), name)
        return fn(request, *args, **kwargs)

    return view


urlpatterns = [
    path("", _import_view("tenants.registration_views.tenant_registration_create"), name="api_tenant_registration_create"),
    path(
        "<uuid:registration_id>/",
        _import_view("tenants.registration_views.tenant_registration_status"),
        name="api_tenant_registration_status",
    ),
]
