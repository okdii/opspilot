# Module Spec 01 — Authentication

**Version:** 1.4  
**Date:** 2026-05-29  
**PRD Reference:** §5.1  
**Status:** Ready for Development

---

## 1. Overview

Authentication is the entry point to OpsPilot. Supports multiple accounts with three roles: Admin, Operator, and Viewer. The module covers:

- Setup page (first install only — register admin account)
- Login page (every visit after setup)
- JWT httpOnly cookie session
- Logout
- WebSocket ticket issuance
- 401 auto-redirect (token expiry)

---

## 2. Screens

### 2.1 Setup Page (First Install Only)

**Route:** `/setup`  
**Access:** Public — but only reachable when **no admin account exists** in the database. Once an account is created, this route permanently redirects to `/login`.

---

#### 2.1.1 When It Appears

On fresh install, the backend has an empty database. Any route the user visits (`/`, `/login`, `/anything`) is intercepted by the backend and returns a flag indicating setup is required. The frontend router redirects to `/setup`.

Backend check: `GET /api/setup/status` returns `{ "setup_required": true }` when no admin exists. Frontend calls this on app mount before deciding which route to render.

---

#### 2.1.2 Layout

```
┌──────────────────────────────────────────────┐
│                                              │
│              [OpsPilot Logo]                 │
│              OpsPilot                        │
│           Welcome — Let's get started        │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │         CREATE ADMIN ACCOUNT           │  │
│  │                                        │  │
│  │  Username                              │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │                                  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  Password                              │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │                              👁  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  Confirm Password                      │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │                              👁  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │         Create Account           │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  └────────────────────────────────────────┘  │
│                                              │
└──────────────────────────────────────────────┘
```

Same full-screen centered layout as the login page. Dark background, single card.

---

#### 2.1.3 Form Fields

| Field | Type | Label | Placeholder | Required |
|---|---|---|---|---|
| `username` | text | Username | `Choose a username` | Yes |
| `password` | password | Password | `Min 8 characters` | Yes |
| `confirm_password` | password | Confirm Password | `Repeat password` | Yes |

Both password fields have show/hide eye toggle. Trim whitespace on submit.

---

#### 2.1.4 Validation Rules

Runs on submit only.

| Field | Rule | Error message |
|---|---|---|
| `username` | Required | `Username is required` |
| `username` | Min 3 characters | `Username must be at least 3 characters` |
| `username` | Alphanumeric + underscore only | `Username can only contain letters, numbers, and underscores` |
| `password` | Required | `Password is required` |
| `password` | Min 8 characters | `Password must be at least 8 characters` |
| `confirm_password` | Required | `Please confirm your password` |
| `confirm_password` | Must match `password` | `Passwords do not match` |

---

#### 2.1.5 Submit Button

| State | Appearance |
|---|---|
| Default | Primary colour, full width, `Create Account` label |
| Loading | Spinner, disabled |

---

#### 2.1.6 Successful Setup Flow

1. Admin fills in fields and clicks `Create Account`
2. Button shows spinner
3. Backend creates admin account (bcrypt password), creates `Session` row, issues JWT cookie
4. Response: `200 { "ok": true }`
5. Frontend redirects directly to `/` (dashboard) — no separate login step
6. `/setup` is now permanently inaccessible

---

#### 2.1.7 Error States

**Username already taken (should not happen in practice — only one account — but defensive):**
- Red banner: `This username is already taken`

**Setup already completed (someone hits `/setup` after account exists):**
- Backend returns `403`
- Frontend redirects to `/login` immediately

**Network / server error:**
- Red banner: `Unable to connect. Please try again.`

---

### 2.2 Login Page

**Route:** `/login`  
**Access:** Public (unauthenticated only — redirect to `/` if already authenticated)

---

#### 2.2.1 Layout

```
┌──────────────────────────────────────────────┐
│                                              │
│              [OpsPilot Logo]                 │
│              OpsPilot                        │
│         Server Monitoring Dashboard          │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │              LOGIN                     │  │
│  │                                        │  │
│  │  Username                              │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │                                  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  Password                              │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │                              👁  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │           Sign In                │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  └────────────────────────────────────────┘  │
│                                              │
└──────────────────────────────────────────────┘
```

