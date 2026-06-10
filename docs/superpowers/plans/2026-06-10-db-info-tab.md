# Database Info Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Info" tab to the database monitoring page that shows a live-queried snapshot of database, server, connection, storage, replication, and backup information alongside the existing Metrics tab.

**Architecture:** A new backend endpoint (`GET /api/servers/{server_id}/db-info`) connects directly to the monitored database on demand (using `aiomysql` for MySQL/MariaDB, `asyncpg` for PostgreSQL), merges the result with existing server/Telegraf/job data, and returns a single JSON object. The frontend adds a Metrics/Info tab bar to `DatabasesView.vue` and renders a new `DbInfoPanel.vue` component when the Info tab is active.

**Tech Stack:** FastAPI + aiomysql + asyncpg (backend), Vue 3 + Pinia (frontend)

**Spec:** `docs/superpowers/specs/2026-06-10-db-info-tab-design.md`

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| **Modify** | `backend/requirements.txt` | Add `aiomysql==0.2.0` |
| **Create** | `backend/app/routers/db_info.py` | Live-query endpoint + helper functions |
| **Modify** | `backend/app/main.py` | Register `db_info_router` |
| **Modify** | `frontend/src/stores/databases.ts` | Add `DbInfoData` type + `fetchDbInfo` action |
| **Create** | `frontend/src/components/databases/DbInfoPanel.vue` | Info tab UI — all 6 sections |
| **Modify** | `frontend/src/views/databases/DatabasesView.vue` | Add Metrics/Info tab bar + conditional render |

---

## Task 1: Add aiomysql dependency

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add the dependency**

Open `backend/requirements.txt` and add after the `asyncpg` line:
```
aiomysql==0.2.0
```

- [ ] **Step 2: Install inside the backend container**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend pip install aiomysql==0.2.0
```

Expected: `Successfully installed aiomysql-0.2.0` (or "already satisfied").

- [ ] **Step 3: Verify import works**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend python -c "import aiomysql; print('ok')"
```

Expected output: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt
git commit -m "feat: add aiomysql dependency for db-info live queries"
```

---

## Task 2: Create the db-info backend endpoint

**Files:**
- Create: `backend/app/routers/db_info.py`

This file exposes `GET /api/servers/{server_id}/db-info?credential_id={id}`.
It reuses `_get_credential_by_id` and `_resolve_label` from `app.routers.databases`
and `decrypt` from `app.core.crypto`.

- [ ] **Step 1: Create `backend/app/routers/db_info.py`**

```python
"""On-demand live database info endpoint (spec: 2026-06-10-db-info-tab-design.md).

Connects directly to the monitored database to collect version, charset, sizes,
SSL status, and storage info.  Static fields (host, port, type) come from the
stored credential.  Server hardware info (CPU, RAM, disk) comes from the
existing Telegraf server_metrics table.  Backup info comes from MonitoredJob.

Timeout: 5 s on the live DB connection — if unreachable, returns reachable=false
with static fields only; never raises 5xx for a down database.
"""
from __future__ import annotations

import logging

import asyncpg
import aiomysql
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt
from app.database import get_db
from app.deps import CurrentUser
from app.models.other import DBCredential, MonitoredJob
from app.models.server import Server
from app.routers.databases import _assert_server_access, _get_credential_by_id, _resolve_label

logger = logging.getLogger(__name__)
router = APIRouter(tags=["databases"])

_LIVE_TIMEOUT = 5  # seconds


# ── Live query helpers ────────────────────────────────────────────────────────

