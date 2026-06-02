# Module Spec 02 — Organizations & Server Management

**Version:** 1.0  
**Date:** 2026-06-01  
**PRD Reference:** §5.2, §5.3  
**Status:** Ready for Development

---

## 1. Overview

This module covers two tightly coupled areas:

1. **Organization Management** — CRUD for organizations; org switcher in the sidebar
2. **Server Management** — listing, adding, editing, and deleting servers within an organization

Every server belongs to exactly one organization. All other modules (services, logs, alerts, cron jobs, etc.) are scoped to a server, which is scoped to an org. This module is therefore the foundation everything else builds on.

**Screens in this module:**

| Screen | Route | Access |
|---|---|---|
| Organizations list | `/organizations` | Admin only |
| Server list | `/servers` | All roles (org-scoped) |
| Org switcher | Sidebar component | All roles |

Add/Edit org and Add/Edit server are **modals**, not separate routes.

---

## 2. Org Switcher (Sidebar Component)

The org switcher sits permanently at the **top of the sidebar**, above all nav links. It is the first thing every user interacts with after login.

### 2.1 Layout

```
┌──────────────────────────────────────┐
│  [org icon]  Acme Corp          ▾   │  ← clickable dropdown trigger
└──────────────────────────────────────┘
│  Nav links below...                  │
```

### 2.2 Dropdown — Admin view

```
┌──────────────────────────────────────┐
│  🔍  Search organizations...         │
├──────────────────────────────────────┤
│  ☁  All Organizations               │  ← aggregate view
├──────────────────────────────────────┤
│  ✓  Acme Corp              [Admin]  │  ← active org (checkmark)
│     Client B               [Admin]  │
│     Internal Infra         [Admin]  │
├──────────────────────────────────────┤
│  +  New Organization                 │
└──────────────────────────────────────┘
```

- Search box appears only when org count > 5
- Active org shown with a checkmark
- `[Admin]` badge shown on each row
- `All Organizations` is always pinned at the top
- `+ New Organization` at the bottom — opens Create Org modal

### 2.3 Dropdown — Member view (Operator / Viewer)

```
┌──────────────────────────────────────┐
│  ✓  Acme Corp          [Operator]  │
│     Client B           [Viewer]    │
└──────────────────────────────────────┘
```

- No search (members have few orgs)
- No `All Organizations` option
- No `+ New Organization`
- Role badge shows per-org role

### 2.4 Switching Org Behaviour

1. User selects an org from dropdown
2. `activeOrg` updated in Pinia store + persisted in `localStorage`
3. Dropdown closes
4. Sidebar label updates to the new org name
5. Current page data **refreshes** for the new org (API calls re-fired with new org context)
6. If user is on a page for a resource that doesn't exist in the new org (e.g. viewing a specific server), redirect to the list page for that module

### 2.5 First Login — No Orgs Exist

When Admin logs in for the first time and no organizations exist yet, the sidebar shows:

```
┌──────────────────────────────────────┐
│  [icon]  No organization selected ▾ │
└──────────────────────────────────────┘
```

