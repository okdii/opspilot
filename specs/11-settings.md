# Spec 11 — Settings

**Version:** 1.0  
**Date:** 2026-06-01  
**Status:** Approved

---

## 1. Overview

Settings covers five distinct concerns, each in its own tab:

1. **General** — OpsPilot identity (instance name, base URL) and SMTP email configuration
2. **Team** — invite new members, manage existing team (org assignments, role changes, revocation)
3. **Retention** — TimescaleDB retention policy overrides for metrics, logs, alerts
4. **Security** — active session management (view and revoke sessions)
5. **Infrastructure** — rotate the `opspilot_writer` agent database password across all servers

The `/settings/*` route is **Admin-only**. All roles can change their own password via `/profile` (a separate route covered at the end of this spec).

PRD references: §5.1 (invite flow), §5.19 (settings page), §9 (User, UserOrganization, Invite, Session, Settings models)

---

## 2. Routes

| Route | Access | Description |
|---|---|---|
| `/settings` | Admin only | Redirects to `/settings/general` |
| `/settings/general` | Admin only | Identity + SMTP |
| `/settings/team` | Admin only | Team management |
| `/settings/retention` | Admin only | Data retention policies |
| `/settings/security` | Admin only | Active session management |
| `/settings/infrastructure` | Admin only | Agent DB password rotation |
| `/profile` | All roles | Own password change |

Route guard: any non-admin visiting `/settings/*` is redirected to `/` with a toast: "This area requires admin access."

---

## 3. Settings Page Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ Settings                                                         │
│                                                                  │
│  [General]  [Team]  [Retention]  [Security]  [Infrastructure]   │
│                                                                  │
│  ── General tab content ──────────────────────────────────────  │
└──────────────────────────────────────────────────────────────────┘
```

Tab navigation updates the URL. Active tab is visually highlighted. Navigating away mid-edit shows a discard warning if there are unsaved changes.

---

## 4. General Tab (`/settings/general`)

### 4.1 OpsPilot Identity Section

| Field | Type | Description |
|---|---|---|
| Instance Name | Text | Shown in email subject lines and the public status page header. Default: `OpsPilot`. |
| Base URL | URL | e.g. `https://monitor.yourdomain.com` — used in alert email links and ping URLs. No trailing slash. |

**Base URL note:** Changing this immediately affects all new ping URLs generated for cron/backup jobs and all links in future alert emails. Existing ping URLs already sent to scripts remain functional because they are stored as absolute URLs on the `CronJob`/`BackupJob` records.

**Fallback when not configured:** If `base_url` is not set, the backend falls back to `str(request.base_url)` from the FastAPI `Request` object — the scheme and host derived from the incoming HTTP request. Alert email links and generated ping URLs will still work and will reflect the actual request host. This is shown as an informational warning in Settings, not a blocking error.

Save: `PATCH /api/settings` with `{ "instance_name": "...", "base_url": "..." }`. Toast on success: "Settings saved."

### 4.2 SMTP / Email Section

| Field | Type | Default | Validation |
|---|---|---|---|
| SMTP Host | Text | — | Required; hostname only; no protocol |
| SMTP Port | Number | `587` | 1–65535 |
| Encryption | Select | TLS (STARTTLS) | None / TLS (STARTTLS) / SSL/TLS |
| Username | Text | — | Required |
| Password | Password | — | Required; stored AES-256 encrypted |
| From Address | Email | — | Required; valid email format |
| Alert Recipients | Text (comma-separated emails) | — | Required; at least one valid email |

**Password field in edit mode:** Shows placeholder `••••••••`. Leaving it blank preserves the existing encrypted password. A note reads: "Leave blank to keep existing SMTP password."

**[Send Test Email] button:** Sends a test email to the first recipient address. Shows a spinner while sending. On success: "Test email sent to admin@example.com." On failure: inline error with the SMTP error message (e.g., "Connection refused", "Authentication failed").

