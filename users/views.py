import json
import re
import secrets
from functools import wraps
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlsplit, urlunsplit

# One-shot CSRF token cache: GET /csrf/ stores the issued token here so that
# POST /login/ can validate it even when the browser omits the csrftoken cookie
# (cross-origin fetch without credentials:include discards Set-Cookie responses).
_CSRF_CACHE_PREFIX = "csrf_api_oneshot:"
_CSRF_CACHE_TTL = 300  # seconds — matches typical form-fill window

# One-time token so SPAs on http://localhost:3000 can complete login via top-level
# navigation to the tenant host (first-party Set-Cookie); cross-site fetch cannot.
_SESSION_BOOTSTRAP_PREFIX = "session_bootstrap:"
_SESSION_BOOTSTRAP_TTL = 120


def _bootstrap_token_cache_set(*, token: str, payload: dict) -> None:
    """
    Store bootstrap payload in the *public* schema cache namespace.

    django_tenants prepends connection.schema_name to every cache key; storing under
    the tenant connection can theoretically diverge between POST /login/ and GET
    /session-bootstrap/ if anything differs in routing. Public-schema keys are stable.
    Payload still includes `schema` and is validated against connection.schema_name on GET.
    """
    from django.core.cache import cache
    from django_tenants.utils import get_public_schema_name, schema_context

    with schema_context(get_public_schema_name()):
        cache.set(
            f"{_SESSION_BOOTSTRAP_PREFIX}{token}",
            payload,
            timeout=_SESSION_BOOTSTRAP_TTL,
        )


def _bootstrap_token_cache_pop(token: str) -> dict | None:
    """Atomically read and delete bootstrap payload from public-schema cache.

    Uses cache.add() to claim a 'consumed' marker before reading the payload.
    cache.add() maps to Redis SETNX (atomic), so only the first concurrent
    caller succeeds — subsequent requests with the same token get None,
    preventing replay attacks.
    """
    from django.core.cache import cache
    from django_tenants.utils import get_public_schema_name, schema_context

    with schema_context(get_public_schema_name()):
        key = f"{_SESSION_BOOTSTRAP_PREFIX}{token}"
        consumed_key = f"{_SESSION_BOOTSTRAP_PREFIX}consumed:{token}"
        # Atomically claim the token. add() only writes if the key is absent.
        if not cache.add(consumed_key, "1", timeout=_SESSION_BOOTSTRAP_TTL):
            return None
        payload = cache.get(key)
        cache.delete(key)
        return payload


def _replace_next_query(url: str, next_url: str | None) -> str:
    """Attach or replace the `next` query parameter on a URL."""
    if not url or not next_url:
        return url
    parsed = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != "next"]
    query.append(("next", next_url))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _allowed_redirect_hosts(*urls: str) -> set[str]:
    """
    Build an allow-list for absolute redirects.

    Include both `host` and `host:port` so Django accepts same-tenant redirects
    across the API (:8000) and SPA (:3000) dev ports.
    """
    hosts: set[str] = set()
    for value in urls:
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.hostname:
            hosts.add(parsed.hostname.lower())
        if parsed.netloc:
            hosts.add(parsed.netloc.lower())
    return hosts


from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView, LogoutView
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, csrf_protect, ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods
from django.views.generic import FormView
from django.views.generic.edit import CreateView

from .forms import ClientProfileRegisterForm, ClientUserCredentialsForm, UserRegistrationForm
from .models import ClientProfile, User
from .services import activate_client_profile, archive_client_profile, create_user_with_profile, deactivate_user

CLIENT_REGISTER_SESSION_KEY = "client_register_credentials"
CLIENT_REGISTER_SIGNING_SALT = "client-register-done"


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


