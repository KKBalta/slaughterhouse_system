from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django_tenants.utils import tenant_context

from tenants.forms import (
    CreateTenantForm,
    CreateTenantSuperuserForm,
    PlatformAdminAuthenticationForm,
    PlatformAdminSetupForm,
)
from tenants.models import Client, Domain, PlatformAdmin


def public_landing(request):
    return render(request, "public/landing.html")


class PlatformAdminLoginView(LoginView):
    template_name = "tenants/platform_admin/login.html"
    authentication_form = PlatformAdminAuthenticationForm
    redirect_authenticated_user = False

    def get_login_url(self):
        return "/platform-admin/login/"

    def get_success_url(self):
        return str(reverse_lazy("platform_admin_dashboard"))

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and isinstance(request.user, PlatformAdmin):
            return redirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)


def _require_platform_admin(request):
    """Return None if the request is from an authenticated PlatformAdmin, else an HttpResponse."""
    if not request.user.is_authenticated or not isinstance(request.user, PlatformAdmin):
        logout(request)
        return redirect("/platform-admin/login/")
    return None


@login_required(login_url="/platform-admin/login/")
def platform_admin_dashboard(request):
    guard = _require_platform_admin(request)
    if guard:
        return guard

    create_form = CreateTenantForm()
    if request.method == "POST" and request.POST.get("_action") == "create_tenant":
        create_form = CreateTenantForm(request.POST)
        if create_form.is_valid():
            schema = create_form.cleaned_data["schema_name"]
            base_domain = getattr(settings, "TENANT_BASE_DOMAIN", "carnitrack.samperlabs.com")
            domain_name = create_form.cleaned_data.get("domain") or f"{schema}.{base_domain}"

            tenant = Client(
                schema_name=schema,
                name=create_form.cleaned_data["name"],
                company_name=create_form.cleaned_data.get("company_name", ""),
                contact_email=create_form.cleaned_data.get("contact_email", ""),
            )
            tenant.save()
            Domain.objects.create(domain=domain_name, tenant=tenant, is_primary=True)
            messages.success(request, f'Tenant "{schema}" provisioned at {domain_name}.')
            return redirect("platform_admin_dashboard")

    tenants = Client.objects.all().order_by("schema_name")
    return render(
        request,
        "tenants/platform_admin/dashboard.html",
        {
            "tenants": tenants,
            "platform_admin": request.user,
            "create_form": create_form,
        },
    )


@login_required(login_url="/platform-admin/login/")
def tenant_create_superuser(request, schema_name):
    """
    Provision a Django superuser (tenant auth.User) for one tenant schema.
    Only available to PlatformAdmin; runs ORM inside the tenant's PostgreSQL schema.
    """
    guard = _require_platform_admin(request)
    if guard:
        return guard

    tenant = get_object_or_404(Client, schema_name=schema_name)
    primary_domain = tenant.get_primary_domain()
    domain_hint = primary_domain.domain if primary_domain else ""

    form = CreateTenantSuperuserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"].strip()
        email = form.cleaned_data["email"].strip().lower()
        password = form.cleaned_data["password1"]
        User = get_user_model()
        try:
            with tenant_context(tenant):
                if User.objects.filter(username__iexact=username).exists():
                    form.add_error("username", "A user with this username already exists in this tenant.")
                elif User.objects.filter(email__iexact=email).exists():
                    form.add_error("email", "A user with this email already exists in this tenant.")
                else:
                    User.objects.create_superuser(
                        username=username,
                        email=email,
                        password=password,
                        role=User.Role.ADMIN,
                    )
        except IntegrityError:
            form.add_error(None, "Could not create user (unique constraint). Try a different username or email.")
        else:
            if not form.errors:
                if domain_hint:
                    scheme = "http" if ("localhost" in domain_hint or "127.0.0.1" in domain_hint) else "https"
                    where = f"{scheme}://{domain_hint}/admin/"
                else:
                    where = f"the tenant host you configure for schema «{schema_name}», then /admin/"
                messages.success(
                    request,
                    f'Superuser "{username}" created for tenant "{schema_name}". Sign in at {where}',
                )
                return redirect("platform_admin_dashboard")

    return render(
        request,
        "tenants/platform_admin/tenant_superuser.html",
        {
            "tenant": tenant,
            "domain_hint": domain_hint,
            "form": form,
            "platform_admin": request.user,
        },
    )


@require_POST
@login_required(login_url="/platform-admin/login/")
def toggle_tenant_active(request, schema_name):
    guard = _require_platform_admin(request)
    if guard:
        return guard
    tenant = get_object_or_404(Client, schema_name=schema_name)
    tenant.is_active = not tenant.is_active
    tenant.save(update_fields=["is_active"])
    state = "activated" if tenant.is_active else "deactivated"
    messages.success(request, f'Tenant "{schema_name}" {state}.')
    return redirect("platform_admin_dashboard")


class PlatformAdminLogoutView(LogoutView):
    next_page = reverse_lazy("public_landing")


def platform_admin_setup(request):
    """
    First-run setup: create the initial PlatformAdmin account.
    Redirects to login once any PlatformAdmin exists.
    """
    if PlatformAdmin.objects.exists():
        messages.info(request, "Setup already complete. Please sign in.")
        return redirect("platform_admin_login")

    form = PlatformAdminSetupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        admin = PlatformAdmin(
            email=form.cleaned_data["email"],
            name=form.cleaned_data["name"],
        )
        admin.set_password(form.cleaned_data["password1"])
        admin.is_active = True
        admin.save()
        messages.success(request, "Account created. Please sign in.")
        return redirect("platform_admin_login")

    return render(request, "tenants/platform_admin/setup.html", {"form": form})