The test email body:
```
Subject: [OpsPilot] Test Email — {instance_name}

This is a test email from OpsPilot.
If you received this, your SMTP configuration is working correctly.

Sent by: OpsPilot ({base_url})
```

### 4.3 Save Button Behaviour

Each section (Identity and SMTP) has its own `[Save]` button. Both call `PATCH /api/settings` — the backend applies only the keys present in the request body, leaving others unchanged. A single save cannot accidentally overwrite an adjacent section.

---

## 5. Team Tab (`/settings/team`)

### 5.1 Layout

```
┌────────────────────────────────────────────────────────────────┐
│  Team                                       [+ Invite Member]  │
│                                                                │
│  ── Members ───────────────────────────────────────────────   │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Username    Role    Orgs                         [⋮]   │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │ admin       Admin   All organizations            —     │  │
│  │ alice       Member  Acme (Operator)               [⋮]  │  │
│  │ bob         Member  Acme (Viewer), ClientB (Op.)  [⋮]  │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                                │
│  ── Pending Invites ───────────────────────────────────────   │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Email               Org      Role      Expires   [⋮]  │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │ charlie@example.com  ClientB  Operator  in 36h   [⋮]  │  │
│  └────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

### 5.2 Members Table

| Column | Description |
|---|---|
| Username | Linked to their profile in the audit sense; not navigable |
| Role | `Admin` (global) or `Member` (scoped) |
| Orgs | Comma-separated list of assigned orgs with role in parentheses |
| [⋮] | Actions — differs by row type |

**Admin row** (`User.role = 'admin'`): No kebab menu. Shows `—` in the actions column. Admins cannot be demoted or removed from the team UI.

**Member rows:** Kebab menu:
- **Add to Organisation** — opens org assignment modal
- **Remove from Organisation** — opens dropdown of assigned orgs; removes selected `UserOrganization` entry
- **Remove from Team** — confirmation modal; deletes User record and all UserOrganization entries; action blocked if the member has the only non-admin assignment to a given org (warn: "This member is the only Operator for Acme Corp — assign another before removing.")

### 5.3 Invite Member Modal

Triggered: `[+ Invite Member]` button.

| Field | Type | Default | Validation |
|---|---|---|---|
| Email Address | Email | — | Required; valid email format; not already a member or pending invite |
| Organisation | Dropdown | First org | Required; lists all orgs |
| Role | Radio | Operator | Operator / Viewer |

Submit: POST `/api/invites` → modal closes → pending invite row appears at top of Pending Invites table.

If the email is already a registered member: inline error — "alice@example.com is already a member. To add them to another organisation, use 'Add to Organisation' from the member row."

### 5.4 Add to Organisation Modal

Triggered: `[⋮] → Add to Organisation` on a member row.

| Field | Type | Validation |
|---|---|---|
| Organisation | Dropdown | Required; only shows orgs the member is NOT already in |
| Role | Radio | Operator / Viewer |

Submit: POST `/api/users/:id/org-assignments`. Toast: "alice added to Acme Corp as Operator."

### 5.5 Pending Invites Table

| Column | Description |
|---|---|
| Email | Invitee email address |
| Organisation | Org the invite is for |
| Role | Operator / Viewer |
| Expires | Relative time ("in 36h") or "Expired" (amber text) |
| [⋮] | Resend, Revoke |

**Resend:** Generates a new token (48h expiry), updates the `Invite` record, sends a fresh invite email. Old token is invalidated. Toast: "Invite resent to charlie@example.com."

**Revoke:** Confirmation: "Revoke this invite? The invite link will stop working." On confirm: marks invite as revoked; row removed from table.

**Expired invites** stay visible (greyed out row) for 24 hours after expiry, then are removed by a nightly cleanup job. The `[⋮]` menu for expired invites shows only "Resend" (not "Revoke").

---

## 6. Retention Tab (`/settings/retention`)

### 6.1 Fields

| Setting | Type | Default | Min | Max |
|---|---|---|---|---|
| Raw metrics retention | Number (days) | 30 | 7 | 365 |
| Log retention | Number (days) | 30 | 7 | 365 |
| Service check retention | Number (days) | 90 | 30 | 365 |
| Alert history retention | Number (days) | 90 | 30 | 730 |

All four fields are in one form. A single `[Save Retention Settings]` button at the bottom.

### 6.2 Warning Block

Shown above the form (always visible):

```
⚠ Reducing a retention period will cause existing data beyond the
  new limit to be deleted immediately by the TimescaleDB retention
  policy. This cannot be undone.
  Increasing a period does not restore already-deleted data.