- Page is **full-screen centered**, dark background (Vuestic dark theme)
- Login card: fixed width `400px`, centered vertically and horizontally
- Logo above card, not inside it
- No nav bar, no sidebar — isolated page

---

#### 2.2.2 Form Fields

| Field | Type | Label | Placeholder | Required | Autocomplete |
|---|---|---|---|---|---|
| `username` | text input | Username | `Enter username` | Yes | `username` |
| `password` | password input | Password | `Enter password` | Yes | `current-password` |

- **Password field**: has a show/hide toggle icon (eye icon) on the right side — clicking toggles `type` between `password` and `text`
- Both fields: trim whitespace on submit (not on change)
- Both fields: no character limit enforced on frontend (backend handles it)

---

#### 2.2.3 Validation Rules

Validation runs **on submit only** (not on change or blur — avoids premature red state).

| Field | Rule | Error message |
|---|---|---|
| `username` | Required (non-empty after trim) | `Username is required` |
| `password` | Required (non-empty after trim) | `Password is required` |

Inline error messages appear **below** the relevant field in red (`va-input` error state).

---

#### 2.2.4 Submit Button

| State | Appearance | Behaviour |
|---|---|---|
| Default | Primary colour, full width, `Sign In` label | Submits form |
| Loading | Spinner replaces label, disabled | Shown from submit until API responds |
| Disabled | Greyed out | Never disabled pre-submit — only during loading |

- Button is full width of the card (not a narrow button)
- Pressing **Enter** in either field submits the form (same as clicking the button)

---

#### 2.2.5 Error States

**Wrong credentials (HTTP 401 from backend):**

```
┌─────────────────────────────────────────────┐
│  ⚠  Invalid username or password            │
└─────────────────────────────────────────────┘
```

- Shown as a red alert banner **inside the card**, above the fields
- Password field is **cleared** on 401; username field retains its value
- Focus moves to the password field
- The generic message is intentional — do not distinguish "user not found" from "wrong password"

**Network / server error (non-401, e.g. 500, timeout):**

```
┌─────────────────────────────────────────────┐
│  ⚠  Unable to connect. Please try again.   │
└─────────────────────────────────────────────┘
```

- Same red banner position
- Password field cleared, focus returns to username

---

#### 2.2.6 Successful Login Flow

1. User submits valid credentials
2. Frontend shows loading spinner on button
3. Backend authenticates, creates `Session` row, issues JWT (`jti` in payload), sets `Set-Cookie: opspilot_jwt=<token>; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=86400`
4. Backend response body: `{ "ok": true }`
5. Frontend navigates to `/` (dashboard)

---

### 2.3 Invite Acceptance Page

**Route:** `/invite/:token`  
**Access:** Public — no authentication required

---

#### 2.3.1 Layout

```
┌──────────────────────────────────────────────┐
│                                              │
│              [OpsPilot Logo]                 │
│              OpsPilot                        │
│    You've been invited to join OpsPilot      │
│         Role: Operator                       │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │         CREATE YOUR ACCOUNT            │  │
│  │                                        │  │
│  │  Username                              │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │                                  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  Password                              │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │                              👁  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  Confirm Password                      │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │                              👁  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │         Create Account           │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  └────────────────────────────────────────┘  │
│                                              │
└──────────────────────────────────────────────┘
```

- Subtitle shows the assigned role: `Role: Operator` or `Role: Viewer`
- Same layout and field rules as the setup page

---

#### 2.3.2 Page Load Behaviour

On mount, frontend calls `GET /api/invite/:token` to validate the token before showing the form:

| Backend response | Frontend behaviour |
|---|---|
| `200 { role: "operator", email: "..." }` | Show form with role label pre-filled |
| `404` — token not found | Show error card: "This invite link is invalid." |
| `410` — token expired | Show error card: "This invite link has expired. Ask your admin to resend it." |
| `409` — already accepted | Show error card: "This invite has already been used. Please log in." with link to `/login` |

No form is shown for invalid/expired/used tokens — just the error card.

---

