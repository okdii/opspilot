# Global Dashboard — Design

**Date:** 2026-06-02
**Phase:** 2 — Live Dashboard & Charts (slice 2 of 3)
**Status:** Approved (design), pending implementation plan
**Related:** spec 04 §2 (Overview Page), spec 02 (server cards), PRD §5.4.8 (live fan-out)
**Depends on:** WS live infrastructure slice (`docs/superpowers/specs/2026-06-02-ws-live-infrastructure-design.md`) — shipped

---

## 1. Purpose & scope

Build the global dashboard (`/`): summary stat cards + a live server-card grid, consuming the WS live-metric pipeline shipped in slice 1. This is the first user-facing payoff of Phase 2.

**In scope**
- `GET /api/organizations/:org_id/dashboard` — summary counts + per-server latest metrics
- `GET /api/organizations/:org_id/alerts/recent` — last 10 alerts (returns `[]` now; built against the real `Alert` table)
- Dashboard page: 4 summary stat cards, server-card grid with **live** CPU/RAM/Disk bars, no-servers empty state, Recent Alerts panel (empty state for now)
- Live wiring: `subscribe_org` on mount → bars update live; `unsubscribe_org` on unmount / org switch

**Out of scope (deferred, with rationale)**
- **Services / Alerts / SSL counts** — rendered from the endpoint but return `0` until their phases (Services = Phase 4, Alerts = Phase 8, SSL/Domains = Phase 5). Each summary block is isolated so its phase swaps in the real count.
- **Ack button** on the alerts panel — Phase 8 (no alert-action endpoint yet).
- **All-Organizations aggregate view** (admin selects "All Orgs", `activeOrgId === null`) — needs multi-org subscribe + client merge; this slice targets a **selected org** (the switcher auto-selects one by default). Show a "Select an organization" hint when All-Orgs is active. Tracked fast-follow.
- **Unifying `ServersView`'s inline card** into the new `ServerCard` — the servers-list card carries onboarding-progress + management-menu concerns; not force-refactored here to avoid regressing onboarding. Tracked fast-follow.

## 2. Backend read endpoints

New router: `backend/app/routers/dashboard.py`, registered in `app/main.py`. Both endpoints require auth + org access (reuse the existing org-access check used by the servers router).

### 2.1 `GET /api/organizations/:org_id/dashboard`

Response:
```json
{
  "summary": {
    "servers": { "total": 1, "online": 1, "offline": 0, "maintenance": 0 },
    "services": { "up": 0, "down": 0 },
    "alerts": { "firing": 0, "snoozed": 0, "acknowledged": 0 },
    "ssl_domains": { "expiring": 0, "expired": 0 }
  },
  "servers": [
    {
      "id": "uuid", "name": "lima-ubuntu", "host": "host.docker.internal",
      "tags": [], "status": "online", "last_seen_at": "2026-06-02T08:16:10Z",
      "metrics": { "cpu": 0.21, "ram": 18.4, "disk": 65.4 }
    }
  ]
}
```

