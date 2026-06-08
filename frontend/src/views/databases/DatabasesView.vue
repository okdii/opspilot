<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { PageHeader, EmptyState } from '@/components/ui'
import { useOrgStore } from '@/stores/org'
import { useNotify } from '@/composables/useNotify'
import { useDatabaseStore } from '@/stores/databases'
import type { DbCredentialPayload, DbCredentialStatus } from '@/stores/databases'
import DbNoCredentials from '@/components/databases/DbNoCredentials.vue'
import DbCredentialModal from '@/components/databases/DbCredentialModal.vue'
import DbHealthDashboard from '@/components/databases/DbHealthDashboard.vue'

const orgStore = useOrgStore()
const store = useDatabaseStore()
const notify = useNotify()

const orgId = computed(() => orgStore.activeOrgId)
const canEdit = computed(() => orgStore.canEdit)

const selectedId = ref<string | null>(null)
const modalOpen = ref(false)
const confirmRemove = ref(false)

const servers = computed(() => store.credentials)
const selected = computed<DbCredentialStatus | null>(
  () => servers.value.find((s) => s.server_id === selectedId.value) ?? null,
)

const DB_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/></svg>`

function badge(s: DbCredentialStatus): { glyph: string; tone: string; title: string } {
  if (!s.has_credentials) return { glyph: '—', tone: 'muted', title: 'No credentials configured' }
  if (s.last_check_ok === false) return { glyph: '⚠', tone: 'warn', title: 'Connection error' }
  if (s.last_check_ok == null) return { glyph: '◐', tone: 'pending', title: 'Deploying / awaiting first check' }
  return { glyph: '✓', tone: 'ok', title: 'Connected' }
}

async function load() {
  if (!orgId.value) return
  await store.fetchCredentials(orgId.value)
  // Select first server with credentials, else first server.
  const withCreds = servers.value.find((s) => s.has_credentials)
  selectedId.value = withCreds?.server_id ?? servers.value[0]?.server_id ?? null
}

onMounted(load)
watch(orgId, () => {
  store.reset()
  selectedId.value = null
  void load()
})

function selectServer(id: string) {
  selectedId.value = id
}

// Keyboard: ← / → between tabs.
function onKey(e: KeyboardEvent) {
  if (modalOpen.value || confirmRemove.value) return
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  const idx = servers.value.findIndex((s) => s.server_id === selectedId.value)
  if (idx < 0) return
  const next = e.key === 'ArrowRight' ? idx + 1 : idx - 1
  if (next >= 0 && next < servers.value.length) selectedId.value = servers.value[next].server_id
}
onMounted(() => window.addEventListener('keydown', onKey))

function openSetup() {
  modalOpen.value = true
}

async function onSave(payload: DbCredentialPayload, edit: boolean) {
  if (!selectedId.value) return
  try {
    await store.saveCredentials(selectedId.value, payload, edit)
    modalOpen.value = false
    notify.success('Credentials saved. Re-deploying Telegraf config…')
    // Refresh status so the badge reflects the new state.
    if (orgId.value) await store.fetchCredentials(orgId.value)
  } catch (err) {
    notify.error(err as Error, { title: 'Could not save credentials' })
  }
}

async function onRemove() {
  if (!selectedId.value) return
  try {
    await store.deleteCredentials(selectedId.value)
    confirmRemove.value = false
    notify.success('DB monitoring removed. Re-deploying Telegraf config…')
    if (orgId.value) await store.fetchCredentials(orgId.value)
  } catch (err) {
    notify.error(err as Error, { title: 'Could not remove credentials' })
  }
}
</script>

<template>
  <div class="page">
    <PageHeader title="Database Monitoring" subtitle="MariaDB & PostgreSQL health metrics per server" />

    <!-- No servers in org -->
    <EmptyState
      v-if="!store.loadingCredentials && !servers.length"
      :icon="DB_ICON"
      title="No servers to monitor"
      message="Add and onboard a server before configuring database monitoring."
    >
      <template #action>
        <router-link to="/" class="link-btn">Go to Dashboard</router-link>
      </template>
    </EmptyState>

    <template v-else>
      <!-- Server tab strip -->
      <div class="tab-strip" role="tablist" aria-label="Servers">
        <button
          v-for="s in servers" :key="s.server_id"
          class="srv-tab" :class="{ active: s.server_id === selectedId }"
          role="tab" :aria-selected="s.server_id === selectedId"
          type="button" @click="selectServer(s.server_id)"
        >
          <span class="srv-name">{{ s.server_name }}</span>
          <span class="srv-badge" :class="badge(s).tone" :title="badge(s).title">{{ badge(s).glyph }}</span>
        </button>
      </div>

      <div class="content" v-if="selected">
        <DbNoCredentials
          v-if="!selected.has_credentials"
          :key="`nc-${selected.server_id}`"
          :server-name="selected.server_name"
          :can-edit="canEdit"
          :db-type="selected.db_type ?? 'mysql'"
          @setup="openSetup"
        />
        <DbHealthDashboard
          v-else
          :key="`hd-${selected.server_id}`"
          :server-id="selected.server_id"
          :server-name="selected.server_name"
          :status="selected"
          :can-edit="canEdit"
          :db-type="selected.db_type ?? 'mysql'"
          @edit="modalOpen = true"
          @remove="confirmRemove = true"
        />
      </div>
    </template>

    <!-- Credential modal -->
    <DbCredentialModal
      v-model="modalOpen"
      :server-name="selected?.server_name ?? ''"
      :existing="selected"
      @save="onSave"
    />

    <!-- Remove confirmation -->
    <Teleport to="body">
      <div v-if="confirmRemove" class="confirm-scrim" @click.self="confirmRemove = false">
        <div class="confirm" role="alertdialog" aria-modal="true">
          <h3 class="cf-title">Remove DB monitoring for {{ selected?.server_name }}?</h3>
          <ul class="cf-list">
            <li>Remove stored credentials</li>
            <li>Remove inputs.mysql from Telegraf config (re-deploy required)</li>
            <li>Stop collecting DB metrics (existing history is retained)</li>
          </ul>
          <div class="cf-actions">
            <button class="btn ghost" type="button" @click="confirmRemove = false">Cancel</button>
            <button class="btn danger" type="button" @click="onRemove">Remove</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.page { padding: 28px; max-width: 1300px; }
.link-btn {
  display: inline-block; background: var(--accent); color: #fff; text-decoration: none;
  padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600;
}
.tab-strip {
  display: flex; gap: 6px; flex-wrap: wrap; border-bottom: 1px solid var(--border);
  padding-bottom: 14px; margin-bottom: 20px;
}
.srv-tab {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--surface-2); border: 1px solid var(--border); color: var(--text);
  font-size: 13px; padding: 8px 14px; border-radius: 8px; cursor: pointer; min-height: 38px;
  transition: border-color 0.15s, background 0.15s;
}
.srv-tab:hover { border-color: var(--accent); }
.srv-tab.active { background: rgba(99,102,241,0.15); border-color: var(--accent); color: #fff; }
.srv-name { font-weight: 500; }
.srv-badge {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 50%; font-size: 11px; font-weight: 700;
}
.srv-badge.ok { background: rgba(34,197,94,0.18); color: var(--green); }
.srv-badge.warn { background: rgba(245,158,11,0.18); color: var(--amber); }
.srv-badge.pending { background: rgba(99,102,241,0.18); color: var(--accent-2); }
.srv-badge.muted { background: rgba(107,114,128,0.2); color: var(--muted); }
.content { min-height: 300px; }

.confirm-scrim {
  position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 1200;
  display: flex; align-items: center; justify-content: center; padding: 20px;
}
.confirm {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 22px 24px; max-width: 440px; width: 100%; box-shadow: 0 24px 60px rgba(0,0,0,0.5);
}
.cf-title { font-size: 16px; color: #fff; margin-bottom: 12px; }
.cf-list { margin: 0 0 18px; padding-left: 18px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.cf-actions { display: flex; justify-content: flex-end; gap: 10px; }
.btn { border-radius: 8px; font-size: 13px; font-weight: 600; padding: 9px 16px; cursor: pointer; border: 1px solid transparent; min-height: 40px; }
.btn.ghost { background: var(--surface-2); border-color: var(--border); color: var(--text); }
.btn.ghost:hover { border-color: var(--accent); }
.btn.danger { background: var(--red); color: #fff; }
.btn.danger:hover { opacity: 0.92; }
</style>
