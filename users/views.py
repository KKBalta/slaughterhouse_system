import json
import secrets
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

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
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, csrf_protect, ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from .forms import (
    ClientProfileRegisterForm,
    ClientUserCredentialsForm,
    SelfServiceContactForm,
    SelfServicePasswordForm,
    TenantManagedUserForm,
)
from .models import CLIENT_MANAGEMENT_ROLES, ClientProfile, User
from .policies import (
    can_access_reception,
    can_access_user_management,
    can_create_role,
    can_edit_user,
    can_manage_client_accounts,
    can_manage_company_settings,
    can_manage_tenant_users,
    creatable_roles_for,
)
from .services import (
    activate_client_profile,
    archive_client_profile,
    change_user_password,
    create_user_with_profile,
    deactivate_user,
    generate_random_password,
    link_walk_in_orders_to_client_profile,
    update_self_service_contact_channels,
    update_user_credentials,
)


def _password_for_create(cd: dict) -> tuple[str, bool]:
    """Return (password, was_generated) when creating a user from credential form data."""
    raw = (cd.get("new_password1") or "").strip()
    if raw:
        return raw, False
    return generate_random_password(), True


# New home view for the landing page
def home_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "users/home.html")


# New view for the logged out confirmation page
def logged_out_view(request):
    return render(request, "users/logged_out.html")


@sensitive_post_parameters("current_password", "new_password1", "new_password2")
@login_required
def account_profile_view(request):
    contact_form = SelfServiceContactForm(user_instance=request.user)
    password_form = SelfServicePasswordForm(user_instance=request.user)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()
        if action == "contact":
            contact_form = SelfServiceContactForm(request.POST, user_instance=request.user)
            if contact_form.is_valid():
                update_self_service_contact_channels(
                    request.user,
                    email=contact_form.cleaned_data.get("email") or "",
                    phone_number=contact_form.cleaned_data.get("phone_number") or "",
                )
                messages.success(request, _("Your contact details were updated."))
                return redirect("account_profile")
        elif action == "password":
            password_form = SelfServicePasswordForm(request.POST, user_instance=request.user)
            if password_form.is_valid():
                changed = change_user_password(
                    request.user,
                    old_password=password_form.cleaned_data["current_password"],
                    new_password=password_form.cleaned_data["new_password1"],
                )
                if not changed:
                    password_form.add_error("current_password", _("Your current password was entered incorrectly."))
                else:
                    update_session_auth_hash(request, request.user)
                    messages.success(request, _("Your password was changed."))
                    return redirect("account_profile")
        else:
            messages.error(request, _("Unknown account action."))

    client_profile = None
    if getattr(request.user, "role", "") == User.Role.CLIENT:
        try:
            client_profile = request.user.client_profile
        except ClientProfile.DoesNotExist:
            client_profile = None

    return render(
        request,
        "users/account_profile.html",
        {
            "contact_form": contact_form,
            "password_form": password_form,
            "client_profile": client_profile,
        },
    )


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
        get_tenant_public_host,
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
            host = get_tenant_public_host(t)
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


@login_required
def dashboard_view(request):
    return render(request, "users/dashboard.html", {})


def is_manager_or_admin(user):
    return can_manage_company_settings(user)


def is_admin(user):
    return can_manage_tenant_users(user)


def is_manager(user):
    return user.is_authenticated and user.role in (user.Role.MANAGER, user.Role.OWNER)


def is_operator_or_above(user):
    return can_access_reception(user)


manager_or_admin_required = user_passes_test(is_manager_or_admin, login_url="/login/")
admin_required = user_passes_test(is_admin, login_url="/login/")
manager_required = user_passes_test(is_manager, login_url="/login/")
operator_or_above_required = user_passes_test(is_operator_or_above, login_url="/login/")
client_account_required = user_passes_test(can_manage_client_accounts, login_url="/login/")
user_management_required = user_passes_test(can_access_user_management, login_url="/login/")


