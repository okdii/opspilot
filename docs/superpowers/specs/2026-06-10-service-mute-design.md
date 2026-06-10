# Service Mute — Design Spec
_Date: 2026-06-10_

## Problem

The Services tab shows all detected services including those that are stopped but not used on a given server (e.g. mysql, postgresql on a server running only nginx). These generate `agent_service_down` alerts the operator doesn't want. There is no way to tell OpsPilot "I don't care about this service on this server."

## Solution

Per-server service muting. A bell icon (🔔/🔕) on each service row lets the operator toggle muting. Muted services stay visible (grayed out with a muted badge) but generate no alerts. Muting a service auto-resolves any existing open alert for it.

---

## Data Model

New table:

```sql
CREATE TABLE server_service_mutes (
    server_id    UUID        NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    service_name TEXT        NOT NULL,
    muted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (server_id, service_name)
);
```

One Alembic migration. No changes to existing tables.

---

## Backend

### Modified endpoint

`GET /api/servers/{server_id}/services`

LEFT JOINs against `server_service_mutes` to include a `muted: bool` field on each row:

```sql
SELECT DISTINCT ON (ssm.service_name)
    ssm.service_name, ssm.status, ssm.cpu_pct, ssm.mem_mb, ssm.uptime_seconds,
    (mutes.service_name IS NOT NULL) AS muted
FROM server_service_metrics ssm
LEFT JOIN server_service_mutes mutes
    ON mutes.server_id = ssm.server_id
   AND mutes.service_name = ssm.service_name
WHERE ssm.server_id = :sid
ORDER BY ssm.service_name, ssm.time DESC
```

### New endpoints

```
PUT    /api/servers/{server_id}/services/{service_name}/mute
DELETE /api/servers/{server_id}/services/{service_name}/mute
```

**PUT (mute):**
1. Upsert row into `server_service_mutes`
2. Find any open `agent_service_down:{service_name}` alert for this server → auto-resolve it
3. Return `{"ok": true}`

**DELETE (unmute):**
1. Delete row from `server_service_mutes`
2. Return `{"ok": true}`

Both require the caller to be authenticated and have access to the server (same guard as existing server endpoints).

### Alert engine change

`_evaluate_agent_services` in `ingest.py`: before firing an `agent_service_down` alert, check whether a mute row exists for `(server_id, service_name)`. If muted, skip firing entirely.

---

## Frontend

### Type change

`ServerServiceEntry` in `types/` gains:
```ts
muted: boolean
```

### API functions (`api.ts`)

```ts
muteServerService(serverId: string, serviceName: string): Promise<void>
unmuteServerService(serverId: string, serviceName: string): Promise<void>
```

### ServicesTab.vue

- New rightmost column (no header label) containing the bell icon per row
- 🔔 = monitored (active), 🔕 = muted
- Muted rows: `opacity: 0.45`, status badge forced to gray, small `muted` text badge
- Click bell → optimistic flip of `muted` locally → call mute/unmute API → refetch services
- No new components — all changes in `ServicesTab.vue` and `api.ts`

---

## Behaviour Summary

| State | Bell | Row appearance | Alerts |
|---|---|---|---|
| Monitored | 🔔 | Normal | Fire as usual |
| Muted | 🔕 | 45% opacity, gray badge | Suppressed; existing alert auto-resolved |

---

## Out of Scope

- Global mute (cross-server) — not needed
- Mute reason / notes — not needed
- Mute expiry / time-limited mute — not needed
