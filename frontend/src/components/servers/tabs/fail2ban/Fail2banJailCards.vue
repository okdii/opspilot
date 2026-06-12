<script setup lang="ts">
import type { Fail2banJail } from '@/stores/fail2ban'
defineProps<{ jails: Fail2banJail[] }>()

function fmtDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 0) return 'permanent'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`
  return `${Math.round(seconds / 86400)}d`
}
</script>

<template>
  <div v-if="jails.length" class="jail-row">
    <div v-for="jail in jails" :key="jail.jail_name" class="jail-card">
      <div class="jail-name">{{ jail.jail_name }}</div>
      <div class="jail-stat banned">{{ jail.currently_banned }} banned</div>
      <div class="jail-stat failed">{{ jail.currently_failed }} failing</div>
      <div class="jail-total">{{ jail.total_banned.toLocaleString() }} total</div>
      <div v-if="jail.bantime_seconds !== null" class="jail-config">
        <span class="cfg-item" title="Ban duration">⏱ {{ fmtDuration(jail.bantime_seconds) }}</span>
        <span class="cfg-item" title="Detection window">🔍 {{ fmtDuration(jail.findtime_seconds) }}</span>
        <span class="cfg-item" title="Max retries before ban">✕ {{ jail.maxretry ?? '—' }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.jail-row { display: flex; gap: 12px; flex-wrap: wrap; }
.jail-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 16px; min-width: 160px;
}
.jail-name { font-size: 13px; font-weight: 600; color: var(--text); margin-bottom: 6px; }
.jail-stat { font-size: 12px; margin-bottom: 2px; }
.jail-stat.banned { color: #ef4444; }
.jail-stat.failed { color: #f59e0b; }
.jail-total { font-size: 11px; color: var(--muted); margin-top: 4px; }
.jail-config {
  display: flex; gap: 8px; margin-top: 8px;
  padding-top: 8px; border-top: 1px solid var(--border);
}
.cfg-item { font-size: 11px; color: var(--muted); }
</style>
