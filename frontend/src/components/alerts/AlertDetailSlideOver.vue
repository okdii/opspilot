<script setup lang="ts">
import { computed, ref } from 'vue'
import { SlideOver, StatusBadge } from '@/components/ui'
import { useOrgStore } from '@/stores/org'
import SnoozePicker from './SnoozePicker.vue'
import type { Alert } from '@/types'

const props = defineProps<{ modelValue: boolean; alert: Alert | null }>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'ack', a: Alert): void
  (e: 'snooze', a: Alert, payload: { minutes?: number; until?: string }): void
}>()

const orgStore = useOrgStore()
const snoozeOpen = ref(false)

function fmt(ts: string | null | undefined): string {
  if (!ts) return ''
  return new Date(ts).toLocaleString()
}

const subject = computed(() => {
  const a = props.alert
  if (!a) return ''
  return a.server_name || a.service_name || a.domain_name || a.type
})

interface TimelineItem { label: string; ts: string | null | undefined; tone: string }
const timeline = computed<TimelineItem[]>(() => {
  const a = props.alert
  if (!a) return []
  const items: TimelineItem[] = [{ label: 'Fired', ts: a.sent_at, tone: 'critical' }]
  if (a.acknowledged_at) items.push({ label: 'Acknowledged', ts: a.acknowledged_at, tone: 'warning' })
  if (a.snoozed_until) items.push({ label: 'Snoozed until', ts: a.snoozed_until, tone: 'info' })
  if (a.resolved_at) items.push({ label: 'Resolved', ts: a.resolved_at, tone: 'success' })
  return items
})

function onAck() {
  if (props.alert) emit('ack', props.alert)
}
function onSnooze(payload: { minutes?: number; until?: string }) {
  snoozeOpen.value = false
  if (props.alert) emit('snooze', props.alert, payload)
}
</script>

<template>
  <SlideOver
    :model-value="modelValue"
    :title="subject"
    :subtitle="alert?.type"
    width="520px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template v-if="alert">
      <div class="ad-toprow">
        <span class="ad-dot" :class="alert.severity"></span>
        <StatusBadge :status="alert.state" kind="alert" />
      </div>

      <p class="ad-message">{{ alert.message }}</p>

      <section class="ad-section">
        <h3 class="ad-h">Timeline</h3>
        <ul class="ad-timeline">
          <li v-for="t in timeline" :key="t.label" class="ad-tl-item">
            <span class="ad-tl-dot" :class="t.tone"></span>
            <span class="ad-tl-label">{{ t.label }}</span>
            <time class="ad-tl-ts">{{ fmt(t.ts) }}</time>
          </li>
        </ul>
      </section>

      <section class="ad-section">
        <h3 class="ad-h">Details</h3>
        <dl class="ad-dl">
          <dt>Type</dt><dd>{{ alert.type }}</dd>
          <dt>Severity</dt><dd class="cap">{{ alert.severity }}</dd>
          <dt v-if="alert.server_name">Server</dt><dd v-if="alert.server_name">{{ alert.server_name }}</dd>
          <dt v-if="alert.service_name">Service</dt><dd v-if="alert.service_name">{{ alert.service_name }}</dd>
          <dt v-if="alert.domain_name">Domain</dt><dd v-if="alert.domain_name">{{ alert.domain_name }}</dd>
        </dl>
        <router-link
          v-if="orgStore.canEdit"
          to="/alerts/rules"
          class="ad-link"
        >Manage alert rules →</router-link>
      </section>
    </template>

    <template #footer>
      <template v-if="alert && orgStore.canActOnAlerts && alert.state !== 'resolved'">
        <button
          v-if="alert.state !== 'acknowledged'"
          class="ad-action primary"
          @click="onAck"
        >Acknowledge</button>
        <div class="ad-snooze-wrap">
          <button class="ad-action" @click="snoozeOpen = !snoozeOpen">Snooze</button>
          <SnoozePicker v-if="snoozeOpen" @snooze="onSnooze" @close="snoozeOpen = false" />
        </div>
      </template>
    </template>
  </SlideOver>
</template>

<style scoped>
.ad-toprow { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.ad-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--muted); }
.ad-dot.critical { background: #ef4444; box-shadow: 0 0 6px rgba(239, 68, 68, 0.5); }
.ad-dot.warning { background: #f59e0b; box-shadow: 0 0 6px rgba(245, 158, 11, 0.45); }
.ad-message { color: var(--text); font-size: 14px; line-height: 1.5; margin-bottom: 22px; }
.ad-section { margin-bottom: 22px; }
.ad-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin-bottom: 10px; }
.ad-timeline { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 12px; }
.ad-tl-item { display: flex; align-items: center; gap: 10px; }
.ad-tl-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.ad-tl-dot.critical { background: #ef4444; }
.ad-tl-dot.warning { background: #f59e0b; }
.ad-tl-dot.info { background: var(--accent-2); }
.ad-tl-dot.success { background: var(--green); }
.ad-tl-label { font-size: 13px; color: var(--text); flex: 1; }
.ad-tl-ts { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.ad-dl { display: grid; grid-template-columns: 110px 1fr; gap: 8px 12px; margin: 0; }
.ad-dl dt { font-size: 12px; color: var(--muted); }
.ad-dl dd { font-size: 13px; color: var(--text); margin: 0; }
.cap { text-transform: capitalize; }
.ad-link { display: inline-block; margin-top: 12px; color: var(--accent-2); font-size: 12px; text-decoration: none; }
.ad-link:hover { color: #fff; }
.ad-action {
  background: var(--surface-2); border: 1px solid var(--border); color: var(--text);
  font-size: 13px; font-weight: 600; padding: 8px 16px; border-radius: 8px; cursor: pointer;
  transition: all 0.15s;
}
.ad-action:hover { border-color: var(--accent); color: var(--accent-2); }
.ad-action.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.ad-action.primary:hover { opacity: 0.9; color: #fff; }
.ad-snooze-wrap { position: relative; }
</style>
