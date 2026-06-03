<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { usePublicStatusStore } from '@/stores/publicStatus'
import { EmptyState, StatusBadge } from '@/components/ui'
import UptimeTimeline from '@/components/services/UptimeTimeline.vue'

const store = usePublicStatusStore()

// "Updated Xs ago" counter (spec §6.6) + 60s auto-refresh polling.
const secondsAgo = ref(0)
let tick: ReturnType<typeof setInterval> | undefined
let poll: ReturnType<typeof setInterval> | undefined

async function refresh() {
  await store.fetchAll()
  secondsAgo.value = 0
}

onMounted(async () => {
  await refresh()
  tick = setInterval(() => (secondsAgo.value += 1), 1000)
  poll = setInterval(refresh, 60_000)
})

onUnmounted(() => {
  if (tick) clearInterval(tick)
  if (poll) clearInterval(poll)
})

const updatedLabel = computed(() => {
  const s = secondsAgo.value
  if (s < 60) return `Updated ${s}s ago`
  return `Updated ${Math.floor(s / 60)}m ago`
})

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return iso.slice(0, 10)
}

function fmtDuration(sec: number | null): string {
  if (sec == null) return ''
  const min = Math.round(sec / 60)
  if (min < 60) return `Resolved in ${min} min`
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? `Resolved in ${h}h ${m}m` : `Resolved in ${h}h`
}

function fmtStarted(iso: string | null): string {
  if (!iso) return '—'
  return iso.slice(0, 16).replace('T', ' ')
}
</script>

<template>
  <div class="status-page">
    <div class="status-shell">
      <!-- Header + overall banner -->
      <header class="hdr">
        <h1 class="hdr-title">System Status</h1>

        <div
          class="banner"
          :class="store.allOperational ? 'banner-ok' : 'banner-down'"
          role="status"
          aria-live="polite"
        >
          <span class="banner-icon" aria-hidden="true">
            <svg
              v-if="store.allOperational"
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M20 6 9 17l-5-5" />
            </svg>
            <svg
              v-else
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </span>
          <span class="banner-text">
            {{ store.allOperational ? 'All Systems Operational' : 'Some Systems Are Down' }}
          </span>
        </div>
        <p v-if="store.loaded" class="updated">{{ updatedLabel }}</p>
      </header>

      <!-- Active incident banner(s) -->
      <section v-if="store.activeIncidents.length" class="active-incidents">
        <div v-for="inc in store.activeIncidents" :key="inc.id" class="incident-card">
          <div class="ic-head">
            <span class="ic-icon" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </span>
            <span class="ic-label">Active Incident</span>
          </div>
          <div class="ic-svc">{{ inc.service_name }} — Service disruption</div>
          <div class="ic-meta">Started {{ fmtStarted(inc.started_at) }} · Ongoing</div>
        </div>
      </section>

      <!-- Service list -->
      <main class="card">
        <div v-if="store.loading && !store.loaded" class="loading">Loading status…</div>

        <EmptyState
          v-else-if="!store.services.length"
          title="No public services configured"
          message="There are no public services to display right now."
        />

        <ul v-else class="svc-list">
          <li v-for="svc in store.services" :key="svc.id" class="svc-row">
            <div class="svc-top">
              <span class="svc-name">{{ svc.name }}</span>
              <div class="svc-right">
                <span class="svc-uptime">{{ svc.uptime_30d != null ? svc.uptime_30d + '%' : '—' }}</span>
                <StatusBadge :status="svc.last_status ?? 'down'" kind="service" />
              </div>
            </div>
            <UptimeTimeline :points="svc.timeline ?? []" :days="90" />
          </li>
        </ul>
      </main>

      <!-- Past incidents -->
      <section class="card past">
        <h2 class="past-title">Past Incidents</h2>
        <p v-if="!store.pastIncidents.length" class="past-empty">
          No incidents reported in the last 90 days.
        </p>
        <ul v-else class="past-list">
          <li v-for="inc in store.pastIncidents" :key="inc.id" class="past-row">
            <span class="past-date">{{ fmtDate(inc.started_at) }}</span>
            <span class="past-svc">{{ inc.service_name }} — Service disruption</span>
            <span class="past-dur">{{ fmtDuration(inc.duration_sec) }}</span>
          </li>
        </ul>
      </section>

      <footer class="ftr">Powered by OpsPilot</footer>
    </div>
  </div>
</template>

<style scoped>
.status-page {
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  padding: 48px 16px 64px;
}
.status-shell {
  max-width: 760px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* Header */
.hdr { text-align: center; margin-bottom: 4px; }
.hdr-title {
  font-size: 26px;
  font-weight: 600;
  margin: 0 0 18px;
  color: #fff;
}
.banner {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 14px 24px;
  border-radius: 10px;
  font-size: 18px;
  font-weight: 600;
  border: 1px solid transparent;
}
.banner-ok {
  background: rgba(34, 197, 94, 0.12);
  color: var(--green);
  border-color: rgba(34, 197, 94, 0.3);
}
.banner-down {
  background: rgba(239, 68, 68, 0.12);
  color: var(--red);
  border-color: rgba(239, 68, 68, 0.3);
}
.banner-icon { display: inline-flex; }
.updated {
  margin: 12px 0 0;
  font-size: 12px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

/* Cards */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
}
.loading { padding: 40px; text-align: center; color: var(--muted); }

/* Active incidents */
.active-incidents { display: flex; flex-direction: column; gap: 12px; }
.incident-card {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.35);
  border-radius: 12px;
  padding: 16px 18px;
}
.ic-head { display: flex; align-items: center; gap: 8px; color: var(--red); font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }
.ic-icon { display: inline-flex; }
.ic-svc { margin-top: 8px; font-size: 15px; font-weight: 600; color: #fff; }
.ic-meta { margin-top: 4px; font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }

/* Service list */
.svc-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 22px; }
.svc-row { display: flex; flex-direction: column; gap: 10px; }
.svc-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.svc-name { font-size: 15px; font-weight: 600; color: var(--text); }
.svc-right { display: flex; align-items: center; gap: 14px; }
.svc-uptime { font-size: 13px; font-weight: 600; color: var(--muted); font-variant-numeric: tabular-nums; }

/* Past incidents */
.past-title { font-size: 15px; font-weight: 600; margin: 0 0 14px; color: #fff; }
.past-empty { margin: 0; color: var(--muted); font-size: 13px; }
.past-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.past-row {
  display: flex;
  gap: 12px;
  align-items: baseline;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.past-row:last-child { border-bottom: none; }
.past-date { color: var(--muted); font-variant-numeric: tabular-nums; min-width: 84px; }
.past-svc { color: var(--text); flex: 1; }
.past-dur { color: var(--green); white-space: nowrap; }

.ftr { text-align: center; font-size: 12px; color: var(--muted); margin-top: 12px; }

@media (max-width: 520px) {
  .past-row { flex-wrap: wrap; }
  .svc-right { gap: 10px; }
}
</style>