- **Server `status`** (`online` | `offline` | `maintenance`): reuse the existing online/offline-from-`last_seen_at` derivation already used by `ServerOut` in the servers router. `maintenance` stays 0/none in this slice (no maintenance windows created yet).
- **Latest metrics** per server: a `DISTINCT ON (metric_name)` query over `server_metrics` ordered by `time DESC`, restricted to the three metric names below; each value is nullable (server hasn't reported yet). Telegraf metric-name mapping (to confirm against live data during implementation):
  - `cpu` ← `cpu.usage_active`
  - `ram` ← `mem.used_percent`
  - `disk` ← `disk.used_percent` where label `path = "/"` (root mount)
- **Summary counts:**
  - `servers`: computed from the active servers in the org + their derived status.
  - `alerts`: query the `Alert` table for the org (firing/snoozed/acknowledged) — returns zeros now.
  - `services`, `ssl_domains`: hardcoded `0` blocks (subsystems not built); each isolated for a one-line swap later.

### 2.2 `GET /api/organizations/:org_id/alerts/recent`

Returns the last 10 `Alert` rows for the org ordered by `sent_at DESC` (shape: server name + description + state + timestamp). Returns `[]` now. No Ack action.

## 3. Frontend

### 3.1 Reused components (component-reuse principle)
- `StatCard` (`label`, `value`, `icon?`, `accent?`) → the 4 summary cards
- `StatusBadge` (`status`, `kind`) → `kind="server"` for server status, `kind="alert"` for the panel
- `EmptyState` (`icon?`, `title`, `message?`) → no-servers and no-alerts states

### 3.2 New components
- **`MetricBar.vue`** — reusable atom. Props: `label: string`, `value: number | null`. Color thresholds: green <70, amber 70–84, red ≥85; amber warning icon when value >80; muted "—" track when `null`. (spec 04 §2.3)
- **`ServerCard.vue`** — props: `server` (id/name/host/tags/status/last_seen_at/metrics, plus optional service/alert counts). Renders identity, `StatusBadge`, three `MetricBar`s (CPU/RAM/Disk), "N services · N alerts" line, relative last-seen; click → `/servers/:id`.
- **`RecentAlertsPanel.vue`** — props: `alerts: Alert[]`. Renders the list or an `EmptyState` ("No recent alerts yet"). `[View All →]` → `/alerts`. No Ack button.
- **`DashboardView.vue`** (rewrite) — keeps the existing no-orgs setup states; replaces the placeholder with: summary `StatCard` row → `ServerCard` grid (responsive 3–4 col) → `RecentAlertsPanel`. No-servers → `EmptyState` + "Add Server" (admin). All-Orgs active → "Select an organization" hint.

### 3.3 State & live wiring
- **`dashboard` Pinia store** (`stores/dashboard.ts`): state `{ summary, servers, loading, error }`; actions:
  - `fetchDashboard(orgId)` — calls the dashboard endpoint, populates state.
  - `applyMetricPush(serverId, rows)` — from a `server_metrics` batch, extract the three mapped metric names (disk filtered to `path="/"`) and update that server's `metrics` in place (no re-fetch).
  - `reset()`.
- **Service calls** (`services/api.ts`): `getDashboard(orgId)`, `getRecentAlerts(orgId)`.
- **Live flow** (in `DashboardView` on mount): `fetchDashboard(activeOrgId)` → register `wsClient.on(handler)` that routes `server_metrics:{id}` batches to `dashboardStore.applyMetricPush` → `wsClient.send({ action: "subscribe_org", org_id })`. Watch `activeOrgId`: on change, `unsubscribe_org` old, fetch + `subscribe_org` new. On unmount: `unsubscribe_org` + remove the handler. `ws.ts` already auto-reconnects and resubscribes.
- **WS connection prerequisite:** the live flow assumes a single authenticated `wsClient` connection exists for the session. The implementation plan must first confirm where `wsClient.connect()` is invoked (app bootstrap after login). If no such global connection exists yet, the plan adds an idempotent `wsClient.connect()` at app bootstrap (guard against opening a second socket) — the dashboard itself only registers a handler and sends subscribe/unsubscribe, it does not own the connection lifecycle.

### 3.4 States
- **Loading:** skeleton/placeholder while `fetchDashboard` is pending.
- **Empty:** no servers → `EmptyState` + "Add Server" (admin only); All-Orgs active → "Select an organization" hint.
- **Error:** fetch failure → inline error message + retry.
- **Visual design:** produced via the **UI/UX Pro Max skill** (CLAUDE.md Rule 2) — modern dark dashboard, consistent with existing components/tokens.

## 4. Verification (against live `lima-ubuntu`)

1. `curl /api/organizations/:org/dashboard` → summary counts + the lima server with non-null `cpu`/`ram`/`disk`.
2. `curl /api/organizations/:org/alerts/recent` → `[]`.
3. Browser (Playwright, as in Phase 1): dashboard loads → Servers stat card shows "1 online"; the lima `ServerCard` shows three real % bars → screenshot.
4. **Live:** capture the dashboard, wait ~10s for a Telegraf flush, re-capture → a bar value changes with no reload (proves `subscribe_org` → `applyMetricPush`).
5. No-servers empty state renders for an org with no servers.

## 5. File structure

| File | Responsibility | Action |
|---|---|---|
| `backend/app/routers/dashboard.py` | dashboard + alerts/recent read endpoints | Create |
| `backend/app/main.py` | register the dashboard router | Modify |
| `frontend/src/components/ui/MetricBar.vue` | metric progress bar atom | Create |
| `frontend/src/components/servers/ServerCard.vue` | live server card | Create |
| `frontend/src/components/dashboard/RecentAlertsPanel.vue` | recent alerts panel | Create |
| `frontend/src/stores/dashboard.ts` | dashboard state + live push application | Create |
| `frontend/src/services/api.ts` | `getDashboard`, `getRecentAlerts` | Modify |
| `frontend/src/views/dashboard/DashboardView.vue` | assemble the dashboard | Modify (rewrite body) |
| `frontend/src/components/ui/index.ts` | export `MetricBar` | Modify |