def _get_safe_next_url(request) -> str:
    from django.utils.http import url_has_allowed_host_and_scheme

    next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if not next_url:
        return ""
    allowed_hosts = {
        request.get_host().lower(),
        request.get_host().split(":")[0].lower(),
    }
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts=allowed_hosts, require_https=request.is_secure()):
        return next_url
    return ""


def _redirect_next_or(request, default_name: str, **kwargs):
    next_url = _get_safe_next_url(request)
    if next_url:
        return redirect(next_url)
    return redirect(default_name, **kwargs)


def _user_management_queryset_for(actor):
    qs = User.objects.select_related("client_profile").order_by("username")
    if not can_manage_tenant_users(actor):
        qs = qs.filter(role__in=CLIENT_MANAGEMENT_ROLES)
    return qs


def _staff_allowed_roles(actor) -> tuple[str, ...]:
    return tuple(
        role for role in creatable_roles_for(actor) if role in (User.Role.OWNER, User.Role.ADMIN, User.Role.MANAGER, User.Role.OPERATOR)
    )


def _client_profile_form_instance(user: User | None, profile: ClientProfile | None) -> ClientProfile:
    if profile is not None:
        return profile
    account_type = (
        ClientProfile.AccountType.UNCLASSIFIED
        if user is not None and getattr(user, "role", "") == User.Role.WALKIN
        else ClientProfile.AccountType.INDIVIDUAL
    )
    return ClientProfile(
        user=user,
        account_type=account_type,
        phone_number="",
        address="",
    )


def _save_client_profile(instance: ClientProfile, cleaned_data: dict) -> ClientProfile:
    profile_fields = {
        "account_type": cleaned_data["account_type"],
        "contact_person": cleaned_data.get("contact_person") or "",
        "phone_number": cleaned_data.get("phone_number") or "",
        "address": cleaned_data["address"],
        "default_destination": cleaned_data.get("default_destination") or None,
        "company_name": cleaned_data.get("company_name") or None,
        "tax_id": cleaned_data.get("tax_id") or None,
    }
    for field, value in profile_fields.items():
        setattr(instance, field, value)
    instance.save()
    return instance


def _linked_client_profile(user: User | None) -> ClientProfile | None:
    if user is None:
        return None
    try:
        return user.client_profile
    except ClientProfile.DoesNotExist:
        return None