```

### 6.3 Save Behaviour

`PATCH /api/settings` with `{ "metrics_retention_days": 30, ... }`.

Backend applies each changed value by calling `SELECT add_retention_policy(...)` (or `SELECT alter_retention_policy(...)` if policy already exists) on the relevant TimescaleDB hypertable. This takes effect within the next compression/retention job cycle (up to a few minutes for large datasets).

Toast on success: "Retention settings saved. Changes will take effect shortly."

---

## 7. Security Tab (`/settings/security`)

### 7.1 Active Sessions Table

Lists all rows from the `Session` table where `revoked = false` AND `expires_at > now()`.

```
┌───────────────────────────────────────────────────────────────────┐
│  Active Sessions                                                  │
├───────────────────────────────────────────────────────────────────┤
│  This device   Chrome 124 · macOS   Issued: 1h ago   Exp: 23h    │
│  Other device  Firefox 125 · Windows  Issued: 2d ago  Exp: 22h  [Revoke]│
│  Other device  curl/7.81 · Unknown   Issued: 12h ago  Exp: 12h  [Revoke]│
└───────────────────────────────────────────────────────────────────┘
```

| Column | Description |
|---|---|
| Label | "This device" if the `jti` matches current session; "Other device" otherwise |
| Browser/OS | Parsed from `user_agent` — best-effort; shows raw UA if not parseable |
| IP Address | `ip_address` from Session record |
| Issued | Relative time since `issued_at` |
| Expires | Relative time until `expires_at` |
| [Revoke] | Not shown for current device; shown for all others |

**[Revoke All Other Sessions]** button at the top right — revokes all sessions except the current one. Shows confirmation: "This will sign out all other devices. Continue?"

**Revoke individual session:** `PATCH /api/sessions/:jti/revoke` → sets `Session.revoked = true` → row removed from table immediately. The revoked session will receive a 401 on its next API request and the frontend will redirect to login.

**Current session** shows no revoke button — "This device" label in italic.

### 7.2 Change Password (Admin)

Below the sessions table, a password change form for the currently logged-in admin:

| Field | Type | Validation |
|---|---|---|
| Current Password | Password | Required; verified server-side |
| New Password | Password | Required; min 8 chars |
| Confirm New Password | Password | Must match new password |

`PATCH /api/auth/password` — same endpoint used by `/profile`. On success: toast "Password changed. All other sessions have been revoked." (backend auto-revokes all other sessions after a password change — security best practice).

---

## 8. Infrastructure Tab (`/settings/infrastructure`)

### 8.1 Rotate Writer Password Section

```
┌────────────────────────────────────────────────────────────────┐
│  Agent Database Password Rotation                              │
│                                                                │
│  The opspilot_writer PostgreSQL user is used by Telegraf       │
│  and Fluent Bit agents on all servers to write metrics and     │
│  logs. Rotating this password updates the PostgreSQL user,     │
│  re-deploys agent configs to all servers, and restarts agents. │
│                                                                │
│  ⚠ There will be a brief data gap (~5–30s per server) during  │
│     agent restart. No data is lost — gaps appear as missing    │
│     points in time-series charts.                              │
│                                                                │
│  New Password:    [__________________________]                 │
│  Confirm:         [__________________________]                 │
│                                                                │
│                    [Rotate Password]                           │
└────────────────────────────────────────────────────────────────┘
```

| Field | Validation |
|---|---|
| New Password | Required; min 16 chars; no spaces |
| Confirm Password | Must match new password |

**Submit flow:**

1. Modal confirmation: "This will restart Telegraf and Fluent Bit on all X active servers. Each server will have a brief data gap. Proceed?" — `[Cancel]` / `[Rotate Password]`
2. On confirm: `POST /api/settings/rotate-writer-password`
3. Backend:
   a. Validates new password
   b. Runs `ALTER USER opspilot_writer PASSWORD '<new>'` on PostgreSQL
   c. Updates `OPSPILOT_WRITER_PASSWORD` value in `Settings` table (encrypted)
   d. For each active server: enqueues SSH re-deploy job (same as "Re-deploy agents" — steps 6–10)
4. Progress panel appears below the form:

```
┌────────────────────────────────────────────────────────────┐
│  Rotation in progress...                                   │
│                                                            │
│  ✓ web-01      Updated successfully                        │
│  ✓ db-01       Updated successfully                        │
│  ⟳ app-02      Re-deploying...                             │
│  ○ worker-01   Waiting                                     │
│  ✕ legacy-01   SSH connection failed                       │
└────────────────────────────────────────────────────────────┘
```

- Progress updates via WebSocket on a dedicated per-rotation channel. The `POST /api/settings/rotate-writer-password` response includes a `rotation_id` UUID:
  ```json
  { "ok": true, "rotation_id": "uuid", "total_servers": 5 }
  ```
  The frontend subscribes immediately after: `{ "action": "subscribe_rotation", "rotation_id": "uuid" }`. The backend pushes per-server progress events on that channel:
  ```json
  { "event": "writer_rotation_progress", "data": { "rotation_id": "uuid", "server_id": "uuid", "server_name": "web-01", "status": "ok"|"error"|"pending"|"deploying", "message": "Updated successfully" } }
  ```
  The channel is auto-unsubscribed when all servers reach a terminal state (`ok` or `error`).
- Failed servers show the error message and a `[Retry →]` button that triggers a re-deploy for that server only
- When all servers complete (success or failure): "Rotation complete. X of Y servers updated. [View failed →]"
- Servers that permanently fail: admin can re-deploy manually from the Servers page

### 8.2 Env Var Reference

Read-only informational block (collapsed by default):

```
▼ Environment Variables

  OPSPILOT_ENCRYPTION_KEY — AES-256 key for encrypting stored credentials.
  OPSPILOT_JWT_SECRET     — Signs JWT tokens.
  DATABASE_URL            — PostgreSQL connection string.
  OPSPILOT_WRITER_PASSWORD— Initial writer password (used only by Alembic
                            on first migration; value in Settings takes over
                            after rotation).

  These values are set at deployment time in your .env file or Docker
  environment. They cannot be changed from this UI.
