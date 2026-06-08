<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getServerMonitoring } from '@/services/api'
import { useMetricsStore } from '@/stores/metrics'
import ServiceDetail from '@/views/services/ServiceDetail.vue'
import type { MonitoringService } from '@/types/index'

const metrics = useMetricsStore()
const services = ref<MonitoringService[]>([])
const loading = ref(true)
const selectedId = ref<string | null>(null)

onMounted(async () => {
  const id = metrics.activeServerId
  if (!id) return
  try {
    services.value = await getServerMonitoring(id)
  } catch {
    // show empty state
  } finally {
    loading.value = false
  }
})

function statusClass(s: MonitoringService): string {
  return `dot--${s.last_status ?? 'unknown'}`
}

function fmtUptime(v: number | null): string {
  return v != null ? `${v}%` : '—'
}

function fmtMs(v: number | null): string {
  return v != null ? `${v}ms` : '—'
}

function typeLabel(t: string): string {
  return t.toUpperCase()
}
</script>

<template>
  <div class="mon">

    <!-- Loading -->
    <div v-if="loading" class="placeholder">Loading…</div>

    <!-- Empty -->
    <div v-else-if="!services.length" class="placeholder">
      <span>No services monitored for this server.</span>
      <router-link class="add-link" to="/services">Manage services →</router-link>
    </div>

    <!-- Detail drill-in -->
    <template v-else-if="selectedId">
      <button class="back-btn" @click="selectedId = null">← All services</button>
      <ServiceDetail :key="selectedId" :service-id="selectedId" :embedded="true" />
    </template>

    <!-- Service list -->
    <template v-else>
      <div class="list-head">
        <span>{{ services.length }} service{{ services.length !== 1 ? 's' : '' }} monitored</span>
        <router-link class="manage-link" to="/services">Manage →</router-link>
      </div>

      <div class="svc-table">
        <div class="svc-thead">
          <span>Service</span>
          <span>Type</span>
          <span>Uptime 24h</span>
          <span>Avg Response</span>
        </div>
        <div
          v-for="s in services"
          :key="s.id"
          class="svc-row"
          @click="selectedId = s.id"
        >
          <span class="svc-name">
            <span class="dot" :class="statusClass(s)"></span>
            {{ s.name }}
          </span>
          <span class="type-badge">{{ typeLabel(s.type) }}</span>
          <span class="uptime" :class="{ 'uptime-warn': (s.uptime_24h ?? 100) < 99 }">
            {{ fmtUptime(s.uptime_24h) }}
          </span>
          <span class="resp">{{ fmtMs(s.avg_response_ms_24h) }}</span>
        </div>
      </div>
    </template>

  </div>
</template>

<style scoped>
.mon { padding: 4px 0; }

.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--muted);
  font-size: 13px;
  text-align: center;
  padding: 60px 20px;
}
.add-link { color: var(--accent-2); text-decoration: none; font-size: 13px; }
.add-link:hover { text-decoration: underline; }

/* Back button */
.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
  padding: 0;
  margin-bottom: 14px;
}
.back-btn:hover { color: var(--text); }

/* List header */
.list-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--muted);
}
.manage-link { color: var(--accent-2); text-decoration: none; font-size: 12px; }
.manage-link:hover { text-decoration: underline; }

/* Table */
.svc-table {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}

.svc-thead, .svc-row {
  display: grid;
  grid-template-columns: 1fr 80px 110px 120px;
  gap: 12px;
  padding: 11px 16px;
  align-items: center;
}
.svc-thead {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
  border-bottom: 1px solid var(--border);
}
.svc-row {
  font-size: 13px;
  color: var(--text);
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.1s;
}
.svc-row:last-child { border-bottom: none; }
.svc-row:hover { background: var(--surface-2); }

.svc-name {
  display: flex;
  align-items: center;
  gap: 9px;
  font-weight: 500;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot--up      { background: var(--green); box-shadow: 0 0 5px rgba(34,197,94,0.5); }
.dot--down    { background: var(--red); }
.dot--timeout { background: var(--amber); }
.dot--unknown { background: var(--grey, #6b7280); }

.type-badge {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(59,130,246,0.15);
  color: var(--blue, #3b82f6);
  width: fit-content;
}

.uptime { font-family: ui-monospace, monospace; font-size: 12px; }
.uptime-warn { color: var(--amber); }

.resp { font-family: ui-monospace, monospace; font-size: 12px; color: var(--muted); }
</style>
