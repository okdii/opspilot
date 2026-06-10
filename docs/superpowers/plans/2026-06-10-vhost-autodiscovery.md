# Vhost Auto-Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Scan Web Services" button to the server ServicesTab that SSHes into the server, discovers virtual hosts from nginx/apache/caddy/litespeed configs, and lets the user bulk-register selected domains as HTTP monitoring services via a slide-over.

**Architecture:** A new FastAPI router (`vhost_scan.py`) handles the scan via the existing `SSHSession`. It detects which web servers are running, runs the appropriate discovery commands, parses the output, cross-checks against existing monitored services, and returns a list. The frontend presents results in a `VhostScanSlideOver.vue` that reuses the existing `SlideOver` component and `useServiceStore().createService()` for registration.

**Tech Stack:** Python 3.11 + FastAPI + asyncssh (existing), Vue 3 + Pinia + Vuestic SlideOver (existing)

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `backend/app/routers/vhost_scan.py` | Create | Scan endpoint + 4 web server parsers |
| `backend/app/main.py` | Modify (line 31–32, 124) | Import + register new router |
| `frontend/src/types/index.ts` | Modify (after line 233) | Add `VhostEntry` interface |
| `frontend/src/services/api.ts` | Modify (after last export) | Add `scanVhosts()` API function |
| `frontend/src/components/servers/VhostScanSlideOver.vue` | Create | Scan + select + register slide-over |
| `frontend/src/components/servers/tabs/ServicesTab.vue` | Modify | Add button + wire up slide-over |

---

## Task 1: Backend — vhost_scan.py router

**Files:**
- Create: `backend/app/routers/vhost_scan.py`

- [ ] **Step 1: Create the router file with all parsers and the endpoint**

Create `backend/app/routers/vhost_scan.py` with the following content:

