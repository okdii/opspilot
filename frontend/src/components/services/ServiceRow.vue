<script setup lang="ts">
import { computed } from 'vue'
import { StatusBadge } from '@/components/ui'
import { relativeTime } from '@/utils/metrics'
import type { Service } from '@/stores/services'

const props = defineProps<{ service: Service; canEdit: boolean; menuOpen: boolean }>()
const emit = defineEmits<{
  (e: 'open'): void
  (e: 'toggle-menu'): void
  (e: 'edit'): void
  (e: 'delete'): void
}>()

const s = computed(() => props.service)

const dotClass = computed(() => {
  if (!s.value.is_active) return 'dot-paused'
  switch (s.value.last_status) {
    case 'up': return 'dot-up'
    case 'down': return 'dot-down'
    case 'timeout': return 'dot-timeout'
    default: return 'dot-unknown'
  }
})

const typeBadge = computed(() => {
  switch (s.value.type) {
    case 'http': return { label: 'HTTP', cls: 'tb-http' }
    case 'tcp': return { label: 'TCP', cls: 'tb-tcp' }
    case 'db': return { label: 'DB', cls: 'tb-db' }
    default: return { label: String(s.value.type).toUpperCase(), cls: 'tb-http' }
  }
})

const target = computed(() =>
  s.value.type === 'http' ? (s.value.url ?? s.value.name) : `${s.value.url ?? ''}:${s.value.port ?? ''}`,
)

const uptimeLabel = computed(() => {
  if (s.value.last_status === 'down') return { text: '↓ DOWN', down: true }
  const u = s.value.uptime_24h
  return { text: u != null ? `↑ ${u}%` : '↑ —', down: false }
})

const avg = computed(() => (s.value.avg_response_ms_24h != null ? `${s.value.avg_response_ms_24h}ms avg` : '— avg'))

function pct(v: number | null): string {
  return v != null ? `${v}%` : '—'
}
</script>

<template>
  <div class="row" :class="{ 'is-down': s.last_status === 'down' && s.is_active }" @click="emit('open')">
    <div class="main">
      <span class="dot" :class="dotClass"></span>
      <div class="ident">
        <div class="line1">
          <span class="name">{{ s.name }}</span>
          <span class="type-badge" :class="typeBadge.cls">{{ typeBadge.label }}</span>
          <span class="server">{{ s.server_name }}</span>
          <span v-if="!s.is_active" class="paused-badge">Paused</span>
          <span v-if="s.is_public" class="public-badge">Public</span>
          <span
            v-if="s.ssl_enabled && ['expiring_soon', 'critical', 'expired'].includes(s.ssl_status ?? '')"
            class="ssl-pill"
            :class="`ssl-pill--${s.ssl_status}`"
            :title="`SSL ${s.ssl_status === 'expiring_soon' ? 'expiring soon' : s.ssl_status} · ${s.ssl_days_remaining ?? '?'} days left`"
          >SSL {{ s.ssl_status === 'expiring_soon' ? 'expiring' : s.ssl_status }}</span>
        </div>
        <div class="target">{{ target }}</div>
      </div>
    </div>

    <div class="stats">
      <span class="uptime" :class="{ down: uptimeLabel.down }">{{ uptimeLabel.text }}</span>
      <span class="meta">{{ avg }}</span>
      <span class="meta">Last: {{ relativeTime(s.last_checked) }}</span>
      <div class="chips">
        <span class="chip">24h {{ pct(s.uptime_24h) }}</span>
        <span class="chip">7d {{ pct(s.uptime_7d) }}</span>
      </div>
    </div>

    <div v-if="canEdit" class="menu-wrap" @click.stop>
      <button class="kebab" aria-label="Service actions" @click="emit('toggle-menu')">⋮</button>
      <div v-if="menuOpen" class="kebab-menu">
        <button class="kmi" @click="emit('open')">View Details</button>
        <button class="kmi" @click="emit('edit')">Edit</button>
        <div class="kmi-div"></div>
        <button class="kmi danger" @click="emit('delete')">Delete</button>
      </div>
    </div>

    <div v-if="s.last_status === 'down' && s.is_active" class="down-banner">
      <StatusBadge kind="service" status="down" />
      <span class="db-text">Service is down — checks are failing.</span>
    </div>
  </div>