@method_decorator(sensitive_post_parameters(), name="dispatch")
@method_decorator(csrf_protect, name="dispatch")
@method_decorator(ensure_csrf_cookie, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class CustomLoginView(LoginView):
    template_name = "users/login.html"
    fields = "__all__"
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if request.method in ("GET", "HEAD"):
            # Chromium can retain a stale csrftoken while restoring a cached login page.
            # Force a fresh token + Set-Cookie on every login-page GET so the hidden form
            # token and cookie secret stay aligned.
            rotate_token(request)
            get_token(request)
        response = super().dispatch(request, *args, **kwargs)
        # Flash messages are rendered once server-side; without this, the browser's
        # back-forward cache can restore an old login snapshot that still shows them.
        if response.status_code == 200:
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response["Pragma"] = "no-cache"
            if (
                request.method in ("GET", "HEAD")
                and getattr(settings, "DEBUG", False)
                and request.get_host().split(":")[0].endswith(".localhost")
            ):
                # Clean up any old domain-scoped dev cookies left over from previous
                # localhost experiments so host-only tenant cookies win consistently.
                response.delete_cookie(
                    settings.CSRF_COOKIE_NAME,
                    path="/",
                    domain=".localhost",
                    samesite=settings.CSRF_COOKIE_SAMESITE,
                )
                response.delete_cookie(
                    getattr(settings, "SESSION_COOKIE_NAME", "sessionid"),
                    path="/",
                    domain=".localhost",
                    samesite=settings.SESSION_COOKIE_SAMESITE,
                )
        return response

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
    from django.core.cache import cache

    token = get_token(request)
    # Store the issued token so login can validate it even when the browser omits
    # the csrftoken cookie (credentials:omit on the GET /csrf/ fetch).
    cache.set(f"{_CSRF_CACHE_PREFIX}{token}", "1", _CSRF_CACHE_TTL)
    return JsonResponse({"csrfToken": token})


@csrf_exempt
@require_http_methods(["POST"])
def session_login_api(request):
    # Hybrid CSRF guard: accept either the standard double-submit cookie OR a
    # one-shot cache token issued by GET /csrf/. The cache path handles cross-origin
    # SPAs that call GET /csrf/ without credentials:include (so the browser discards
    # the Set-Cookie response and never stores the csrftoken cookie).
    from django.core.cache import cache

    x_csrf = request.META.get("HTTP_X_CSRFTOKEN", "")
    if "csrftoken" not in request.COOKIES:
        # No cookie — validate against the one-shot cache entry (consumed on use).
        if not cache.delete(f"{_CSRF_CACHE_PREFIX}{x_csrf}"):
            return JsonResponse(
                {"detail": "CSRF token missing or expired. Call GET /api/v1/auth/csrf/ first."},
                status=403,
            )
    # Accept JSON body (SPA) and x-www-form-urlencoded (fallback).
    payload = {}
    if request.content_type and "application/json" in request.content_type:
        try:
            payload = json.loads(request.body.decode("utf-8")) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse({"detail": "Invalid JSON body."}, status=400)
    else:
        payload = request.POST

    username = payload.get("username") or payload.get("email") or payload.get("phone") or payload.get("phone_number")
    password = payload.get("password")
    if not username or not password:
        return JsonResponse({"detail": "username, email, or phone and password are required."}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        return JsonResponse({"detail": "Invalid credentials."}, status=401)

    from django.db import connection as _db_conn

    _needs_bootstrap = False
    if getattr(settings, "USE_MULTITENANT", False):
        _oh = (request.META.get("HTTP_ORIGIN") or "").strip()
        if _oh:
            try:
                _origin_host = (urlparse(_oh).hostname or "").lower()
            except ValueError:
                _origin_host = ""
            _api_host = (request.get_host().split(":")[0] or "").lower()
            _needs_bootstrap = (
                _origin_host in ("localhost", "127.0.0.1")
                and _api_host.endswith(".localhost")
                and _api_host != "localhost"
            )

    if _needs_bootstrap:
        _schema = getattr(_db_conn, "schema_name", "") or ""
        _token = secrets.token_urlsafe(32)
        _bootstrap_token_cache_set(
            token=_token,
            payload={"user_id": user.pk, "schema": _schema},
        )
        _bs_path = f"/api/v1/auth/session-bootstrap/?token={_token}"
        _bootstrap_url = request.build_absolute_uri(_bs_path)
        payload_out = {
            "authenticated": True,
            "session_pending": True,
            "session_bootstrap_url": _bootstrap_url,
            "user": {
                "id": user.id,
                "username": user.get_username(),
                "email": getattr(user, "email", ""),
                "role": getattr(user, "role", ""),
            },
        }
    else:
        if getattr(settings, "USE_MULTITENANT", False) and not getattr(user, "backend", None):
            login(request, user, backend="tenants.auth_backends.PublicSchemaSafeModelBackend")
        else:
            login(request, user)
        # Stamp CSRF_COOKIE_USED so Django's CSRF middleware sets the csrftoken cookie
        # in this response. The SPA can then use it for the subsequent logout POST.
        get_token(request)
        payload_out = {
            "authenticated": True,
            "user": {
                "id": user.id,
                "username": user.get_username(),
                "email": getattr(user, "email", ""),
                "role": getattr(user, "role", ""),
            },
        }
    _post_raw = (payload.get("post_login_redirect") or "").strip().lower()
    tenant_client = None
    if getattr(settings, "USE_MULTITENANT", False):
        from tenants.email_index import build_post_login_redirect_url, get_client_tenant_from_connection

        tenant_client = get_client_tenant_from_connection()
        if tenant_client is not None:
            post_login = _post_raw
            use_api_host = None
            if post_login in ("django", "django_dashboard", "api", "api_host"):
                use_api_host = True
            elif post_login in ("spa", "web", "frontend", "react"):
                use_api_host = False
            final_redirect_url = build_post_login_redirect_url(
                tenant_client,
                use_api_host=use_api_host,
            )
            if payload_out.get("session_pending") and payload_out.get("session_bootstrap_url"):
                bootstrap_redirect_url = _replace_next_query(payload_out["session_bootstrap_url"], final_redirect_url)
                payload_out["session_bootstrap_url"] = bootstrap_redirect_url
                payload_out["post_bootstrap_redirect_url"] = final_redirect_url
                payload_out["redirect_url"] = bootstrap_redirect_url
            else:
                payload_out["redirect_url"] = final_redirect_url
    if (
        payload_out.get("session_pending")
        and payload_out.get("session_bootstrap_url")
        and not payload_out.get("redirect_url")
    ):
        payload_out["redirect_url"] = payload_out["session_bootstrap_url"]
    if getattr(settings, "DEBUG", False) and getattr(settings, "USE_MULTITENANT", False):
        if payload_out.get("session_pending"):
            payload_out.setdefault("debug", {})["cookie_same_site"] = (
                "Navigate to redirect_url or session_bootstrap_url in the same tab to finish login; "
                "the session cookie is set on that first-party GET to the tenant host."
            )
        else:
            _oh = (request.META.get("HTTP_ORIGIN") or "").strip()
            if _oh and payload_out.get("redirect_url"):
                try:
                    _origin_host = (urlparse(_oh).hostname or "").lower()
                except ValueError:
                    _origin_host = ""
                _api_host = (request.get_host().split(":")[0] or "").lower()
                if (
                    _origin_host in ("localhost", "127.0.0.1")
                    and _api_host.endswith(".localhost")
                    and _api_host != "localhost"
                ):
                    from tenants.email_index import build_tenant_web_app_base_url

                    _web = build_tenant_web_app_base_url(tenant_client) if tenant_client is not None else ""
                    _tenant_subdomain = _api_host.split(".")[0]
                    _fallback_web = f"http://{_tenant_subdomain}.localhost:3000"
                    payload_out.setdefault("debug", {})["cookie_same_site"] = (
                        "The SPA origin is http://localhost:* but the API is on a tenant host "
                        f"({_api_host}). Browsers treat those as different sites, so the session "
                        "cookie from POST /login/ is often blocked or not sent on navigation. "
                        "Run the Vite/Webpack dev server on the tenant web origin instead "
                        f"(same-site with the API), e.g. {_web or _fallback_web} "
                        "and list that URL in CORS_ALLOWED_ORIGINS / CSRF_TRUSTED_ORIGINS."
                    )
    return JsonResponse(payload_out)


@csrf_exempt
@require_GET
def session_bootstrap_api(request):
    """
    Complete session login after POST /login/ when the SPA is cross-site (e.g. localhost:3000
    vs tenant.localhost:8000). Top-level navigation here sets the session cookie first-party.
    """
    from django.contrib.auth import get_user_model
    from django.db import connection
    from django.utils.http import url_has_allowed_host_and_scheme
    from django_tenants.utils import get_public_schema_name

    token = (request.GET.get("token") or "").strip()
    if not token:
        return HttpResponse("Missing token.", status=400, content_type="text/plain")

    payload = _bootstrap_token_cache_pop(token)
    if not payload:
        return HttpResponse("Login link expired or already used.", status=400, content_type="text/plain")
    expected_schema = payload.get("schema")
    current_schema = getattr(connection, "schema_name", None)
    if not expected_schema or current_schema != expected_schema:
        return HttpResponse("Invalid link for this site.", status=400, content_type="text/plain")

    if expected_schema == get_public_schema_name():
        return HttpResponse("Invalid link.", status=400, content_type="text/plain")

    user_id = payload.get("user_id")
    if not user_id:
        return HttpResponse("Invalid token.", status=400, content_type="text/plain")

    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return HttpResponse("User not found.", status=400, content_type="text/plain")

    if not user.is_active:
        return HttpResponse("Account inactive.", status=403, content_type="text/plain")

    # Multiple AUTHENTICATION_BACKENDS: user from ORM has no .backend; login() requires it.
    _tenant_backend = "tenants.auth_backends.PublicSchemaSafeModelBackend"
    if getattr(settings, "USE_MULTITENANT", False):
        login(request, user, backend=_tenant_backend)
    else:
        login(request, user)
    get_token(request)

    next_url = request.GET.get("next")
    tenant_client = None
    if getattr(settings, "USE_MULTITENANT", False):
        from tenants.email_index import (
            build_post_login_redirect_url,
            build_tenant_api_base_url,
            build_tenant_web_app_base_url,
            get_client_tenant_from_connection,
        )

        tenant_client = get_client_tenant_from_connection()
        if next_url:
            allowed_hosts = {
                request.get_host().lower(),
                request.get_host().split(":")[0].lower(),
            }
            if tenant_client is not None:
                allowed_hosts |= _allowed_redirect_hosts(
                    build_tenant_api_base_url(tenant_client),
                    build_tenant_web_app_base_url(tenant_client),
                    build_post_login_redirect_url(tenant_client, use_api_host=True),
                    build_post_login_redirect_url(tenant_client, use_api_host=False),
                )
            if url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts=allowed_hosts,
                require_https=request.is_secure(),
            ):
                return redirect(next_url)

        if tenant_client is not None:
            return redirect(build_post_login_redirect_url(tenant_client, use_api_host=True))

    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)

    return redirect("/")