```python
"""Vhost auto-discovery — SSH into a server and extract virtual host config.

Supports nginx, apache (Debian + RHEL), caddy, and LiteSpeed.
Returns a list of discovered domains with already_monitored flag.
"""
import re
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser
from app.models.other import Service
from app.models.server import Server
from app.services.ssh import SSHError, SSHSession

router = APIRouter(tags=["servers"])


class VhostEntry(BaseModel):
    domain: str
    url: str
    port: int
    scheme: str
    server_type: str
    already_monitored: bool


# ── Web server detection ────────────────────────────────────────────────────


async def _has_nginx(session: SSHSession) -> bool:
    return (await session.run("nginx -v", timeout=5)).exit_code == 0


async def _has_apache(session: SSHSession) -> bool:
    for cmd in ("apache2ctl -v", "httpd -v"):
        if (await session.run(cmd, timeout=5)).exit_code == 0:
            return True
    return False


async def _has_caddy(session: SSHSession) -> bool:
    return (await session.run("caddy version", timeout=5)).exit_code == 0


async def _has_litespeed(session: SSHSession) -> bool:
    return (await session.run("/usr/local/lsws/bin/lshttpd -v", timeout=5)).exit_code == 0


# ── Parsers ─────────────────────────────────────────────────────────────────


def _parse_nginx(stdout: str) -> list[dict]:
    """Extract vhosts from `nginx -T` merged config dump."""
    entries: list[dict] = []
    seen: set[tuple] = set()

    # Split on server { blocks; index 0 is preamble
    for block in re.split(r'\bserver\s*\{', stdout)[1:]:
        names = re.findall(r'server_name\s+([^;]+);', block)
        listens = re.findall(r'listen\s+([^;]+);', block)

        port, scheme = 80, 'http'
        for listen in listens:
            if '443' in listen or 'ssl' in listen:
                port, scheme = 443, 'https'
                break
            m = re.search(r'\b(\d+)\b', listen)
            if m:
                port = int(m.group(1))

        for name_group in names:
            for name in name_group.split():
                name = name.strip()
                # Skip wildcard and default catch-all entries
                if name and name != '_' and '.' in name and not name.startswith('~'):
                    key = (name, port)
                    if key not in seen:
                        seen.add(key)
                        entries.append({'domain': name, 'port': port, 'scheme': scheme})

    return entries


def _parse_apache(output: str) -> list[dict]:
    """Extract vhosts from `apache2ctl -S` / `httpd -S` output.

    apache2ctl -S writes to stderr on Debian; callers pass stderr+stdout combined.
    Lines look like:  port 443 namevhost app.example.com (/etc/apache2/...)
    """
    entries: list[dict] = []
    seen: set[tuple] = set()

    for line in output.splitlines():
        m = re.search(r'port\s+(\d+)\s+namevhost\s+(\S+)', line)
        if not m:
            continue
        port = int(m.group(1))
        domain = m.group(2).split(':')[0]
        scheme = 'https' if port == 443 else 'http'
        if '.' not in domain:
            continue
        key = (domain, port)
        if key not in seen:
            seen.add(key)
            entries.append({'domain': domain, 'port': port, 'scheme': scheme})

    return entries


def _parse_caddy(content: str) -> list[dict]:
    """Extract site addresses from a Caddyfile.

    Handles: domain.com { ... }, https://domain.com { ... }, http://domain.com { ... }
    Ignores bare-port blocks like :2019 { ... }.
    """
    entries: list[dict] = []
    seen: set[tuple] = set()

    for m in re.finditer(r'^([^\s{#\n][^\n{]*)\{', content, re.MULTILINE):
        addr_part = m.group(1).strip()
        for part in addr_part.split(','):
            part = part.strip()
            if part.startswith('https://'):
                domain = part[8:].split('/')[0].split(':')[0]
                port, scheme = 443, 'https'
            elif part.startswith('http://'):
                domain = part[7:].split('/')[0].split(':')[0]
                port, scheme = 80, 'http'
            elif re.match(r'^:\d+$', part):
                continue  # bare port, no domain
            else:
                domain = part.split('/')[0].split(':')[0]
                port, scheme = 443, 'https'

            if '.' not in domain or not domain:
                continue
            key = (domain, port)
            if key not in seen:
                seen.add(key)
                entries.append({'domain': domain, 'port': port, 'scheme': scheme})

    return entries


def _parse_litespeed(xml_content: str) -> list[dict]:
    """Extract vhosts from LiteSpeed httpd_config.xml."""
    entries: list[dict] = []
    seen: set[tuple] = set()

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return entries

    # Determine if any SSL listener exists (port 443)
    ssl_ports: set[int] = set()
    for listener in root.iter('listener'):
        ssl_el = listener.find('secure')
        port_el = listener.find('port')
        if ssl_el is not None and ssl_el.text == '1' and port_el is not None:
            try:
                ssl_ports.add(int(port_el.text))
            except (ValueError, TypeError):
                pass

    for vh in root.iter('virtualHostConfig'):
        name_el = vh.find('serverName')
        if name_el is None or not name_el.text:
            continue
        domain = name_el.text.strip()
        if '.' not in domain:
            continue
        port = 443 if ssl_ports else 80
        scheme = 'https' if ssl_ports else 'http'
        key = (domain, port)
        if key not in seen:
            seen.add(key)
            entries.append({'domain': domain, 'port': port, 'scheme': scheme})

    return entries


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.post("/api/servers/{server_id}/scan-vhosts", response_model=list[VhostEntry])
async def scan_vhosts(
    server_id: str,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """SSH into a server and return all discovered virtual hosts."""
    server = await db.get(Server, server_id)
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    raw: list[dict] = []

    try:
        async with SSHSession(server) as ssh:
            detected_any = False

            # nginx
            if await _has_nginx(ssh):
                detected_any = True
                r = await ssh.run("nginx -T", timeout=30, sudo=True)
                if r.ok:
                    for e in _parse_nginx(r.stdout):
                        raw.append({**e, 'server_type': 'nginx'})

            # apache (Debian: apache2ctl, RHEL: httpd)
            if await _has_apache(ssh):
                detected_any = True
                for cmd in ("apache2ctl -S", "httpd -S"):
                    r = await ssh.run(cmd, timeout=30, sudo=True)
                    if r.ok or r.stderr:
                        combined = r.stderr + '\n' + r.stdout
                        for e in _parse_apache(combined):
                            raw.append({**e, 'server_type': 'apache'})
                        break

            # caddy
            if await _has_caddy(ssh):
                detected_any = True
                for path in ("/etc/caddy/Caddyfile", "/etc/caddy/conf.d/*.conf"):
                    r = await ssh.run(f"cat {path} 2>/dev/null", timeout=15)
                    if r.ok and r.stdout.strip():
                        for e in _parse_caddy(r.stdout):
                            raw.append({**e, 'server_type': 'caddy'})

            # litespeed
            if await _has_litespeed(ssh):
                detected_any = True
                r = await ssh.run("cat /usr/local/lsws/conf/httpd_config.xml", timeout=15)
                if r.ok and r.stdout.strip():
                    for e in _parse_litespeed(r.stdout):
                        raw.append({**e, 'server_type': 'litespeed'})

    except SSHError as exc:
        raise HTTPException(502, detail={"error": "ssh_failed", "message": str(exc)})

    if not detected_any:
        raise HTTPException(422, detail={"error": "no_webserver", "message": "No supported web server found (nginx/apache/caddy/litespeed)"})

    # Zero vhosts found is not an error — server may use default config only
    if not raw:
        return []

    # Cross-check against services already monitored in this org
    monitored_urls = {
        u.lower()
        for u in (
            await db.execute(
                select(Service.url)
                .join(Server, Service.server_id == Server.id)
                .where(Server.org_id == server.org_id, Service.url.isnot(None))
            )
        ).scalars().all()
    }

    # Deduplicate across web servers, then build response
    seen: set[tuple] = set()
    result: list[VhostEntry] = []
    for e in raw:
        key = (e['domain'], e['port'])
        if key in seen:
            continue
        seen.add(key)
        url = f"{e['scheme']}://{e['domain']}"
        result.append(
            VhostEntry(
                domain=e['domain'],
                url=url,
                port=e['port'],
                scheme=e['scheme'],
                server_type=e['server_type'],
                already_monitored=url.lower() in monitored_urls,
            )
        )

    return result
```

