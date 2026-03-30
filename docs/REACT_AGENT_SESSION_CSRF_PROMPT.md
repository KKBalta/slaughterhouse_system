# Copy-paste prompt: React client + Django session auth (multi-tenant)

Paste the block below into your React/frontend coding agent. It encodes the **exact** API contract for this backend.

---

## Prompt (for the agent)

You are implementing or fixing **browser session authentication** against a **Django** backend that uses **django-tenants** and **cookie sessions** (`sessionid`). Follow these rules **literally**; violating them causes **401 on `GET /api/v1/auth/me/`** even after a successful login.

### Two different API origins (non-negotiable)

1. **Public API host** — used **only** for tenant discovery by email.  
   Example dev: `http://api.carnitrack.localhost:8000`  
   Example: `POST /api/v1/auth/discover-tenants/` with JSON `{ "email": "user@example.com" }`.  
   This route is **csrf_exempt**; you do **not** need `GET /csrf/` on this host for discovery.

2. **Tenant API host** — the **`api_base_url`** returned **inside each item** of `discover-tenants` response (e.g. `http://dev.localhost:8000`, `http://farm1.localhost:8000`).  
   You **must** use this origin for:
   - `GET /api/v1/auth/csrf/`
   - `POST /api/v1/auth/login/`
   - `GET /api/v1/auth/me/`
   - `POST /api/v1/auth/logout/`

**Never** call `GET /api/v1/auth/me/` on the **public** host after logging in on a **tenant** host. The session lives in the **tenant** database schema and the `sessionid` cookie is scoped to the **tenant host**. The public host has **no** tenant user session; the backend may return **401** with `code: "tenant_session_wrong_host"` if you do.

**401 JSON bodies** (use `response.json().code` in the SPA):

| `code` | Meaning | Fix |
|--------|---------|-----|
| `tenant_session_wrong_host` | `/me/` was called on the **public** host (e.g. `api.carnitrack.localhost:8000`). | Use **only** the chosen tenant’s `api_base_url` for `/me/` — do not reuse one env var for both discovery and session. |
| `no_session_cookie` | Tenant host is correct but **no `sessionid`** arrived on the request. | Use `credentials: "include"`; if login returned `session_pending`, `window.location = session_bootstrap_url` before `/me/`; see SameSite/CORS in `docs/EMAIL_FIRST_LOGIN.md`. |

### `fetch` defaults break auth

- Default `fetch` uses **`credentials: "omit"`**. For every request to the **tenant** `api_base_url` that participates in the session (CSRF, login, me, logout), use **`credentials: "include"`** (or Axios **`withCredentials: true`**).

### CSRF on tenant POSTs

1. `GET {api_base_url}/api/v1/auth/csrf/` with `credentials: "include"`.
2. Parse JSON `{ "csrfToken": "..." }`.
3. `POST` login/logout with header **`X-CSRFToken: <csrfToken>`**, `Content-Type: application/json`, `credentials: "include"`.

If the browser never stores the CSRF cookie (wrong credentials mode), login returns **403** CSRF errors.

### Recommended client state shape

After discovery, persist **`tenantApiBaseUrl`** (the chosen tenant’s `api_base_url`, no trailing slash ambiguity — normalize once). All session calls use:

`const url = \`${tenantApiBaseUrl}/api/v1/auth/...\``

Do **not** reuse a single global `API_URL` pointing at the public host for `/me/` or `/login/`.

### Cross-origin SPA (e.g. app on `:3000`, API on `:8000`)

List **every** SPA origin in Django **`CORS_ALLOWED_ORIGINS`** and **`CSRF_TRUSTED_ORIGINS`**. For cross-site cookies, the backend often needs **`SESSION_COOKIE_SAMESITE=none`** and **`CSRF_COOKIE_SAMESITE=none`** in dev (with **`SESSION_COOKIE_SECURE`** rules as documented). See `docs/EMAIL_FIRST_LOGIN.md`.

### Dev trap: `localhost` vs `*.localhost` (login OK, `/me/` still 401)

Runtime evidence: `/me/` can hit the **correct** tenant host (`dev.localhost:8000`) and still see **no `sessionid`** if the SPA runs on **`http://localhost:3000`** while the API is **`http://dev.localhost:8000`**. Those are **different sites**; browsers may not send or persist cookies the way you expect.

**Do this:** Open the app at the **same tenant hostname** as the API, e.g. **`http://dev.localhost:3000`** (match `web_app_base_url` / tenant subdomain from discover-tenants). Configure Vite/Webpack `server.host` / `allowedHosts` so `dev.localhost` resolves and is allowed.

**Alternatives:** Proxy API through the dev server so the browser only talks to one origin, or use a tunnel that keeps SPA and API on one host.

### Minimal tenant login sequence (TypeScript)

```ts
const tenantBase = selectedTenant.api_base_url.replace(/\/$/, "");

const csrfRes = await fetch(`${tenantBase}/api/v1/auth/csrf/`, {
  credentials: "include",
});
const { csrfToken } = await csrfRes.json();

const loginRes = await fetch(`${tenantBase}/api/v1/auth/login/`, {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": csrfToken,
  },
  body: JSON.stringify({ email: "user@example.com", password: "..." }),
});
const loginJson = await loginRes.json();
if (loginJson.session_pending && loginJson.session_bootstrap_url) {
  window.location.assign(loginJson.session_bootstrap_url);
  return;
}

const meRes = await fetch(`${tenantBase}/api/v1/auth/me/`, {
  credentials: "include",
});
// expect 200 JSON { authenticated: true, user: { ... } }
```

---

## Short reference (human)

| Step | Host | Endpoint |
|------|------|----------|
| Discover | **Public** | `POST .../api/v1/auth/discover-tenants/` |
| CSRF, login, me, logout | **Tenant `api_base_url`** | `/api/v1/auth/csrf/`, `login/`, `me/`, `logout/` |

Further detail: `docs/EMAIL_FIRST_LOGIN.md`.
