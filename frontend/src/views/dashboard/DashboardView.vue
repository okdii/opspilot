<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useOrgStore } from '@/stores/org'
import { useDashboardStore } from '@/stores/dashboard'
import { getRecentAlerts } from '@/services/api'
import { wsClient } from '@/utils/ws'
import { StatCard, EmptyState } from '@/components/ui'
import ServerCard from '@/components/servers/ServerCard.vue'
import RecentAlertsPanel from '@/components/dashboard/RecentAlertsPanel.vue'
import GlobalDashboard from '@/components/dashboard/GlobalDashboard.vue'
import type { RecentAlert } from '@/types'

const auth = useAuthStore()
const orgStore = useOrgStore()
const dashboard = useDashboardStore()

const recentAlerts = ref<RecentAlert[]>([])
let unbindWs: (() => void) | null = null
let subscribedOrg: string | null = null

const alertAccent = computed<'success' | 'warning' | 'danger'>(() => {
  const f = dashboard.summary.alerts.firing
  if (f >= 3) return 'danger'
  if (f >= 1) return 'warning'
  return 'success'
})

async function load(orgId: string) {
  await dashboard.fetchDashboard(orgId)
  try { recentAlerts.value = await getRecentAlerts(orgId) } catch { recentAlerts.value = [] }
}

function subscribe(orgId: string) {
  if (subscribedOrg === orgId) return
  if (subscribedOrg) wsClient.send({ action: 'unsubscribe_org', org_id: subscribedOrg })
  wsClient.send({ action: 'subscribe_org', org_id: orgId })
  subscribedOrg = orgId
}

function unsubscribe() {
  if (subscribedOrg) wsClient.send({ action: 'unsubscribe_org', org_id: subscribedOrg })
  subscribedOrg = null
}

onMounted(() => {
  unbindWs = wsClient.on((msg: any) => {
    const channel: string | undefined = msg?.channel
    if (typeof channel === 'string' && channel.startsWith('server_metrics:')) {
      dashboard.applyMetricPush(channel.slice('server_metrics:'.length), msg.rows ?? [])
    }
  })
  const orgId = orgStore.activeOrgId
  if (orgId) { void load(orgId); subscribe(orgId) }
})

watch(() => orgStore.activeOrgId, (orgId) => {
  dashboard.reset()
  recentAlerts.value = []
  if (orgId) { void load(orgId); subscribe(orgId) }
  else unsubscribe()
})

onUnmounted(() => {
  unbindWs?.()
  unbindWs = null
  unsubscribe()
  dashboard.reset()
})
</script>