- [ ] **Step 2: Smoke-check Python syntax**

```bash
cd /Users/pocketdata/Code/Work/opspilot
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend python -c "from app.routers.vhost_scan import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/vhost_scan.py
git commit -m "feat: add vhost_scan router with nginx/apache/caddy/litespeed parsers"
```

---

## Task 2: Backend — Register router in main.py

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add import after the db_info_router import (line 31)**

Find this line in `backend/app/main.py`:
```python
from app.routers.db_info import router as db_info_router
```

Add immediately after it:
```python
from app.routers.vhost_scan import router as vhost_scan_router
```

- [ ] **Step 2: Register the router after db_info_router (line 123)**

Find this line in `backend/app/main.py`:
```python
app.include_router(db_info_router)
```

Add immediately after it:
```python
app.include_router(vhost_scan_router)
```

- [ ] **Step 3: Verify backend starts clean**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
sleep 3
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend --tail=20
```

Expected: No `ImportError` or `AttributeError`. Server starts and logs show `Application startup complete`.

- [ ] **Step 4: Smoke-test the endpoint exists**

```bash
# Get a valid auth token first (replace EMAIL/PASSWORD with dev credentials)
TOKEN=$(curl -s -c /tmp/op-cookies.txt -X POST http://localhost:9090/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"your@email.com","password":"yourpassword"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

# Hit the endpoint with a dummy server_id to confirm routing works
curl -s -b /tmp/op-cookies.txt \
  -X POST http://localhost:9090/api/servers/00000000-0000-0000-0000-000000000000/scan-vhosts \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: `{"detail": {"error": "not_found", "message": "Server not found."}}` — confirms the route is live and resolves.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: register vhost_scan router in main.py"
```

---

## Task 3: Frontend — VhostEntry type + scanVhosts API

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Add VhostEntry interface to types/index.ts**

Open `frontend/src/types/index.ts`. Find the end of the file (after the `MonitoringService` interface, around line 233). Add:

```typescript
// --- Vhost auto-discovery ---------------------------------------------------

export interface VhostEntry {
  domain: string
  url: string
  port: number
  scheme: 'http' | 'https'
  server_type: string
  already_monitored: boolean
}
```

- [ ] **Step 2: Add VhostEntry to the imports in api.ts**

Open `frontend/src/services/api.ts`. Find the import block at the top (lines 2–28):
```typescript
import type {
  ...
  LogRulePayload,
} from '@/types'
```

Add `VhostEntry` to the import list:
```typescript
import type {
  ...
  LogRulePayload,
  VhostEntry,
} from '@/types'
```

- [ ] **Step 3: Add scanVhosts function to api.ts**

At the end of `frontend/src/services/api.ts`, add:

```typescript
export async function scanVhosts(serverId: string): Promise<VhostEntry[]> {
  const { data } = await api.post<VhostEntry[]>(`/api/servers/${serverId}/scan-vhosts`)
  return data
}
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /Users/pocketdata/Code/Work/opspilot
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npx vue-tsc --noEmit 2>&1 | head -30
```

Expected: No errors related to `VhostEntry` or `scanVhosts`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/services/api.ts
git commit -m "feat: add VhostEntry type and scanVhosts API call"
```

---

## Task 4: Frontend — VhostScanSlideOver.vue component

**Files:**
- Create: `frontend/src/components/servers/VhostScanSlideOver.vue`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/servers/VhostScanSlideOver.vue`:

```vue
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { SlideOver } from '@/components/ui'
import { scanVhosts } from '@/services/api'
import { useServiceStore } from '@/stores/services'
import { useNotify } from '@/composables/useNotify'
import type { VhostEntry } from '@/types'

const props = defineProps<{
  modelValue: boolean
  serverId: string
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'registered', count: number): void
}>()