#### 2.3.3 Form Fields & Validation

Same fields and rules as the setup page (§2.1.3 and §2.1.4):
- Username (required, min 3 chars, alphanumeric + underscore)
- Password (required, min 8 chars)
- Confirm password (must match)

---

#### 2.3.4 Successful Acceptance Flow

1. Invitee submits the form
2. Backend validates token, creates `User` record with the invite's assigned role, sets `Invite.accepted_at = now()`, issues JWT cookie
3. Response: `200 { "ok": true }`
4. Frontend redirects to `/` (dashboard) — logged in immediately

---

#### 2.3.5 Error States

| Error | Message |
|---|---|
| Username already taken | `This username is already taken` |
| Token expired (race: expired between load and submit) | `This invite link has expired. Ask your admin to resend it.` |
| Network error | `Unable to connect. Please try again.` |

---

### 2.4 No Forgot Password Screen

- No `/forgot-password` route — password reset is done only via `Settings → Change Password` when authenticated
- If the admin is locked out (lost password), recovery is via the CLI: `docker compose exec backend python -m app.cli reset-password` — documented in deployment runbook, not in UI

---

## 3. Session & Token Behaviour

### 3.1 JWT Cookie

| Property | Value |
|---|---|
| Cookie name | `opspilot_jwt` |
| Storage | httpOnly, Secure, SameSite=Strict |
| Lifetime | 24 hours (`Max-Age=86400`) |
| Payload claims | `sub` (user id), `jti` (UUID — matches Session table), `iat`, `exp` |
| Refresh | None in v1 — on expiry frontend gets 401 and redirects to `/login` |

The cookie is sent automatically by the browser on every request to the same origin — no manual `Authorization: Bearer` header handling needed on the frontend.

### 3.2 Authenticated Request Validation (Backend)

On every protected API request, backend:
1. Reads `opspilot_jwt` cookie
2. Verifies JWT signature and `exp`
3. Looks up `jti` in `Session` table — rejects if `revoked = true` or `expires_at < now()`
4. Returns **401** if any check fails

Frontend intercepts all 401 responses globally (Axios interceptor) and redirects to `/login` with no additional user prompt.

### 3.3 Token Expiry During Active Session

If the JWT expires while the admin is actively using the dashboard:
- The next API call returns 401
- Global Axios interceptor catches it
- Pinia auth store is cleared
- User is redirected to `/login?reason=expired`
- Login page shows a subtle info banner: `"Your session has expired. Please sign in again."`
- After successful re-login: redirect to `/` (not back to the page that triggered the 401 — to avoid partial state issues)

---

## 4. Logout

### 4.1 Trigger Points

| Location | Element |
|---|---|
| Sidebar (bottom) | Avatar / username with `Sign Out` menu item |
| Top navigation bar | User menu dropdown → `Sign Out` |

No confirmation dialog — logout is immediate.

### 4.2 Logout Flow

1. User clicks `Sign Out`
2. Frontend calls `POST /api/auth/logout`
3. Backend marks `Session.revoked = true` for the current `jti`
4. Backend clears the cookie: `Set-Cookie: opspilot_jwt=; Max-Age=0; HttpOnly; ...`
5. Frontend clears Pinia auth store
6. Frontend navigates to `/login`

If the logout API call fails (network error): frontend still clears local state and redirects to `/login` — logout must never be blocked by a network error.

---

## 5. WebSocket Authentication

### 5.1 Flow

WebSocket connections require a short-lived ticket because httpOnly cookies are not accessible to JavaScript and the WS upgrade request may not reliably carry cookies in all browser/proxy combinations.

```
Frontend                          Backend
   │                                 │
   │  GET /api/ws-ticket             │
   │ ────────────────────────────►   │
   │  (JWT cookie sent automatically)│
   │                                 │  validates JWT
   │                                 │  generates ticket UUID
   │                                 │  stores {ticket_uuid: {user_id, exp: now+30s}} in memory dict
   │  200 { "ticket": "<uuid>" }     │
   │ ◄────────────────────────────   │
   │                                 │
   │  WS upgrade: /ws?ticket=<uuid>  │
   │ ────────────────────────────►   │
   │                                 │  validates ticket (exists, not expired, not used)
   │                                 │  deletes ticket immediately (single-use)
   │  101 Switching Protocols        │
   │ ◄────────────────────────────   │
   │                                 │
   │  [WebSocket connection open]    │
```

