# Service Mute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-server service muting — a bell icon on each service row lets operators suppress alerts for services they don't use, with muted rows staying visible but grayed out.

**Architecture:** New `server_service_mutes` DB table (server_id + service_name PK) stores mutes. The GET services endpoint LEFT JOINs against it to return a `muted` flag. Two new PUT/DELETE endpoints handle toggling. The heartbeat alert evaluator skips muted services. The frontend adds a bell column with optimistic toggle.

**Tech Stack:** Python/FastAPI + SQLAlchemy (backend), Vue 3 + Pinia (frontend), PostgreSQL (DB), Alembic (migrations)

---

## Task 1: DB Migration — `server_service_mutes` table

**Files:**
- Create: `backend/migrations/versions/0019_service_mutes.py`

- [ ] **Step 1: Create the migration file**

```python
# backend/migrations/versions/0019_service_mutes.py
"""Add server_service_mutes table.

Revision ID: 0019_service_mutes
Revises: 0018_job_last_label
"""
import sqlalchemy as sa
from alembic import op

revision = "0019_service_mutes"
down_revision = "0018_job_last_label"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_service_mutes",
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column(
            "muted_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("server_id", "service_name"),
    )


def downgrade() -> None:
    op.drop_table("server_service_mutes")
```

- [ ] **Step 2: Apply and verify migration**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend alembic upgrade head
```

Expected: `Running upgrade 0018_job_last_label -> 0019_service_mutes`

Then verify the table exists:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -c "\d server_service_mutes"
```

Expected: table with columns `server_id`, `service_name`, `muted_at`.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/versions/0019_service_mutes.py
git commit -m "feat: add server_service_mutes migration"
```

---

## Task 2: Backend — GET services + mute/unmute endpoints

**Files:**
- Modify: `backend/app/routers/servers.py`

- [ ] **Step 1: Update imports at top of servers.py**

Add `and_` to the sqlalchemy import and add the alerting imports:

```python
from sqlalchemy import and_, func, select, text
```

Also add after the existing service imports:
```python
from app.services.alerting import OPEN_STATES, resolve_alert
```

- [ ] **Step 2: Replace `get_server_services` (lines 304–332)**

Replace the entire function with:

```python
@router.get("/api/servers/{server_id}/services")
async def get_server_services(
    server_id: str,
    user: CurrentUser,
    include_not_installed: bool = False,
    db: AsyncSession = Depends(get_db),
):
    await _get_accessible_server(server_id, user, db)
    rows = (await db.execute(
        text("""
            SELECT DISTINCT ON (ssm.service_name)
                ssm.service_name, ssm.status, ssm.cpu_pct, ssm.mem_mb,
                ssm.uptime_seconds,
                (mutes.service_name IS NOT NULL) AS muted
            FROM server_service_metrics ssm
            LEFT JOIN server_service_mutes mutes
                ON mutes.server_id = ssm.server_id
               AND mutes.service_name = ssm.service_name
            WHERE ssm.server_id = :sid
              AND (:include_ni OR ssm.status != 'not_installed')
            ORDER BY ssm.service_name, ssm.time DESC
        """),
        {"sid": server_id, "include_ni": include_not_installed},
    )).all()
    return [
        {
            "name": row.service_name,
            "status": row.status,
            "cpu_pct": row.cpu_pct,
            "mem_mb": row.mem_mb,
            "uptime_seconds": row.uptime_seconds,
            "muted": bool(row.muted),
        }
        for row in rows
    ]