const serviceStore = useServiceStore()
const notify = useNotify()

type Phase = 'scanning' | 'results' | 'error'
const phase = ref<Phase>('scanning')
const errorMessage = ref('')
const vhosts = ref<VhostEntry[]>([])
const selected = ref(new Set<string>())
const registering = ref(false)
const rowErrors = ref<Record<string, string>>({})

const selectableVhosts = computed(() => vhosts.value.filter(v => !v.already_monitored))
const selectedCount = computed(() => selected.value.size)

async function startScan() {
  phase.value = 'scanning'
  errorMessage.value = ''
  vhosts.value = []
  selected.value = new Set()
  rowErrors.value = {}
  try {
    const results = await scanVhosts(props.serverId)
    vhosts.value = results
    // Default: HTTPS domains checked, HTTP unchecked
    selected.value = new Set(
      results.filter(v => !v.already_monitored && v.scheme === 'https').map(v => v.url)
    )
    phase.value = 'results'
  } catch (err: any) {
    const msg = err?.response?.data?.detail?.message ?? 'Failed to scan server'
    errorMessage.value = msg
    phase.value = 'error'
  }
}

function toggle(url: string) {
  const next = new Set(selected.value)
  if (next.has(url)) next.delete(url)
  else next.add(url)
  selected.value = next
}

async function register() {
  registering.value = true
  rowErrors.value = {}
  let successCount = 0

  for (const vhost of selectableVhosts.value) {
    if (!selected.value.has(vhost.url)) continue
    try {
      await serviceStore.createService({
        server_id: props.serverId,
        name: vhost.domain,
        type: 'http',
        url: vhost.url,
        expected_status: 200,
        interval_sec: 60,
        timeout_sec: 5,
        is_active: true,
        is_public: false,
        ignore_ssl_errors: false,
        ...(vhost.scheme === 'https' ? { ssl_warn_days: 30, ssl_critical_days: 7 } : {}),
      })
      successCount++
    } catch {
      rowErrors.value = { ...rowErrors.value, [vhost.url]: 'Failed to register' }
    }
  }

  registering.value = false

  const failCount = Object.keys(rowErrors.value).length
  if (failCount === 0) {
    notify.success(`${successCount} service${successCount !== 1 ? 's' : ''} registered`)
    emit('registered', successCount)
    emit('update:modelValue', false)
  } else {
    notify.error(`${successCount} registered, ${failCount} failed — see errors above`)
    emit('registered', successCount)
  }
}

watch(() => props.modelValue, (v) => { if (v) startScan() })
</script>

