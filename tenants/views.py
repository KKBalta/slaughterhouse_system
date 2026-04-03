from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django_tenants.utils import tenant_context

from tenants.email_index import build_tenant_api_base_url
from tenants.forms import (
    CreateTenantForm,
    CreateTenantSuperuserForm,
    PlatformAdminAuthenticationForm,
    PlatformAdminSetupForm,
    PublicTenantRegistrationForm,
    TenantCompanyProfileForm,
)
from tenants.models import Client, PlatformAdmin, TenantRegistrationRequest
from tenants.registration_views import TenantRegistrationStatusLookupError, get_tenant_registration_status_payload
from tenants.services import (
    approve_registration,
    create_registration_request,
    hard_delete_tenant,
    provision_tenant,
    reject_registration,
)
from users.policies import can_manage_company_settings


def public_landing(request):
    return render(request, "public/landing.html")


def public_signin(request):
    return render(
        request,
        "public/signin.html",
        {
            "initial_email": (request.GET.get("email") or "").strip(),
            "signin_enabled": getattr(settings, "USE_MULTITENANT", False),
        },
    )


def public_setup(request):
    registration_enabled = getattr(settings, "USE_MULTITENANT", False)
    form = PublicTenantRegistrationForm(request.POST or None)
    if not registration_enabled:
        messages.error(request, "Tenant registration is only available in multi-tenant mode.")
    elif request.method == "POST" and form.is_valid():
        reg, raw_token = create_registration_request(**form.registration_kwargs())
        return redirect(f"{reverse('public_setup_status', args=[reg.id])}?token={raw_token}")

    return render(
        request,
        "public/setup.html",
        {
            "form": form,
            "registration_enabled": registration_enabled,
        },
    )


def public_setup_status(request, registration_id):
    token = (request.GET.get("token") or request.GET.get("status_token") or "").strip()
    status_payload = None
    status_error = ""
    if not getattr(settings, "USE_MULTITENANT", False):
        status_error = "Tenant registration is only available in multi-tenant mode."
    elif not token:
        status_error = "Missing status token."
    else:
        try:
            status_payload = get_tenant_registration_status_payload(registration_id, token)
        except TenantRegistrationStatusLookupError as exc:
            status_error = exc.detail

    return render(
        request,
        "public/setup_status.html",
        {
            "registration_id": registration_id,
            "status_token": token,
            "status_payload": status_payload,
            "status_error": status_error,
        },
    )


class PlatformAdminLoginView(LoginView):
    template_name = "tenants/platform_admin/login.html"
    authentication_form = PlatformAdminAuthenticationForm
    redirect_authenticated_user = False

    def get_login_url(self):
        return "/platform-admin/login/"

    def get_default_redirect_url(self):
        return str(reverse_lazy("platform_admin_dashboard"))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["public_site_url"] = getattr(settings, "SITE_URL_FALLBACK", "") or ""
        return ctx

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
            base_domain = settings.TENANT_BASE_DOMAIN
            domain_name = create_form.cleaned_data.get("domain") or f"{schema}.{base_domain}"
            provision_tenant(
                schema_name=schema,
                name=create_form.cleaned_data["name"],
                company_name=create_form.cleaned_data.get("company_name", ""),
                contact_email=create_form.cleaned_data.get("contact_email", ""),
                domain_name=domain_name,
            )
            messages.success(request, f'Tenant "{schema}" provisioned at {domain_name}.')
            return redirect("platform_admin_dashboard")

    pending_regs = (
        TenantRegistrationRequest.objects.filter(status=TenantRegistrationRequest.Status.PENDING)
        .select_related("reviewed_by")
        .order_by("created_at")
    )

    tenants_qs = Client.objects.all().prefetch_related("domains").order_by("schema_name")
    tenant_rows = [{"tenant": t, "app_url": build_tenant_api_base_url(t)} for t in tenants_qs]
    return render(
        request,
        "tenants/platform_admin/dashboard.html",
        {
            "tenant_rows": tenant_rows,
            "platform_admin": request.user,
            "create_form": create_form,
            "pending_registrations": pending_regs,
        },
    )