def _render_client_account_form(request, *, user: User | None = None, profile: ClientProfile | None = None):
    next_url = _get_safe_next_url(request)
    profile_instance = _client_profile_form_instance(user, profile)
    require_password = user is None
    show_credentials_form = user is None or getattr(user, "role", "") == User.Role.CLIENT
    cred_form = None

    if request.method == "POST":
        allow_existing_phone_user = user is None and profile is None
        profile_form = ClientProfileRegisterForm(
            request.POST,
            instance=profile_instance,
            allow_existing_phone_user=allow_existing_phone_user,
        )
        if show_credentials_form:
            cred_form = ClientUserCredentialsForm(
                request.POST,
                user_instance=user,
                require_password=require_password,
                require_contact=False,
            )
        profile_ok = profile_form.is_valid()
        profile_phone = profile_form.cleaned_data.get("phone_number") or "" if profile_ok else ""
        registered_phone_user = getattr(profile_form, "registered_phone_user", None) if profile_ok else None
        registered_phone_profile = _linked_client_profile(registered_phone_user)
        should_skip_user_creation = (
            user is None and profile is None and registered_phone_user is not None and registered_phone_profile is None
        )
        cred_ok = True if should_skip_user_creation else cred_form.is_valid() if cred_form else True
        if profile_ok and cred_ok:
            with transaction.atomic():
                if user is None and cred_form:
                    if should_skip_user_creation:
                        profile_instance.user = (
                            registered_phone_user
                            if registered_phone_user.role in CLIENT_MANAGEMENT_ROLES
                            else None
                        )
                        saved_profile = _save_client_profile(profile_instance, profile_form.cleaned_data)
                        linked_orders = link_walk_in_orders_to_client_profile(
                            profile=saved_profile,
                            phone_number=profile_phone,
                        )
                        if registered_phone_user.role == User.Role.CLIENT:
                            messages.success(
                                request,
                                _("Client profile created and linked to the existing registered account."),
                            )
                        elif registered_phone_user.role == User.Role.WALKIN:
                            messages.success(
                                request,
                                _("Client profile created and linked to the existing walk-in record."),
                            )
                        else:
                            messages.success(
                                request,
                                _("Client profile created without creating a second login for this registered phone number."),
                            )
                        if linked_orders:
                            messages.success(request, _("Matching walk-in orders were linked by phone number."))
                        if saved_profile.pk and not next_url:
                            return redirect("client_profile_detail", pk=saved_profile.pk)
                        return _redirect_next_or(request, "tenant_user_list")

                    cd = cred_form.cleaned_data
                    password, password_generated = _password_for_create(cd)
                    created_user = create_user_with_profile(
                        cd["username"],
                        password,
                        User.Role.CLIENT,
                        email=cd.get("email") or "",
                        phone_number=profile_phone,
                        profile_phone_number=profile_phone,
                        account_type=profile_form.cleaned_data["account_type"],
                        contact_person=profile_form.cleaned_data.get("contact_person") or "",
                        address=profile_form.cleaned_data["address"],
                        default_destination=profile_form.cleaned_data.get("default_destination") or None,
                        company_name=profile_form.cleaned_data.get("company_name") or None,
                        tax_id=profile_form.cleaned_data.get("tax_id") or None,
                    )
                    saved_profile = _linked_client_profile(created_user)
                    linked_orders = (
                        link_walk_in_orders_to_client_profile(profile=saved_profile, phone_number=profile_phone)
                        if saved_profile is not None
                        else 0
                    )
                    redirect_response = _redirect_next_or(request, "tenant_user_list")
                    if next_url:
                        if password_generated:
                            messages.success(
                                request,
                                _(
                                    "Client created. Temporary password: %(pwd)s — copy it now; "
                                    "the user can change it later."
                                )
                                % {"pwd": password},
                            )
                        else:
                            messages.success(request, _("Client created."))
                        if linked_orders:
                            messages.success(request, _("Matching walk-in orders were linked by phone number."))
                        return redirect_response
                    if password_generated:
                        messages.success(
                            request,
                            _(
                                "Client created. Temporary password: %(pwd)s — copy it now; "
                                "the user can change it later."
                            )
                            % {"pwd": password},
                        )
                    else:
                        messages.success(request, _("Client created."))
                    if linked_orders:
                        messages.success(request, _("Matching walk-in orders were linked by phone number."))
                    return redirect("tenant_user_edit", pk=created_user.pk)

                saved_profile = _save_client_profile(profile_instance, profile_form.cleaned_data)
                linked_orders = link_walk_in_orders_to_client_profile(
                    profile=saved_profile,
                    phone_number=profile_phone,
                )
                if user is not None and cred_form:
                    cd = cred_form.cleaned_data
                    update_user_credentials(
                        user,
                        username=cd["username"],
                        email=cd.get("email") or "",
                        phone_number=profile_phone,
                        password=(cd.get("new_password1") or "").strip(),
                    )
                if user is not None and getattr(user, "role", "") == User.Role.WALKIN:
                    messages.success(request, "Walk-in prospect updated.")
                else:
                    messages.success(request, "Client updated.")
                if linked_orders:
                    messages.success(request, _("Matching walk-in orders were linked by phone number."))
                if saved_profile.pk and not next_url:
                    return redirect("client_profile_detail", pk=saved_profile.pk)
                return _redirect_next_or(request, "tenant_user_list")
    else:
        profile_form = ClientProfileRegisterForm(instance=profile_instance)
        if show_credentials_form:
            cred_form = ClientUserCredentialsForm(
                initial={"username": user.username, "email": user.email or ""} if user else None,
                user_instance=user,
                require_password=require_password,
                require_contact=False,
            )

    return render(
        request,
        "users/client_profile_form.html",
        {
            "profile_form": profile_form,
            "cred_form": cred_form,
            "mode": "edit" if user or profile else "add",
            "profile": profile,
            "back_url": next_url or reverse("tenant_user_list"),
            "back_label": "Back to users",
            "show_credential_phone": False,
            "next_url": next_url,
        },
    )


