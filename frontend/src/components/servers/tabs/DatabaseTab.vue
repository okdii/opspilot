<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useOrgStore } from '@/stores/org'
import { useDatabaseStore } from '@/stores/databases'
import type { DbInstanceStatus } from '@/stores/databases'
import { EmptyState } from '@/components/ui'
import DbHealthDashboard from '@/components/databases/DbHealthDashboard.vue'

const route = useRoute()
const orgStore = useOrgStore()
const store = useDatabaseStore()

const serverId = computed(() => route.params.id as string)
const orgId = computed(() => orgStore.activeOrgId)

const serverEntry = computed(() => store.serverFor(serverId.value))
const instances = computed(() => serverEntry.value?.instances ?? [])
const selectedInstanceId = ref<string | null>(null)
const selectedInstance = computed(
  () => instances.value.find((i) => i.credential_id === selectedInstanceId.value) ?? null,
)

function selectInstance(credentialId: string) {
  selectedInstanceId.value = credentialId
}

function instanceDot(inst: DbInstanceStatus): string {
  if (inst.last_check_ok === false) return '⚠'
  if (inst.last_check_ok == null) return '◐'
  return '●'
}

function instanceDotClass(inst: DbInstanceStatus): string {
  if (inst.last_check_ok === false) return 'warn'
  if (inst.last_check_ok == null) return 'pending'
  return 'ok'
}

let pollTimer: ReturnType<typeof setInterval> | null = null

function hasPending(): boolean {
  return instances.value.some((i) => i.last_check_ok == null)
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (!orgId.value) return
    await store.fetchCredentials(orgId.value)
    if (!hasPending()) stopPolling()
  }, 10_000)
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

async function load() {
  if (!orgId.value) return
  await store.fetchCredentials(orgId.value)
  const best =
    instances.value.find((i) => i.last_check_ok === true) ??
    instances.value.find((i) => i.last_check_ok == null) ??
    instances.value[0]
  if (best) selectedInstanceId.value = best.credential_id
  if (hasPending()) startPolling()
}

watch(
  () => orgId.value,
  async (id) => { if (id) await load() },
)

onMounted(load)
onUnmounted(stopPolling)

const DB_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/></svg>`
</script>

<template>
  <div class="db-tab">
    <div v-if="store.loadingCredentials" class="loading">Loading database info…</div>

    <EmptyState
      v-else-if="!instances.length"
      :icon="DB_ICON"
      title="No database monitoring configured"
      message="Set up credentials from the Databases page to monitor this server's database instances."
    />

    <template v-else>
      <div v-if="instances.length > 1" class="inst-bar">
        <button
          v-for="inst in instances" :key="inst.credential_id"
          class="inst-pill"
          :class="{ active: inst.credential_id === selectedInstanceId }"
          type="button"
          @click="selectInstance(inst.credential_id)"
        >
          <span class="inst-dot" :class="instanceDotClass(inst)" aria-hidden="true">{{ instanceDot(inst) }}</span>
          {{ inst.label }}
        </button>
      </div>

      <DbHealthDashboard
        v-if="selectedInstance"
        :key="`hd-${selectedInstance.credential_id}`"
        :server-id="serverId"
        :server-name="serverEntry?.server_name ?? ''"
        :status="selectedInstance"
        :can-edit="false"
        :db-type="selectedInstance.db_type"
        :credential-id="selectedInstance.credential_id"
      />
    </template>
  </div>
</template>

<style scoped>
.db-tab { padding: 4px 0; }
.loading { color: var(--muted); font-size: 13px; padding: 40px 0; text-align: center; }
.inst-bar {
  display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px; align-items: center;
}
.inst-pill {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--surface-2); border: 1px solid var(--border); color: var(--muted);
  font-size: 12px; font-weight: 500; padding: 5px 12px; border-radius: 20px; cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.inst-pill:hover { border-color: var(--accent); color: var(--text); }
.inst-pill.active { background: rgba(99,102,241,0.15); border-color: var(--accent); color: #fff; }
.inst-dot { font-size: 10px; }
.inst-dot.ok { color: var(--green); }
.inst-dot.warn { color: var(--amber); }
.inst-dot.pending { color: var(--accent-2); }
</style>