```

---

## 9. Profile Page (`/profile`)

Accessible to all roles (Admin, Operator, Viewer). Not part of `/settings`.

### 9.1 Layout

```
┌────────────────────────────────────────────────────────────┐
│  My Profile                                                │
│                                                            │
│  Username:  alice  (read-only)                             │
│  Role:      Member — Operator in Acme Corp, ClientB        │
│  Member since: 2026-04-15                                  │
│                                                            │
│  ── Change Password ──────────────────────────────────── │
│                                                            │
│  Current Password     [__________________________]         │
│  New Password         [__________________________]         │
│  Confirm New Password [__________________________]         │
│                                                            │
│                              [Save Password]               │
└────────────────────────────────────────────────────────────┘
```

### 9.2 Fields

- **Username**: displayed as read-only text — usernames cannot be changed after account creation
- **Role**: "Admin" or list of org assignments for members ("Operator in Acme Corp, Viewer in ClientB")
- **Member since**: `User.created_at` formatted as `YYYY-MM-DD`

### 9.3 Password Change

Same form and validation as the Security tab. API: `PATCH /api/auth/password` with `{ "current_password": "...", "new_password": "..." }`.

Validation:
- Current password: verified server-side; 401 if wrong → "Current password is incorrect"
- New password: min 8 chars
- Confirm: must match new password

On success: toast "Password changed. You have been signed out of all other devices." Backend auto-revokes all other sessions for this user.

---

## 10. Backend — Settings Storage

All settings are stored in the `Settings` table as key-value pairs:

| Key | Sensitive | Default |
|---|---|---|
| `instance_name` | No | `OpsPilot` |
| `base_url` | No | — |
| `smtp_host` | No | — |
| `smtp_port` | No | `587` |
| `smtp_encryption` | No | `tls` |
| `smtp_username` | No | — |
| `smtp_password` | Yes (encrypted) | — |
| `smtp_from_address` | No | — |
| `smtp_recipients` | No | — |
| `metrics_retention_days` | No | `30` |
| `logs_retention_days` | No | `30` |
| `service_checks_retention_days` | No | `90` |
| `alerts_retention_days` | No | `90` |

`OPSPILOT_WRITER_PASSWORD` is read from the env var on first start and copied to `Settings` (encrypted) during the initial migration — subsequent rotations update only the `Settings` row.

`OPSPILOT_ENCRYPTION_KEY` and `OPSPILOT_JWT_SECRET` are never stored in the database — env vars only. Backend aborts startup if either is absent.

---

## 11. Pinia Store — `useSettingsStore`

```ts
// State
general: {
  instanceName: string
  baseUrl: string
}
smtp: {
  host: string
  port: number
  encryption: 'none' | 'tls' | 'ssl'
  username: string
  fromAddress: string
  recipients: string
  hasPassword: boolean    // true if encrypted password exists; password itself never sent to frontend
}
retention: {
  metricsRetentionDays: number
  logsRetentionDays: number
  serviceChecksRetentionDays: number
  alertsRetentionDays: number
}
sessions: Session[]
team: {
  members: TeamMember[]
  pendingInvites: Invite[]
}
isLoading: boolean
error: string | null