<template>
  <SlideOver
    :model-value="modelValue"
    title="Discover Web Services"
    subtitle="Scan web server config and register domains for monitoring"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <!-- Scanning phase -->
    <div v-if="phase === 'scanning'" class="scan-phase">
      <span class="spin"></span>
      <p class="scan-msg">Connecting to server and reading web server config…</p>
    </div>

    <!-- Error phase -->
    <div v-else-if="phase === 'error'" class="error-phase">
      <p class="error-msg">{{ errorMessage }}</p>
      <button class="btn ghost" @click="startScan">Retry</button>
    </div>

    <!-- Results phase -->
    <template v-else-if="phase === 'results'">
      <p v-if="!vhosts.length" class="empty-msg">No virtual hosts found in the web server config.</p>

      <template v-else>
        <p class="found-msg">Found {{ vhosts.length }} web service{{ vhosts.length !== 1 ? 's' : '' }} on this server</p>

        <div class="vhost-list">
          <div
            v-for="v in vhosts"
            :key="v.url"
            class="vhost-row"
            :class="{
              'is-monitored': v.already_monitored,
              'is-selected': !v.already_monitored && selected.has(v.url),
            }"
          >
            <label v-if="!v.already_monitored" class="vhost-check">
              <input type="checkbox" :checked="selected.has(v.url)" @change="toggle(v.url)" />
            </label>
            <span v-else class="vhost-dash">—</span>

            <div class="vhost-info">
              <span class="vhost-url">{{ v.url }}</span>
              <span class="vhost-server">{{ v.server_type }}</span>
            </div>

            <span v-if="v.already_monitored" class="badge badge-gray">already monitoring</span>
            <span v-else-if="rowErrors[v.url]" class="badge badge-red">failed</span>
          </div>
        </div>
      </template>
    </template>

    <template #footer>
      <button type="button" class="btn ghost" @click="emit('update:modelValue', false)">Cancel</button>
      <button
        v-if="phase === 'results' && selectableVhosts.length > 0"
        class="btn primary"
        :disabled="selectedCount === 0 || registering"
        @click="register"
      >
        <span v-if="registering" class="spin btn-spin"></span>
        <span v-else>Register {{ selectedCount > 0 ? selectedCount + ' ' : '' }}service{{ selectedCount !== 1 ? 's' : '' }}</span>
      </button>
    </template>
  </SlideOver>
</template>

<style scoped>
/* Scanning */
.scan-phase { display: flex; flex-direction: column; align-items: center; gap: 16px; padding: 56px 0; }
.scan-msg { color: var(--muted); font-size: 13px; }

/* Error */
.error-phase { display: flex; flex-direction: column; gap: 14px; padding: 24px 0; }
.error-msg {
  color: var(--red); font-size: 13px;
  background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.25);
  border-radius: 8px; padding: 12px 14px;
}

/* Results */
.found-msg { font-size: 12px; color: var(--muted); margin-bottom: 8px; }
.empty-msg { color: var(--muted); font-size: 13px; padding: 48px 0; text-align: center; }

.vhost-list { display: flex; flex-direction: column; gap: 6px; }

.vhost-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--surface-2);
  transition: border-color 0.15s, background 0.15s;
}
.vhost-row.is-selected { border-color: var(--accent); background: rgba(99,102,241,0.07); }
.vhost-row.is-monitored { opacity: 0.4; }

.vhost-check { display: flex; align-items: center; cursor: pointer; }
.vhost-check input { width: 14px; height: 14px; cursor: pointer; accent-color: var(--accent); }
.vhost-dash { width: 18px; text-align: center; color: var(--muted); font-size: 12px; flex-shrink: 0; }