### 5.2 Ticket Properties

| Property | Value |
|---|---|
| Format | UUID v4 |
| TTL | 30 seconds from issuance |
| Use | Single-use — deleted immediately after successful WS upgrade |
| Storage | In-process dict on backend (not DB — no persistence needed) |
| Rejection | Expired, unknown, or already-used ticket → 401, WS upgrade rejected |

### 5.3 WS Reconnect on Disconnect

If the WebSocket drops (network blip, backend restart):
1. Frontend detects `onclose` event
2. Show subtle reconnecting indicator in the UI (immediately)
3. Wait 2 seconds before reconnect attempt
4. Call `GET /api/ws-ticket`:
   - If **401** → session has expired — stop reconnecting, clear auth store, redirect to `/login?reason=expired`
   - If **200** → proceed with reconnect
5. Reconnect WS with new ticket
6. Re-subscribe to all active channels (re-send `subscribe` messages for the currently viewed server)

Max reconnect attempts: unlimited with exponential backoff (2s → 4s → 8s → … capped at 30s between attempts).

### 5.4 WebSocket Channel Authorization

After the WS connection is established, the backend validates each subscription message before sending any data:

| Subscribe action | Authorization check |
|---|---|
| `subscribe_org` | User must have access to the `org_id`: Admins always pass; Members must have a `UserOrganization` row for that org. Unauthorized → push `{ "event": "error", "code": "forbidden", "message": "Access denied to org" }` |
| `subscribe` (server) | Server must belong to an org the user has access to. |
| `subscribe_rotation` | `user.role` must be `'admin'`. Non-admin connections receive `{ "event": "error", "code": "forbidden" }` and no rotation events are pushed. |

The WS connection itself is authenticated at upgrade time (§5.1). Channel-level authorization is enforced on each `subscribe` message independently.

---

## 6. Route Guards (Frontend)

On app mount, frontend calls `GET /api/setup/status` first to determine which mode to enter:

```
App mounts
    │
    ▼
GET /api/setup/status
    │
    ├── setup_required: true  →  redirect to /setup (regardless of current route)
    │
    └── setup_required: false
            │
            ▼
        GET /api/auth/me
            │
            ├── 200 (valid session)  →  render requested route
            │
            └── 401 (no session)    →  redirect to /login
```

| Route pattern | Guard behaviour |
|---|---|
| `/setup` | Accessible only when `setup_required: true`; redirects to `/login` once setup complete |
| `/login` | Redirect to `/` if already authenticated |
| `/invite/:token` | Always public — authenticated users are not redirected away (they may want to accept on a different account) |
| All other routes | Redirect to `/login` if not authenticated; redirect to `/setup` if setup not complete |

**Role-based route guards** — certain pages are additionally restricted by role:

| Route | Minimum role required |
|---|---|
| `/settings/*` | Admin only → redirect to `/` with toast "Access denied" |
| `/profile` | Any authenticated role |
| All other routes | Any authenticated role (Admin / Operator / Viewer) |

The role is read from the Pinia auth store (`user.role`). The backend enforces permissions independently — the frontend guard is for UX only.

---

## 7. API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/setup/status` | Public | Returns whether initial setup is needed |
| `POST` | `/api/setup/register` | Public (setup mode only) | Create the admin account |
| `POST` | `/api/auth/login` | Public | Submit credentials, receive JWT cookie |
| `POST` | `/api/auth/logout` | Required | Revoke session, clear cookie |
| `GET` | `/api/auth/me` | Required | Returns current user info including role |
| `GET` | `/api/ws-ticket` | Required | Issue one-time WebSocket upgrade ticket |
| `GET` | `/api/invite/:token` | Public | Validate invite token, return role + email |
| `POST` | `/api/invite/:token/accept` | Public | Accept invite, create account, issue JWT cookie |
| `PATCH` | `/api/auth/password` | Any role | Change own password (requires current password) |