async def _query_mysql(host: str, port: int, user: str, password: str) -> dict:
    """Connect to MySQL/MariaDB and collect info fields. Returns reachable=False on any error."""
    try:
        conn = await aiomysql.connect(
            host=host, port=port, user=user, password=password,
            connect_timeout=_LIVE_TIMEOUT,
        )
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SHOW GLOBAL VARIABLES WHERE Variable_name IN "
                "('version','datadir','character_set_server','collation_server','time_zone')"
            )
            variables = {r["Variable_name"]: r["Value"] for r in await cur.fetchall()}

            await cur.execute(
                "SHOW GLOBAL STATUS WHERE Variable_name IN ('Uptime','Ssl_cipher')"
            )
            status = {r["Variable_name"]: r["Value"] for r in await cur.fetchall()}

            await cur.execute(
                "SELECT COALESCE(SUM(data_length + index_length), 0) AS b "
                "FROM information_schema.tables"
            )
            total_size = (await cur.fetchone() or {}).get("b")

            await cur.execute(
                "SELECT COUNT(DISTINCT table_schema) AS n FROM information_schema.tables "
                "WHERE table_schema NOT IN ('information_schema','performance_schema','mysql','sys')"
            )
            db_count = (await cur.fetchone() or {}).get("n")

            await cur.execute(
                "SELECT COUNT(*) AS n FROM information_schema.tables "
                "WHERE table_schema NOT IN ('information_schema','performance_schema','mysql','sys')"
            )
            table_count = (await cur.fetchone() or {}).get("n")

            await cur.execute(
                "SELECT table_schema AS name, SUM(data_length + index_length) AS sz "
                "FROM information_schema.tables "
                "WHERE table_schema NOT IN ('information_schema','performance_schema','mysql','sys') "
                "GROUP BY table_schema ORDER BY sz DESC LIMIT 1"
            )
            largest_db = await cur.fetchone()

            await cur.execute(
                "SELECT CONCAT(table_schema,'.',table_name) AS name, "
                "(data_length + index_length) AS sz "
                "FROM information_schema.tables "
                "WHERE table_schema NOT IN ('information_schema','performance_schema','mysql','sys') "
                "ORDER BY sz DESC LIMIT 1"
            )
            largest_table = await cur.fetchone()

        conn.close()
        ssl_cipher = status.get("Ssl_cipher", "")
        return {
            "reachable": True,
            "version": variables.get("version"),
            "data_directory": variables.get("datadir"),
            "character_set": variables.get("character_set_server"),
            "collation": variables.get("collation_server"),
            "time_zone": variables.get("time_zone"),
            "uptime_seconds": int(status["Uptime"]) if status.get("Uptime") else None,
            "ssl_enabled": bool(ssl_cipher),
            "ssl_version": ssl_cipher or None,
            "size_bytes": int(total_size) if total_size is not None else None,
            "total_databases": int(db_count) if db_count is not None else None,
            "total_tables": int(table_count) if table_count is not None else None,
            "largest_db": {"name": largest_db["name"], "size_bytes": int(largest_db["sz"])} if largest_db and largest_db["sz"] else None,
            "largest_table": {"name": largest_table["name"], "size_bytes": int(largest_table["sz"])} if largest_table and largest_table["sz"] else None,
        }
    except Exception:  # noqa: BLE001
        logger.warning("db_info: mysql query failed for %s:%s", host, port)
        return {"reachable": False}


async def _query_postgres(host: str, port: int, user: str, password: str) -> dict:
    """Connect to PostgreSQL and collect info fields. Returns reachable=False on any error."""
    try:
        conn = await asyncpg.connect(
            host=host, port=port, user=user, password=password,
            database="postgres", timeout=_LIVE_TIMEOUT,
        )
        version = await conn.fetchval("SELECT version()")
        data_dir = await conn.fetchval("SHOW data_directory")
        encoding = await conn.fetchval("SHOW server_encoding")
        collation = await conn.fetchval("SHOW lc_collate")
        timezone = await conn.fetchval("SHOW TimeZone")
        uptime_sec = await conn.fetchval(
            "SELECT EXTRACT(EPOCH FROM (NOW() - pg_postmaster_start_time()))::bigint"
        )
        ssl_row = await conn.fetchrow(
            "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
        )
        total_size = await conn.fetchval(
            "SELECT COALESCE(SUM(pg_database_size(datname)),0) "
            "FROM pg_database WHERE datistemplate = false"
        )
        db_count = await conn.fetchval(
            "SELECT COUNT(*) FROM pg_database WHERE datistemplate = false"
        )
        table_count = await conn.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog','information_schema')"
        )
        largest_db = await conn.fetchrow(
            "SELECT datname AS name, pg_database_size(datname) AS sz "
            "FROM pg_database WHERE datistemplate = false ORDER BY sz DESC LIMIT 1"
        )
        largest_table = await conn.fetchrow(
            "SELECT schemaname || '.' || relname AS name, "
            "pg_total_relation_size(relid) AS sz "
            "FROM pg_stat_user_tables ORDER BY sz DESC LIMIT 1"
        )
        await conn.close()

        ssl_on = bool(ssl_row and ssl_row["ssl"])
        return {
            "reachable": True,
            "version": version,
            "data_directory": data_dir,
            "character_set": encoding,
            "collation": collation,
            "time_zone": timezone,
            "uptime_seconds": int(uptime_sec) if uptime_sec is not None else None,
            "ssl_enabled": ssl_on,
            "ssl_version": "Enabled" if ssl_on else None,
            "size_bytes": int(total_size) if total_size is not None else None,
            "total_databases": int(db_count) if db_count is not None else None,
            "total_tables": int(table_count) if table_count is not None else None,
            "largest_db": {"name": largest_db["name"], "size_bytes": int(largest_db["sz"])} if largest_db else None,
            "largest_table": {"name": largest_table["name"], "size_bytes": int(largest_table["sz"])} if largest_table else None,
        }
    except Exception:  # noqa: BLE001
        logger.warning("db_info: postgres query failed for %s:%s", host, port)
        return {"reachable": False}