// Actions
fetchSettings(): Promise<void>
saveGeneral(payload): Promise<void>
saveSmtp(payload): Promise<void>
testSmtp(): Promise<void>
saveRetention(payload): Promise<void>
fetchSessions(): Promise<void>
revokeSession(jti: string): Promise<void>
revokeAllOtherSessions(): Promise<void>
fetchTeam(): Promise<void>
inviteMember(payload): Promise<void>
addOrgAssignment(user_id: string, payload): Promise<void>
removeOrgAssignment(user_id: string, org_id: string): Promise<void>
removeMember(user_id: string): Promise<void>
resendInvite(invite_id: string): Promise<void>
revokeInvite(invite_id: string): Promise<void>
rotateWriterPassword(payload): Promise<void>
changePassword(payload): Promise<void>    // used by both /settings/security and /profile
```

---

## 12. API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/settings` | Admin | Fetch all settings (no sensitive values) |
| PATCH | `/api/settings` | Admin | Update one or more settings keys |
| POST | `/api/settings/smtp/test` | Admin | Send test email |
| GET | `/api/team` | Admin | List members + pending invites |
| POST | `/api/invites` | Admin | Send invite |
| POST | `/api/invites/:id/resend` | Admin | Resend invite (new token, new email) |
| DELETE | `/api/invites/:id` | Admin | Revoke pending invite |
| POST | `/api/users/:id/org-assignments` | Admin | Add user to org |
| DELETE | `/api/users/:id/org-assignments/:org_id` | Admin | Remove user from org |
| DELETE | `/api/users/:id` | Admin | Remove user from team |

