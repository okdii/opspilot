<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { SlideOver } from '@/components/ui'
import { getApiError } from '@/services/api'
import type { LogRule } from '@/types'

const props = defineProps<{
  modelValue: boolean
  rule: LogRule | null
  servers: { id: string; name: string }[]
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'submit', payload: { id?: string; body: Record<string, unknown> }): void
}>()

const SOURCES = ['php_app', 'nginx_access', 'nginx_error', 'php_fpm', 'mariadb_error', 'mariadb_slow', 'auth', 'syslog', 'kernel']
const COOLDOWNS = [15, 30, 60, 120, 240]

const serverId = ref('')
const source = ref('php_app')
const pattern = ref('')
const severity = ref<'warning' | 'critical'>('critical')
const threshold = ref(1)
const windowSec = ref(300)
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
      source.value = props.rule.source
      pattern.value = props.rule.pattern
      severity.value = (props.rule.severity as 'warning' | 'critical') || 'critical'
      threshold.value = props.rule.threshold
      windowSec.value = props.rule.window_sec
      cooldown.value = props.rule.cooldown_min
      enabled.value = props.rule.enabled
    } else {
      serverId.value = props.servers[0]?.id ?? ''
      source.value = 'php_app'
      pattern.value = ''
      severity.value = 'critical'
      threshold.value = 1
      windowSec.value = 300
      cooldown.value = 60
      enabled.value = true
    }
  },
)

function save() {
  error.value = null
  if (!pattern.value.trim()) {
    error.value = 'Pattern is required.'
    return
  }
  if (windowSec.value < 10 || windowSec.value > 3600) {
    error.value = 'Window must be between 10 and 3600 seconds.'
    return
  }
  saving.value = true
  try {
    const body = {
      source: source.value,
      pattern: pattern.value,
      severity: severity.value,
      threshold: threshold.value,
      window_sec: windowSec.value,
      cooldown_min: cooldown.value,
      enabled: enabled.value,
    }
    if (isEdit.value && props.rule) {
      emit('submit', { id: props.rule.id, body })
    } else {
      emit('submit', { body: { ...body, server_id: serverId.value } })
    }
  } finally {
    saving.value = false
  }
}

function setError(err: unknown) {
  error.value = getApiError(err)?.message ?? 'Could not save rule.'
}
defineExpose({ setError })
</script>

<template>
  <SlideOver
    :model-value="modelValue"
    :title="isEdit ? 'Edit Log Rule' : 'New Log Rule'"
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
        <span class="lbl">Source</span>
        <select v-model="source" class="ctl">
          <option v-for="s in SOURCES" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>

      <label class="field">
        <span class="lbl">Pattern (ILIKE, use %)</span>
        <input v-model="pattern" class="ctl" placeholder="%Fatal error%" maxlength="500" />
      </label>

      <label class="field">
        <span class="lbl">Severity</span>
        <select v-model="severity" class="ctl">
          <option value="critical">Critical</option>
          <option value="warning">Warning</option>
        </select>
      </label>

      <label class="field">
        <span class="lbl">Threshold (matches)</span>
        <input v-model.number="threshold" type="number" min="1" class="ctl" />
      </label>

      <label class="field">
        <span class="lbl">Window (seconds)</span>
        <input v-model.number="windowSec" type="number" min="10" max="3600" class="ctl" />
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
