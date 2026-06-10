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
