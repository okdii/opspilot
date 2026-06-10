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