async def _get_server_hw(db: AsyncSession, server_id: str) -> dict:
    """Latest hardware metrics from Telegraf (CPU, RAM, disk)."""
    rows = (
        await db.execute(
            text("""
                SELECT DISTINCT ON (metric_name) metric_name, value
                FROM server_metrics
                WHERE server_id = :sid
                  AND metric_name IN ('system.n_cpus','mem.total','disk.total','disk.free')
                  AND time >= now() - INTERVAL '10 minutes'
                ORDER BY metric_name, time DESC
            """),
            {"sid": str(server_id)},
        )
    ).all()
    return {m: v for m, v, in rows if v is not None}


async def _get_conn_metrics(
    db: AsyncSession, server_id: str, label: str, db_type: str
) -> dict:
    """Current and max connections from the latest Telegraf metrics."""
    if db_type == "postgres":
        metric_cur = "postgresql.numbackends"
        metric_max = None
    else:
        metric_cur = "mysql.threads_connected"
        metric_max = "mysql.max_connections"

    wanted = [m for m in [metric_cur, metric_max] if m]
    rows = (
        await db.execute(
            text("""
                SELECT DISTINCT ON (metric_name) metric_name, value
                FROM server_metrics
                WHERE server_id = :sid
                  AND metric_name = ANY(:metrics)
                  AND (labels->>'db_label' = :label OR labels->>'db_label' IS NULL)
                  AND time >= now() - INTERVAL '10 minutes'
                ORDER BY metric_name, time DESC
            """),
            {"sid": str(server_id), "metrics": wanted, "label": label},
        )
    ).all()
    vals = {m: v for m, v in rows if v is not None}
    return {
        "current": int(vals[metric_cur]) if metric_cur in vals else None,
        "max": int(vals[metric_max]) if metric_max and metric_max in vals else None,
    }


async def _get_backup(db: AsyncSession, server_id: str) -> dict | None:
    """Latest MonitoredJob record for this server (first by last_ping_at desc)."""
    job = await db.scalar(
        select(MonitoredJob)
        .where(MonitoredJob.server_id == server_id)
        .order_by(MonitoredJob.last_ping_at.desc().nulls_last())
        .limit(1)
    )
    if not job:
        return None
    return {
        "last_run_at": job.last_ping_at.isoformat() if job.last_ping_at else None,
        "status": job.status,
        "size_bytes": job.last_size_bytes,
    }