```

- [ ] **Step 3: Add mute/unmute endpoints after `get_server_services`**

Add these two functions immediately after the updated `get_server_services`:

```python
@router.put("/api/servers/{server_id}/services/{service_name}/mute")
async def mute_server_service(
    server_id: str,
    service_name: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _get_accessible_server(server_id, user, db)
    await db.execute(
        text("""
            INSERT INTO server_service_mutes (server_id, service_name)
            VALUES (:sid, :sname)
            ON CONFLICT (server_id, service_name) DO NOTHING
        """),
        {"sid": server_id, "sname": service_name},
    )
    alert_type = f"agent_service_down:{service_name}"
    open_alert = (
        await db.execute(
            select(Alert).where(
                and_(
                    Alert.type == alert_type,
                    Alert.server_id == server_id,
                    Alert.state.in_(OPEN_STATES),
                )
            ).limit(1)
        )
    ).scalar_one_or_none()
    if open_alert:
        await resolve_alert(db, open_alert, commit=False)
    await db.commit()
    return {"ok": True}


@router.delete("/api/servers/{server_id}/services/{service_name}/mute")
async def unmute_server_service(
    server_id: str,
    service_name: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _get_accessible_server(server_id, user, db)
    await db.execute(
        text(
            "DELETE FROM server_service_mutes "
            "WHERE server_id = :sid AND service_name = :sname"
        ),
        {"sid": server_id, "sname": service_name},
    )
    await db.commit()
    return {"ok": True}
```

- [ ] **Step 4: Smoke test the endpoints**

```bash
# Get a server ID and token from the DB first
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -c "SELECT id FROM servers LIMIT 1;"

# Login and get a session token, then test (replace SERVER_ID and TOKEN):
curl -s "http://localhost:9090/api/servers/SERVER_ID/services?include_not_installed=true" \
  -H "Cookie: TOKEN" | python3 -m json.tool | grep -E "name|muted"
```

Expected: each entry has a `"muted": false` field.

```bash
# Mute "mysql" — replace SERVER_ID
curl -s -X PUT "http://localhost:9090/api/servers/SERVER_ID/services/mysql/mute" \
  -H "Cookie: TOKEN"
```

Expected: `{"ok": true}`

```bash
# Verify muted flag appears
curl -s "http://localhost:9090/api/servers/SERVER_ID/services?include_not_installed=true" \
  -H "Cookie: TOKEN" | python3 -m json.tool | grep -A2 '"mysql"'
```

Expected: `"muted": true` on the mysql entry.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/servers.py
git commit -m "feat: add muted flag to services endpoint and mute/unmute endpoints"
```

---

## Task 3: Backend — Skip muted services in alert evaluator

**Files:**
- Modify: `backend/app/routers/ingest.py` (lines 104–133)

- [ ] **Step 1: Replace `_evaluate_agent_services`**

Replace the entire function (lines 104–133) with:

```python
async def _evaluate_agent_services(
    db: AsyncSession, server_id, server_name: str, services: list[_ServiceMetric]
) -> None:
    """Fire/resolve agent_service_down alerts based on heartbeat service statuses."""
    muted_result = await db.execute(
        text("SELECT service_name FROM server_service_mutes WHERE server_id = :sid"),
        {"sid": server_id},
    )
    muted = {row.service_name for row in muted_result.all()}

    for svc in services:
        if svc.name in muted:
            continue
        alert_type = f"agent_service_down:{svc.name}"
        if svc.status == "stopped":
            await fire_alert(
                db,
                type=alert_type,
                severity="critical",
                message=f"Service {svc.name} is down (reported by OpsPilot agent)",
                server_id=server_id,
                cooldown_min=60,
                commit=False,
            )
        elif svc.status == "running":
            open_alert = (
                await db.execute(
                    select(Alert).where(
                        and_(
                            Alert.type == alert_type,
                            Alert.server_id == server_id,
                            Alert.state.in_(OPEN_STATES),
                        )
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if open_alert:
                await resolve_alert(db, open_alert, commit=False)
```

- [ ] **Step 2: Verify backend starts cleanly**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend --tail=20
```

Expected: no import errors, uvicorn running.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/ingest.py
git commit -m "feat: skip muted services in heartbeat alert evaluator"
```

---

## Task 4: Frontend — Type + API functions

**Files:**
- Modify: `frontend/src/types/index.ts` (line 216 — after `uptime_seconds`)
- Modify: `frontend/src/services/api.ts` (after `getServerServices`)

- [ ] **Step 1: Add `muted` to `ServerServiceEntry` in `types/index.ts`**

Find the interface (around line 210) and add the `muted` field:

```typescript
export interface ServerServiceEntry {
  name: string
  status: 'running' | 'stopped' | 'not_installed'
  cpu_pct: number | null
  mem_mb: number | null
  uptime_seconds: number | null
  muted: boolean
}
```

- [ ] **Step 2: Add API functions in `api.ts` after `getServerServices`**

```typescript
export async function muteServerService(
  serverId: string,
  serviceName: string,
): Promise<void> {
  await api.put(`/api/servers/${serverId}/services/${encodeURIComponent(serviceName)}/mute`)
}

export async function unmuteServerService(
  serverId: string,
  serviceName: string,
): Promise<void> {
  await api.delete(`/api/servers/${serverId}/services/${encodeURIComponent(serviceName)}/mute`)
}
```

- [ ] **Step 3: Check TypeScript compiles**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend \
  npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/services/api.ts
git commit -m "feat: add muted field to ServerServiceEntry and mute API functions"
```

---

## Task 5: Frontend — ServicesTab.vue bell column

**Files:**
- Modify: `frontend/src/components/servers/tabs/ServicesTab.vue`

- [ ] **Step 1: Replace the entire file**

```vue
<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { EmptyState, StatusBadge } from '@/components/ui'
import { getServerServices, muteServerService, unmuteServerService } from '@/services/api'
import { useMetricsStore } from '@/stores/metrics'
import type { ServerServiceEntry } from '@/types'

const metrics = useMetricsStore()
const services = ref<ServerServiceEntry[]>([])
const loading = ref(true)

async function fetchServices() {
  const id = metrics.activeServerId
  if (!id) return
  loading.value = true
  try {
    services.value = await getServerServices(id, true)
  } catch {
    // keep stale data on transient error
  } finally {
    loading.value = false
  }
}

async function toggleMute(svc: ServerServiceEntry) {
  const id = metrics.activeServerId
  if (!id) return
  const prev = svc.muted
  svc.muted = !prev
  try {
    if (svc.muted) {
      await muteServerService(id, svc.name)
    } else {
      await unmuteServerService(id, svc.name)
    }
  } catch {
    svc.muted = prev
  }
  await fetchServices()
}

function formatUptime(seconds: number | null): string {
  if (seconds == null) return '—'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

onMounted(() => void fetchServices())
watch(() => metrics.latestValues, () => void fetchServices(), { deep: false })
</script>

<template>
  <div class="svc">
    <div class="svc-head">
      <h3>System Services</h3>
    </div>

    <div v-if="loading && !services.length" class="skeleton-wrap">
      <div class="skeleton-row" v-for="i in 6" :key="i" />
    </div>

    <EmptyState
      v-else-if="!loading && !services.length"
      title="No service data"
      message="No service data — make sure your agent is up to date."
    />

    <div class="table-wrap" v-else>
      <table class="svc-table">
        <thead>
          <tr>
            <th class="t-name">Service</th>
            <th class="t-status">Status</th>
            <th class="t-num">CPU</th>
            <th class="t-num">Memory</th>
            <th class="t-num">Uptime</th>
            <th class="t-bell"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="svc in services" :key="svc.name" :class="{ 'is-muted': svc.muted }">
            <td class="t-name">{{ svc.name }}</td>
            <td class="t-status">
              <StatusBadge kind="process_service" :status="svc.status" />
              <span v-if="svc.muted" class="muted-badge">muted</span>
            </td>
            <td class="t-num">{{ svc.cpu_pct != null ? svc.cpu_pct.toFixed(1) + '%' : '—' }}</td>
            <td class="t-num">{{ svc.mem_mb != null ? svc.mem_mb.toFixed(0) + ' MB' : '—' }}</td>
            <td class="t-num">{{ formatUptime(svc.uptime_seconds) }}</td>
            <td class="t-bell">
              <button
                class="bell-btn"
                :class="{ 'is-muted': svc.muted }"
                :title="svc.muted ? 'Unmute alerts' : 'Mute alerts'"
                @click="toggleMute(svc)"
              >
                <svg v-if="!svc.muted" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
                  <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
                </svg>
                <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
                  <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
                  <line x1="1" y1="1" x2="23" y2="23"/>
                </svg>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.svc { display: flex; flex-direction: column; gap: 16px; }

.svc-head { display: flex; align-items: center; justify-content: space-between; }
.svc-head h3 { font-size: 15px; color: var(--text); font-weight: 600; }

.skeleton-wrap { display: flex; flex-direction: column; gap: 8px; }
.skeleton-row {
  height: 44px; border-radius: 8px;
  background: var(--surface);
  animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

.table-wrap {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden;
}

.svc-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.svc-table th {
  text-align: left; color: var(--muted); font-size: 11px; font-weight: 500;
  text-transform: uppercase; letter-spacing: 0.05em; padding: 11px 16px;
  border-bottom: 1px solid var(--border); white-space: nowrap;
  background: var(--surface-2);
}
.svc-table td { padding: 11px 16px; color: var(--text); border-bottom: 1px solid var(--border); }
.svc-table tbody tr:last-child td { border-bottom: none; }
.svc-table tbody tr:hover { background: rgba(255,255,255,0.025); }

.t-name { font-weight: 500; min-width: 100px; }
.t-status { width: 130px; }
.t-num { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); min-width: 80px; }
.t-bell { width: 36px; text-align: center; padding: 0 8px !important; }

/* Muted row — fade all cells except the bell column */
tr.is-muted td:not(.t-bell) { opacity: 0.45; }

.muted-badge {
  display: inline-block; margin-left: 6px;
  background: rgba(255,255,255,0.07); color: var(--muted);
  font-size: 10px; font-weight: 500; text-transform: uppercase;
  letter-spacing: 0.04em; padding: 1px 5px; border-radius: 3px;
  vertical-align: middle;
}

.bell-btn {
  background: none; border: none; cursor: pointer; padding: 4px;
  border-radius: 4px; color: var(--muted); display: flex; align-items: center;
  transition: color 0.15s, background 0.15s;
}
.bell-btn:hover { background: rgba(255,255,255,0.08); color: var(--text); }
.bell-btn.is-muted { color: rgba(255,255,255,0.25); }
.bell-btn.is-muted:hover { color: var(--text); background: rgba(255,255,255,0.08); }
</style>
```

- [ ] **Step 2: Open the browser and verify**

Open `http://localhost:9090` → navigate to a server → Services tab.

Check:
- Each row has a bell icon on the right
- Clicking 🔔 on a stopped service → row fades + 🔕 + "muted" badge appears
- Clicking 🔕 → row returns to normal

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/servers/tabs/ServicesTab.vue
git commit -m "feat: add bell icon mute toggle to services tab"
```

---

## Task 6: Release

- [ ] **Step 1: Push and tag**

```bash
git push origin main
git tag v1.2.3
git push origin v1.2.3
```