def _render_staff_user_form(request, *, user: User | None = None, initial_role: str):
    next_url = _get_safe_next_url(request)
    allowed_roles = _staff_allowed_roles(request.user)
    if initial_role not in allowed_roles:
        raise PermissionDenied("You cannot create that role from this screen.")

    require_password = user is None
    if request.method == "POST":
        form = TenantManagedUserForm(
            request.POST,
            user_instance=user,
            require_password=require_password,
            allowed_roles=allowed_roles,
        )
        if form.is_valid():
            cd = form.cleaned_data
            with transaction.atomic():
                if user is None:
                    password, password_generated = _password_for_create(cd)
                    user = User.objects.create_user(
                        username=cd["username"],
                        email=cd.get("email") or "",
                        password=password,
                        phone_number=cd.get("phone_number") or "",
                        role=cd["role"],
                        is_active=cd["is_active"],
                    )
                    if password_generated:
                        messages.success(
                            request,
                            _("User created. Temporary password: %(pwd)s — copy it now; the user can change it later.")
                            % {"pwd": password},
                        )
                    else:
                        messages.success(request, _("User created."))
                else:
                    update_user_credentials(
                        user,
                        username=cd["username"],
                        email=cd.get("email") or "",
                        phone_number=cd.get("phone_number") or "",
                        password=(cd.get("new_password1") or "").strip(),
                        role=cd["role"],
                        is_active=cd["is_active"],
                    )
                    messages.success(request, "User updated.")
            if next_url:
                return redirect(next_url)
            return redirect("tenant_user_list")
    else:
        form = TenantManagedUserForm(
            initial={"role": initial_role, "is_active": True},
            user_instance=user,
            require_password=require_password,
            allowed_roles=allowed_roles,
        )

    return render(
        request,
        "users/staff_user_form.html",
        {
            "form": form,
            "managed_user": user,
            "back_url": next_url or reverse("tenant_user_list"),
            "next_url": next_url,
        },
    )


@user_management_required
def tenant_user_list_view(request):
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "all").strip().lower()
    role_filter = (request.GET.get("role") or "all").strip().upper()

    base_qs = _user_management_queryset_for(request.user)
    allowed_roles = (
        [User.Role.CLIENT, User.Role.WALKIN]
        if not can_manage_tenant_users(request.user)
        else [
            User.Role.OWNER,
            User.Role.ADMIN,
            User.Role.MANAGER,
            User.Role.OPERATOR,
            User.Role.CLIENT,
            User.Role.WALKIN,
        ]
    )
    if role_filter != "ALL" and role_filter not in allowed_roles:
        role_filter = "ALL"
    if status not in {"all", "active", "inactive"}:
        status = "all"

    qs = base_qs
    if role_filter != "ALL":
        qs = qs.filter(role=role_filter)
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(phone_number__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(client_profile__company_name__icontains=q)
            | Q(client_profile__contact_person__icontains=q)
        )

    role_filters = [{"value": "ALL", "label": "All"}] + [
        {"value": role, "label": User.Role(role).label} for role in allowed_roles
    ]
    counts = {
        "all": base_qs.count(),
        "active": base_qs.filter(is_active=True).count(),
        "inactive": base_qs.filter(is_active=False).count(),
    }
    user_rows = []
    for managed_user in qs:
        try:
            profile = managed_user.client_profile
        except ClientProfile.DoesNotExist:
            profile = None
        if managed_user.role in CLIENT_MANAGEMENT_ROLES and profile is not None:
            display_name = profile.get_full_name()
            secondary_text = profile.contact_person or profile.company_name or ""
            legacy_detail_url = reverse("client_profile_detail", kwargs={"pk": profile.pk})
        else:
            display_name = managed_user.get_full_name() or managed_user.username
            secondary_text = managed_user.username
            legacy_detail_url = ""
        user_rows.append(
            {
                "user": managed_user,
                "profile": profile,
                "display_name": display_name,
                "secondary_text": secondary_text,
                "edit_url": (
                    reverse("tenant_user_edit", kwargs={"pk": managed_user.pk})
                    if can_edit_user(request.user, managed_user)
                    else ""
                ),
                "legacy_detail_url": legacy_detail_url,
            }
        )

    # Include user-less ClientProfiles (visible to OWNER, ADMIN, MANAGER)
    client_rows = []
    if can_manage_client_accounts(request.user):
        cp_qs = ClientProfile.objects.filter(user__isnull=True).order_by("company_name", "contact_person")
        if role_filter in {"CLIENT", "WALKIN", "ALL"}:
            if q:
                cp_qs = cp_qs.filter(
                    Q(company_name__icontains=q)
                    | Q(contact_person__icontains=q)
                    | Q(phone_number__icontains=q)
                    | Q(tax_id__icontains=q)
                )
            for profile in cp_qs:
                client_rows.append({
                    "profile": profile,
                    "display_name": profile.get_full_name(),
                    "secondary_text": profile.contact_person or "",
                    "phone": profile.phone_number or "—",
                    "detail_url": reverse("client_profile_detail", kwargs={"pk": profile.pk}),
                })

    return render(
        request,
        "users/user_management_list.html",
        {
            "user_rows": user_rows,
            "client_rows": client_rows,
            "q": q,
            "status_filter": status,
            "role_filter": role_filter,
            "role_filters": role_filters,
            "count_all": counts["all"] + len(client_rows),
            "count_active": counts["active"],
            "count_inactive": counts["inactive"],
            "creatable_roles": creatable_roles_for(request.user),
        },
    )


