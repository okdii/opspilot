<script setup lang="ts">
// Dev-only gallery. Each subsequent task adds a <section> here.
import { ref } from 'vue'
import { useNotify } from '@/composables/useNotify'
const notify = useNotify()
import EmptyState from '@/components/ui/EmptyState.vue'
const serverIcon = `<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>`
import PageHeader from '@/components/ui/PageHeader.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
const badgeKinds: { kind: any; statuses: string[] }[] = [
  { kind: 'server', statuses: ['pending', 'online', 'offline', 'maintenance'] },
  { kind: 'service', statuses: ['up', 'down', 'maintenance'] },
  { kind: 'alert', statuses: ['firing', 'acknowledged', 'snoozed', 'resolved', 'suppressed'] },
  { kind: 'ssl', statuses: ['valid', 'expiring_soon', 'critical', 'expired', 'unreachable'] },
  { kind: 'domain', statuses: ['valid', 'expiring_soon', 'critical', 'expired'] },
  { kind: 'job', statuses: ['healthy', 'late', 'missing', 'paused'] },
]
import StatCard from '@/components/ui/StatCard.vue'
import SlideOver from '@/components/ui/SlideOver.vue'
const slideOpen = ref(false)
import DataGrid, { type FetchPageParams, type FetchPageResult } from '@/components/ui/DataGrid.vue'
import type { ColDef } from 'ag-grid-community'
import { api } from '@/services/api'
import type { Server } from '@/types'

const gridColumns: ColDef[] = [
  { field: 'name', headerName: 'Name' },
  { field: 'host', headerName: 'Host' },
  { field: 'status', headerName: 'Status' },
  { field: 'os_distro', headerName: 'OS' },
]

async function fetchServers(p: FetchPageParams): Promise<FetchPageResult<Server>> {
  const { data } = await api.get<Server[]>('/api/servers')
  const slice = data.slice(p.startRow, p.endRow)
  return { rows: slice, lastRow: data.length }
}
</script>

<template>
  <div class="ui-kit">
    <h1>OpsPilot UI Kit</h1>
    <p class="subtitle">Reusable components &amp; theme reference (dev only)</p>
    <section>
      <h2 class="sec">Notifications (useNotify)</h2>
      <div class="row-demo">
        <VaButton color="success" @click="notify.success('Server saved successfully')">success</VaButton>
        <VaButton color="info" @click="notify.info('Onboarding queued')">info</VaButton>
        <VaButton color="warning" @click="notify.warning('SSL expires in 7 days')">warning</VaButton>
        <VaButton color="danger" @click="notify.error({ message: 'Failed to connect to host' })">error</VaButton>
      </div>
    </section>
    <section>
      <h2 class="sec">EmptyState</h2>
      <div style="border:1px dashed var(--border); border-radius:12px;">
        <EmptyState :icon="serverIcon" title="No servers yet" message="Add your first server to start monitoring.">
          <template #action><VaButton>+ Add Server</VaButton></template>
        </EmptyState>
      </div>
    </section>
    <section>
      <h2 class="sec">PageHeader</h2>
      <PageHeader title="Servers — Acme Corp" subtitle="12 servers • 9 online • 1 pending">
        <template #actions><VaButton>+ Add Server</VaButton></template>
      </PageHeader>
    </section>
    <section>
      <h2 class="sec">StatusBadge</h2>
      <div v-for="g in badgeKinds" :key="g.kind" style="margin-bottom:12px;">
        <div style="color:var(--muted); font-size:11px; margin-bottom:6px;">{{ g.kind }}</div>
        <div class="row-demo">
          <StatusBadge v-for="s in g.statuses" :key="s" :kind="g.kind" :status="s" />
        </div>
      </div>
    </section>
    <section>
      <h2 class="sec">StatCard</h2>
      <div class="row-demo">
        <StatCard label="Servers" :value="12" :icon="serverIcon" accent="primary" />
        <StatCard label="Active Alerts" :value="3" :delta="{ value: '+2 today', direction: 'up' }" />
        <StatCard label="Avg Uptime" value="99.98%" :delta="{ value: '0.0%', direction: 'flat' }" />
      </div>
    </section>
    <section>
      <h2 class="sec">SlideOver</h2>
      <VaButton @click="slideOpen = true">Open SlideOver</VaButton>
      <SlideOver v-model="slideOpen" title="Panel Title" subtitle="example · subtitle">
        <p style="color:var(--text);">Body content goes here. Scrolls if long.</p>
        <template #footer>
          <VaButton preset="secondary" @click="slideOpen = false">Cancel</VaButton>
          <VaButton @click="slideOpen = false">Confirm</VaButton>
        </template>
      </SlideOver>
    </section>
    <section>
      <h2 class="sec">DataGrid (AG Grid Community · Infinite Row Model)</h2>
      <p style="color:var(--muted);font-size:12px;margin-bottom:10px;">Demo adapts /api/servers (client-sliced). Log in first.</p>
      <div style="height:420px;">
        <DataGrid :columns="gridColumns" :fetch-page="fetchServers" :get-row-id="(r:any)=>r.id" />
      </div>
    </section>
    <!-- sections added per task -->
  </div>
</template>

<style scoped>
.ui-kit { padding: 32px 40px; max-width: 1200px; margin: 0 auto; color: var(--text); }
.ui-kit h1 { font-size: 24px; color: #fff; }
.subtitle { color: var(--muted); margin: 4px 0 28px; font-size: 13px; }
.ui-kit :deep(section) { margin-bottom: 40px; }
.ui-kit :deep(h2.sec) { font-size: 14px; color: var(--accent-2); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 14px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
.ui-kit :deep(.row-demo) { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
</style>
