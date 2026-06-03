<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useOrgStore } from '@/stores/org'
import { useAlertStore } from '@/stores/alerts'
import { useNotify } from '@/composables/useNotify'
import { PageHeader, EmptyState } from '@/components/ui'
import AlertRow from '@/components/alerts/AlertRow.vue'
import AlertFrequencyChart from '@/components/alerts/AlertFrequencyChart.vue'
import AlertDetailSlideOver from '@/components/alerts/AlertDetailSlideOver.vue'
import type { Alert } from '@/types'

const orgStore = useOrgStore()
const store = useAlertStore()
const notify = useNotify()

type Tab = 'active' | 'history'
const tab = ref<Tab>('active')

const detailOpen = ref(false)
const selected = ref<Alert | null>(null)

const historySearch = ref('')

const BELL_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.73 21a2 2 0 0 1-3.46 0"/><path d="M18.63 13A17.9 17.9 0 0 1 18 8"/><path d="M6.26 6.26A5.86 5.86 0 0 0 6 8c0 7-3 9-3 9h14"/><path d="M18 8a6 6 0 0 0-9.33-5"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`

const orgId = computed(() => orgStore.activeOrgId)

async function loadAll(id: string) {
  await Promise.all([store.fetchActive(id), store.fetchFrequency(id)])
}

function loadHistory(id: string) {
  store.fetchHistory(id, { search: historySearch.value || undefined })
}

onMounted(() => {
  if (orgId.value) loadAll(orgId.value)
})

watch(orgId, (id) => {
  store.reset()
  if (id) {
    loadAll(id)
    if (tab.value === 'history') loadHistory(id)
  }
})

watch(tab, (t) => {
  if (t === 'history' && orgId.value && !store.history.length) loadHistory(orgId.value)
})

function searchHistory() {
  if (orgId.value) loadHistory(orgId.value)
}

function loadMore() {
  if (orgId.value) store.fetchHistory(orgId.value, { search: historySearch.value || undefined }, true)
}

function openDetail(a: Alert) {
  selected.value = a
  detailOpen.value = true
}

async function onAck(a: Alert) {
  try {
    await store.acknowledge(a.id)
    notify.success('Alert acknowledged')
  } catch {
    notify.error('Could not acknowledge alert')
  }
}

async function onSnooze(a: Alert, payload: { minutes?: number; until?: string }) {
  try {
    await store.snooze(a.id, payload)
    notify.success('Alert snoozed')
    detailOpen.value = false
  } catch {
    notify.error('Could not snooze alert')
  }
}

function rel(ts: string | null): string {
  if (!ts) return ''
  const secs = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}
</script>

<template>
  <div class="page">
    <PageHeader title="Alerts" subtitle="Active incidents and resolved alert history">
      <template #actions>
        <router-link v-if="orgStore.canEdit" to="/alerts/rules" class="rules-link">
          Alert Rules
        </router-link>
      </template>
    </PageHeader>

    <AlertFrequencyChart :buckets="store.frequency" />

    <div class="tabs" role="tablist">
      <button
        class="tab" :class="{ active: tab === 'active' }"
        role="tab" :aria-selected="tab === 'active'"
        @click="tab = 'active'"
      >
        Active
        <span v-if="store.active.length" class="tab-count">{{ store.active.length }}</span>
      </button>
      <button
        class="tab" :class="{ active: tab === 'history' }"
        role="tab" :aria-selected="tab === 'history'"
        @click="tab = 'history'"
      >History</button>
    </div>

    <!-- Active tab -->
    <section v-show="tab === 'active'" class="panel">
      <div v-if="store.loadingActive && !store.active.length" class="loading">Loading…</div>
      <EmptyState
        v-else-if="!store.active.length"
        :icon="BELL_SVG"
        title="No active alerts"
        message="Everything is healthy. Alerts will appear here when a rule fires."
      />
      <ul v-else class="alert-list" role="list">
        <AlertRow
          v-for="a in store.active"
          :key="a.id"
          :alert="a"
          @open="openDetail"
          @ack="onAck"
          @snooze="onSnooze"
        />
      </ul>
    </section>

    <!-- History tab -->
    <section v-show="tab === 'history'" class="panel">
      <div class="history-bar">
        <input
          v-model="historySearch"
          class="search-input"
          placeholder="Search message…"
          @keyup.enter="searchHistory"
        />
        <button class="search-btn" @click="searchHistory">Search</button>
      </div>

      <div v-if="store.loadingHistory && !store.history.length" class="loading">Loading…</div>
      <EmptyState
        v-else-if="!store.history.length"
        :icon="BELL_SVG"
        title="No resolved alerts"
        message="Resolved alerts will be archived here."
      />
      <template v-else>
        <ul class="alert-list" role="list">
          <li
            v-for="a in store.history"
            :key="a.id"
            class="hist-row"
            @click="openDetail(a)"
          >
            <span class="ar-dot" :class="a.severity"></span>
            <span class="hist-desc">
              <span class="hist-subject">{{ a.server_name || a.service_name || a.domain_name || a.type }}</span>
              <span class="hist-sep"> — </span>
              <span class="hist-msg">{{ a.message }}</span>
            </span>
            <time class="hist-time">{{ rel(a.resolved_at || a.sent_at) }}</time>
          </li>
        </ul>
        <div v-if="store.historyHasMore" class="load-more-wrap">
          <button class="load-more" :disabled="store.loadingHistory" @click="loadMore">
            {{ store.loadingHistory ? 'Loading…' : 'Load more' }}
          </button>
        </div>
      </template>
    </section>

    <AlertDetailSlideOver
      v-model="detailOpen"
      :alert="selected"
      @ack="onAck"
      @snooze="onSnooze"
    />
  </div>
