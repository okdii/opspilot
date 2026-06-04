<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { EmptyState, StatusBadge } from '@/components/ui'
import { getServerServices } from '@/services/api'
import { useMetricsStore } from '@/stores/metrics'
import type { ServerServiceEntry } from '@/types'

const metrics = useMetricsStore()
const services = ref<ServerServiceEntry[]>([])
const loading = ref(true)
const showNotInstalled = ref(false)

async function fetchServices() {
  const id = metrics.activeServerId
  if (!id) return
  loading.value = true
  try {
    services.value = await getServerServices(id, showNotInstalled.value)
  } catch {
    // keep stale data on transient error
  } finally {
    loading.value = false
  }
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
watch(showNotInstalled, () => void fetchServices())
// Refresh when the server's metrics update (WS heartbeat path)
watch(() => metrics.latestValues, () => void fetchServices(), { deep: false })
</script>

<template>
  <div class="svc">
    <div class="svc-head">
      <h3>System Services</h3>
      <label class="toggle">
        <input type="checkbox" v-model="showNotInstalled" />
        <span>Show not installed</span>
      </label>
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
          </tr>
        </thead>
        <tbody>
          <tr v-for="svc in services" :key="svc.name">
            <td class="t-name">{{ svc.name }}</td>
            <td class="t-status">
              <StatusBadge kind="process_service" :status="svc.status" />
            </td>
            <td class="t-num">{{ svc.cpu_pct != null ? svc.cpu_pct.toFixed(1) + '%' : '—' }}</td>
            <td class="t-num">{{ svc.mem_mb != null ? svc.mem_mb.toFixed(0) + ' MB' : '—' }}</td>
            <td class="t-num">{{ formatUptime(svc.uptime_seconds) }}</td>
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

.toggle { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); cursor: pointer; user-select: none; }
.toggle input { accent-color: var(--accent); cursor: pointer; }

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
</style>