And the main content area shows a full-screen empty state:

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│              🏢                                     │
│    Create your first organization                   │
│    Organizations group your servers and team.       │
│                                                     │
│    [ + Create Organization ]                        │
│                                                     │
└─────────────────────────────────────────────────────┘
```

Clicking `+ Create Organization` opens the Create Org modal. No other navigation works until at least one org exists.

---

## 3. Organizations Page

**Route:** `/organizations`  
**Access:** Admin only — redirect to `/` with toast "Access denied" for non-admin  
**Nav location:** Sidebar → Organizations

### 3.1 Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Organizations                          [ + New Organization ]  │
│  Manage your client and team workspaces                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ Acme Corp        │  │ Client B         │  │ Internal     │  │
│  │ acme-corp        │  │ client-b         │  │ internal-    │  │
│  │                  │  │                  │  │ infra        │  │
│  │ 8 servers        │  │ 3 servers        │  │              │  │
│  │ 2 domains        │  │ 1 domain         │  │ 5 servers    │  │
│  │ 4 members        │  │ 2 members        │  │ 0 domains    │  │
│  │                  │  │                  │  │ 1 member     │  │
│  │ [Edit] [Delete]  │  │ [Edit] [Delete]  │  │ [Edit][Del]  │  │
│  └──────────────────┘  └──────────────────┘  └──────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

- Card grid — 3 columns on desktop, 2 on tablet, 1 on mobile
- Each card shows: name, slug, server count, domain count, member count
- Edit and Delete action buttons on each card
- `+ New Organization` button top-right

### 3.2 Empty State

When no organizations exist:

```
│              🏢                              │
│    No organizations yet                      │
│    Create one to start adding servers.       │
│    [ + Create Organization ]                 │
```

---

## 4. Create / Edit Organization Modal

### 4.1 Layout

```
┌────────────────────────────────────────────┐
│  Create Organization               [  ✕  ] │
├────────────────────────────────────────────┤
│                                            │
│  Name *                                    │
│  ┌──────────────────────────────────────┐  │
│  │  e.g. Acme Corp                      │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  Slug *                                    │
│  ┌──────────────────────────────────────┐  │
│  │  acme-corp                           │  │
│  └──────────────────────────────────────┘  │
│  ⓘ Auto-generated. Locked after creation.  │
│                                            │
│  Description                               │
│  ┌──────────────────────────────────────┐  │
│  │                                      │  │
│  │                                      │  │
│  └──────────────────────────────────────┘  │
│                                            │
│             [Cancel]  [Create Organization]│
└────────────────────────────────────────────┘
```

- Edit mode: title changes to `Edit Organization`; slug field is **disabled** (read-only) with a lock icon and tooltip: *"Slug cannot be changed after creation"*; button label changes to `Save Changes`

### 4.2 Form Fields

| Field | Type | Required | Rules |
|---|---|---|---|
| `name` | Text | Yes | Min 2 chars, max 80 chars |
| `slug` | Text | Yes (auto) | Auto-generated from name (lowercase, spaces → hyphens, strip special chars). Editable before submit on create. Locked on edit. Pattern: `^[a-z0-9-]+$`. Min 2, max 50 chars. Must be globally unique. |
| `description` | Textarea | No | Max 300 chars |

**Slug auto-generation logic:** fires on `name` input (debounced 300ms). Example: `"Acme Corp!"` → `"acme-corp"`. If the generated slug is already taken, append `-2`, `-3`, etc. Backend validates uniqueness on submit.

### 4.3 Validation (on submit)

| Field | Rule | Error |
|---|---|---|
| `name` | Required | `Organization name is required` |
| `name` | Min 2 chars | `Name must be at least 2 characters` |
| `slug` | Required | `Slug is required` |
| `slug` | Pattern `^[a-z0-9-]+$` | `Slug can only contain lowercase letters, numbers, and hyphens` |
| `slug` | Unique (from API) | `This slug is already taken` |

### 4.4 Button States

| State | Create label | Edit label |
|---|---|---|
| Default | `Create Organization` | `Save Changes` |
| Loading | Spinner, disabled | Spinner, disabled |

### 4.5 Success Behaviour

- **Create**: modal closes, new org card appears in grid, org is added to the switcher dropdown, toast: `"Organization created"`
- **Edit**: modal closes, card updates in place, switcher label updates if this was the active org, toast: `"Organization updated"`

---

## 5. Delete Organization

### 5.1 Trigger

Delete button on the org card (Admin only). No confirmation needed to open — clicking Delete immediately checks if deletion is allowed.

### 5.2 Blocked Delete (org has resources)

If the org has servers OR domains, show an error modal instead of a confirmation:

```
┌────────────────────────────────────────────┐
│  Cannot delete "Acme Corp"         [ ✕ ]  │
├────────────────────────────────────────────┤
│                                            │
│  ⚠  This organization still has:          │
│      • 8 servers                           │
│      • 2 domains                           │
│                                            │
│  Remove or reassign all servers and        │
│  domains before deleting.                  │
│                                            │
│                              [OK]          │
└────────────────────────────────────────────┘
```

### 5.3 Allowed Delete (org is empty)

If the org has no servers and no domains, show a standard confirmation:

```
┌────────────────────────────────────────────┐
│  Delete "Internal Infra"?          [ ✕ ]  │
├────────────────────────────────────────────┤
│                                            │
│  This will also remove all team member     │
│  assignments for this organization.        │
│  This action cannot be undone.             │
│                                            │
│         [Cancel]   [Delete Organization]   │
└────────────────────────────────────────────┘
```

- `Delete Organization` button is red/danger colour
- On confirm: org deleted, card removed from grid, org removed from switcher
- If deleted org was the active org: switcher falls back to the first remaining org (or `All Organizations` if admin)
- Toast: `"Organization deleted"`

---

## 6. Server List Page

**Route:** `/servers`  
**Access:** All roles (data scoped to `activeOrg`)

### 6.1 Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Servers — Acme Corp                         [ + Add Server ]       │
│  8 servers  •  6 online  •  1 offline  •  1 maintenance            │
├──────────────────────────────────────────────────────────────────────┤
│  🔍 Search servers...     [Status ▾]  [Tags ▾]    [Grid | Table]    │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│  │ ● web-01    │  │ ● web-02    │  │ ○ db-01     │                 │
│  │ 192.168.1.1 │  │ 192.168.1.2 │  │ 192.168.1.3 │                 │
│  │ Ubuntu 22   │  │ Ubuntu 22   │  │ Ubuntu 20   │                 │
│  │ ONLINE      │  │ ONLINE      │  │ OFFLINE     │                 │
│  │ 2 alerts    │  │ 0 alerts    │  │ 1 alert     │                 │
│  │ 2min ago    │  │ 30s ago     │  │ 8min ago    │                 │
│  └─────────────┘  └─────────────┘  └─────────────┘                 │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

- Page title shows active org name (or `All Servers` when Admin on `All Organizations` view)
- Summary line: total, online count, offline count, maintenance count
- `+ Add Server` button: Admin only — hidden for Operator and Viewer
- Toggle between Grid view and Table view (preference saved in `localStorage`)

### 6.2 All Organizations View (Admin only)

When Admin selects `All Organizations` in the switcher:
- Page title: `All Servers`
- Summary counts span all orgs
- An `Organization` column appears in Table view; org badge appears on each card in Grid view
- `+ Add Server` still available — org picker in form defaults to first org

### 6.3 Server Card (Grid View)

```
┌──────────────────────────────────┐
│  ● web-01                [⋮]    │  ← status dot + name + action menu
│  192.168.1.10                    │
│  Ubuntu 22.04 · 4 vCPU · 8GB    │
│  ──────────────────────────────  │
│  ONLINE              2 min ago   │
│  2 active alerts    [production] │
└──────────────────────────────────┘
```

**Status dot colours:**
| Status | Dot colour | Badge |
|---|---|---|
| Online | Green | `ONLINE` |
| Offline | Red | `OFFLINE` |
| Maintenance | Yellow/amber | `MAINTENANCE` |
| Pending (not onboarded) | Grey | `PENDING` |

**Action menu `[⋮]` (Admin only):**
- View Server
- Edit Server
- Re-deploy Agents
- Toggle Maintenance
- Delete Server

Card is fully clickable (navigates to server detail) for all roles.

### 6.4 Server Table View

| Column | Description |
|---|---|
| Status | Coloured dot |
| Name | Server display name — clickable |
| IP / Host | IP address or hostname |
| OS | e.g. `Ubuntu 22.04` |
| Tags | Tag chips (truncated to 2, +N more) |
| Last Seen | Relative timestamp (e.g. `2 min ago`) |
| Active Alerts | Count badge (red if > 0) |
| Organization | Shown only in All Organizations view |
| Actions | Edit, Delete (Admin only) |

Sortable columns: Name, Last Seen, Active Alerts. Default sort: Status (online first), then Name A–Z.

### 6.5 Filters

| Filter | Type | Options |
|---|---|---|
| Search | Text | Matches name, IP, hostname |
| Status | Multi-select dropdown | Online, Offline, Maintenance, Pending |
| Tags | Multi-select dropdown | All unique tags across servers in active org |

Filters are applied client-side on the loaded server list (no extra API call per filter change). All filters are reset when org is switched.

### 6.6 Empty State

When active org has no servers:

```
│              🖥                                  │
│    No servers in Acme Corp                       │
│    Add your first server to start monitoring.    │
│    [ + Add Server ]       ← Admin only           │
```

For non-admin with no servers:
```
│    No servers in this organization yet.          │
│    Ask your admin to add servers.                │
```

---

## 7. Add / Edit Server Modal

### 7.1 Layout

```
┌────────────────────────────────────────────────────┐
│  Add Server                               [  ✕  ]  │
├────────────────────────────────────────────────────┤
│                                                    │
│  Organization *                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │  Acme Corp                               ▾  │  │  ← pre-filled, dropdown
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  Display Name *                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │  e.g. web-01                                 │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  IP Address / Hostname *                           │
│  ┌──────────────────────────────────────────────┐  │
│  │  e.g. 192.168.1.10                           │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  SSH Port *                                        │
│  ┌─────────┐                                       │
│  │  22     │                                       │
│  └─────────┘                                       │
│                                                    │
│  SSH Username *                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │  e.g. ubuntu                                 │  │
│  └──────────────────────────────────────────────┘  │
│  ⓘ Must have passwordless sudo (NOPASSWD)          │
│                                                    │
│  SSH Authentication *                              │
│  ○ Private Key   ● Password                        │
│                                                    │
│  [If Private Key selected:]                        │
│  Private Key (PEM) *                               │
│  ┌──────────────────────────────────────────────┐  │
│  │                                              │  │
│  │  -----BEGIN OPENSSH PRIVATE KEY-----        │  │
│  │                                              │  │
│  └──────────────────────────────────────────────┘  │
│  or [ Upload .pem file ]                           │
│                                                    │
│  [If Password selected:]                           │
│  SSH Password *                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │                                          👁  │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  Tags                                              │
│  ┌──────────────────────────────────────────────┐  │
│  │  production  ✕     staging  ✕     [+tag]     │  │
│  └──────────────────────────────────────────────┘  │
│  ⓘ Press Enter or comma to add a tag               │
│                                                    │
│                  [Cancel]  [Add Server]            │
└────────────────────────────────────────────────────┘
```

- Edit mode: title → `Edit Server`; button → `Save Changes`; SSH auth fields show `[Change]` toggles instead of being visible by default (current key/password is never sent to frontend — only masked indicator shown)

### 7.2 Form Fields

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `org_id` | Dropdown | Yes | Active org | Admin can change; hidden if only one org exists |
| `name` | Text | Yes | — | Max 80 chars |
| `host` | Text | Yes | — | IP address or hostname. No protocol prefix. |
| `ssh_port` | Number | Yes | `22` | 1–65535 |
| `ssh_user` | Text | Yes | — | SSH username |
| `ssh_auth_type` | Radio | Yes | `password` | `'key'` or `'password'` |
| `ssh_key` | Textarea | Conditional | — | Shown when auth type = key. Accepts PEM text or file upload. |
| `ssh_password` | Password | Conditional | — | Shown when auth type = password. Show/hide toggle. |
| `tags` | Tag input | No | — | Comma or Enter to add. Each tag max 30 chars, max 10 tags. |

### 7.3 Validation Rules (on submit)

| Field | Rule | Error |
|---|---|---|
| `name` | Required | `Server name is required` |
| `name` | Max 80 chars | `Name is too long` |
| `host` | Required | `IP address or hostname is required` |
| `host` | No spaces | `Enter a valid IP address or hostname` |
| `ssh_port` | Required, 1–65535 | `Enter a valid port number` |
| `ssh_user` | Required | `SSH username is required` |
| `ssh_key` | Required when auth=key | `SSH private key is required` |
| `ssh_key` | Must start with `-----BEGIN` | `Enter a valid PEM private key` |
| `ssh_password` | Required when auth=password | `SSH password is required` |

### 7.4 SSH Key File Upload

- Accepts `.pem`, `.key`, `.txt` files
- File content is read client-side and pasted into the textarea
- No server upload — the key text is submitted as part of the JSON body
- File size limit: 16 KB (enforced client-side)

### 7.5 Edit Mode — Credential Handling

In edit mode, SSH credentials are **never returned to the frontend** (they are AES-256 encrypted at rest). The form shows:

```
SSH Authentication
● Private Key  ○ Password

