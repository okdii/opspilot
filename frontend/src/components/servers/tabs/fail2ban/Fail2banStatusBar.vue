<script setup lang="ts">
import type { Fail2banStatus } from '@/stores/fail2ban'

defineProps<{ status: Fail2banStatus | null }>()
</script>

<template>
  <div class="status-bar">
    <div class="stat-card" :class="status?.running ? 'ok' : 'err'">
      <div class="label">STATUS</div>
      <div class="value">
        <span class="dot">●</span>
        {{ status?.running ? 'Active' : 'Inactive' }}
      </div>
    </div>
    <div class="stat-card">
      <div class="label">JAILS</div>
      <div class="value">{{ status?.jail_count ?? '—' }}</div>
    </div>
    <div class="stat-card" :class="(status?.currently_banned ?? 0) > 0 ? 'warn' : ''">
      <div class="label">BANNED NOW</div>
      <div class="value">{{ status?.currently_banned ?? '—' }}</div>
    </div>
    <div class="stat-card">
      <div class="label">BANS TODAY</div>
      <div class="value">{{ status?.bans_today ?? '—' }}</div>
    </div>
  </div>
</template>

<style scoped>
.status-bar { display: flex; gap: 12px; }
.stat-card {
  flex: 1; background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px 16px;
}
.stat-card.ok { border-color: #22c55e; }
.stat-card.err { border-color: #ef4444; }
.stat-card.warn { border-color: #ef4444; }
.label { font-size: 10px; text-transform: uppercase; color: var(--muted); margin-bottom: 6px; letter-spacing: 0.05em; }
.value { font-size: 22px; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
.stat-card.ok .value, .stat-card.ok .dot { color: #22c55e; }
.stat-card.err .value, .stat-card.err .dot { color: #ef4444; }
.stat-card.warn .value { color: #ef4444; }
</style>
