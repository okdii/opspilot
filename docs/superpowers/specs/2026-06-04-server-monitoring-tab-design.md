# Server Detail — Monitoring Tab

**Date:** 2026-06-04  
**Status:** Approved  
**Scope:** Add a "Monitoring" tab to the server detail page showing HTTP/TCP monitoring checks scoped to that server, with delete capability.

---

## Problem

The main Services page (`/services`) shows all monitoring checks across the org. When viewing a specific server, there's no way to see which monitoring checks are registered for that server without leaving the detail view. Users also can't delete a stale check from server context.

---

## Goal

Add a **Monitoring tab** to the server detail page (`/servers/:id`) that shows the monitoring checks registered for that server only, and allows deleting them.

---

## Out of Scope

- Adding new monitoring checks from this tab (use the main Services page)
- Editing check configuration from this tab
- Check history, uptime timeline charts (covered by the main Services page)

---

## Backend

### New Endpoint

```
GET /api/servers/{server_id}/services
```

- **Auth:** `CurrentUser` — verify user is a member of the server's org (same pattern as `_get_accessible_service`)
- **Returns:** `list[ServiceOut]` — same schema as `GET /api/organizations/{org_id}/services`, filtered to `server_id`
- **Ordering:** `Service.name` ascending
- **Error:** 404 if server not found, 403 if user has no org membership

No new schema needed — reuses existing `ServiceOut`.

---

## Frontend

### New API function

`frontend/src/services/api.ts`

```ts
getServerMonitoringServices(serverId: string): Promise<ServiceOut[]>
// GET /api/servers/{serverId}/services
```

### New Component

`frontend/src/components/servers/tabs/MonitoringTab.vue`

**Props:** receives `serverId` (string) via the metrics store (`metrics.activeServerId`)

**Table columns:**

| Column | Source |
|---|---|
| Name | `service.name` |
| Type | `service.type` — badge: HTTP / TCP / DB |
| URL / Host | `service.url` + optional `:service.port` |
| Status | `StatusBadge` — `up` / `down` / `unknown` from `service.last_status` |
| Uptime 24h | `service.uptime_24h` — `"—"` if null |
| Avg Response | `service.avg_response_ms_24h` — `"—"` if null, else `Xms` |
| Actions | Delete icon button |

**Delete flow:**
1. User clicks trash icon → row enters confirmation state (shows "Confirm?" + Cancel inline, replaces action button)
2. Confirm → `DELETE /api/services/{id}` → remove row from local list
3. Cancel → row returns to normal state
4. No modal, no page reload

**States:**
- Loading: skeleton rows (6)
- Empty: `EmptyState` component — title "No monitoring checks", message "Register checks for this server on the Services page."
- Error on delete: show brief inline error text on the row, do not remove it

**Reused components:** `StatusBadge`, `EmptyState` (no new shared components needed)

### ServerDetail.vue changes

1. Import `MonitoringTab`
2. Add `'Monitoring'` to the `TABS` const — position: after `'Services'`
3. Add `Monitoring: MonitoringTab` to `TAB_COMPONENTS`

---

## Styling

- Matches existing `ServicesTab` table style (dark theme, consistent row height)
- Type badge: small pill, same color conventions as StatusBadge variants
- Delete icon: `va-icon name="delete"`, muted color, hover → danger red
- Confirmation state: inline text "Delete?" with small Confirm / Cancel text buttons

---

## Smoke Test

1. Open a server detail page — "Monitoring" tab visible in tab bar
2. Tab shows only monitoring checks registered for that server (verify against main Services page)
3. Delete a check → row disappears, check gone from main Services page too
4. Server with no checks → EmptyState renders correctly