<template>
  <div class="page">
    <header class="hdr">
      <h1>Dashboard</h1>
      <p>Welcome back, {{ auth.user?.username }}</p>
    </header>

    <!-- Admin with no orgs: setup flow -->
    <div v-if="orgStore.orgs.length === 0 && auth.isAdmin" class="center-wrap">
      <div class="setup-card">
        <div class="setup-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/>
            <path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/>
            <path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/>
            <path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>
          </svg>
        </div>
        <h2>Welcome to OpsPilot</h2>
        <p class="desc">Create your first organization to start monitoring your infrastructure.</p>

        <div class="steps">
          <div class="step step-active">
            <span class="step-n">1</span>
            <div class="step-text">
              <strong>Create an organization</strong>
              <small>Group servers and team members under a shared workspace</small>
            </div>
          </div>
          <div class="step step-dim">
            <span class="step-n dim">2</span>
            <div class="step-text dim">
              <strong>Add servers</strong>
              <small>Connect infrastructure via SSH to begin monitoring</small>
            </div>
          </div>
          <div class="step step-dim">
            <span class="step-n dim">3</span>
            <div class="step-text dim">
              <strong>Configure alerts</strong>
              <small>Get notified when something needs your attention</small>
            </div>
          </div>
        </div>

        <router-link to="/organizations" class="cta">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          Create Organization
        </router-link>
      </div>
    </div>

    <!-- Non-admin with no orgs -->
    <div v-else-if="orgStore.orgs.length === 0" class="center-wrap">
      <div class="setup-card">
        <div class="setup-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
            <circle cx="9" cy="7" r="4"/>
            <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
            <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
          </svg>
        </div>
        <h2>No organization yet</h2>
        <p class="desc">Ask your administrator to set up an organization and invite you to it.</p>
      </div>
    </div>

    <!-- Has orgs — live dashboard -->
    <div v-else class="dash">
      <GlobalDashboard v-if="!orgStore.activeOrgId && auth.isAdmin" />
      <div v-else-if="!orgStore.activeOrgId" class="hint">Select an organization to view its dashboard.</div>

      <template v-else>
        <div class="stat-grid">
          <StatCard label="Servers" :value="dashboard.summary.servers.total"
            :delta="{ value: `${dashboard.summary.servers.online} online · ${dashboard.summary.servers.offline} offline`, direction: 'flat' }"
            accent="info" />
          <StatCard label="Services Up" :value="dashboard.summary.services.up"
            :delta="{ value: `${dashboard.summary.services.down} down`, direction: 'flat' }" accent="success" />
          <StatCard label="Firing Alerts" :value="dashboard.summary.alerts.firing"
            :delta="{ value: `${dashboard.summary.alerts.snoozed} snoozed · ${dashboard.summary.alerts.acknowledged} ack`, direction: 'flat' }"
            :accent="alertAccent" />
          <StatCard label="SSL / Domains" :value="dashboard.summary.ssl_domains.expiring"
            :delta="{ value: `${dashboard.summary.ssl_domains.expired} expired`, direction: 'flat' }" accent="warning" />
        </div>

        <div v-if="dashboard.loading && !dashboard.servers.length" class="dash-loading">Loading…</div>
        <div v-else-if="dashboard.error" class="dash-error">{{ dashboard.error }}</div>

        <EmptyState v-else-if="!dashboard.servers.length"
          title="No servers yet"
          :message="auth.isAdmin ? 'Add your first server to start seeing data.' : 'No servers in this organization yet.'" />

        <div v-else class="server-grid">
          <ServerCard v-for="s in dashboard.servers" :key="s.id" :server="s" />
        </div>

        <RecentAlertsPanel :alerts="recentAlerts" />
      </template>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 28px; }
.hdr h1 { font-size: 22px; color: #fff; letter-spacing: -0.3px; }
.hdr p { color: var(--muted); font-size: 13px; margin-top: 4px; margin-bottom: 28px; }

/* Empty / setup states */
.center-wrap { display: flex; justify-content: center; padding: 48px 20px; }
.setup-card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 36px 40px; max-width: 440px; width: 100%; text-align: center; }
.setup-icon { width: 56px; height: 56px; background: rgba(99,102,241,0.12); border: 1px solid rgba(99,102,241,0.25); border-radius: 14px; display: flex; align-items: center; justify-content: center; margin: 0 auto 20px; color: var(--accent-2); }
.setup-card h2 { font-size: 17px; color: #fff; margin-bottom: 8px; letter-spacing: -0.2px; }
.setup-card .desc { color: var(--muted); font-size: 13px; line-height: 1.6; margin-bottom: 24px; }

/* Steps */
.steps { display: flex; flex-direction: column; margin-bottom: 24px; text-align: left; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.step { display: flex; align-items: flex-start; gap: 12px; padding: 13px 16px; border-bottom: 1px solid var(--border); }
.step:last-child { border-bottom: none; }
.step-active { background: rgba(99,102,241,0.07); }
.step-n { width: 22px; height: 22px; border-radius: 50%; background: var(--accent); color: #fff; font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }
.step-n.dim { background: var(--surface-2); border: 1px solid var(--border); color: var(--muted); }
.step-text strong { display: block; font-size: 13px; color: #fff; font-weight: 500; margin-bottom: 2px; }
.step-text.dim strong { color: var(--muted); }
.step-text small { font-size: 11px; color: var(--muted); line-height: 1.4; display: block; }

/* CTA */
.cta { display: inline-flex; align-items: center; gap: 7px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; padding: 10px 22px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 13px; transition: opacity 0.15s; }
.cta:hover { opacity: 0.88; }

/* Live dashboard */
.dash { }
.hint { color: var(--muted); font-size: 13px; padding: 40px; text-align: center; }
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.server-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.dash-loading, .dash-error { padding: 32px; text-align: center; color: var(--muted); font-size: 13px; }
.dash-error { color: #ef4444; }
@media (max-width: 900px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
