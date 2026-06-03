<script setup lang="ts">
import { ref } from 'vue'
import { StatusBadge } from '@/components/ui'
import { useOrgStore } from '@/stores/org'
import SnoozePicker from './SnoozePicker.vue'
import type { Alert } from '@/types'

const props = defineProps<{ alert: Alert }>()
const emit = defineEmits<{
  (e: 'open', a: Alert): void
  (e: 'ack', a: Alert): void
  (e: 'snooze', a: Alert, payload: { minutes?: number; until?: string }): void
}>()

const orgStore = useOrgStore()
const snoozeOpen = ref(false)

function rel(ts: string | null): string {
  if (!ts) return ''
  const secs = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

const subject = (a: Alert) =>
  a.server_name || a.service_name || a.domain_name || a.type || 'Alert'

function onAck() {
  emit('ack', props.alert)
}
function onSnooze(payload: { minutes?: number; until?: string }) {
  snoozeOpen.value = false
  emit('snooze', props.alert, payload)
}
</script>

<template>
  <li class="alert-row" @click="emit('open', alert)">
    <span
      class="ar-dot"
      :class="alert.severity"
      :aria-label="`${alert.severity} severity`"
      role="img"
    ></span>

    <span class="ar-desc">
      <span class="ar-subject">{{ subject(alert) }}</span>
      <span class="ar-sep" aria-hidden="true"> — </span>
      <span class="ar-msg">{{ alert.message }}</span>
    </span>

    <StatusBadge :status="alert.state" kind="alert" />

    <time class="ar-time" :datetime="alert.sent_at ?? undefined" :title="alert.sent_at ?? undefined">
      {{ rel(alert.sent_at) }}
    </time>

    <div
      v-if="orgStore.canActOnAlerts && alert.state !== 'resolved'"
      class="ar-actions"
      @click.stop
    >
      <button
        v-if="alert.state !== 'acknowledged'"
        class="ar-btn"
        @click="onAck"
      >Ack</button>
      <div class="ar-snooze-wrap">
        <button class="ar-btn" @click="snoozeOpen = !snoozeOpen">Snooze</button>
        <SnoozePicker v-if="snoozeOpen" @snooze="onSnooze" @close="snoozeOpen = false" />
      </div>
    </div>
  </li>
</template>

<style scoped>
.alert-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 8px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  border-radius: 6px;
  transition: background 150ms ease-out;
  cursor: pointer;
  position: relative;
}
.alert-row:last-child { border-bottom: none; }
.alert-row:hover { background: rgba(255, 255, 255, 0.03); }

.ar-dot {
  width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--muted);
  transition: box-shadow 150ms ease-out;
}
.ar-dot.critical { background: #ef4444; box-shadow: 0 0 4px rgba(239, 68, 68, 0.5); }
.ar-dot.warning { background: #f59e0b; box-shadow: 0 0 4px rgba(245, 158, 11, 0.45); }

.ar-desc {
  flex: 1; color: var(--text); overflow: hidden; white-space: nowrap;
  text-overflow: ellipsis; min-width: 0;
}
.ar-subject { font-weight: 500; color: #e2e8f0; }
.ar-sep { color: var(--muted); }
.ar-msg { color: var(--muted); }

.ar-time {
  font-size: 11px; font-variant-numeric: tabular-nums; color: var(--muted);
  white-space: nowrap; flex-shrink: 0;
}

.ar-actions { display: flex; gap: 6px; flex-shrink: 0; align-items: center; }
.ar-snooze-wrap { position: relative; }
.ar-btn {
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}
.ar-btn:hover { border-color: var(--accent); color: var(--accent-2); }
</style>
