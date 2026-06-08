<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { SlideOver } from '@/components/ui'
import type { DbCredentialPayload, DbInstanceStatus, DbType } from '@/stores/databases'

const props = defineProps<{
  modelValue: boolean
  serverName: string
  existing: DbInstanceStatus | null
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'save', payload: DbCredentialPayload, credentialId: string | null): void
}>()

const dbType = ref<DbType>('mysql')

const form = reactive<DbCredentialPayload>({
  host: '127.0.0.1',
  port: 3306,
  username: 'opspilot_monitor',
  password: '',
  is_replica: false,
  db_type: 'mysql',
  label: '',
})
const saving = ref(false)
const errors = reactive<Record<string, string>>({})
const isEdit = ref(false)

watch(dbType, (t) => {
  if (isEdit.value) return
  form.port = t === 'postgres' ? 5432 : 3306
  if (!form.username || form.username === 'opspilot_monitor' || form.username === 'opspilot') {
    form.username = t === 'postgres' ? 'opspilot' : 'opspilot_monitor'
  }
})

watch(
  () => props.modelValue,
  (open) => {
    saving.value = false
    if (!open) return
    Object.keys(errors).forEach((k) => delete errors[k])
    const e = props.existing
    isEdit.value = !!e
    dbType.value = e?.db_type ?? 'mysql'
    form.host = e?.host ?? '127.0.0.1'
    form.port = e?.port ?? (dbType.value === 'postgres' ? 5432 : 3306)
    form.username = e?.username ?? (dbType.value === 'postgres' ? 'opspilot' : 'opspilot_monitor')
    form.password = ''
    form.is_replica = e?.is_replica ?? false
    form.db_type = dbType.value
    form.label = e?.label ?? ''
  },
)

