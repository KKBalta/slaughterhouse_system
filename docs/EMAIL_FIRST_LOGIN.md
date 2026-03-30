# Email-first tenant login (frontend contract)

## Overview

1. User enters **email** on the public frontend (e.g. `https://carnitrack.samperlabs.com/signin`).
2. Frontend calls **discovery** on the **public API host** (e.g. `https://api.carnitrack.samperlabs.com`).
3. Backend returns **zero or more tenants** where that email exists as a tenant user (`users.User`). **Platform admin** accounts are **never** returned here.
4. If multiple tenants match, the user **chooses one**.
5. User enters **password**; frontend sends `POST` **only to the selected tenant’s `api_base_url`**:
   - `POST {api_base_url}/api/v1/auth/login/`
6. Session cookies are set for that **tenant host**. Subsequent API calls use that host + `credentials: "include"`.

## Discovery endpoint

- **URL:** `POST /api/v1/auth/discover-tenants/`
- **Host:** public API (`api.carnitrack.localhost:8000` in dev, `api.carnitrack.samperlabs.com` in prod).
- **Body (JSON):** `{ "email": "user@example.com" }`
- **Response (JSON):**

```json
{
  "tenants": [
    {
      "schema_name": "farm1",
      "name": "Farm One",
      "slug": "farm1",
      "primary_domain": "farm1.localhost",
      "api_base_url": "http://farm1.localhost:8000",
      "auth_login_url": "http://farm1.localhost:8000/api/v1/auth/login/",
      "web_app_base_url": "http://farm1.localhost:3000",
      "post_login_redirect_url": "http://farm1.localhost:3000/dashboard"
    }
  ]
}
```

- **`web_app_base_url`**: tenant SPA origin (often port 3000 in dev; HTTPS same host in prod).
- **`post_login_redirect_url`**: full URL to navigate after successful login (see `TENANT_LOGIN_SUCCESS_REDIRECT_PATH`). By default the base is the SPA (`web_app_base_url`); with `TENANT_POST_LOGIN_USE_API_HOST=True` the base matches `api_base_url` (e.g. `http://farm1.localhost:8000/dashboard` in dev).

- Empty or unknown email: `{ "tenants": [] }` (no user enumeration signal in message).
- **CSRF:** `POST discover-tenants` is **`csrf_exempt`** so the SPA does not need a prior **`GET /csrf/`** on the public host (cross-origin cookie bootstrap is unreliable). **Login and logout still require CSRF** (see below).

## CSRF on tenant `POST` (login / logout)

Django enforces CSRF on:

- `POST {api_base_url}/api/v1/auth/login/` (tenant host)
- `POST {api_base_url}/api/v1/auth/logout/` (tenant host)

**Not** on `POST /api/v1/auth/discover-tenants/` (public host; exempt for cross-origin ergonomics; consider rate limiting in production).

**Pattern:** for the **tenant** origin, call **`GET {api_base_url}/api/v1/auth/csrf/`** with `credentials: "include"`. The response is JSON `{ "csrfToken": "..." }` and sets the `csrftoken` cookie. Send **`X-CSRFToken`** on login/logout POSTs with **`credentials: "include"`**.

### Cross-origin pitfall (SPA on :3000, API on :8000)

`fetch` defaults to **`credentials: "omit"`**. Without **`credentials: "include"`**, the browser may not persist or send cookies for the API host, so CSRF-protected POSTs fail with **403**. Axios: **`withCredentials: true`**.

## Tenant login endpoint

- **URL:** `POST {api_base_url}/api/v1/auth/login/`
- **Body:** `{ "username": "...", "password": "..." }` or use `email` + `password` if your `User` model matches by email (field is `username` or `email` in existing handler).
- **Optional — avoid logging in twice (React + Django templates):**  
  `post_login_redirect` in the JSON body controls where `redirect_url` points:
  - **`django`** (aliases: `django_dashboard`, `api`, `api_host`) — `redirect_url` is the **Django app** on `api_base_url`, e.g. `http://farm1.localhost:8000/tr/dashboard/` (includes `LANGUAGE_CODE` prefix). Use this when users should open **server-rendered** pages with the **same session** cookie already set by the login API (no second password prompt).
  - **`spa`** (aliases: `web`, `frontend`, `react`) — `redirect_url` uses **`web_app_base_url`** (e.g. port `:3000` in dev).
  - **Omitted** — follows **`TENANT_POST_LOGIN_USE_API_HOST`** in settings (see below).
- **Success (JSON):** includes `redirect_url` so the client can `window.location.assign(redirect_url)` after login.
- Use **`credentials: "include"`** and **`X-CSRFToken`** on this POST (after tenant CSRF prefetch).

## Session check (`/me`)

- **URL:** `GET {api_base_url}/api/v1/auth/me/` — **same `api_base_url` as login**, not the public `api.*` host.
- **Fetch:** `fetch(url, { credentials: "include" })` so the session cookie is sent.
- Cross-origin (SPA on port 3000, API on 8000): browsers **do not** send `SameSite=Lax` cookies on cross-site `fetch`. Set `SESSION_COOKIE_SAMESITE=none` (and matching CSRF cookie) in dev env so the session works; list every SPA origin in `CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS`.

## Index maintenance

- Rows in `EmailTenantMembership` are updated automatically when tenant `User` records are saved or deleted.
- After deploy or data fixes, run:

```bash
python manage.py backfill_email_tenant_membership
```

## Settings

- `PUBLIC_TENANT_HTTP_PORT` (default `8000`): used when building `api_base_url` for `*.localhost` hostnames.
- `PUBLIC_TENANT_WEB_HTTP_PORT` (default `3000`): used when building `web_app_base_url` for `*.localhost` hostnames.
- `TENANT_LOGIN_SUCCESS_REDIRECT_PATH` (default `/dashboard`): path appended to the chosen base for `post_login_redirect_url` and login `redirect_url`. On the **Django** host, the URL is built as `{api_base_url}/{LANGUAGE_CODE}{path}` (i18n prefix).
- `TENANT_POST_LOGIN_USE_API_HOST` (default `False`): when `True`, default `redirect_url` uses the same origin as `api_base_url` (Django on `:8000` in local dev) instead of `web_app_base_url`. You can still override per request with `post_login_redirect` on login.
- `SESSION_COOKIE_SAMESITE` / `CSRF_COOKIE_SAMESITE`: env values `lax`, `strict`, or `none` (cross-site SPA + API in dev).