### GET /api/setup/status

**Success response (200):**
```json
{ "setup_required": true }
```
Returns `false` once admin account exists. Called on every app mount.

### POST /api/setup/register

**Request body:**
```json
{
  "username": "admin",
  "password": "mypassword"
}
```

**Success response (200):**
```json
{ "ok": true }
```
Cookie set in response headers — admin is auto-logged in.

**Error responses:**
- `403` — setup already completed (account exists)
- `422` — validation error (password too short, etc.)

### POST /api/auth/login

**Request body:**
```json
{
  "username": "admin",
  "password": "mypassword"
}
```

**Success response (200):**
```json
{ "ok": true }
```
Cookie set in response headers.

**Error responses:**
- `401` — invalid credentials (generic)
- `429` — rate limit exceeded
- `422` — missing/malformed request body

### POST /api/auth/logout

**Request:** No body (cookie sent automatically)  
**Success response (204):** No content  
Cookie cleared in response headers.

### GET /api/auth/me

**Success response (200):**
```json
{
  "id": "uuid",
  "username": "admin",
  "role": "admin",
  "orgs": [
    { "id": "uuid", "name": "Acme Corp", "slug": "acme-corp", "my_role": "admin" },
    { "id": "uuid", "name": "Client B",  "slug": "client-b",  "my_role": "admin" }
  ]
}
```
- Admin: `role = 'admin'`, `orgs` contains all organizations with `my_role = 'admin'`
- Member: `role = 'member'`, `orgs` contains only their assigned organizations with their per-org role

**Error:** `401` — session expired or revoked

### GET /api/invite/:token

**Success response (200):**
```json
{
  "email": "teammate@example.com",
  "role": "operator"
}
```

**Error responses:**
- `404` — token not found
- `410` — token expired
- `409` — already accepted

### POST /api/invite/:token/accept

**Request body:**
```json
{
  "username": "teammate",
  "password": "mypassword"
}
```

**Success response (200):**
```json
{ "ok": true }
```
Cookie set in response headers — user is auto-logged in.

**Error responses:**
- `404` / `410` / `409` — same as GET (token invalid/expired/used)
- `422` — username taken or validation error

### GET /api/ws-ticket

**Success response (200):**
```json
{
  "ticket": "550e8400-e29b-41d4-a716-446655440000"
}
```
**Error:** `401` — not authenticated

---

## 8. Pinia Auth Store (`useAuthStore`)

| State | Type | Description |
|---|---|---|
| `isAuthenticated` | `boolean` | True after successful login / `/me` check |
| `setupRequired` | `boolean` | True when no admin account exists — drives route guard |
| `user` | `{ id, username, role }` or `null` | `role` is `'admin'` or `'member'` |
| `orgs` | `{ id, name, slug, myRole }[]` | Orgs the user has access to (all orgs for Admin; assigned orgs for Member). `myRole` is `'admin'` / `'operator'` / `'viewer'` per org |
| `activeOrg` | `{ id, name, slug }` or `null` | Currently selected org — persisted in `localStorage` |

| Getter | Returns |
|---|---|
| `isAdmin` | `user.role === 'admin'` (global admin) |
| `activeOrgRole` | `myRole` from `orgs` for the `activeOrg` (or `'admin'` if global admin) |
| `canEdit` | `isAdmin` |
| `canActOnAlerts` | `isAdmin \|\| activeOrgRole === 'operator'` |

| Action | Description |
|---|---|
| `checkSetupStatus()` | Calls GET `/api/setup/status`, sets `setupRequired` |
| `register(username, password)` | Calls POST `/api/setup/register`, auto-logs in on success |
| `login(username, password)` | Calls POST `/api/auth/login`, sets state on success |
| `logout()` | Calls POST `/api/auth/logout`, clears state, redirects |
| `fetchMe()` | Calls GET `/api/auth/me`, used on app mount |
| `acceptInvite(token, username, password)` | Calls POST `/api/invite/:token/accept`, auto-logs in on success |

---

## 9. Change Password

All roles (Admin, Operator, Viewer) can change their own password. Since `/settings/*` is Admin-only, password change is exposed via a dedicated route accessible to all authenticated users.

