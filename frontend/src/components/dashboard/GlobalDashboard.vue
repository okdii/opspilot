<script setup lang="ts">
import { onMounted } from 'vue'
import { useOrgStore } from '@/stores/org'
import { useGlobalDashboardStore } from '@/stores/globalDashboard'
import { StatCard } from '@/components/ui'

const orgStore = useOrgStore()
const global = useGlobalDashboardStore()

onMounted(() => global.fetch())

function switchToOrg(orgId: string) {
  orgStore.setActiveOrg(orgId)
}
</script>

<template>
  <div class="global-dash">
    <div v-if="global.loading && !global.orgs.length" class="loading">Loading…</div>
    <div v-else-if="global.error" class="error">{{ global.error }}</div>
    <template v-else>
      <div class="stat-grid">
        <StatCard
          label="Total Servers"
          :value="global.totals.servers"
          :delta="{ value: `${global.totals.online} online · ${global.totals.offline} offline`, direction: 'flat' }"
          accent="info"
        />
        <StatCard
          label="Firing Alerts"
          :value="global.totals.firing"
          :delta="{ value: 'across all organizations', direction: 'flat' }"
          :accent="global.totals.firing > 0 ? 'danger' : 'success'"
        />
        <StatCard
          label="Organizations"
          :value="global.orgs.length"
          :delta="{ value: 'registered', direction: 'flat' }"
          accent="info"
        />
      </div>

      <div class="org-grid">
        <div
          v-for="o in global.orgs"
          :key="o.org.id"
          class="org-card"
          :class="{ 'has-alerts': o.alerts.firing > 0 }"
          @click="switchToOrg(o.org.id)"
        >
          <div class="org-name">{{ o.org.name }}</div>
          <div class="org-stats">
            <span class="stat-pill online">{{ o.servers.online }} online</span>
            <span v-if="o.servers.offline" class="stat-pill offline">{{ o.servers.offline }} offline</span>
            <span v-if="o.alerts.firing" class="stat-pill firing">{{ o.alerts.firing }} firing</span>
          </div>
          <div class="org-total">{{ o.servers.total }} server{{ o.servers.total !== 1 ? 's' : '' }} total</div>
          <div class="org-arrow">→</div>
        </div>
      </div>

      <div v-if="global.orgs.length === 0" class="empty">No organizations yet.</div>
    </template>
  </div>
</template>

<style scoped>
.global-dash { }
.loading, .error { padding: 40px; text-align: center; color: var(--muted); font-size: 13px; }
.error { color: #ef4444; }
.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}
@media (max-width: 767px) { .stat-grid { grid-template-columns: 1fr; } }
.org-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.org-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 20px;
  cursor: pointer;
  transition: border-color 0.15s;
  position: relative;
  min-width: 0;
}
.org-card:hover { border-color: var(--accent); }
.org-card.has-alerts { border-color: rgba(239,68,68,0.35); }
.org-name { font-size: 15px; font-weight: 600; color: #fff; margin-bottom: 10px; }
.org-stats { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.stat-pill { font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 999px; }
.stat-pill.online  { background: rgba(34,197,94,0.12);  color: #22c55e; }
.stat-pill.offline { background: rgba(239,68,68,0.12);  color: #ef4444; }
.stat-pill.firing  { background: rgba(239,68,68,0.15);  color: #ef4444; }
.org-total { font-size: 12px; color: var(--muted); }
.org-arrow {
  position: absolute; top: 18px; right: 18px;
  color: var(--muted); font-size: 14px; transition: color 0.15s;
}
.org-card:hover .org-arrow { color: var(--accent-2); }
.empty { color: var(--muted); font-size: 13px; text-align: center; padding: 40px; }
@media (max-width: 900px) { .stat-grid { grid-template-columns: 1fr 1fr; } }
</style>