Current key:  [Key on file — ends in ...Xk4=]   [Replace Key]
```

`[Replace Key]` toggles the textarea visible. If the admin clicks `Save Changes` without touching the credential fields, the existing encrypted values are preserved unchanged.

### 7.6 Successful Add Flow

1. Admin fills form and clicks `Add Server`
2. Button shows spinner
3. Backend creates `Server` record with `status = 'pending'`
4. Modal closes
5. New server card appears in the list with `PENDING` status badge
6. **Onboarding automatically begins** — the server card shows an inline progress indicator
7. Toast: `"Server added — onboarding in progress"`

The full onboarding flow (SSH steps, agent deploy, progress log) is covered in **spec 03**.

### 7.7 Successful Edit Flow

1. Admin saves changes
2. Modal closes
3. Server card/row updates in place
4. Toast: `"Server updated"`
5. If SSH credentials were changed → backend re-deploys agents automatically (same as "Re-deploy Agents" action)

---

## 8. Delete Server

### 8.1 Trigger

`Delete Server` from the `[⋮]` action menu on a server card (Admin only).

### 8.2 Confirmation Modal

```
┌────────────────────────────────────────────┐
│  Delete "web-01"?                  [ ✕ ]  │
├────────────────────────────────────────────┤
│                                            │
│  This will soft-delete the server and      │
│  cascade-deactivate all associated:        │
│   • Services (3)                           │
│   • Alert rules (4)                        │
│   • Cron jobs (2)                          │
│   • Backup jobs (1)                        │
│                                            │
│  Metric and log history will be retained   │
│  until the natural 30-day expiry.          │
│  Agents on the server are NOT uninstalled. │
│                                            │
│  Type the server name to confirm:          │
│  ┌──────────────────────────────────────┐  │
│  │                                      │  │
│  └──────────────────────────────────────┘  │
│                                            │
│         [Cancel]   [Delete Server]         │
└────────────────────────────────────────────┘
```

- `Delete Server` button stays **disabled** until the user types the exact server name
- Button turns red/danger colour when name matches
- Counts shown are live (fetched when modal opens)

### 8.3 Post-Delete Behaviour

- Server card removed from list
- Active alerts for this server resolved immediately
- Toast: `"web-01 has been deleted"`
- If user was on the server detail page, redirect to `/servers`

---

## 9. Re-deploy Agents Action

Available from the `[⋮]` menu on any online server (Admin only). Useful after SSH credentials change or if agents fall out of sync.

Flow:
1. Admin clicks `Re-deploy Agents`
2. Toast: `"Re-deploying agents on web-01…"`
3. Background job runs the same SSH deploy sequence as onboarding (steps 3–7 of the onboarding flow — spec 03)
4. On success: toast updates to `"Agents re-deployed successfully"`
5. On failure: toast updates to `"Re-deploy failed — check onboarding log"` with link to the server's onboarding log

No modal needed — this is a fire-and-forget action with toast feedback.

---

## 10. API Endpoints

### Organizations

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/organizations` | Required | List orgs (all for Admin; assigned for Member) |
| `POST` | `/api/organizations` | Admin | Create org |
| `GET` | `/api/organizations/:id` | Required | Get single org |
| `PATCH` | `/api/organizations/:id` | Admin | Update name / description (slug locked) |
| `DELETE` | `/api/organizations/:id` | Admin | Delete org (blocked if resources exist) |
| `GET` | `/api/organizations/:id/stats` | Required | Server count, domain count, member count for org card |