@require_http_methods(["POST"])
def session_logout_api(request):
    logout(request)
    return JsonResponse({"authenticated": False})


@require_GET
def session_me_api(request):
    from django.db import connection

    _sn = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
    _schema = getattr(connection, "schema_name", None)
    _is_public = False
    if getattr(settings, "USE_MULTITENANT", False):
        from django_tenants.utils import get_public_schema_name

        _is_public = _schema == get_public_schema_name()
    if not request.user.is_authenticated:
        payload = {"authenticated": False, "detail": "Not authenticated."}
        if getattr(settings, "USE_MULTITENANT", False) and _is_public:
            payload["detail"] = (
                "Tenant user sessions are not available on this host. "
                "Call GET /api/v1/auth/me/ on the same origin as POST /api/v1/auth/login/ "
                "(the tenant api_base_url returned by discover-tenants)."
            )
            payload["code"] = "tenant_session_wrong_host"
        elif getattr(settings, "USE_MULTITENANT", False) and not _is_public and _sn not in request.COOKIES:
            payload["code"] = "no_session_cookie"
            payload["detail"] = (
                "No session cookie on this request. Log in with POST /api/v1/auth/login/ on this host; "
                "if the response has session_pending, navigate to session_bootstrap_url. "
                "Use fetch(..., { credentials: 'include' })."
            )
        if settings.DEBUG:
            _hint = (
                "Call GET /api/v1/auth/me/ on the same host as login (tenant api_base_url) with "
                "fetch(..., { credentials: 'include' }). Cross-origin SPAs need SESSION_COOKIE_SAMESITE=none in .env."
            )
            if getattr(settings, "USE_MULTITENANT", False) and _is_public:
                _hint = (
                    "You are on the public API host. Tenant sessions are stored per tenant schema; "
                    "use the tenant api_base_url for login and /me/ (same host for both)."
                )
            elif getattr(settings, "USE_MULTITENANT", False) and not _is_public:
                _cn = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
                if _cn not in request.COOKIES:
                    _hint = (
                        "sessionid cookie not sent; use fetch(..., { credentials: 'include' }). "
                        "Cross-origin SPAs need SESSION_COOKIE_SAMESITE=none and CORS_ALLOWED_ORIGINS."
                    )
            payload["debug"] = {
                "request_host": request.get_host(),
                "schema_name": getattr(connection, "schema_name", None),
                "hint": _hint,
            }
        return JsonResponse(payload, status=401)
    return JsonResponse(
        {
            "authenticated": True,
            "user": {
                "id": request.user.id,
                "username": request.user.get_username(),
                "email": getattr(request.user, "email", ""),
                "role": getattr(request.user, "role", ""),
            },
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def discover_tenants_api(request):
    """
    Public identifier discovery: returns tenant options for a user email or phone.
    Does not expose platform-admin accounts. Password login must be done on the
    selected tenant host (see docs/EMAIL_FIRST_LOGIN.md).

    CSRF is exempt here so cross-origin SPAs can POST without a prior csrftoken
    cookie (browser + CORS often block that bootstrap). Risk is limited (no
    session); add rate limiting in production. Login/logout remain CSRF-protected.
    """
    if not getattr(settings, "USE_MULTITENANT", False):
        return JsonResponse({"detail": "Tenant discovery is only available in multi-tenant mode."}, status=400)

    from tenants.email_index import (
        build_post_login_redirect_url,
        build_tenant_api_base_url,
        build_tenant_web_app_base_url,
        normalize_email as normalize_login_email,
        normalize_phone as normalize_login_phone,
    )

    payload = {}
    if request.content_type and "application/json" in request.content_type:
        try:
            payload = json.loads(request.body.decode("utf-8")) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse({"detail": "Invalid JSON body."}, status=400)
    else:
        payload = request.POST

    email = normalize_login_email(payload.get("email"))
    phone = normalize_login_phone(payload.get("phone") or payload.get("phone_number"))
    if not email and not phone:
        return JsonResponse({"tenants": []})

    from django.core.cache import cache
    from django_tenants.utils import get_public_schema_name, schema_context

    _DISCOVERY_CACHE_TTL = 300  # 5 minutes — safe; membership rows change rarely

    cache_key = None
    if email and not phone:
        cache_key = f"tenant_discovery:{email}"
    elif phone and not email:
        cache_key = f"tenant_discovery_phone:{phone}"

    if cache_key:
        with schema_context(get_public_schema_name()):
            cached = cache.get(cache_key)
        if cached is not None:
            return JsonResponse(cached)

    from tenants.models import EmailTenantMembership

    membership_filter = Q()
    if email:
        membership_filter |= Q(email_normalized=email)
    if phone:
        membership_filter |= Q(phone_normalized=phone)

    with schema_context(get_public_schema_name()):
        qs = (
            EmailTenantMembership.objects.filter(
                membership_filter,
                is_active=True,
                tenant__is_active=True,
            )
            .select_related("tenant")
            .order_by("tenant__schema_name", "tenant_user_id")
        )

        tenants_payload = []
        seen_tenant_ids = set()
        for m in qs:
            t = m.tenant
            if t.pk in seen_tenant_ids:
                continue
            seen_tenant_ids.add(t.pk)
            primary = t.get_primary_domain()
            host = primary.domain if primary else f"{t.slug or t.schema_name}.localhost"
            base = build_tenant_api_base_url(t)
            web_base = build_tenant_web_app_base_url(t)
            tenants_payload.append(
                {
                    "schema_name": t.schema_name,
                    "name": t.name,
                    "slug": t.slug or t.schema_name,
                    "primary_domain": host,
                    "api_base_url": base,
                    "auth_login_url": f"{base.rstrip('/')}/api/v1/auth/login/",
                    "web_app_base_url": web_base,
                    "post_login_redirect_url": build_post_login_redirect_url(t),
                    "role": m.role,
                }
            )

    out: dict = {"tenants": tenants_payload}
    if not tenants_payload and (email or phone):
        out["discovery_hint"] = (
            "No tenants are indexed for this email or phone number. Each tenant user needs at least one "
            "contact identifier and a public EmailTenantMembership row (created automatically on save, or run: "
            "python manage.py backfill_email_tenant_membership)."
        )

    if cache_key:
        with schema_context(get_public_schema_name()):
            cache.set(cache_key, out, timeout=_DISCOVERY_CACHE_TTL)

    return JsonResponse(out)


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy("logged_out")  # Redirect to logged_out page after logout


def _unique_client_username(base_name: str, phone_last4: str) -> str:
    """Build a username from name + phone suffix; ensure uniqueness (max 150 chars)."""
    slug = re.sub(r"[^a-z0-9]", "", (base_name or "client").lower())[:80] or "client"
    candidate = f"{slug}{phone_last4}"
    if len(candidate) > 150:
        candidate = candidate[:150]
    n = 0
    while User.objects.filter(username=candidate).exists():
        n += 1
        suffix = secrets.token_hex(3) if n > 15 else str(n)
        candidate = f"{slug}{phone_last4}{suffix}"[:150]
    return candidate


class ClientProfileRegisterView(FormView):
    form_class = ClientProfileRegisterForm
    template_name = "users/client_profile_register.html"
    success_url = reverse_lazy("client_register_done")

    def form_valid(self, form):
        phone = form.cleaned_data["phone_number"]
        email = form.cleaned_data.get("email") or ""
        account_type = form.cleaned_data["account_type"]
        contact_person = form.cleaned_data.get("contact_person")
        company_name = form.cleaned_data.get("company_name")
        if account_type == ClientProfile.AccountType.ENTERPRISE and company_name:
            base_name = company_name
        else:
            base_name = contact_person or "client"
        phone_last4 = phone[-4:] if len(phone) >= 4 else phone
        username = _unique_client_username(base_name, phone_last4)
        password = secrets.token_urlsafe(8)
        profile_data = {
            "account_type": form.cleaned_data["account_type"],
            "contact_person": form.cleaned_data.get("contact_person") or "",
            "address": form.cleaned_data["address"],
            "company_name": form.cleaned_data.get("company_name") or None,
            "tax_id": form.cleaned_data.get("tax_id") or None,
        }
        create_user_with_profile(
            username,
            password,
            User.Role.CLIENT,
            email=email,
            phone_number=phone,
            profile_phone_number=phone,
            **profile_data,
        )
        # Session backup (optional); primary success payload is signed URL (works across workers / cache session).
        self.request.session[CLIENT_REGISTER_SESSION_KEY] = {
            "username": username,
            "password": password,
        }
        self.request.session.modified = True
        # signing.dumps() already applies TimestampSigner + HMAC; do not wrap in .sign() again.
        token = signing.dumps(
            {"username": username, "password": password},
            salt=CLIENT_REGISTER_SIGNING_SALT,
        )
        done_url = reverse("client_register_done") + "?t=" + quote(token, safe="")
        return HttpResponseRedirect(done_url)


def client_register_done_view(request):
    token = request.GET.get("t")
    if token:
        try:
            data = signing.loads(
                token,
                salt=CLIENT_REGISTER_SIGNING_SALT,
                max_age=600,
            )
        except signing.SignatureExpired:
            messages.error(
                request,
                "That confirmation link expired. Please submit the registration form again or sign in if you already have an account.",
            )
            return redirect("login")
        except signing.BadSignature:
            pass
        else:
            if isinstance(data, dict) and data.get("username") and data.get("password") is not None:
                request.session.pop(CLIENT_REGISTER_SESSION_KEY, None)
                return render(
                    request,
                    "users/client_register_done.html",
                    {
                        "username": data["username"],
                        "password": data["password"],
                    },
                )

    creds = request.session.pop(CLIENT_REGISTER_SESSION_KEY, None)
    if creds:
        return render(
            request,
            "users/client_register_done.html",
            {
                "username": creds["username"],
                "password": creds["password"],
            },
        )
    messages.info(
        request,
        "If you just registered, sign in below. Otherwise complete the registration form first.",
    )
    return redirect("login")


@login_required
def dashboard_view(request):
    return render(request, "users/dashboard.html", {})


# RBAC Decorators using Django's built-in functionality


def is_manager_or_admin(user):
    """Check if user has MANAGER, ADMIN, or OWNER role"""
    return user.is_authenticated and user.role in [
        user.Role.OWNER,
        user.Role.ADMIN,
        user.Role.MANAGER,
    ]


def is_admin(user):
    """Tenant admin: OWNER or ADMIN (full app privileges; not Django /admin/)."""
    return user.is_authenticated and user.role in [user.Role.OWNER, user.Role.ADMIN]


def is_manager(user):
    """MANAGER or OWNER — same operational permissions (OWNER is the registration-approved tenant owner)."""
    return user.is_authenticated and user.role in (user.Role.MANAGER, user.Role.OWNER)


def is_operator_or_above(user):
    """OPERATOR and above (includes OWNER, ADMIN, MANAGER)."""
    return user.is_authenticated and user.role in [
        user.Role.OWNER,
        user.Role.ADMIN,
        user.Role.MANAGER,
        user.Role.OPERATOR,
    ]


# Decorators using Django's user_passes_test
manager_or_admin_required = user_passes_test(is_manager_or_admin, login_url="/login/")
admin_required = user_passes_test(is_admin, login_url="/login/")
manager_required = user_passes_test(is_manager, login_url="/login/")
operator_or_above_required = user_passes_test(is_operator_or_above, login_url="/login/")


@manager_or_admin_required
def client_profile_list_view(request):
    """List registered client profiles (staff: owner, admin, manager)."""
    q = request.GET.get("q", "").strip()
    status = (request.GET.get("status") or "all").strip().lower()
    if status not in ("all", "active", "archived"):
        status = "all"

    qs = ClientProfile.objects.select_related("user").order_by("-created_at")
    if q:
        qs = qs.filter(
            Q(company_name__icontains=q)
            | Q(contact_person__icontains=q)
            | Q(phone_number__icontains=q)
            | Q(user__username__icontains=q)
            | Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
        )
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "archived":
        qs = qs.filter(is_active=False)

    counts = ClientProfile.objects.aggregate(
        n_active=Count("id", filter=Q(is_active=True)),
        n_archived=Count("id", filter=Q(is_active=False)),
    )

    return render(
        request,
        "users/client_profile_list.html",
        {
            "clients": qs,
            "q": q,
            "status_filter": status,
            "count_active": counts["n_active"],
            "count_archived": counts["n_archived"],
            "count_all": counts["n_active"] + counts["n_archived"],
        },
    )


def _assert_staff_may_manage_client_profile(profile: ClientProfile) -> None:
    """Only profiles for client-role users (or walk-in without user) are managed here."""
    u = profile.user
    if u is not None and u.role != User.Role.CLIENT:
        raise PermissionDenied("This account cannot be managed from the client list.")


@manager_or_admin_required
def client_profile_detail_view(request, pk):
    profile = get_object_or_404(ClientProfile.objects.select_related("user"), pk=pk)
    _assert_staff_may_manage_client_profile(profile)
    return render(request, "users/client_profile_detail.html", {"profile": profile})


@manager_or_admin_required
def client_profile_add_view(request):
    if request.method == "POST":
        profile_form_data = request.POST.copy()
        profile_form_data.pop("email", None)
        profile_form = ClientProfileRegisterForm(profile_form_data)
        cred_form = ClientUserCredentialsForm(request.POST, user_instance=None, require_password=True)
        if profile_form.is_valid() and cred_form.is_valid():
            cd = cred_form.cleaned_data
            pd = profile_form.cleaned_data
            profile_data = {
                "account_type": pd["account_type"],
                "contact_person": pd.get("contact_person") or "",
                "address": pd["address"],
                "company_name": pd.get("company_name") or None,
                "tax_id": pd.get("tax_id") or None,
            }
            with transaction.atomic():
                user = create_user_with_profile(
                    cd["username"],
                    cd["new_password1"],
                    User.Role.CLIENT,
                    email=cd.get("email") or "",
                    phone_number=cd.get("phone_number") or "",
                    profile_phone_number=pd["phone_number"],
                    **profile_data,
                )
            messages.success(request, "Client created.")
            return redirect("client_profile_detail", pk=user.client_profile.pk)
    else:
        profile_form = ClientProfileRegisterForm()
        cred_form = ClientUserCredentialsForm(user_instance=None, require_password=True)
    return render(
        request,
        "users/client_profile_form.html",
        {
            "profile_form": profile_form,
            "cred_form": cred_form,
            "mode": "add",
            "profile": None,
        },
    )


@manager_or_admin_required
def client_profile_edit_view(request, pk):
    profile = get_object_or_404(ClientProfile.objects.select_related("user"), pk=pk)
    _assert_staff_may_manage_client_profile(profile)
    user = profile.user
    if request.method == "POST":
        profile_form_data = request.POST.copy()
        profile_form_data.pop("email", None)
        profile_form = ClientProfileRegisterForm(profile_form_data, instance=profile)
        cred_form = ClientUserCredentialsForm(request.POST, user_instance=user) if user else None
        profile_ok = profile_form.is_valid()
        cred_ok = cred_form.is_valid() if cred_form else True
        if profile_ok and cred_ok:
            with transaction.atomic():
                profile_form.save()
                if user and cred_form:
                    cd = cred_form.cleaned_data
                    user.username = cd["username"]
                    user.email = cd.get("email") or ""
                    user.phone_number = cd.get("phone_number") or ""
                    p1 = (cd.get("new_password1") or "").strip()
                    if p1:
                        user.set_password(p1)
                    user.save()
            messages.success(request, "Client updated.")
            return redirect("client_profile_detail", pk=profile.pk)
    else:
        profile_form = ClientProfileRegisterForm(instance=profile)
        cred_form = (
            ClientUserCredentialsForm(
                initial={
                    "username": user.username,
                    "email": user.email or "",
                    "phone_number": user.phone_number or "",
                },
                user_instance=user,
            )
            if user
            else None
        )
    return render(
        request,
        "users/client_profile_form.html",
        {
            "profile_form": profile_form,
            "cred_form": cred_form,
            "mode": "edit",
            "profile": profile,
        },
    )


@manager_or_admin_required
@require_http_methods(["POST"])
def client_profile_activate_view(request, pk):
    profile = get_object_or_404(ClientProfile.objects.select_related("user"), pk=pk)
    _assert_staff_may_manage_client_profile(profile)
    if profile.is_active:
        messages.info(request, "This client is already active.")
        return redirect("client_profile_detail", pk=profile.pk)
    activate_client_profile(profile)
    messages.success(request, "Client activated and login enabled.")
    return redirect("client_profile_list")


@manager_or_admin_required
def client_profile_delete_view(request, pk):
    profile = get_object_or_404(ClientProfile.objects.select_related("user"), pk=pk)
    _assert_staff_may_manage_client_profile(profile)
    if request.method == "POST":
        u = profile.user
        with transaction.atomic():
            archive_client_profile(profile)
            if u:
                deactivate_user(u)
        messages.success(request, "Client archived and login disabled.")
        return redirect("client_profile_list")
    return render(request, "users/client_profile_confirm_delete.html", {"profile": profile})


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