async def _get_replication(
    db: AsyncSession, server_id: str, label: str, cred: DBCredential
) -> dict:
    """Replication status from Telegraf metrics."""
    if cred.db_type == "postgres":
        metric_running = "postgresql.replication_delay"
        metric_lag = "postgresql.replication_delay"
    else:
        metric_running = "mariadb.replication_running"
        metric_lag = "mariadb.seconds_behind_master"

    rows = (
        await db.execute(
            text("""
                SELECT DISTINCT ON (metric_name) metric_name, value
                FROM server_metrics
                WHERE server_id = :sid
                  AND metric_name IN (:m_run, :m_lag)
                  AND (labels->>'db_label' = :label OR labels->>'db_label' IS NULL)
                  AND time >= now() - INTERVAL '10 minutes'
                ORDER BY metric_name, time DESC
            """),
            {"sid": str(server_id), "m_run": metric_running, "m_lag": metric_lag, "label": label},
        )
    ).all()
    vals = {m: v for m, v in rows if v is not None}

    role = "replica" if cred.is_replica else "primary"
    if cred.db_type == "postgres":
        lag = float(vals.get(metric_lag, 0)) if vals.get(metric_lag) is not None else None
        running = lag is not None
    else:
        running_v = vals.get(metric_running)
        running = bool(running_v) if running_v is not None else None
        lag_v = vals.get(metric_lag)
        lag = float(lag_v) if lag_v is not None else None

    return {"role": role, "running": running, "lag_sec": lag}


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/api/servers/{server_id}/db-info")
async def get_db_info(
    server_id: str,
    user: CurrentUser,
    credential_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Live database information snapshot for the Info tab."""
    await _assert_server_access(server_id, user, db)
    cred = await _get_credential_by_id(credential_id, server_id, db)
    password = decrypt(cred.password_encrypted)
    label = _resolve_label(cred)

    server = await db.scalar(select(Server).where(Server.id == server_id))

    if cred.db_type == "postgres":
        live = await _query_postgres(cred.host, cred.port, cred.username, password)
    else:
        live = await _query_mysql(cred.host, cred.port, cred.username, password)

    hw = await _get_server_hw(db, server_id)
    conn_metrics = await _get_conn_metrics(db, server_id, label, cred.db_type)
    backup = await _get_backup(db, server_id)
    replication = await _get_replication(db, server_id, label, cred)

    return {
        "reachable": live.get("reachable", False),
        "db": {
            "type": cred.db_type,
            "version": live.get("version"),
            "host": cred.host,
            "port": cred.port,
            "uptime_seconds": live.get("uptime_seconds"),
            "data_directory": live.get("data_directory"),
            "character_set": live.get("character_set"),
            "collation": live.get("collation"),
            "time_zone": live.get("time_zone"),
            "size_bytes": live.get("size_bytes"),
        },
        "server": {
            "name": server.name if server else None,
            "os": server.os_distro if server else None,
            "cpu_cores": int(hw["system.n_cpus"]) if "system.n_cpus" in hw else None,
            "ram_bytes": int(hw["mem.total"]) if "mem.total" in hw else None,
            "disk_total_bytes": int(hw["disk.total"]) if "disk.total" in hw else None,
            "disk_free_bytes": int(hw["disk.free"]) if "disk.free" in hw else None,
        },
        "connections": {
            "current": conn_metrics["current"],
            "max": conn_metrics["max"],
            "ssl_enabled": live.get("ssl_enabled", False),
            "ssl_version": live.get("ssl_version"),
        },
        "storage": {
            "total_databases": live.get("total_databases"),
            "total_tables": live.get("total_tables"),
            "largest_db": live.get("largest_db"),
            "largest_table": live.get("largest_table"),
            "used_bytes": live.get("size_bytes"),
            "free_bytes": int(hw["disk.free"]) if "disk.free" in hw else None,
        },
        "replication": replication,
        "backup": backup,
    }
```

- [ ] **Step 2: Verify the file parses without errors**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend python -c "from app.routers.db_info import router; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/db_info.py
git commit -m "feat: add db-info live query endpoint"
```

---

## Task 3: Register the router in main.py

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add the import** (after the `databases_router` import on line ~30)

```python
from app.routers.db_info import router as db_info_router
```

- [ ] **Step 2: Register the router** (after `app.include_router(databases_router)` on line ~121)

```python
app.include_router(db_info_router)
```

- [ ] **Step 3: Smoke-test the endpoint is reachable**

```bash
curl -s http://localhost:9090/api/servers/00000000-0000-0000-0000-000000000000/db-info?credential_id=test 2>&1 | head -5
```

Expected: a JSON error response (401 or 404), NOT a 404 "route not found". This confirms the route registered correctly.

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: register db_info router"
```

---

## Task 4: Add DbInfoData type and fetchDbInfo to the store

**Files:**
- Modify: `frontend/src/stores/databases.ts`

- [ ] **Step 1: Add the `DbInfoData` interface** after the `DbSeriesResponse` interface (around line 69 in `databases.ts`)

```typescript
export interface DbInfoData {
  reachable: boolean
  db: {
    type: string
    version: string | null
    host: string
    port: number
    uptime_seconds: number | null
    data_directory: string | null
    character_set: string | null
    collation: string | null
    time_zone: string | null
    size_bytes: number | null
  }
  server: {
    name: string | null
    os: string | null
    cpu_cores: number | null
    ram_bytes: number | null
    disk_total_bytes: number | null
    disk_free_bytes: number | null
  }
  connections: {
    current: number | null
    max: number | null
    ssl_enabled: boolean
    ssl_version: string | null
  }
  storage: {
    total_databases: number | null
    total_tables: number | null
    largest_db: { name: string; size_bytes: number } | null
    largest_table: { name: string; size_bytes: number } | null
    used_bytes: number | null
    free_bytes: number | null
  }
  replication: {
    role: string
    running: boolean | null
    lag_sec: number | null
  }
  backup: {
    last_run_at: string | null
    status: string | null
    size_bytes: number | null
  } | null
}
```

- [ ] **Step 2: Add the `fetchDbInfo` action** inside `useDatabaseStore`, after the `fetchPassword` function

```typescript
async function fetchDbInfo(serverId: string, credentialId: string): Promise<DbInfoData> {
  const { data } = await api.get<DbInfoData>(`/api/servers/${serverId}/db-info`, {
    params: { credential_id: credentialId },
  })
  return data
}
```

- [ ] **Step 3: Export `fetchDbInfo`** — add it to the return object of the store (alongside `fetchLatest`, `fetchSeries`, `fetchPassword`)

```typescript
return {
  // … existing exports …
  fetchDbInfo,
}
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/databases.ts
git commit -m "feat: add DbInfoData type and fetchDbInfo store action"
```

---

## Task 5: Create DbInfoPanel.vue

**Files:**
- Create: `frontend/src/components/databases/DbInfoPanel.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useDatabaseStore } from '@/stores/databases'
import type { DbInfoData } from '@/stores/databases'

const props = defineProps<{
  serverId: string
  credentialId: string
}>()

const store = useDatabaseStore()
const info = ref<DbInfoData | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const fetchedAt = ref<Date | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    info.value = await store.fetchDbInfo(props.serverId, props.credentialId)
    fetchedAt.value = new Date()
  } catch {
    error.value = 'Could not load database info.'
  } finally {
    loading.value = false
  }
}

onMounted(load)

function fmtUptime(sec: number | null): string {
  if (sec == null) return '—'
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const parts: string[] = []
  if (d) parts.push(`${d}d`)
  if (h) parts.push(`${h}h`)
  if (m) parts.push(`${m}m`)
  return parts.length ? parts.join(' ') : '< 1m'
}

function fmtBytes(b: number | null): string {
  if (b == null) return '—'
  if (b >= 1_073_741_824) return `${(b / 1_073_741_824).toFixed(1)} GB`
  if (b >= 1_048_576) return `${(b / 1_048_576).toFixed(1)} MB`
  if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${b} B`
}

function fmtDbType(t: string): string {
  if (t === 'postgres') return 'PostgreSQL'
  if (t === 'mysql') return 'MySQL / MariaDB'
  return t
}

const connPct = computed(() => {
  const c = info.value?.connections
  if (!c?.current || !c?.max) return null
  return Math.round((c.current / c.max) * 100)
})

const connAccent = computed(() => {
  const p = connPct.value
  if (p == null) return 'ok'
  if (p > 80) return 'danger'
  if (p > 60) return 'warn'
  return 'ok'
})

const backupStatusLabel = computed(() => {
  const s = info.value?.backup?.status
  if (!s) return '—'
  if (s === 'healthy') return 'Success'
  if (s === 'late') return 'Late'
  if (s === 'failed') return 'Failed'
  return s
})

const backupStatusClass = computed(() => {
  const s = info.value?.backup?.status
  if (s === 'healthy') return 'ok'
  if (s === 'late') return 'warn'
  return 'err'
})

const replStatusLabel = computed(() => {
  const r = info.value?.replication
  if (!r) return '—'
  if (r.running === null) return '—'
  return r.running ? 'Running' : 'Stopped'
})

const replStatusClass = computed(() => {
  const r = info.value?.replication
  if (!r || r.running === null) return 'muted'
  return r.running ? 'ok' : 'err'
})

function fmtFetchedAt(): string {
  if (!fetchedAt.value) return ''
  const secs = Math.floor((Date.now() - fetchedAt.value.getTime()) / 1000)
  if (secs < 10) return 'just now'
  if (secs < 60) return `${secs}s ago`
  return `${Math.floor(secs / 60)}m ago`
}
</script>

<template>
  <div class="info-panel">
    <!-- Unreachable banner -->
    <div v-if="info && !info.reachable" class="banner warn">
      Could not connect to database — showing cached data only
    </div>

    <!-- Error state -->
    <div v-if="error" class="banner err">{{ error }}</div>

    <!-- Loading skeleton -->
    <div v-if="loading" class="skeleton-grid">
      <div v-for="i in 6" :key="i" class="skeleton-block"></div>
    </div>

    <!-- Content -->
    <template v-if="!loading && info">
      <div class="grid">

        <!-- 1. Database Information -->
        <div class="block">
          <div class="block-hd db">🗄 Database Information</div>
          <div class="rows">
            <div class="row"><span class="k">Type</span><span class="v">{{ fmtDbType(info.db.type) }}</span></div>
            <div class="row"><span class="k">Version</span><span class="v">{{ info.db.version ?? '—' }}</span></div>
            <div class="row"><span class="k">Hostname</span><span class="v">{{ info.db.host }}</span></div>
            <div class="row"><span class="k">Port</span><span class="v">{{ info.db.port }}</span></div>
            <div class="row"><span class="k">Uptime</span><span class="v">{{ fmtUptime(info.db.uptime_seconds) }}</span></div>
            <div class="row"><span class="k">Data Directory</span><span class="v mono">{{ info.db.data_directory ?? '—' }}</span></div>
            <div class="row"><span class="k">Character Set</span><span class="v">{{ info.db.character_set ?? '—' }}</span></div>
            <div class="row"><span class="k">Collation</span><span class="v">{{ info.db.collation ?? '—' }}</span></div>
            <div class="row"><span class="k">Time Zone</span><span class="v">{{ info.db.time_zone ?? '—' }}</span></div>
            <div class="row"><span class="k">Database Size</span><span class="v">{{ fmtBytes(info.db.size_bytes) }}</span></div>
          </div>
        </div>

        <!-- 2. Server Information -->
        <div class="block">
          <div class="block-hd srv">🖥 Server Information</div>
          <div class="rows">
            <div class="row"><span class="k">Server Name</span><span class="v">{{ info.server.name ?? '—' }}</span></div>
            <div class="row"><span class="k">Operating System</span><span class="v">{{ info.server.os ?? '—' }}</span></div>
            <div class="row"><span class="k">CPU Cores</span><span class="v">{{ info.server.cpu_cores ?? '—' }}</span></div>
            <div class="row"><span class="k">Total RAM</span><span class="v">{{ fmtBytes(info.server.ram_bytes) }}</span></div>
            <div class="row"><span class="k">Storage Capacity</span><span class="v">{{ fmtBytes(info.server.disk_total_bytes) }}</span></div>
            <div class="row"><span class="k">Storage Type</span><span class="v muted">Not available</span></div>
          </div>
        </div>

        <!-- 3. Connection Information -->
        <div class="block">
          <div class="block-hd conn">🔗 Connection Information</div>
          <div class="rows">
            <div class="row"><span class="k">Current Connections</span><span class="v">{{ info.connections.current ?? '—' }}</span></div>
            <div class="row"><span class="k">Max Connections</span><span class="v">{{ info.connections.max ?? '—' }}</span></div>
            <div class="row">
              <span class="k">Connection Usage</span>
              <span v-if="connPct != null" class="v conn-usage">
                <span class="usage-bar"><span class="usage-fill" :class="connAccent" :style="{ width: connPct + '%' }"></span></span>
                <span :class="connAccent">{{ connPct }}%</span>
              </span>
              <span v-else class="v muted">—</span>
            </div>
            <div class="row">
              <span class="k">SSL / TLS</span>
              <span v-if="info.connections.ssl_enabled" class="v pill ok">✓ {{ info.connections.ssl_version ?? 'Enabled' }}</span>
              <span v-else class="v muted">—</span>
            </div>
          </div>
        </div>

        <!-- 4. Storage Information -->
        <div class="block">
          <div class="block-hd stor">💾 Storage Information</div>
          <div class="rows">
            <div class="row"><span class="k">Total Databases</span><span class="v">{{ info.storage.total_databases ?? '—' }}</span></div>
            <div class="row"><span class="k">Total Tables</span><span class="v">{{ info.storage.total_tables ?? '—' }}</span></div>
            <div class="row"><span class="k">Largest Database</span><span class="v">{{ info.storage.largest_db ? `${info.storage.largest_db.name} (${fmtBytes(info.storage.largest_db.size_bytes)})` : '—' }}</span></div>
            <div class="row"><span class="k">Largest Table</span><span class="v">{{ info.storage.largest_table ? `${info.storage.largest_table.name} (${fmtBytes(info.storage.largest_table.size_bytes)})` : '—' }}</span></div>
            <div class="row"><span class="k">Used Storage</span><span class="v">{{ fmtBytes(info.storage.used_bytes) }}</span></div>
            <div class="row"><span class="k">Free Storage</span><span class="v ok">{{ fmtBytes(info.storage.free_bytes) }}</span></div>
          </div>
        </div>

        <!-- 5. Replication -->
        <div class="block">
          <div class="block-hd repl">🔄 Replication</div>
          <div class="rows">
            <div class="row"><span class="k">Role</span><span class="v">{{ info.replication.role === 'primary' ? 'Primary' : 'Replica' }}</span></div>
            <div class="row">
              <span class="k">Replication Status</span>
              <span class="v" :class="replStatusClass">{{ replStatusLabel }}</span>
            </div>
            <div class="row">
              <span class="k">Replication Lag</span>
              <span class="v" :class="info.replication.lag_sec != null && info.replication.lag_sec > 30 ? 'warn' : 'ok'">
                {{ info.replication.lag_sec != null ? `${info.replication.lag_sec}s` : '—' }}
              </span>
            </div>
          </div>
        </div>

        <!-- 6. Backup Information -->
        <div class="block">
          <div class="block-hd bkp">📦 Backup Information</div>
          <div v-if="info.backup" class="rows">
            <div class="row"><span class="k">Last Backup</span><span class="v">{{ info.backup.last_run_at ? new Date(info.backup.last_run_at).toLocaleString() : '—' }}</span></div>
            <div class="row">
              <span class="k">Backup Status</span>
              <span class="v pill" :class="backupStatusClass">{{ backupStatusLabel }}</span>
            </div>
            <div class="row"><span class="k">Backup Size</span><span class="v">{{ fmtBytes(info.backup.size_bytes) }}</span></div>
          </div>
          <div v-else class="empty-msg">No backup job configured</div>
        </div>

      </div>
    </template>

    <!-- Footer -->
    <div v-if="!loading" class="footer">
      <span class="fetch-time">Last fetched: {{ fmtFetchedAt() }} · Live query to database</span>
      <button class="btn-refresh" type="button" :disabled="loading" @click="load">
        ↻ Refresh
      </button>
    </div>
  </div>
</template>

<style scoped>
.info-panel { display: flex; flex-direction: column; gap: 0; }

.banner { padding: 10px 16px; font-size: 13px; border-radius: 7px; margin: 12px 0 0; }
.banner.warn { background: rgba(251,191,36,.12); color: #fbbf24; border: 1px solid rgba(251,191,36,.25); }
.banner.err  { background: rgba(248,113,113,.12); color: #f87171; border: 1px solid rgba(248,113,113,.25); }

.skeleton-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; padding: 14px; }
.skeleton-block { background: var(--surface-2); border-radius: 8px; height: 180px; animation: pulse 1.5s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity: .6 } 50% { opacity: 1 } }

.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; padding: 14px; }

.block { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.block-hd { padding: 8px 12px; font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; border-bottom: 1px solid var(--border); }
.block-hd.db   { color: #60a5fa; background: rgba(59,130,246,.07); }
.block-hd.srv  { color: #a78bfa; background: rgba(139,92,246,.07); }
.block-hd.conn { color: #34d399; background: rgba(52,211,153,.07); }
.block-hd.stor { color: #fbbf24; background: rgba(251,191,36,.07); }
.block-hd.repl { color: #fb923c; background: rgba(251,146,60,.07); }
.block-hd.bkp  { color: #f87171; background: rgba(248,113,113,.07); }

.rows { display: flex; flex-direction: column; }
.row { display: flex; justify-content: space-between; align-items: center; padding: 7px 12px; border-bottom: 1px solid var(--border); font-size: 13px; gap: 8px; }
.row:last-child { border-bottom: none; }
.k { color: var(--text-muted); white-space: nowrap; }
.v { color: var(--text); font-weight: 500; text-align: right; word-break: break-all; }
.v.mono { font-family: monospace; font-size: 12px; }
.v.muted { color: var(--text-dim, #4b5563); font-style: italic; font-weight: 400; }
.v.ok   { color: #4ade80; }
.v.warn { color: #fbbf24; }
.v.err  { color: #f87171; }
.v.danger { color: #f87171; }

.pill { display: inline-block; padding: 2px 9px; border-radius: 20px; font-size: 11px; }
.pill.ok   { background: rgba(74,222,128,.12); color: #4ade80; }
.pill.warn { background: rgba(251,191,36,.12); color: #fbbf24; }
.pill.err  { background: rgba(248,113,113,.12); color: #f87171; }

.conn-usage { display: flex; align-items: center; gap: 8px; }
.usage-bar  { width: 60px; height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; }
.usage-fill { height: 100%; border-radius: 3px; }
.usage-fill.ok     { background: #4ade80; }
.usage-fill.warn   { background: #fbbf24; }
.usage-fill.danger { background: #f87171; }

.empty-msg { padding: 16px 12px; font-size: 13px; color: var(--text-muted); text-align: center; }

.footer { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; border-top: 1px solid var(--border); }
.fetch-time { font-size: 12px; color: var(--text-muted); }
.btn-refresh { font-size: 12px; padding: 5px 14px; border-radius: 6px; background: rgba(59,130,246,.15); color: #60a5fa; border: 1px solid rgba(59,130,246,.3); cursor: pointer; }
.btn-refresh:hover { background: rgba(59,130,246,.25); }
.btn-refresh:disabled { opacity: .5; cursor: default; }
</style>
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/databases/DbInfoPanel.vue
git commit -m "feat: add DbInfoPanel component with all 6 info sections"
```

---

## Task 6: Wire the Info tab into DatabasesView.vue

**Files:**
- Modify: `frontend/src/views/databases/DatabasesView.vue`

- [ ] **Step 1: Import DbInfoPanel** — add to the import block at the top of `<script setup>`

```typescript
import DbInfoPanel from '@/components/databases/DbInfoPanel.vue'
```

- [ ] **Step 2: Add `activePanel` state** — add after the existing `ref` declarations (around line 19)

```typescript
const activePanel = ref<'metrics' | 'info'>('metrics')
```

- [ ] **Step 3: Reset `activePanel` when instance changes** — add a `watch` after the existing watches (around line 104)

```typescript
watch(selectedInstanceId, () => { activePanel.value = 'metrics' })
```

- [ ] **Step 4: Replace the `DbHealthDashboard` block** in the template.

Find this block (around line 233–245):
```html
        <!-- Health dashboard for selected instance -->
        <DbHealthDashboard
          v-else-if="selectedInstance"
          :key="`hd-${selectedInstance.credential_id}`"
          :server-id="selected.server_id"
          :server-name="selected.server_name"
          :status="selectedInstance"
          :can-edit="canEdit"
          :db-type="selectedInstance.db_type"
          :credential-id="selectedInstance.credential_id"
          @edit="openEditInstance(selectedInstance)"
          @remove="promptRemove(selectedInstance)"
        />
```

Replace it with:
```html
        <!-- Metrics / Info tab bar -->
        <div v-else-if="selectedInstance" class="panel-tabs">
          <button
            class="panel-tab" :class="{ active: activePanel === 'metrics' }"
            type="button" @click="activePanel = 'metrics'"
          >Metrics</button>
          <button
            class="panel-tab" :class="{ active: activePanel === 'info' }"
            type="button" @click="activePanel = 'info'"
          >Info</button>
        </div>

        <!-- Health dashboard for selected instance -->
        <DbHealthDashboard
          v-if="selectedInstance && activePanel === 'metrics'"
          :key="`hd-${selectedInstance.credential_id}`"
          :server-id="selected.server_id"
          :server-name="selected.server_name"
          :status="selectedInstance"
          :can-edit="canEdit"
          :db-type="selectedInstance.db_type"
          :credential-id="selectedInstance.credential_id"
          @edit="openEditInstance(selectedInstance)"
          @remove="promptRemove(selectedInstance)"
        />

        <!-- Info panel for selected instance -->
        <DbInfoPanel
          v-else-if="selectedInstance && activePanel === 'info'"
          :key="`info-${selectedInstance.credential_id}`"
          :server-id="selected.server_id"
          :credential-id="selectedInstance.credential_id"
        />
```

- [ ] **Step 5: Add panel tab styles** — add at the bottom of the `<style scoped>` block

```css
.panel-tabs {
  display: flex; gap: 0; border-bottom: 1px solid var(--border);
  margin-bottom: 20px;
}
.panel-tab {
  padding: 9px 20px; font-size: 13px; font-weight: 600;
  color: var(--text-muted); background: none; border: none;
  border-bottom: 2px solid transparent; cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.panel-tab:hover { color: var(--text); }
.panel-tab.active { color: #60a5fa; border-bottom-color: #3b82f6; }
```

- [ ] **Step 6: Verify TypeScript compiles**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/databases/DatabasesView.vue
git commit -m "feat: add Metrics/Info tab bar to database monitoring page"
```

---

## Task 7: Smoke test

- [ ] **Step 1: Open the database monitoring page**

Navigate to `http://localhost:9090` → Databases.

- [ ] **Step 2: Verify Metrics tab still works**

The existing charts, stat cards, and gauges should render exactly as before. No regressions.

- [ ] **Step 3: Click the Info tab**

A loading skeleton should appear briefly, then all 6 sections populate with data.

- [ ] **Step 4: Verify each section**

- Database Information: type, version, host, port, uptime visible
- Server Information: server name, OS, CPU cores, RAM visible
- Connection Information: current/max connections, SSL status
- Storage Information: databases count, tables count, sizes
- Replication: role shown (Primary/Replica), status
- Backup: either last backup details or "No backup job configured"

- [ ] **Step 5: Click ↻ Refresh**

Sections should briefly show skeleton then re-populate.

- [ ] **Step 6: Tag the release**

```bash
git describe --tags --abbrev=0
# increment patch from result, e.g. v1.1.7 → v1.1.8
git tag v1.1.8
git push origin main v1.1.8
```
