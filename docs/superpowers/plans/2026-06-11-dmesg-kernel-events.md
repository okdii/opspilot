# dmesg / Kernel Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect kernel messages (dmesg) from monitored servers via Fluent Bit kmsg stream + SSH poll, and surface them as a Kernel Events card at the bottom of the System tab.

**Architecture:** Fluent Bit reads `/dev/kmsg` in real-time (warn+ only) and ships kernel log entries through the existing ingest pipeline into `server_logs` with `source='kernel'`. A new APScheduler job polls `dmesg -T -l warn,err,crit,alert,emerg` via SSH every 15 minutes as a historical backfill, deduplicating against already-stored rows. A new API endpoint returns severity counts + recent events; a new `KernelEventsCard.vue` component renders the summary strip + event list in the System tab.

**Tech Stack:** Python/FastAPI (backend), APScheduler, asyncpg/SQLAlchemy, Fluent Bit Jinja2 templates, Vue 3 + Vuestic/Pinia (frontend)

---

## File Map

| Action | Path |
|--------|------|
| Modify | `backend/app/services/templates/fluent-bit.conf.j2` |
| Create | `backend/app/services/dmesg_collector.py` |
| Modify | `backend/app/jobs/scheduler.py` |
| Modify | `backend/app/routers/servers.py` |
| Modify | `frontend/src/services/api.ts` |
| Create | `frontend/src/components/servers/tabs/KernelEventsCard.vue` |
| Modify | `frontend/src/components/servers/tabs/SystemTab.vue` |
| Modify | `frontend/src/components/servers/tabs/LogsTab.vue` |
| Modify | `PROGRESS.md` + `DASHBOARD.html` |

---

## Task 1: Add kmsg INPUT block to Fluent Bit template

**Files:**
- Modify: `backend/app/services/templates/fluent-bit.conf.j2`

- [ ] **Step 1: Open the template and add the kmsg block after the auth log INPUT section**

In `backend/app/services/templates/fluent-bit.conf.j2`, insert after line 31 (after the `# ── Auth log` block ends):

```
# ── Kernel messages ──────────────────────────────────────────────────────────
[INPUT]
    Name              kmsg
    Tag               kernel
    Prio_Level        warning
    DB                /var/lib/fluent-bit/kernel.db
    Skip_Long_Lines   On

```

