# React agent prompt: tenant registration + post-approval login

Give this document to a coding agent (or paste as a **user** message with “implement according to this spec”) when building the CarniTrack **tenant registration** UI and API wiring.

## Context

- Backend: **Django**, multi-tenant (`django-tenants`). **No Firebase Auth** — tenant users use **Django sessions** on the **tenant API host**.
- **Public API** (registration, discover-tenants): e.g. `https://api.carnitrack.samperlabs.com`.
- **Tenant API** (login, `/me`, app APIs): host comes from **discover-tenants** as `api_base_url`.
- **Slug / schema name:** The backend **derives** the tenant slug from **company name** (user does **not** pick it). Keep the form **minimal and company-centric**.

## Flow to implement

1. **Registration** — User submits **company info + owner email/password**; backend stores a **pending** request.
2. **Optional status** — Poll with `id` + `status_token` if returned.
3. **Owner login** — After approval: **discover-tenants** then **login** on tenant host (`docs/EMAIL_FIRST_LOGIN.md`).
4. **Employees** — OWNER creates users with roles **ADMIN → MANAGER → OPERATOR** (and **CLIENT** if applicable) inside the app; not part of this task unless APIs exist.

---

## Task 1: Registration page (minimal fields)

**Do not** ask for a tenant slug or schema name unless the backend later adds an optional “advanced” override (default: **no slug field**).

**Required (typical contract):**

- **`company_name`** (string) — primary; used server-side to build the tenant slug.
- **`owner_email`**
- **`owner_password`** + **`owner_password_confirm`** (confirm on client only; optionally send confirm for server validation)

**Optional (only if backend documents them — prefer few fields):**

- `company_full_name`, `company_address`, `contact_phone`, `license_no`, `operation_no`, notes — align with CarniTrack `Client` / registration API.

**Client-side validation:**

- Email format.
- Password policy (length + complexity) **aligned with backend** error messages.
- Password match for confirm.
- **No** slug format validation — user does not enter slug.

**Request:**

```http
POST /api/v1/tenant-registration/
Host: api.carnitrack.samperlabs.com
Content-Type: application/json
```

Example body (exact keys **must match** backend implementation):

```json
{
  "company_name": "Örnek Gıda Sanayi A.Ş.",
  "owner_email": "owner@example.com",
  "owner_password": "…",
  "owner_password_confirm": "…"
}
```

- `credentials: "omit"` unless cookies are required.
- No Firebase tokens.

**Responses:**

- Success: `{ "id": "<uuid>", "status_token": "…", "derived_schema_preview": "ornek-gida-sanayi" }` — **if** backend returns a preview slug for UX, display it as informational (“Your workspace address will look like …”); **backend is authoritative**.
- `400`: field errors — display per field.
- `429`: rate limited.

---

## Task 2: Optional status page

Poll `GET /api/v1/tenant-registration/<uuid>/` until `status` is `approved` or `rejected`. Pass the secret from registration **one** of these ways (all supported):

- Query: `?status_token=<value>` (matches the POST response field name), or `?token=<value>`
- Header: `Authorization: Bearer <value>`

---

## Task 3: Owner login (after approval)

Follow **`docs/EMAIL_FIRST_LOGIN.md`** (discover → CSRF on tenant → login with `credentials: "include"`).

**Note:** The approved owner’s role is **OWNER** (highest tenant role). App UI for “admin” features should treat **OWNER** like full tenant access where the product allows — but **tenant users never use Django `/admin/`** (that is for SamperLabs platform ops only).

---

## Task 4: Employees

Out of scope unless REST endpoints are specified. The **OWNER** (and **ADMIN**s) create **MANAGER** / **OPERATOR** users in the product.

---

## Technical notes

- CORS / CSRF: same as `docs/REACT_AGENT_SESSION_CSRF_PROMPT.md` / `EMAIL_FIRST_LOGIN.md` for tenant login.
- Never log passwords; HTTPS in production.

## Deliverables

- Minimal registration UI (company + owner credentials + optional company details).
- Typed API helpers for registration + discover + login.
