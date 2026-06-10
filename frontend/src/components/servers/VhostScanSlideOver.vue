<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { SlideOver } from '@/components/ui'
import { scanVhosts } from '@/services/api'
import { useServiceStore } from '@/stores/services'
import { useNotify } from '@/composables/useNotify'
import type { VhostEntry } from '@/types'

const props = defineProps<{
  modelValue: boolean
  serverId: string
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'registered', count: number): void
}>()

const serviceStore = useServiceStore()
const notify = useNotify()

type Phase = 'scanning' | 'results' | 'error'
const phase = ref<Phase>('scanning')
const errorMessage = ref('')
const vhosts = ref<VhostEntry[]>([])
const selected = ref(new Set<string>())
const registering = ref(false)
const rowErrors = ref<Record<string, string>>({})

const selectableVhosts = computed(() => vhosts.value.filter(v => !v.already_monitored))
const selectedCount = computed(() => selected.value.size)

async function startScan() {
  phase.value = 'scanning'
  errorMessage.value = ''
  vhosts.value = []
  selected.value = new Set()
  rowErrors.value = {}
  try {
    const results = await scanVhosts(props.serverId)
    vhosts.value = results
    // Default: HTTPS domains checked, HTTP unchecked
    selected.value = new Set(
      results.filter(v => !v.already_monitored && v.scheme === 'https').map(v => v.url)
    )
    phase.value = 'results'
  } catch (err: any) {
    const msg = err?.response?.data?.detail?.message ?? 'Failed to scan server'
    errorMessage.value = msg
    phase.value = 'error'
  }
}

function toggle(url: string) {
  const next = new Set(selected.value)
  if (next.has(url)) next.delete(url)
  else next.add(url)
  selected.value = next
}

async function register() {
  registering.value = true
  rowErrors.value = {}
  let successCount = 0

  for (const vhost of selectableVhosts.value) {
    if (!selected.value.has(vhost.url)) continue
    try {
      await serviceStore.createService({
        server_id: props.serverId,
        name: vhost.domain,
        type: 'http',
        url: vhost.url,
        expected_status: 200,
        interval_sec: 60,
        timeout_sec: 5,
        is_active: true,
        is_public: false,
        ignore_ssl_errors: false,
        ...(vhost.scheme === 'https' ? { ssl_warn_days: 30, ssl_critical_days: 7 } : {}),
      })
      successCount++
    } catch {
      rowErrors.value = { ...rowErrors.value, [vhost.url]: 'Failed to register' }
    }
  }

  registering.value = false

  const failCount = Object.keys(rowErrors.value).length
  if (failCount === 0) {
    notify.success(`${successCount} service${successCount !== 1 ? 's' : ''} registered`)
    emit('registered', successCount)
    emit('update:modelValue', false)
  } else {
    notify.error(`${successCount} registered, ${failCount} failed — see errors above`)
    emit('registered', successCount)
  }
}

watch(() => props.modelValue, (v) => { if (v) startScan() })
</script>