**DELETE `/api/users/:id` — sole-operator guard:**
Before deleting, the backend checks: for each org where this user is the only active Operator (i.e., no other `UserOrganization` row with `role='operator'` for that `org_id`), deletion is blocked.

Error response: `409 Conflict`
```json
{
  "error": "sole_operator",
  "orgs": [
    { "org_id": "uuid", "org_name": "Acme Corp" }
  ],
  "message": "This user is the only Operator for 1 organisation. Assign another Operator before removing."
}
```
The frontend shows this message in the confirmation modal if the API returns 409.
| GET | `/api/sessions` | Admin | List active sessions |
| PATCH | `/api/sessions/:jti/revoke` | Admin | Revoke a session |
| POST | `/api/sessions/revoke-others` | Admin | Revoke all sessions except current |
| POST | `/api/settings/rotate-writer-password` | Admin | Start writer password rotation |
| PATCH | `/api/auth/password` | All roles | Change own password |

### 12.1 GET `/api/settings` Response

```json
{
  "instance_name": "OpsPilot",
  "base_url": "https://monitor.example.com",
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "smtp_encryption": "tls",
  "smtp_username": "alerts@example.com",
  "smtp_from_address": "alerts@example.com",
  "smtp_recipients": "admin@example.com",
  "smtp_has_password": true,
  "metrics_retention_days": 30,
  "logs_retention_days": 30,
  "service_checks_retention_days": 90,
  "alerts_retention_days": 90
}
```

`smtp_has_password: true` indicates an encrypted password exists. The actual password is never returned.

### 12.2 GET `/api/team` Response

```json
{
  "members": [
    {
      "id": "uuid",
      "username": "alice",
      "role": "member",
      "created_at": "2026-04-15T09:00:00Z",
      "org_assignments": [
        { "org_id": "uuid", "org_name": "Acme Corp", "role": "operator" }
      ]
    }
  ],
  "pending_invites": [
    {
      "id": "uuid",
      "email": "charlie@example.com",
      "org_id": "uuid",
      "org_name": "ClientB",
      "role": "operator",
      "expires_at": "2026-06-03T10:00:00Z"
    }
  ]
}
```

---

## 13. Edge States

| State | Behaviour |
|---|---|
| No SMTP configured | SMTP section shows amber banner: "Email notifications are disabled — configure SMTP to receive alerts." Test button disabled. |
| Test email fails (SMTP unreachable) | Inline error below the button with the SMTP error message; form stays open |
| Base URL not set | Warning banner on General tab: "Base URL is not configured — links will use the request Host header as fallback." The backend uses `str(request.base_url)` as fallback; emails and ping URLs still work but reflect the Host header rather than a configured canonical URL. |
| Invite to already-registered email | Inline error in invite modal: "This email is already a member." |
| Invite token expired | Row shows "Expired" label in amber; `[⋮]` shows Resend only |
| Member removed, open alert assigned to their action | Alert remains in DB; `acknowledged_by` / `snoozed_by` fields are informational only — no cascading effect |
| Writer password rotation, all servers succeed | Progress panel shows all green; "Rotation complete. 5 of 5 servers updated." |
| Writer password rotation, some servers fail | Partial success; failed servers show SSH error and `[Retry]`; data from failed servers will gap until admin re-deploys |
| Session table empty (only current session) | "No other active sessions" shown below the current session row |
| Password change: current password wrong | 401 from API → "Current password is incorrect" inline under the field |
| Reducing retention below existing data volume | Warning shown; save proceeds; TimescaleDB retention job will delete excess data asynchronously |
| Viewer visits `/settings/*` | Redirected to `/` with toast: "This area requires admin access" |
| `/profile` — admin viewing their own profile | Shows "Admin — Global Access" in the Role field |

---

## 14. Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `1`–`5` | Switch between tabs (General / Team / Retention / Security / Infrastructure) |
| `Escape` | Close modal |
| `r` | Refresh current tab data |
