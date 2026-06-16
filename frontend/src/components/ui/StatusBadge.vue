<script setup lang="ts">
import { computed } from 'vue'

type Kind = 'server' | 'service' | 'process_service' | 'alert' | 'ssl' | 'domain' | 'job' | 'severity'
type Tone = 'success' | 'danger' | 'warning' | 'info' | 'muted'

const props = defineProps<{ status: string; kind: Kind }>()

const MAP: Record<Kind, Record<string, { label: string; tone: Tone }>> = {
  server: {
    pending: { label: 'Pending', tone: 'muted' },
    online: { label: 'Online', tone: 'success' },
    offline: { label: 'Offline', tone: 'danger' },
    maintenance: { label: 'Maintenance', tone: 'warning' },
  },
  service: {
    up: { label: 'Up', tone: 'success' },
    down: { label: 'Down', tone: 'danger' },
    maintenance: { label: 'Maintenance', tone: 'warning' },
  },
  process_service: {
    running: { label: 'Running', tone: 'success' },
    stopped: { label: 'Stopped', tone: 'danger' },
    not_installed: { label: 'Not Installed', tone: 'muted' },
  },
  alert: {
    firing: { label: 'Firing', tone: 'danger' },
    acknowledged: { label: 'Acknowledged', tone: 'warning' },
    snoozed: { label: 'Snoozed', tone: 'info' },
    resolved: { label: 'Resolved', tone: 'success' },
    suppressed: { label: 'Suppressed', tone: 'muted' },
  },
  ssl: {
    valid: { label: 'Valid', tone: 'success' },
    expiring_soon: { label: 'Expiring Soon', tone: 'warning' },
    critical: { label: 'Critical', tone: 'danger' },
    expired: { label: 'Expired', tone: 'danger' },
    unreachable: { label: 'Unreachable', tone: 'muted' },
  },
  domain: {
    valid: { label: 'Valid', tone: 'success' },
    expiring_soon: { label: 'Expiring Soon', tone: 'warning' },
    critical: { label: 'Critical', tone: 'danger' },
    expired: { label: 'Expired', tone: 'danger' },
  },
  job: {
    healthy: { label: 'Healthy', tone: 'success' },
    late: { label: 'Late', tone: 'warning' },
    missing: { label: 'Missing', tone: 'danger' },
    paused: { label: 'Paused', tone: 'muted' },
  },
  severity: {
    critical: { label: 'Critical', tone: 'danger' },
    warning: { label: 'Warning', tone: 'warning' },
  },
}

const entry = computed(
  () => MAP[props.kind]?.[props.status] ?? { label: props.status, tone: 'muted' as Tone },
)
</script>

<template>
  <span class="status-badge" :class="`tone-${entry.tone}`">
    <span class="sb-dot"></span>{{ entry.label }}
  </span>
</template>

<style scoped>
.status-badge { display: inline-flex; align-items: center; gap: 6px; font-size: 10px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; padding: 3px 8px; border-radius: 4px; }
.sb-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.tone-success { background: rgba(34,197,94,0.15); color: var(--green); }
.tone-danger  { background: rgba(239,68,68,0.15); color: var(--red); }
.tone-warning { background: rgba(245,158,11,0.15); color: var(--amber); }
.tone-info    { background: rgba(99,102,241,0.15); color: var(--accent-2); }
.tone-muted   { background: rgba(107,114,128,0.2); color: var(--muted); }
</style>