.vhost-info { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.vhost-url { font-size: 13px; color: var(--text); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vhost-server { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }

.badge {
  font-size: 10px; font-weight: 500; text-transform: uppercase;
  letter-spacing: 0.04em; padding: 2px 7px; border-radius: 4px; white-space: nowrap; flex-shrink: 0;
}
.badge-gray { color: var(--muted); background: rgba(107,114,128,0.2); }
.badge-red { color: var(--red); background: rgba(239,68,68,0.15); }

/* Buttons */
.btn {
  padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600;
  cursor: pointer; border: 1px solid var(--border); background: var(--surface-2);
  color: var(--text); display: inline-flex; align-items: center; justify-content: center;
  gap: 8px; min-height: 38px;
}
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
.btn.primary { background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; }
.btn.primary:disabled { opacity: 0.6; cursor: not-allowed; }

/* Spinner */
.spin {
  width: 22px; height: 22px;
  border: 2px solid rgba(99,102,241,0.25); border-top-color: var(--accent);
  border-radius: 50%; animation: spin 0.8s linear infinite;
}
.btn-spin { width: 14px; height: 14px; border-color: rgba(255,255,255,0.4); border-top-color: #fff; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npx vue-tsc --noEmit 2>&1 | head -30
```

Expected: No errors in `VhostScanSlideOver.vue`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/servers/VhostScanSlideOver.vue
git commit -m "feat: add VhostScanSlideOver component with scan/select/register flow"
```

---

## Task 5: Frontend — Wire into ServicesTab.vue

**Files:**
- Modify: `frontend/src/components/servers/tabs/ServicesTab.vue`

- [ ] **Step 1: Add imports at the top of the script block**

In `frontend/src/components/servers/tabs/ServicesTab.vue`, find the existing imports:
```typescript
import { onMounted, ref, watch } from 'vue'
import { EmptyState, StatusBadge } from '@/components/ui'
import { getServerServices, muteServerService, unmuteServerService } from '@/services/api'
import { useMetricsStore } from '@/stores/metrics'
import type { ServerServiceEntry } from '@/types'
```

Replace with:
```typescript
import { onMounted, ref, watch } from 'vue'
import { EmptyState, StatusBadge } from '@/components/ui'
import { getServerServices, muteServerService, unmuteServerService } from '@/services/api'
import { useMetricsStore } from '@/stores/metrics'
import { useAuthStore } from '@/stores/auth'
import VhostScanSlideOver from '@/components/servers/VhostScanSlideOver.vue'
import type { ServerServiceEntry } from '@/types'
```

- [ ] **Step 2: Add auth store + scanOpen ref after the existing store declarations**

In the script block, after:
```typescript
const metrics = useMetricsStore()
```

Add:
```typescript
const auth = useAuthStore()
const scanOpen = ref(false)
```

- [ ] **Step 3: Add onRegistered handler after the existing fetchServices function**

After the `toggleMute` function, add:

```typescript
function onRegistered(count: number) {
  void fetchServices()
}
```

- [ ] **Step 4: Update the template header to add the scan button**

Find in the template:
```html
<div class="svc-head">
  <h3>System Services</h3>
</div>
```

Replace with:
```html
<div class="svc-head">
  <h3>System Services</h3>
  <button v-if="auth.isAdmin" class="scan-btn" @click="scanOpen = true">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
    </svg>
    Scan Web Services
  </button>
</div>
```

- [ ] **Step 5: Add VhostScanSlideOver to template (before closing `</div>`)**

Find the closing `</div>` of the root `.svc` element (the last `</div>` in the template). Add before it:

```html
<VhostScanSlideOver
  v-if="metrics.activeServerId"
  v-model="scanOpen"
  :server-id="metrics.activeServerId"
  @registered="onRegistered"
/>
```

- [ ] **Step 6: Add the scan-btn style to the scoped styles**

In the `<style scoped>` block, after `.svc-head h3 { ... }`, add:

```css
.scan-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 500;
  color: var(--muted); background: var(--surface-2); border: 1px solid var(--border);
  cursor: pointer; transition: color 0.15s, border-color 0.15s;
}
.scan-btn:hover { color: var(--accent-2); border-color: var(--accent); }
```

- [ ] **Step 7: Verify TypeScript compiles**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npx vue-tsc --noEmit 2>&1 | head -30
```

Expected: No errors.

- [ ] **Step 8: Smoke test in browser**

1. Open `http://localhost:9090` and log in as admin
2. Navigate to any server's detail page → Services tab
3. Confirm "Scan Web Services" button appears in the top-right of the System Services header
4. Click the button → slide-over should open with a spinning loader
5. If server has nginx/apache/caddy/litespeed: results list should appear with domains and checkboxes
6. HTTPS domains should be pre-checked; HTTP domains unchecked; already-monitored rows grayed with badge
7. Select some domains → "Register X services" button should update its label
8. Click Register → success toast fires, slide-over closes
9. Open the Services monitoring view — newly registered domains should appear

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/servers/tabs/ServicesTab.vue
git commit -m "feat: add Scan Web Services button and slide-over to ServicesTab"
```

---

## Task 6: Release

- [ ] **Step 1: Check latest tag**

```bash
git describe --tags --abbrev=0
```

- [ ] **Step 2: Tag and push**

Bump the patch version by 1 from whatever the latest tag shows (e.g. if latest is `v1.2.4`, use `v1.2.5`):

```bash
git push origin main
git tag v1.2.X  # replace X with the correct next patch number
git push origin v1.2.X
```

Expected: CI `release` job triggers and creates a GitHub Release.
