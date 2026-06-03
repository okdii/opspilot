<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { SlideOver } from '@/components/ui'
import { getApiError } from '@/services/api'
import type { MetricRule } from '@/types'

const props = defineProps<{
  modelValue: boolean
  rule: MetricRule | null
  servers: { id: string; name: string }[]
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'submit', payload: { id?: string; body: Record<string, unknown> }): void
}>()

const METRICS = [
  { value: 'cpu', label: 'CPU usage %' },
  { value: 'ram', label: 'RAM usage %' },
  { value: 'disk', label: 'Disk usage %' },
  { value: 'disk_inode', label: 'Disk inodes %' },
  { value: 'db_connections', label: 'DB connections' },
  { value: 'db_replication_lag', label: 'DB replication lag' },
]
const WINDOWS = [1, 3, 5, 10, 15]
const COOLDOWNS = [15, 30, 60, 120, 240]

const serverId = ref('')
const metric = ref('cpu')
const threshold = ref<number>(85)
const window = ref(5)
const cooldown = ref(60)
const enabled = ref(true)
const error = ref<string | null>(null)
const saving = ref(false)

const isEdit = computed(() => !!props.rule)

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    error.value = null
    if (props.rule) {
      serverId.value = props.rule.server_id
      metric.value = props.rule.metric
      threshold.value = props.rule.threshold
      window.value = props.rule.rolling_window_min
      cooldown.value = props.rule.cooldown_min
      enabled.value = props.rule.enabled
    } else {
      serverId.value = props.servers[0]?.id ?? ''
      metric.value = 'cpu'
      threshold.value = 85
      window.value = 5
      cooldown.value = 60
      enabled.value = true
    }
  },
)

async function save() {
  error.value = null
  if (threshold.value <= 0) {
    error.value = 'Threshold must be greater than 0.'
    return
  }
  saving.value = true
  try {
    if (isEdit.value && props.rule) {
      emit('submit', {
        id: props.rule.id,
        body: {
          threshold: threshold.value,
          rolling_window_min: window.value,
          cooldown_min: cooldown.value,
          enabled: enabled.value,
        },
      })
    } else {
      emit('submit', {
        body: {
          server_id: serverId.value,
          metric: metric.value,
          threshold: threshold.value,
          rolling_window_min: window.value,
          cooldown_min: cooldown.value,
          enabled: enabled.value,
        },
      })
    }
  } finally {
    saving.value = false
  }
}

// Allow parent to surface a server error inline.
function setError(err: unknown) {
  error.value = getApiError(err)?.message ?? 'Could not save rule.'
}
defineExpose({ setError })
</script>

<template>
  <SlideOver
    :model-value="modelValue"
    :title="isEdit ? 'Edit Metric Rule' : 'New Metric Rule'"
    width="460px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="form">
      <label class="field">
        <span class="lbl">Server</span>
        <select v-model="serverId" :disabled="isEdit" class="ctl">
          <option v-for="s in servers" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
      </label>

      <label class="field">
        <span class="lbl">Metric</span>
        <select v-model="metric" :disabled="isEdit" class="ctl">
          <option v-for="m in METRICS" :key="m.value" :value="m.value">{{ m.label }}</option>
        </select>
      </label>

      <label class="field">
        <span class="lbl">Threshold</span>
        <input v-model.number="threshold" type="number" min="1" class="ctl" />
      </label>

      <label class="field">
        <span class="lbl">Rolling window (min)</span>
        <select v-model.number="window" class="ctl">
          <option v-for="w in WINDOWS" :key="w" :value="w">{{ w }}</option>
        </select>
      </label>

      <label class="field">
        <span class="lbl">Cooldown (min)</span>
        <select v-model.number="cooldown" class="ctl">
          <option v-for="c in COOLDOWNS" :key="c" :value="c">{{ c }}</option>
        </select>
      </label>

      <label class="toggle-field">
        <input v-model="enabled" type="checkbox" />
        <span>Enabled</span>
      </label>

      <p v-if="error" class="err">{{ error }}</p>
    </div>

    <template #footer>
      <button class="btn ghost" @click="emit('update:modelValue', false)">Cancel</button>
      <button class="btn primary" :disabled="saving" @click="save">Save Rule</button>
    </template>
  </SlideOver>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: 16px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: 12px; color: var(--muted); }
.ctl {
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px;
  color: var(--text); font-size: 13px; padding: 9px 11px;
}
.ctl:disabled { opacity: 0.6; }
.ctl:focus { outline: none; border-color: var(--accent); }
.toggle-field { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text); }
.err { color: var(--red); font-size: 12px; }
.btn { padding: 8px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid var(--border); }
.btn.ghost { background: var(--surface-2); color: var(--text); }
.btn.ghost:hover { border-color: var(--accent); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn.primary:hover { opacity: 0.9; }
.btn:disabled { opacity: 0.5; cursor: default; }
</style>