### GET /api/organizations

**Response (200):**
```json
[
  {
    "id": "uuid",
    "name": "Acme Corp",
    "slug": "acme-corp",
    "description": "Primary client",
    "created_at": "2026-01-01T00:00:00Z"
  }
]
```

### POST /api/organizations

**Request body:**
```json
{ "name": "Acme Corp", "slug": "acme-corp", "description": "Optional" }
```
**Responses:** `201` created | `409` slug already taken | `403` not admin

### PATCH /api/organizations/:id

**Request body:**
```json
{ "name": "Acme Corp Updated", "description": "New description" }
```
Slug field ignored even if sent — never updated.

### DELETE /api/organizations/:id

**Responses:**
- `204` deleted
- `409` org has servers or domains — body: `{ "servers": 8, "domains": 2 }`
- `403` not admin

---

### Servers

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/organizations/:org_id/servers` | Required | List servers in org |
| `GET` | `/api/servers` | Admin | List all servers across all orgs (All Organizations view) |
| `POST` | `/api/organizations/:org_id/servers` | Admin | Add server to org |
| `GET` | `/api/servers/:id` | Required | Get single server |
| `PATCH` | `/api/servers/:id` | Admin | Update server |
| `DELETE` | `/api/servers/:id` | Admin | Soft-delete server |
| `POST` | `/api/servers/:id/redeploy` | Admin | Trigger agent re-deploy |

### GET /api/organizations/:org_id/servers

**Response (200):**
```json
[
  {
    "id": "uuid",
    "org_id": "uuid",
    "name": "web-01",
    "host": "192.168.1.10",
    "ssh_port": 22,
    "ssh_user": "ubuntu",
    "ssh_auth_type": "key",
    "os_distro": "Ubuntu 22.04",
    "kernel_version": "5.15.0",
    "tags": ["production"],
    "is_active": true,
    "status": "online",
    "last_seen_at": "2026-06-01T12:00:00Z",
    "active_alert_count": 2,
    "created_at": "2026-01-01T00:00:00Z"
  }
]
```

Note: `ssh_key_encrypted` and `ssh_password_encrypted` are **never returned**. The response includes `ssh_auth_type` so the frontend knows which credential type is stored.

`status` is a **computed field** (not stored): derived by backend on each list call:
- `pending` — `os_distro` is NULL (onboarding not completed)
- `online` — last metric received within 2 minutes
- `offline` — no metric for > 2 minutes (and not pending)
- `maintenance` — active `MaintenanceWindow` record exists

### POST /api/organizations/:org_id/servers

**Request body:**
```json
{
  "name": "web-01",
  "host": "192.168.1.10",
  "ssh_port": 22,
  "ssh_user": "ubuntu",
  "ssh_auth_type": "key",
  "ssh_key": "-----BEGIN OPENSSH PRIVATE KEY-----\n...",
  "tags": ["production"]
}
```

**Response `201`:**
```json
{ "id": "uuid", "name": "web-01", "status": "pending" }
```
Onboarding starts automatically after server record is created.

### PATCH /api/servers/:id

Same shape as POST body — all fields optional. If `ssh_key` or `ssh_password` included in the patch body, the new value is encrypted and saved; omitting them leaves the existing encrypted value unchanged.

**Response `200`:** Updated server object (same shape as list item).

If SSH credentials were changed: backend queues an agent re-deploy job.

### DELETE /api/servers/:id

**Response `204`** on success.  
Cascade soft-deletes: Services, AlertRules, LogAlertRules, CronJobs, BackupJobs, DBCredentials linked to this server.  
Active alerts resolved immediately.

---

## 11. Pinia Stores

### `useOrgStore`

| State | Type | Description |
|---|---|---|
| `orgs` | `Organization[]` | All orgs the user can access |
| `activeOrg` | `Organization \| null` | Currently selected org — persisted in `localStorage` |
| `loading` | `boolean` | True while fetching orgs |

| Action | Description |
|---|---|
| `fetchOrgs()` | GET `/api/organizations`, populates `orgs` |
| `setActiveOrg(org)` | Updates `activeOrg` in store + `localStorage` |
| `createOrg(data)` | POST `/api/organizations`, adds to `orgs` |
| `updateOrg(id, data)` | PATCH `/api/organizations/:id`, updates in `orgs` |
| `deleteOrg(id)` | DELETE `/api/organizations/:id`, removes from `orgs`; updates `activeOrg` if needed |

### `useServerStore`

| State | Type | Description |
|---|---|---|
| `servers` | `Server[]` | Servers in the active org |
| `loading` | `boolean` | True while fetching |
| `selectedServer` | `Server \| null` | The server currently being viewed in detail |

| Action | Description |
|---|---|
| `fetchServers(orgId)` | GET `/api/organizations/:org_id/servers` |
| `fetchAllServers()` | GET `/api/servers` (Admin, All Orgs view) |
| `addServer(orgId, data)` | POST — creates server + triggers onboarding |
| `updateServer(id, data)` | PATCH — updates server |
| `deleteServer(id)` | DELETE — soft-deletes, removes from list |
| `redeployAgents(id)` | POST `/api/servers/:id/redeploy` |

---

## 12. Empty & Edge States Summary

| Scenario | Behaviour |
|---|---|
| Admin first login — no orgs | Full-screen "Create your first organization" prompt |
| Member has no org assignments | Sidebar shows "No organization" — blank main content with message "You have no organization access. Contact your admin." |
| Active org is deleted by admin | Switch to first remaining org; if none, show "no orgs" state |
| Server added — onboarding fails | Card stays `PENDING`, shows error indicator; link to onboarding log |
| Server goes offline | Card dot turns red in real-time via WebSocket push |
| All Organizations selected, servers have no org (shouldn't happen) | Not possible — `org_id` is required on server creation |
| Admin tries to delete org with resources | Blocked modal showing counts — no delete performed |
| Non-admin visits `/organizations` | Redirect to `/` with toast "Access denied" |
| Delete server with typed name mismatch | `Delete Server` button stays disabled |
| Edit server — no credential change | Existing encrypted values preserved; no re-deploy triggered |
| Re-deploy triggered on offline server | Allowed — backend will attempt SSH; will log failure if unreachable |
