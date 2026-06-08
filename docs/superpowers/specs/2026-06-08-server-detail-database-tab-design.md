# Server Detail — Database Tab (Read-Only)

**Date:** 2026-06-08
**Status:** Approved

## Goal

Add a read-only "Database" tab to the server detail page that surfaces the database health dashboard for all DB instances linked to that server. Admins manage credentials from the standalone Databases page; this tab is purely for monitoring at a glance while already on a server.

---

## Scope

- **In scope:** New `DatabaseTab.vue` component; wiring into `ServerDetail.vue`; instance pill bar; loading/empty states; read-only dashboard display
- **Out of scope:** Add/edit/remove credentials; any backend changes; any changes to `DatabasesView.vue`

---

## Architecture

### New File

**`frontend/src/components/servers/tabs/DatabaseTab.vue`**

Follows the same pattern as `ServicesTab.vue`:
- Gets `serverId` from `metrics.activeServerId` (metrics store)
- Gets `orgId` from `useOrgStore().activeOrgId`
- On mount: calls `useDatabaseStore().fetchCredentials(orgId)` to populate the store (no-op if already loaded from visiting the Databases page)
- Computes `instances` via `store.serverFor(serverId)?.instances ?? []`
- Tracks `selectedInstanceId` with a `ref<string | null>` — auto-selects the first instance on load

**Props received from `ServerDetail.vue`:** `:range="currentRange"` — declared but unused; `DbHealthDashboard` manages its own range selector internally.

### Modified File

**`frontend/src/views/servers/ServerDetail.vue`**

- Add `"Database"` to the `TABS` const array, positioned after `"Services"` and before `"Monitoring"`:
  ```
  [..., 'Services', 'Database', 'Monitoring', ...]
  ```
- Import `DatabaseTab` and add to `TAB_COMPONENTS`

---

## Component States

| Condition | UI |
|---|---|
| `loadingCredentials` | Subtle skeleton / spinner |
| `instances.length === 0` | `EmptyState` — "No database monitoring configured" with muted note to visit the Databases page |
| `instances.length === 1` | Instance pill bar with one pill (auto-selected) + `DbHealthDashboard` |
| `instances.length > 1` | Instance pill bar with N pills + `DbHealthDashboard` for selected instance |

---

## Instance Pill Bar

Reuses the exact same `.inst-bar` / `.inst-pill` / `.inst-dot` CSS classes and `instanceDot` / `instanceDotClass` logic from `DatabasesView.vue`. No "Add Instance" button (read-only).

---

## DbHealthDashboard Usage

```html
<DbHealthDashboard
  :key="`hd-${selectedInstance.credential_id}`"
  :server-id="serverId"
  :server-name="serverName"
  :status="selectedInstance"
  :can-edit="false"
  :db-type="selectedInstance.db_type"
  :credential-id="selectedInstance.credential_id"
/>
```

`canEdit=false` hides Edit Credentials, Remove DB Monitoring, and Copy Password buttons.

---

## Data Flow

```
ServerDetail.vue
  └─ DatabaseTab.vue
       ├─ metrics.activeServerId  → serverId
       ├─ useOrgStore.activeOrgId → orgId
       ├─ store.fetchCredentials(orgId)  [on mount, idempotent]
       ├─ store.serverFor(serverId)      → DbServerStatus | null
       └─ DbHealthDashboard
            ├─ store.fetchLatest(serverId, credentialId)
            └─ store.fetchSeries(serverId, metric, range, credentialId)
```

No new API endpoints. Reuses `GET /api/organizations/{org_id}/db-credentials`.

---

## Empty State Copy

> **No database monitoring configured**
> Set up credentials from the [Databases](/databases) page to monitor this server's database instances.

(Plain text with a router-link — no action button since the tab is read-only.)

---

## File Map

| File | Change |
|---|---|
| `frontend/src/components/servers/tabs/DatabaseTab.vue` | **Create** |
| `frontend/src/views/servers/ServerDetail.vue` | **Modify** — add tab entry |