<template>
  <SlideOver
    :model-value="modelValue"
    title="Discover Web Services"
    subtitle="Scan web server config and register domains for monitoring"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <!-- Scanning phase -->
    <div v-if="phase === 'scanning'" class="scan-phase">
      <span class="spin"></span>
      <p class="scan-msg">Connecting to server and reading web server config…</p>
    </div>

    <!-- Error phase -->
    <div v-else-if="phase === 'error'" class="error-phase">
      <p class="error-msg">{{ errorMessage }}</p>
      <button class="btn ghost" @click="startScan">Retry</button>
    </div>

    <!-- Results phase -->
    <template v-else-if="phase === 'results'">
      <p v-if="!vhosts.length" class="empty-msg">No virtual hosts found in the web server config.</p>

      <template v-else>
        <p class="found-msg">Found {{ vhosts.length }} web service{{ vhosts.length !== 1 ? 's' : '' }} on this server</p>

        <div class="vhost-list">
          <div
            v-for="v in vhosts"
            :key="v.url"
            class="vhost-row"
            :class="{
              'is-monitored': v.already_monitored,
              'is-selected': !v.already_monitored && selected.has(v.url),
            }"
          >
            <label v-if="!v.already_monitored" class="vhost-check">
              <input type="checkbox" :checked="selected.has(v.url)" @change="toggle(v.url)" />
            </label>
            <span v-else class="vhost-dash">—</span>

            <div class="vhost-info">
              <span class="vhost-url">{{ v.url }}</span>
              <span class="vhost-server">{{ v.server_type }}</span>
            </div>

            <span v-if="v.already_monitored" class="badge badge-gray">already monitoring</span>
            <span v-else-if="rowErrors[v.url]" class="badge badge-red">failed</span>
          </div>
        </div>
      </template>
    </template>

    <template #footer>
      <button type="button" class="btn ghost" @click="emit('update:modelValue', false)">Cancel</button>
      <button
        v-if="phase === 'results' && selectableVhosts.length > 0"
        class="btn primary"
        :disabled="selectedCount === 0 || registering"
        @click="register"
      >
        <span v-if="registering" class="spin btn-spin"></span>
        <span v-else>Register {{ selectedCount > 0 ? selectedCount + ' ' : '' }}service{{ selectedCount !== 1 ? 's' : '' }}</span>
      </button>
    </template>
  </SlideOver>
</template>

<style scoped>
/* Scanning */
.scan-phase { display: flex; flex-direction: column; align-items: center; gap: 16px; padding: 56px 0; }
.scan-msg { color: var(--muted); font-size: 13px; }

/* Error */
.error-phase { display: flex; flex-direction: column; gap: 14px; padding: 24px 0; }
.error-msg {
  color: var(--red); font-size: 13px;
  background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.25);
  border-radius: 8px; padding: 12px 14px;
}

/* Results */
.found-msg { font-size: 12px; color: var(--muted); margin-bottom: 8px; }
.empty-msg { color: var(--muted); font-size: 13px; padding: 48px 0; text-align: center; }

.vhost-list { display: flex; flex-direction: column; gap: 6px; }

.vhost-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--surface-2);
  transition: border-color 0.15s, background 0.15s;
}
.vhost-row.is-selected { border-color: var(--accent); background: rgba(99,102,241,0.07); }
.vhost-row.is-monitored { opacity: 0.4; }

.vhost-check { display: flex; align-items: center; cursor: pointer; }
.vhost-check input { width: 14px; height: 14px; cursor: pointer; accent-color: var(--accent); }
.vhost-dash { width: 18px; text-align: center; color: var(--muted); font-size: 12px; flex-shrink: 0; }

.vhost-info { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.vhost-url { font-size: 13px; color: var(--text); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vhost-server { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }

.badge {
  font-size: 10px; font-weight: 500; text-transform: uppercase;
  letter-spacing: 0.04em; padding: 2px 7px; border-radius: 4px; white-space: nowrap; flex-shrink: 0;
}
.badge-gray { color: var(--muted); background: rgba(107,114,128,0.2); }
.badge-red { color: var(--red); background: rgba(239,68,68,0.15); }

/* Buttons */
.btn {
  padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600;
  cursor: pointer; border: 1px solid var(--border); background: var(--surface-2);
  color: var(--text); display: inline-flex; align-items: center; justify-content: center;
  gap: 8px; min-height: 38px;
}
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
.btn.primary { background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; }
.btn.primary:disabled { opacity: 0.6; cursor: not-allowed; }

/* Spinner */
.spin {
  width: 22px; height: 22px;
  border: 2px solid rgba(99,102,241,0.25); border-top-color: var(--accent);
  border-radius: 50%; animation: spin 0.8s linear infinite;
}
.btn-spin { width: 14px; height: 14px; border-color: rgba(255,255,255,0.4); border-top-color: #fff; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