@require_POST
@login_required(login_url="/platform-admin/login/")
def tenant_registration_approve(request, registration_id):
    guard = _require_platform_admin(request)
    if guard:
        return guard
    reg = get_object_or_404(
        TenantRegistrationRequest,
        pk=registration_id,
        status=TenantRegistrationRequest.Status.PENDING,
    )
    try:
        approve_registration(reg, request.user)
        messages.success(
            request,
            f'Approved registration "{reg.company_name}" — tenant «{reg.derived_schema_name}» provisioned.',
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
    return redirect("platform_admin_dashboard")


@require_POST
@login_required(login_url="/platform-admin/login/")
def tenant_registration_reject(request, registration_id):
    guard = _require_platform_admin(request)
    if guard:
        return guard
    reg = get_object_or_404(
        TenantRegistrationRequest,
        pk=registration_id,
        status=TenantRegistrationRequest.Status.PENDING,
    )
    reason = (request.POST.get("rejection_reason") or "").strip()
    try:
        reject_registration(reg, request.user, reason=reason)
        messages.success(request, f'Rejected registration for "{reg.company_name}".')
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
    return redirect("platform_admin_dashboard")


@login_required(login_url="/platform-admin/login/")
def tenant_create_superuser(request, schema_name):
    """
    Create a User row in the tenant schema (CarniTrack app login on the tenant host).
    Optional Django /admin/ access via grant_django_admin. Platform admin only.
    """
    guard = _require_platform_admin(request)
    if guard:
        return guard

    tenant = get_object_or_404(Client, schema_name=schema_name)
    primary_domain = tenant.get_primary_domain()
    domain_hint = primary_domain.domain if primary_domain else ""

    User = get_user_model()
    lang_code = getattr(settings, "LANGUAGE_CODE", "tr") or "tr"
    tenant_login_url = f"{build_tenant_api_base_url(tenant).rstrip('/')}/{lang_code}/login/"

    existing_users = []
    with tenant_context(tenant):
        existing_users = list(
            User.objects.order_by("username").values(
                "username", "email", "role", "is_active", "is_staff", "is_superuser"
            )
        )

    form = CreateTenantSuperuserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"].strip()
        email = form.cleaned_data["email"].strip().lower()
        password = form.cleaned_data["password1"]
        account_kind = form.cleaned_data.get("account_kind") or "app_admin"
        grant_django = account_kind == "django_superuser"
        try:
            with tenant_context(tenant):
                if User.objects.filter(username__iexact=username).exists():
                    form.add_error("username", "A user with this username already exists in this tenant.")
                elif User.objects.filter(email__iexact=email).exists():
                    form.add_error("email", "A user with this email already exists in this tenant.")
                else:
                    User.objects.create_user(
                        username=username,
                        email=email,
                        password=password,
                        role=User.Role.ADMIN.value,
                        is_staff=grant_django,
                        is_superuser=grant_django,
                    )
        except IntegrityError:
            form.add_error(None, "Could not create user (unique constraint). Try a different username or email.")
        else:
            if not form.errors:
                kind_label = "Django superuser + app admin" if grant_django else "tenant app admin (ADMIN)"
                messages.success(
                    request,
                    f'User "{username}" created for tenant "{schema_name}" ({kind_label}). '
                    f"Sign in at the tenant app login page (not platform-admin): {tenant_login_url}",
                )
                return redirect("platform_admin_dashboard")

    return render(
        request,
        "tenants/platform_admin/tenant_superuser.html",
        {
            "tenant": tenant,
            "domain_hint": domain_hint,
            "tenant_login_url": tenant_login_url,
            "existing_users": existing_users,
            "form": form,
            "platform_admin": request.user,
        },
    )


@require_POST
@login_required(login_url="/platform-admin/login/")
def tenant_hard_delete(request, schema_name):
    guard = _require_platform_admin(request)
    if guard:
        return guard
    confirm = (request.POST.get("confirm_schema") or "").strip()
    if confirm != schema_name:
        messages.error(
            request,
            f'Confirmation failed: type the schema name exactly ("{schema_name}") to delete this tenant.',
        )
        return redirect("platform_admin_dashboard")
    try:
        hard_delete_tenant(schema_name=schema_name)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        return redirect("platform_admin_dashboard")
    messages.success(
        request,
        f'Tenant "{schema_name}" was permanently deleted (PostgreSQL schema dropped).',
    )
    return redirect("platform_admin_dashboard")


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


@login_required
def tenant_company_settings_view(request):
    """
    Tenant managers edit `Client` company / İşletme onay no / printer fields (stored in public schema).
    """
    from django_tenants.utils import get_public_schema_name, schema_context

    if not getattr(settings, "USE_MULTITENANT", False):
        raise Http404()
    tenant = getattr(request, "tenant", None)
    if tenant is None:
        raise Http404()
    if not can_manage_company_settings(request.user):
        raise PermissionDenied()

    with schema_context(get_public_schema_name()):
        client = get_object_or_404(Client, pk=tenant.pk)

    if request.method == "POST":
        form = TenantCompanyProfileForm(request.POST, request.FILES, instance=client)
        if form.is_valid():
            with schema_context(get_public_schema_name()):
                form.save()
            messages.success(
                request,
                _("Company and label settings saved. They apply to new labels and reports."),
            )
            return redirect("tenant_company_settings")
    else:
        form = TenantCompanyProfileForm(instance=client)

    return render(
        request,
        "tenants/tenant_company_settings.html",
        {"form": form},
    )


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