</template>

<style scoped>
.row { position: relative; display: flex; align-items: center; gap: 16px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; cursor: pointer; transition: border-color 0.15s; flex-wrap: wrap; }
.row:hover { border-color: var(--accent); }
.row.is-down { border-color: rgba(239,68,68,0.4); }
.main { display: flex; align-items: center; gap: 12px; flex: 1; min-width: 240px; }
.dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.dot-up { background: var(--green); box-shadow: 0 0 8px rgba(34,197,94,0.6); }
.dot-down { background: var(--red); box-shadow: 0 0 8px rgba(239,68,68,0.5); animation: pulse 1.4s ease-in-out infinite; }
.dot-timeout { background: var(--amber); }
.dot-unknown { background: var(--grey, #6b7280); }
.dot-paused { background: var(--grey, #6b7280); opacity: 0.6; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.ident { min-width: 0; }
.line1 { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.name { font-weight: 600; color: #fff; font-size: 14px; }
.type-badge { font-size: 10px; font-weight: 700; letter-spacing: 0.04em; padding: 2px 6px; border-radius: 4px; }
.tb-http { background: rgba(59,130,246,0.15); color: var(--blue, #3b82f6); }
.tb-tcp { background: rgba(129,140,248,0.15); color: #a5b4fc; }
.tb-db { background: rgba(45,212,191,0.15); color: #2dd4bf; }
.server { font-size: 11px; color: var(--muted); }
.paused-badge { font-size: 10px; font-weight: 600; text-transform: uppercase; padding: 2px 6px; border-radius: 4px; background: rgba(245,158,11,0.15); color: var(--amber); }
.public-badge { font-size: 10px; font-weight: 600; text-transform: uppercase; padding: 2px 6px; border-radius: 4px; background: rgba(99,102,241,0.15); color: var(--accent-2); }
.target { font-size: 12px; color: var(--muted); font-family: ui-monospace, monospace; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 360px; }
.stats { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.uptime { font-size: 14px; font-weight: 700; color: var(--green); font-variant-numeric: tabular-nums; }
.uptime.down { color: var(--red); }
.meta { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.chips { display: flex; gap: 6px; }
.chip { font-size: 10px; color: var(--muted); background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 2px 7px; font-variant-numeric: tabular-nums; }
.menu-wrap { position: relative; }
.kebab { background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; padding: 2px 8px; border-radius: 6px; line-height: 1; }
.kebab:hover { background: var(--surface-2); color: var(--text); }
.kebab-menu { position: absolute; top: 100%; right: 0; margin-top: 4px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 4px 0; min-width: 160px; z-index: 50; box-shadow: 0 12px 30px rgba(0,0,0,0.4); }
.kmi { display: block; width: 100%; text-align: left; background: none; border: none; color: var(--text); font-size: 12px; padding: 8px 14px; cursor: pointer; }
.kmi:hover { background: rgba(99,102,241,0.1); color: var(--accent-2); }
.kmi.danger { color: #fca5a5; }
.kmi.danger:hover { background: rgba(239,68,68,0.1); color: var(--red); }
.kmi-div { height: 1px; background: var(--border); margin: 2px 0; }
.down-banner { width: 100%; display: flex; align-items: center; gap: 10px; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); }
.db-text { font-size: 12px; color: #fca5a5; }
.ssl-pill { display: inline-block; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; padding: 2px 6px; border-radius: 4px; }
.ssl-pill--expiring_soon { background: rgba(245,158,11,0.15); color: #f59e0b; }
.ssl-pill--critical      { background: rgba(239,68,68,0.15);  color: #ef4444; }
.ssl-pill--expired       { background: rgba(239,68,68,0.2);   color: #fca5a5; }
</style>