**Route:** `/profile` — accessible to all roles  
**Location in UI:** User menu dropdown (top nav) → `My Profile` — shows username, role badge, and change password form

**Endpoint:** `PATCH /api/auth/password`  
**Auth:** Any authenticated role  
**Body:** `{ "current_password": "...", "new_password": "..." }`  
**Validation:** `new_password` min 8 characters; `current_password` must be correct (returns `401` if wrong — does not reveal whether account exists)

The full Profile page spec (layout, fields, error states) is covered in the **Settings module spec (spec 11)**. The endpoint is listed here because it is part of the auth surface.

**Admin password reset for locked-out users:** Admin can reset any team member's password from `Settings → Team` without knowing their current password. The reset generates a new temporary password displayed once — the user must change it on next login. This is also covered in spec 11.

---

## 10. Security Notes for Implementation

| Concern | Implementation |
|---|---|
| Brute force | Backend rate-limits `/api/auth/login` to **10 attempts per IP per 15 minutes** — returns `429 Too Many Requests` with `Retry-After` header. Frontend shows: `"Too many attempts. Try again in X minutes."` |
| Cookie flags | `HttpOnly`, `Secure`, `SameSite=Strict` — no JavaScript cookie access |
| Password storage | bcrypt with cost factor ≥ 12 |
| JWT secret | Long random string from env var `OPSPILOT_JWT_SECRET` — abort on startup if absent (add to required env vars list) |
| Ticket storage | In-memory dict — entries auto-expire after 30s; backend sweeps expired tickets every 60s to prevent unbounded growth |
| Session table | Nightly APScheduler job cleans up `expires_at < now()` rows |

---

## 11. Empty / Edge States Summary

| Scenario | Behaviour |
|---|---|
| Fresh install — no admin account | Any route → redirect to `/setup` |
| Admin visits `/setup` after account exists | Redirect to `/login` immediately (403 from backend) |
| Admin visits `/login` while already logged in | Redirect to `/` immediately |
| Admin visits any protected route without cookie | Redirect to `/login` |
| JWT expires mid-session | Global 401 interceptor → redirect to `/login?reason=expired` |
| Backend down on login or setup attempt | Generic "Unable to connect" error in card |
| WS ticket expired before use | WS upgrade rejected; frontend retries ticket + connect flow |
| Rate limit hit on login (429) | Banner in card: "Too many attempts. Try again in X minutes." |
| Passwords don't match on setup | Inline error under confirm field — no API call made |
| Invite token expired on page load | Error card: "This invite link has expired" — no form shown |
| Invite token already used | Error card: "This invite has already been used. Please log in." |
| Authenticated user visits `/invite/:token` | Form is still shown — they may want to accept on a different account |
| Viewer tries to access `/settings` | Redirect to `/` with toast: "Access denied" |
| Operator tries to access `/settings` | Redirect to `/` with toast: "Access denied" |
| WS reconnect — `GET /api/ws-ticket` returns 401 | Stop reconnecting, clear auth store, redirect to `/login?reason=expired` |
| Operator or Viewer wants to change password | `/profile` route — accessible to all roles via user menu |
| Admin resets a team member's password | Via `Settings → Team` — generates temporary password, covered in spec 11 |

---

## 12. API Error Response Format

All API endpoints across all modules return errors using a consistent JSON envelope:

```json
{ "error": "error_code", "message": "Human-readable description." }
```

| HTTP Status | When used |
|---|---|
| `400` | Malformed request body or missing required field |
| `401` | Not authenticated, or credentials rejected |
| `403` | Authenticated but not authorised for this resource |
| `404` | Resource not found |
| `409` | Conflict (e.g., username taken, sole-operator guard) |
| `410` | Resource expired (e.g., invite token) |
| `422` | Validation error (field constraint violation) |
| `429` | Rate limit hit — includes `Retry-After` header |
| `500` | Unexpected server error |

`error_code` is a machine-readable snake_case string (e.g., `invalid_credentials`, `setup_complete`, `sole_operator`). `message` is human-readable. This format applies uniformly across all modules (specs 01–11).