function validate(): boolean {
  Object.keys(errors).forEach((k) => delete errors[k])
  if (!form.host.trim()) errors.host = 'Host is required.'
  else if (/^\w+:\/\//.test(form.host)) errors.host = 'Enter a hostname or IP, no protocol prefix.'
  if (!form.port || form.port < 1 || form.port > 65535) errors.port = 'Port must be 1–65535.'
  if (!form.username.trim()) errors.username = 'Username is required.'
  else if (form.username.length > 80) errors.username = 'Max 80 characters.'
  if (!isEdit.value && !form.password) errors.password = 'Password is required.'
  if (form.password && form.password.length > 255) errors.password = 'Max 255 characters.'
  if (form.label && form.label.length > 60) errors.label = 'Max 60 characters.'
  return Object.keys(errors).length === 0
}

function submit() {
  if (saving.value) return
  if (!validate()) return
  saving.value = true
  const payload: DbCredentialPayload = {
    host: form.host.trim(),
    port: Number(form.port),
    username: form.username.trim(),
    is_replica: form.is_replica,
    db_type: dbType.value,
    label: form.label?.trim() || undefined,
  }
  if (form.password) payload.password = form.password
  emit('save', payload, props.existing?.credential_id ?? null)
}

const showPassword = ref(false)
</script>

<template>
  <SlideOver
    :model-value="modelValue"
    :title="isEdit ? `Edit DB Instance — ${existing?.label ?? serverName}` : `Add DB Instance — ${serverName}`"
    subtitle="Read-only database monitoring user"
    width="480px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <form class="dbc-form" @submit.prevent="submit">
      <!-- DB type selector -->
      <div class="field">
        <label class="label lbl">Database Type</label>
        <div class="type-pills">
          <button
            type="button"
            class="type-pill"
            :class="{ active: dbType === 'mysql' }"
            :disabled="isEdit"
            @click="dbType = 'mysql'"
          >MySQL / MariaDB</button>
          <button
            type="button"
            class="type-pill"
            :class="{ active: dbType === 'postgres' }"
            :disabled="isEdit"
            @click="dbType = 'postgres'"
          >PostgreSQL</button>
        </div>
        <p v-if="isEdit" class="field-hint">Database type cannot be changed after setup.</p>
      </div>

      <div class="row two">
        <label class="field">
          <span class="lbl">Host <i class="req">*</i></span>
          <input v-model="form.host" class="inp" :class="{ err: errors.host }" placeholder="127.0.0.1" />
          <small v-if="errors.host" class="err-msg">{{ errors.host }}</small>
        </label>
        <label class="field port">
          <span class="lbl">Port <i class="req">*</i></span>
          <input v-model.number="form.port" type="number" min="1" max="65535" class="inp" :class="{ err: errors.port }" />
          <small v-if="errors.port" class="err-msg">{{ errors.port }}</small>
        </label>
      </div>

      <label class="field">
        <span class="lbl">Username <i class="req">*</i></span>
        <input v-model="form.username" class="inp" :class="{ err: errors.username }" autocomplete="off" />
        <small v-if="errors.username" class="err-msg">{{ errors.username }}</small>
      </label>

      <label class="field">
        <span class="lbl">Password <i v-if="!isEdit" class="req">*</i></span>
        <div class="pw-wrap">
          <input
            v-model="form.password"
            :type="showPassword ? 'text' : 'password'"
            class="inp"
            :class="{ err: errors.password }"
            :placeholder="isEdit ? '••••••••' : 'monitoring user password'"
            autocomplete="new-password"
          />
          <button type="button" class="pw-toggle" @click="showPassword = !showPassword">
            {{ showPassword ? 'Hide' : 'Show' }}
          </button>
        </div>
        <small v-if="errors.password" class="err-msg">{{ errors.password }}</small>
        <small v-else-if="isEdit" class="hint">Leave password blank to keep existing credentials.</small>
      </label>

      <label class="field">
        <span class="lbl">Instance Label</span>
        <input
          v-model="form.label"
          class="inp"
          :class="{ err: errors.label }"
          placeholder="e.g. Primary, Analytics, Port 3307"
          autocomplete="off"
          maxlength="60"
        />
        <small v-if="errors.label" class="err-msg">{{ errors.label }}</small>
        <small v-else class="hint">Optional — defaults to "{{ dbType }}:{{ form.port }}" if blank.</small>
      </label>

      <label class="toggle-row">
        <input v-model="form.is_replica" type="checkbox" class="chk" />
        <span class="toggle-text">
          <span class="lbl">This server is a replica</span>
          <small class="hint">Enables replication monitoring &amp; lag alerts.</small>
        </span>
      </label>

      <div v-if="form.is_replica" class="info-block">
        <strong>Replication alerts enabled</strong>
        <ul>
          <li>Alert if the replication thread stops running</li>
          <li>Alert if replication lag exceeds 30 seconds</li>
        </ul>
      </div>
    </form>

    <template #footer>
      <button class="btn ghost" type="button" @click="emit('update:modelValue', false)">Cancel</button>
      <button class="btn primary" type="button" :disabled="saving" @click="submit">
        {{ saving ? 'Saving…' : isEdit ? 'Save Credentials' : 'Set Up Monitoring' }}
      </button>
    </template>
  </SlideOver>
</template>

<style scoped>
.dbc-form { display: flex; flex-direction: column; gap: 16px; }
.row.two { display: grid; grid-template-columns: 1fr 120px; gap: 12px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: 12px; color: var(--muted); font-weight: 500; }
.req { color: var(--red); font-style: normal; }
.inp {
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px;
  color: var(--text); font-size: 13px; padding: 10px 12px; width: 100%; height: 40px;
}
.inp:focus { outline: none; border-color: var(--accent); }
.inp.err { border-color: var(--red); }
.err-msg { color: var(--red); font-size: 11px; }
.hint { color: var(--muted); font-size: 11px; }
.pw-wrap { position: relative; display: flex; }
.pw-toggle {
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  background: none; border: none; color: var(--accent-2); font-size: 11px; cursor: pointer; padding: 4px 6px;
}
.toggle-row { display: flex; align-items: flex-start; gap: 10px; cursor: pointer; }
.chk { width: 18px; height: 18px; margin-top: 2px; accent-color: var(--accent); cursor: pointer; }
.toggle-text { display: flex; flex-direction: column; gap: 2px; }
.info-block {
  background: rgba(99,102,241,0.08); border: 1px solid rgba(99,102,241,0.25); border-radius: 8px;
  padding: 12px 14px; font-size: 12px; color: var(--text);
}
.info-block strong { color: var(--accent-2); display: block; margin-bottom: 6px; }
.info-block ul { margin: 0; padding-left: 18px; color: var(--muted); }
.info-block li { margin: 2px 0; }
.btn {
  border-radius: 8px; font-size: 13px; font-weight: 600; padding: 9px 16px; cursor: pointer;
  border: 1px solid transparent; min-height: 40px;
}
.btn.ghost { background: var(--surface-2); border-color: var(--border); color: var(--text); }
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
.btn.primary { background: var(--accent); color: #fff; }
.btn.primary:hover:not(:disabled) { opacity: 0.92; }
.btn.primary:disabled { opacity: 0.5; cursor: default; }
.type-pills { display: flex; gap: 8px; }
.type-pill {
  flex: 1; padding: 8px 16px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--surface-2);
  color: var(--muted); font-size: 13px; font-weight: 500; cursor: pointer;
  transition: all 0.15s;
}
.type-pill.active { background: rgba(99,102,241,0.15); border-color: var(--accent); color: var(--accent-2); }
.type-pill:disabled { opacity: 0.6; cursor: not-allowed; }
.field-hint { font-size: 11px; color: var(--muted); margin-top: 4px; }
</style>