@user_management_required
def tenant_user_create_view(request, role: str):
    requested_role = (role or "").upper()
    if requested_role not in {choice[0] for choice in User.Role.choices}:
        raise Http404()
    if not can_create_role(request.user, requested_role):
        raise PermissionDenied()
    if requested_role == User.Role.CLIENT:
        return _render_client_account_form(request)
    return _render_staff_user_form(request, initial_role=requested_role)


@user_management_required
def tenant_user_edit_view(request, pk: int):
    managed_user = get_object_or_404(User.objects.select_related("client_profile"), pk=pk)
    if not can_edit_user(request.user, managed_user):
        raise PermissionDenied()
    if managed_user.role in CLIENT_MANAGEMENT_ROLES:
        return _render_client_account_form(
            request, user=managed_user, profile=getattr(managed_user, "client_profile", None)
        )
    return _render_staff_user_form(request, user=managed_user, initial_role=managed_user.role)


@client_account_required
def client_profile_list_view(request):
    q = request.GET.get("q", "").strip()
    status = (request.GET.get("status") or "all").strip().lower()
    if status not in ("all", "active", "archived"):
        status = "all"

    manageable_qs = ClientProfile.objects.select_related("user").filter(
        Q(user__isnull=True) | Q(user__role__in=CLIENT_MANAGEMENT_ROLES)
    )
    qs = manageable_qs.order_by("-created_at")
    if q:
        qs = qs.filter(
            Q(company_name__icontains=q)
            | Q(contact_person__icontains=q)
            | Q(phone_number__icontains=q)
            | Q(default_destination__icontains=q)
            | Q(user__username__icontains=q)
            | Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
        )
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "archived":
        qs = qs.filter(is_active=False)

    counts = manageable_qs.aggregate(
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
    u = profile.user
    if u is not None and u.role not in CLIENT_MANAGEMENT_ROLES:
        raise PermissionDenied("This account cannot be managed from the client list.")


@client_account_required
def client_profile_detail_view(request, pk):
    profile = get_object_or_404(ClientProfile.objects.select_related("user"), pk=pk)
    _assert_staff_may_manage_client_profile(profile)
    return render(request, "users/client_profile_detail.html", {"profile": profile})


@client_account_required
def client_profile_add_view(request):
    return _render_client_account_form(request)


@client_account_required
def client_profile_edit_view(request, pk):
    profile = get_object_or_404(ClientProfile.objects.select_related("user"), pk=pk)
    _assert_staff_may_manage_client_profile(profile)
    return _render_client_account_form(request, user=profile.user, profile=profile)


@client_account_required
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


@client_account_required
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
