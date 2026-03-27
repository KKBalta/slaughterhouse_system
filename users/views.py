import secrets
import json
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods
from django.views.generic.edit import CreateView

from .forms import ClientProfileRegisterForm, UserRegistrationForm


# New home view for the landing page
def home_view(request):
    return render(request, "users/home.html")


# New view for the logged out confirmation page
def logged_out_view(request):
    return render(request, "users/logged_out.html")


class RegisterView(CreateView):
    form_class = UserRegistrationForm
    success_url = reverse_lazy("login")  # Redirect to login page after successful registration
    template_name = "users/register.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    # def dispatch(self, request, *args, **kwargs):
    #     if request.user.is_authenticated:
    #         return redirect(reverse_lazy('dashboard')) # Redirect to dashboard if already logged in
    #     return super().dispatch(request, *args, **kwargs)


class CustomLoginView(LoginView):
    template_name = "users/login.html"
    fields = "__all__"
    redirect_authenticated_user = True

    def get_success_url(self):
        """
        Redirect to the 'next' parameter if provided, otherwise to dashboard.
        This allows proper redirection after login when accessing protected pages.
        Handles both GET and POST parameters for the 'next' value.
        """
        # Check POST first (form submission), then GET (URL parameter)
        next_url = self.request.POST.get("next") or self.request.GET.get("next")

        if next_url:
            # Validate that the next URL is safe (same domain)
            from django.utils.http import url_has_allowed_host_and_scheme

            allowed_hosts = {self.request.get_host()}

            if url_has_allowed_host_and_scheme(next_url, allowed_hosts=allowed_hosts):
                return next_url

        # Default redirect to dashboard
        return reverse_lazy("dashboard")


@require_GET
@ensure_csrf_cookie
def csrf_token_api(request):
    return JsonResponse({"csrfToken": get_token(request)})


@require_http_methods(["POST"])
def session_login_api(request):
    # Accept JSON body (SPA) and x-www-form-urlencoded (fallback).
    payload = {}
    if request.content_type and "application/json" in request.content_type:
        try:
            payload = json.loads(request.body.decode("utf-8")) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse({"detail": "Invalid JSON body."}, status=400)
    else:
        payload = request.POST

    username = payload.get("username") or payload.get("email")
    password = payload.get("password")
    if not username or not password:
        return JsonResponse({"detail": "username/email and password are required."}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        return JsonResponse({"detail": "Invalid credentials."}, status=401)

    login(request, user)
    return JsonResponse(
        {
            "authenticated": True,
            "user": {
                "id": user.id,
                "username": user.get_username(),
                "email": getattr(user, "email", ""),
            },
        }
    )


@require_http_methods(["POST"])
def session_logout_api(request):
    logout(request)
    return JsonResponse({"authenticated": False})


@require_GET
def session_me_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=401)
    return JsonResponse(
        {
            "authenticated": True,
            "user": {
                "id": request.user.id,
                "username": request.user.get_username(),
                "email": getattr(request.user, "email", ""),
            },
        }
    )


# Local dev ergonomics: browsers can block cross-origin CSRF cookie flows on localhost
# variants; keep production strict by only relaxing in DEBUG.
if settings.DEBUG:
    session_login_api = csrf_exempt(session_login_api)
    session_logout_api = csrf_exempt(session_logout_api)


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy("logged_out")  # Redirect to logged_out page after logout


class ClientProfileRegisterView(CreateView):
    form_class = ClientProfileRegisterForm
    template_name = "users/client_profile_register.html"
    success_url = reverse_lazy("login")

    def form_valid(self, form):
        # Generate username and password
        phone = form.cleaned_data["phone_number"]
        account_type = form.cleaned_data["account_type"]
        contact_person = form.cleaned_data.get("contact_person")
        company_name = form.cleaned_data.get("company_name")
        # Username: company_name or contact_person + last 4 digits of phone
        if account_type == "ENTERPRISE" and company_name:
            base_name = company_name.replace(" ", "").lower()
        else:
            base_name = (contact_person or "client").replace(" ", "").lower()
        username = f"{base_name}{phone[-4:]}"
        password = secrets.token_urlsafe(8)
        # Create user and profile
        # Optionally, show credentials to user (flash message)
        messages.success(self.request, f"Your account has been created. Username: {username}, Password: {password}")
        return super().form_valid(form)


@login_required
def dashboard_view(request):
    return render(request, "users/dashboard.html", {})


# RBAC Decorators using Django's built-in functionality


def is_manager_or_admin(user):
    """Check if user has MANAGER or ADMIN role"""
    return user.is_authenticated and user.role in [user.Role.MANAGER, user.Role.ADMIN]


def is_admin(user):
    """Check if user has ADMIN role"""
    return user.is_authenticated and user.role == user.Role.ADMIN


def is_manager(user):
    """Check if user has MANAGER role"""
    return user.is_authenticated and user.role == user.Role.MANAGER


def is_operator_or_above(user):
    """Check if user has OPERATOR, MANAGER, or ADMIN role"""
    return user.is_authenticated and user.role in [user.Role.OPERATOR, user.Role.MANAGER, user.Role.ADMIN]


# Decorators using Django's user_passes_test
manager_or_admin_required = user_passes_test(is_manager_or_admin, login_url="/login/")
admin_required = user_passes_test(is_admin, login_url="/login/")
manager_required = user_passes_test(is_manager, login_url="/login/")
operator_or_above_required = user_passes_test(is_operator_or_above, login_url="/login/")


# Custom decorator for better error handling
def role_required(*allowed_roles):
    """
    Decorator that requires user to have one of the specified roles.

    Usage:
    @role_required('ADMIN', 'MANAGER')
    def my_view(request):
        pass
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("/login/")

            if request.user.role not in allowed_roles:
                raise PermissionDenied("You don't have permission to access this page.")

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