</template>

<style scoped>
.page { padding: 28px; }
.rules-link {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--surface-2); border: 1px solid var(--border); color: var(--text);
  padding: 8px 14px; border-radius: 8px; font-size: 13px; font-weight: 500; text-decoration: none;
  transition: border-color 0.15s;
}
.rules-link:hover { border-color: var(--accent); color: var(--accent-2); }

.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 16px; }
.tab {
  background: none; border: none; color: var(--muted); font-size: 13px; font-weight: 500;
  padding: 10px 14px; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px;
  display: inline-flex; align-items: center; gap: 7px;
}
.tab:hover { color: var(--text); }
.tab.active { color: #fff; border-bottom-color: var(--accent); }
.tab-count {
  background: rgba(99, 102, 241, 0.18); color: var(--accent-2); font-size: 11px; font-weight: 700;
  border-radius: 10px; padding: 1px 7px; min-width: 18px; text-align: center;
}

.panel {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 8px 14px;
}
.alert-list { list-style: none; padding: 0; margin: 0; }
.loading { padding: 40px; text-align: center; color: var(--muted); font-size: 13px; }

.history-bar { display: flex; gap: 8px; padding: 10px 0; }
.search-input {
  flex: 1; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px;
  color: var(--text); font-size: 13px; padding: 8px 12px;
}
.search-input:focus { outline: none; border-color: var(--accent); }
.search-btn {
  background: var(--accent); color: #fff; border: none; border-radius: 8px;
  padding: 8px 16px; font-size: 13px; font-weight: 600; cursor: pointer;
}
.search-btn:hover { opacity: 0.9; }

.hist-row {
  display: flex; align-items: center; gap: 10px; padding: 11px 8px;
  border-bottom: 1px solid var(--border); font-size: 13px; cursor: pointer; border-radius: 6px;
  transition: background 150ms ease-out;
}
.hist-row:last-child { border-bottom: none; }
.hist-row:hover { background: rgba(255, 255, 255, 0.03); }
.ar-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--muted); }
.ar-dot.critical { background: #ef4444; }
.ar-dot.warning { background: #f59e0b; }
.hist-desc { flex: 1; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; min-width: 0; color: var(--text); }
.hist-subject { font-weight: 500; color: #e2e8f0; }
.hist-sep { color: var(--muted); }
.hist-msg { color: var(--muted); }
.hist-time { font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; flex-shrink: 0; }

.load-more-wrap { text-align: center; padding: 14px 0 6px; }
.load-more {
  background: var(--surface-2); border: 1px solid var(--border); color: var(--text);
  padding: 8px 18px; border-radius: 8px; font-size: 13px; cursor: pointer;
}
.load-more:hover:not(:disabled) { border-color: var(--accent); color: var(--accent-2); }
.load-more:disabled { opacity: 0.5; cursor: default; }
</style>