`Prio_Level warning` = warn/err/crit/alert/emerg only. The existing Lua filter at lines 91-95 already stamps `source = tag` (so `source = 'kernel'`). The backend `ALLOWED_SOURCES` already lists `'kernel'` — no further changes needed in the ingest pipeline.

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/templates/fluent-bit.conf.j2
git commit -m "feat: add kmsg INPUT block to Fluent Bit template for kernel log collection"
```

---

## Task 2: Create dmesg collector service

**Files:**
- Create: `backend/app/services/dmesg_collector.py`

- [ ] **Step 1: Create the file**

```python
"""SSH dmesg poll — collect kernel messages every 15 min per active server.

Runs dmesg -T -l warn,err,crit,alert,emerg on each server via SSH,
parses output, deduplicates against server_logs, and inserts new rows.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.database import AsyncSessionLocal
from app.models.server import Server
from app.services.ssh import SSHSession

log = logging.getLogger(__name__)

_DMESG_CMD = "dmesg -T -l warn,err,crit,alert,emerg 2>/dev/null || true"
# Matches: [Wed Jun 11 03:14:22 2026] message text
_LINE_RE = re.compile(r"^\[(\w{3} \w{3}\s+\d+ \d{2}:\d{2}:\d{2} \d{4})\]\s+(.+)$")

_SEVERITY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Out of memory|oom_kill|Killed process", re.I), "crit"),
    (re.compile(r"I/O error|EXT4-fs error|EDAC|Machine check|Kernel panic|BUG:|Oops:", re.I), "err"),
    (re.compile(r"Link is Down|remount-ro|Critical temperature|thermal.*warning", re.I), "warn"),
]


def _classify_severity(message: str) -> str:
    for pattern, sev in _SEVERITY_PATTERNS:
        if pattern.search(message):
            return sev
    return "warn"


def _parse_dmesg(output: str) -> list[dict]:
    rows = []
    for line in output.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        try:
            # dmesg -T uses local time; assume UTC (most servers run UTC)
            ts = datetime.strptime(m.group(1).strip(), "%a %b %d %H:%M:%S %Y").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        message = m.group(2).strip()
        rows.append(
            {"logged_at": ts, "severity": _classify_severity(message), "message": message}
        )
    return rows


async def _already_exists(db, server_id: str, logged_at: datetime, message: str) -> bool:
    result = await db.execute(
        text("""
            SELECT 1 FROM server_logs
            WHERE server_id = :sid
              AND source = 'kernel'
              AND time BETWEEN :lo AND :hi
              AND message = :msg
            LIMIT 1
        """),
        {
            "sid": server_id,
            "lo": logged_at - timedelta(seconds=2),
            "hi": logged_at + timedelta(seconds=2),
            "msg": message,
        },
    )
    return result.fetchone() is not None


async def _collect_one(server: Server) -> None:
    async with SSHSession(server) as ssh:
        result = await ssh.run(_DMESG_CMD, timeout=15)
    if not result.ok or not result.stdout.strip():
        return

    rows = _parse_dmesg(result.stdout)
    if not rows:
        return

    async with AsyncSessionLocal() as db:
        inserted = 0
        for row in rows:
            if await _already_exists(db, str(server.id), row["logged_at"], row["message"]):
                continue
            await db.execute(
                text("""
                    INSERT INTO server_logs (time, server_id, source, severity, message, raw)
                    VALUES (:time, :server_id, 'kernel', :severity, :message, 'null'::jsonb)
                """),
                {
                    "time": row["logged_at"],
                    "server_id": str(server.id),
                    "severity": row["severity"],
                    "message": row["message"],
                },
            )
            inserted += 1
        if inserted:
            await db.commit()
            log.info("dmesg: inserted %d kernel events for server %s", inserted, server.id)


async def collect_dmesg() -> None:
    """Entry point called by APScheduler every 15 minutes."""
    async with AsyncSessionLocal() as db:
        servers = (
            await db.execute(select(Server).where(Server.is_active == True))
        ).scalars().all()

    for server in servers:
        try:
            await _collect_one(server)
        except Exception:
            log.exception("dmesg collection failed for server %s", server.id)
```

- [ ] **Step 2: Verify the import resolves**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend \
  python -c "from app.services.dmesg_collector import collect_dmesg; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/dmesg_collector.py
git commit -m "feat: add dmesg SSH poll collector service"
```

---

## Task 3: Register dmesg_collector job in scheduler

**Files:**
- Modify: `backend/app/jobs/scheduler.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add the import and job registration**

At the bottom of `backend/app/jobs/scheduler.py`, add a new async function and document it:

```python
async def dmesg_collector() -> None:
    """Every 15 min: poll dmesg on each active server for kernel events."""
    from app.services.dmesg_collector import collect_dmesg
    await collect_dmesg()
```

Then in `main.py`, inside the `lifespan` startup block where other jobs are registered (after line 60), add:

```python
    scheduler.add_job(dmesg_collector, "interval", minutes=15, id="dmesg_collector", replace_existing=True)
```

- [ ] **Step 2: Verify the backend starts without errors**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
sleep 3
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend --tail=20
```

Expected: No import errors, scheduler starts normally.

- [ ] **Step 3: Commit**

```bash
git add backend/app/jobs/scheduler.py backend/app/main.py
git commit -m "feat: register dmesg_collector job (every 15 min)"
```

---

## Task 4: Kernel events API endpoint

**Files:**
- Modify: `backend/app/routers/servers.py`

- [ ] **Step 1: Add the import for RANGE_INTERVAL at the top of servers.py**

In `backend/app/routers/servers.py`, find the existing imports block. Add:

```python
from app.services.metric_catalog import RANGE_INTERVAL
```

- [ ] **Step 2: Add the endpoint**

After the existing `get_server_services` endpoint (around line 320), add:

```python
@router.get("/api/servers/{server_id}/kernel-events")
async def get_kernel_events(
    server_id: str,
    range: str = Query("24h"),
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _get_accessible_server(server_id, user, db)

    if range not in RANGE_INTERVAL:
        raise HTTPException(
            400,
            detail={"error": "bad_range", "message": f"range must be one of {sorted(RANGE_INTERVAL)}"},
        )

    interval = RANGE_INTERVAL[range]

    counts_result = await db.execute(
        text("""
            SELECT severity, COUNT(*) AS cnt
            FROM server_logs
            WHERE server_id = :sid
              AND source = 'kernel'
              AND time >= now() - INTERVAL :interval
            GROUP BY severity
        """),
        {"sid": server_id, "interval": interval},
    )
    raw_counts: dict[str, int] = {row.severity: int(row.cnt) for row in counts_result}

    events_result = await db.execute(
        text("""
            SELECT time, severity, message
            FROM server_logs
            WHERE server_id = :sid
              AND source = 'kernel'
              AND time >= now() - INTERVAL :interval
            ORDER BY time DESC
            LIMIT 50
        """),
        {"sid": server_id, "interval": interval},
    )

    return {
        "counts": {
            "emerg": raw_counts.get("emerg", 0),
            "alert": raw_counts.get("alert", 0),
            "crit": raw_counts.get("crit", 0),
            "err": raw_counts.get("err", 0),
            "warn": raw_counts.get("warn", 0),
        },
        "events": [
            {
                "ts": row.time.isoformat(),
                "severity": row.severity or "warn",
                "message": row.message or "",
            }
            for row in events_result
        ],
    }
```

Note: `CurrentUser` is already imported from `app.deps` at the top of `servers.py` — it is an `Annotated` type alias that wraps the dependency. Do not use `Depends(get_current_user)` — `CurrentUser` alone is the correct pattern (matches every other endpoint in this file). `Query` is from `fastapi` — if not yet imported, add it: `from fastapi import APIRouter, Depends, HTTPException, Query`.

- [ ] **Step 3: Smoke test the endpoint**

```bash
# Get a valid token first (login)
TOKEN=$(curl -s -X POST http://localhost:9090/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin@example.com","password":"yourpassword"}' | jq -r '.access_token')

# Get a server ID from the servers list
SERVER_ID=$(curl -s http://localhost:9090/api/servers \
  -H "Authorization: Bearer $TOKEN" | jq -r '.servers[0].id')

# Hit the new endpoint
curl -s "http://localhost:9090/api/servers/$SERVER_ID/kernel-events?range=24h" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

Expected response shape:
```json
{
  "counts": { "emerg": 0, "alert": 0, "crit": 0, "err": 0, "warn": 0 },
  "events": []
}
```

(Empty is correct — no kernel data yet. Non-200 is a failure.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/servers.py
git commit -m "feat: add GET /api/servers/{id}/kernel-events endpoint"
```

---

## Task 5: Frontend API function + types

**Files:**
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Add the type and function**

At the end of `frontend/src/services/api.ts`, add:

```typescript
export interface KernelEventsResponse {
  counts: { emerg: number; alert: number; crit: number; err: number; warn: number }
  events: Array<{ ts: string; severity: string; message: string }>
}

export async function getKernelEvents(
  serverId: string,
  range: string,
): Promise<KernelEventsResponse> {
  const { data } = await axios.get<KernelEventsResponse>(
    `/api/servers/${serverId}/kernel-events`,
    { params: { range } },
  )
  return data
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend \
  npx vue-tsc --noEmit 2>&1 | tail -10
```

Expected: No errors related to the new code.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat: add getKernelEvents API function and KernelEventsResponse type"
```

---

## Task 6: KernelEventsCard.vue component

**Files:**
- Create: `frontend/src/components/servers/tabs/KernelEventsCard.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getKernelEvents, type KernelEventsResponse } from '@/services/api'
import type { MetricRange } from '@/types'

const props = defineProps<{ serverId: string; range: MetricRange }>()
const router = useRouter()

const loading = ref(false)
const data = ref<KernelEventsResponse | null>(null)
const error = ref(false)

async function load() {
  if (!props.serverId) return
  loading.value = true
  error.value = false
  try {
    data.value = await getKernelEvents(props.serverId, props.range)
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.range, load)

function viewAll() {
  router.push({ query: { tab: 'Logs', source: 'kernel' } })
}

const rangeLabel = computed(() => props.range)

const hasEvents = computed(() => (data.value?.events?.length ?? 0) > 0)

function severityBg(sev: string): string {
  if (['emerg', 'alert', 'crit'].includes(sev)) return '#3d1f1f'
  if (sev === 'err') return '#3d2e1f'
  return '#2a2920'
}
function severityColor(sev: string): string {
  if (['emerg', 'alert', 'crit'].includes(sev)) return '#e74c3c'
  if (sev === 'err') return '#f39c12'
  return '#f1c40f'
}
function fmtTime(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
function truncate(msg: string): string {
  return msg.length > 120 ? msg.slice(0, 120) + '…' : msg
}
</script>

<template>
  <section class="card">
    <div class="ke-header">
      <h3>⚡ Kernel Events</h3>
      <button class="ke-view-all" @click="viewAll">View all in Logs →</button>
    </div>

    <template v-if="loading">
      <div class="ke-skeleton" v-for="i in 3" :key="i" />
    </template>

    <div v-else-if="error" class="ke-empty">Failed to load kernel events</div>

    <template v-else-if="data">
      <div class="ke-strip">
        <div class="ke-tile ke-red">
          <span class="ke-num">{{ (data.counts.emerg ?? 0) + (data.counts.alert ?? 0) }}</span>
          <span class="ke-lbl">emerg/alert</span>
        </div>
        <div class="ke-tile ke-red">
          <span class="ke-num">{{ data.counts.crit ?? 0 }}</span>
          <span class="ke-lbl">crit</span>
        </div>
        <div class="ke-tile ke-orange">
          <span class="ke-num">{{ data.counts.err ?? 0 }}</span>
          <span class="ke-lbl">err</span>
        </div>
        <div class="ke-tile ke-yellow">
          <span class="ke-num">{{ data.counts.warn ?? 0 }}</span>
          <span class="ke-lbl">warn</span>
        </div>
      </div>

      <template v-if="hasEvents">
        <div class="ke-section-lbl">Recent events (last {{ rangeLabel }})</div>
        <div class="ke-list">
          <div class="ke-row" v-for="(ev, i) in data.events" :key="i">
            <span
              class="ke-badge"
              :style="{ background: severityBg(ev.severity), color: severityColor(ev.severity) }"
            >{{ ev.severity }}</span>
            <span class="ke-time">{{ fmtTime(ev.ts) }}</span>
            <span class="ke-msg" :title="ev.message">{{ truncate(ev.message) }}</span>
          </div>
        </div>
      </template>

      <div v-else class="ke-empty">✓ No kernel warnings or errors in the last {{ rangeLabel }}</div>
    </template>
  </section>
</template>

<style scoped>
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.ke-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.ke-header h3 { font-size: 13px; color: var(--text); font-weight: 600; margin: 0; }
.ke-view-all { background: none; border: none; color: var(--accent-2); font-size: 12px; cursor: pointer; padding: 0; }
.ke-view-all:hover { text-decoration: underline; }

.ke-strip { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 16px; }
.ke-tile { border-radius: 6px; padding: 8px 10px; text-align: center; border: 1px solid transparent; display: flex; flex-direction: column; align-items: center; }
.ke-tile.ke-red { background: #2d1f1f; border-color: #5a2020; }
.ke-tile.ke-orange { background: #2d2414; border-color: #5a4020; }
.ke-tile.ke-yellow { background: #2a2920; border-color: #4a4820; }
.ke-num { font-size: 20px; font-weight: 700; line-height: 1.2; }
.ke-tile.ke-red .ke-num { color: #e74c3c; }
.ke-tile.ke-orange .ke-num { color: #f39c12; }
.ke-tile.ke-yellow .ke-num { color: #f1c40f; }
.ke-lbl { font-size: 9px; text-transform: uppercase; letter-spacing: .5px; margin-top: 2px; }
.ke-tile.ke-red .ke-lbl { color: #e74c3c; }
.ke-tile.ke-orange .ke-lbl { color: #f39c12; }
.ke-tile.ke-yellow .ke-lbl { color: #f1c40f; }

.ke-section-lbl { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; margin-bottom: 8px; }
.ke-list { display: flex; flex-direction: column; }
.ke-row { display: flex; align-items: flex-start; gap: 8px; padding: 7px 0; border-bottom: 1px solid var(--border); }
.ke-row:last-child { border-bottom: none; }
.ke-badge { padding: 2px 6px; border-radius: 3px; font-size: 9px; white-space: nowrap; min-width: 36px; text-align: center; margin-top: 1px; font-family: monospace; }
.ke-time { color: var(--muted); font-size: 10px; white-space: nowrap; margin-top: 2px; }
.ke-msg { color: var(--text); font-size: 11px; line-height: 1.4; font-family: monospace; word-break: break-all; }

.ke-empty { text-align: center; padding: 24px 0; color: var(--muted); font-size: 12px; }
.ke-skeleton { height: 28px; background: var(--border); border-radius: 4px; margin-bottom: 6px; animation: pulse 1.5s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }
</style>
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend \
  npx vue-tsc --noEmit 2>&1 | tail -10
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/servers/tabs/KernelEventsCard.vue
git commit -m "feat: add KernelEventsCard component (summary strip + event list)"
```

---

## Task 7: Wire KernelEventsCard into SystemTab + pre-select kernel in LogsTab

**Files:**
- Modify: `frontend/src/components/servers/tabs/SystemTab.vue`
- Modify: `frontend/src/components/servers/tabs/LogsTab.vue`

- [ ] **Step 1: Add KernelEventsCard to SystemTab.vue**

In `frontend/src/components/servers/tabs/SystemTab.vue`:

Add import at the top of `<script setup>`:
```typescript
import KernelEventsCard from './KernelEventsCard.vue'
```

In the `<template>`, after the closing `</section>` of the System Info card (around line 113), add:

```html
    <KernelEventsCard
      v-if="metrics.activeServerId"
      :server-id="metrics.activeServerId"
      :range="metrics.rangeFor('System')"
    />
```

- [ ] **Step 2: Pre-select kernel source in LogsTab from query param**

In `frontend/src/components/servers/tabs/LogsTab.vue`:

Add `useRoute` to the vue-router import at the top of `<script setup>`:
```typescript
import { useRoute } from 'vue-router'
const route = useRoute()
```

In `onMounted`, after `logs.setFilter('serverIds', [serverId.value])`, add:
```typescript
  if (route.query.source === 'kernel') {
    logs.setFilter('sources', ['kernel'])
  }
```

So the full `onMounted` block becomes:
```typescript
onMounted(async () => {
  unbindWs = wsClient.on(handleWsMessage)
  logs.reset()
  if (!serverId.value) return
  logs.setFilter('serverIds', [serverId.value])
  if (route.query.source === 'kernel') {
    logs.setFilter('sources', ['kernel'])
  }
  await reload()
})
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend \
  npx vue-tsc --noEmit 2>&1 | tail -10
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/servers/tabs/SystemTab.vue \
        frontend/src/components/servers/tabs/LogsTab.vue
git commit -m "feat: wire KernelEventsCard into System tab, pre-select kernel source in Logs tab"
```

---

## Task 8: Add "Reconfigure agents" button to InfoTab

Existing servers were onboarded before the kmsg block existed. They need Fluent Bit reconfigured to start collecting kernel logs. The `/api/servers/{id}/redeploy` endpoint already exists and re-runs configure steps 6+7. The InfoTab just needs a button.

**Files:**
- Modify: `frontend/src/components/servers/tabs/InfoTab.vue`

- [ ] **Step 1: Add the redeploy call and button to InfoTab**

In `frontend/src/components/servers/tabs/InfoTab.vue`, add to the `<script setup>` imports:

```typescript
import { useServerStore } from '@/stores/server'
const serverStore = useServerStore()
const redeploying = ref(false)
const redeployDone = ref(false)

async function redeployAgents() {
  const id = metrics.activeServerId
  if (!id) return
  redeploying.value = true
  redeployDone.value = false
  try {
    await serverStore.redeploy(id)
    redeployDone.value = true
  } finally {
    redeploying.value = false
  }
}
```

Note: `ref` is already imported in InfoTab. If `useServerStore` is not imported, add: `import { useServerStore } from '@/stores/server'`.

In the `<template>`, find the last `<section class="card">` block (the one showing network interfaces or disk info). Add a new card after it — admin-only:

```html
    <section v-if="isAdmin" class="card">
      <h3>Agent Management</h3>
      <p class="agent-desc">Re-pushes Telegraf and Fluent Bit configuration to this server. Use this after upgrading OpsPilot to enable new collection features (e.g. kernel log collection).</p>
      <button class="agent-btn" :disabled="redeploying" @click="redeployAgents">
        {{ redeploying ? 'Reconfiguring…' : redeployDone ? 'Done ✓' : 'Reconfigure Agents' }}
      </button>
    </section>
```

To expose `isAdmin`, add to `<script setup>`:
```typescript
import { useAuthStore } from '@/stores/auth'
const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')
```

Add styles to `<style scoped>`:
```css
.agent-desc { font-size: 12px; color: var(--muted); margin-bottom: 12px; line-height: 1.5; }
.agent-btn { background: var(--surface); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 7px 14px; font-size: 12px; cursor: pointer; }
.agent-btn:hover:not(:disabled) { border-color: var(--accent-2); color: var(--accent-2); }
.agent-btn:disabled { opacity: 0.5; cursor: not-allowed; }
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend \
  npx vue-tsc --noEmit 2>&1 | tail -10
```

Expected: No errors.

- [ ] **Step 3: Smoke test the button**

Open the app → any server → Info tab. Scroll to the bottom. Verify:
- The "Reconfigure Agents" button appears for admin users
- Clicking it shows "Reconfiguring…" then "Done ✓"
- Backend logs show the onboarding steps re-running

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/servers/tabs/InfoTab.vue
git commit -m "feat: add Reconfigure Agents button to InfoTab for pushing updated Fluent Bit config"
```

---

## Task 9: Smoke test, update progress, release

- [ ] **Step 1: Open the app and navigate to a server → System tab**

Open http://localhost:9090, log in, open any server detail → System tab. Scroll to the bottom. Verify:
- The "⚡ Kernel Events" card is visible
- 4 count tiles render (all 0 is expected until dmesg poll runs or kmsg data arrives)
- "View all in Logs →" button is visible

- [ ] **Step 2: Trigger a manual dmesg poll**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend \
  python -c "
import asyncio
from app.services.dmesg_collector import collect_dmesg
asyncio.run(collect_dmesg())
print('done')
"
```

Expected: `done` with possible log lines like `dmesg: inserted N kernel events for server <id>`

- [ ] **Step 3: Verify kernel events appear in the UI**

Reload the System tab in the browser. The count tiles should now reflect any kernel messages from the server. Click "View all in Logs →" — verify it switches to the Logs tab with the kernel source chip pre-selected.

- [ ] **Step 4: Verify the API endpoint directly**

```bash
TOKEN=$(curl -s -X POST http://localhost:9090/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"<your-admin-email>","password":"<your-password>"}' | jq -r '.access_token')

SERVER_ID=$(curl -s http://localhost:9090/api/servers \
  -H "Authorization: Bearer $TOKEN" | jq -r '.servers[0].id')

curl -s "http://localhost:9090/api/servers/$SERVER_ID/kernel-events?range=7d" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

Expected: `counts` object with non-negative integers, `events` array.

- [ ] **Step 5: Update PROGRESS.md and DASHBOARD.html**

In `PROGRESS.md`, mark the dmesg/kernel events task as done (⬜ → ✅).

In `DASHBOARD.html`, set the matching task's `status: 'pending'` → `status: 'done'` and update `LAST_UPDATED`.

- [ ] **Step 6: Commit progress update**

```bash
git add PROGRESS.md DASHBOARD.html
git commit -m "feat: dmesg kernel events — smoke tested and complete"
```

- [ ] **Step 7: Tag and push release**

```bash
# Check latest tag
git describe --tags --abbrev=0

# Bump patch (e.g. v1.2.13 → v1.2.14 — use the actual next version)
git tag v1.2.14
git push origin main
git push origin v1.2.14
```
