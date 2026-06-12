<script setup lang="ts">
import type { Fail2banJail } from '@/stores/fail2ban'
defineProps<{ jails: Fail2banJail[] }>()
</script>

<template>
  <div v-if="jails.length" class="jail-row">
    <div v-for="jail in jails" :key="jail.jail_name" class="jail-card">
      <div class="jail-name">{{ jail.jail_name }}</div>
      <div class="jail-stat banned">{{ jail.currently_banned }} banned</div>
      <div class="jail-stat failed">{{ jail.currently_failed }} failing</div>
      <div class="jail-total">{{ jail.total_banned.toLocaleString() }} total</div>
    </div>
  </div>
</template>

<style scoped>
.jail-row { display: flex; gap: 12px; flex-wrap: wrap; }
.jail-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 16px; min-width: 140px;
}
.jail-name { font-size: 13px; font-weight: 600; color: var(--text); margin-bottom: 6px; }
.jail-stat { font-size: 12px; margin-bottom: 2px; }
.jail-stat.banned { color: #ef4444; }
.jail-stat.failed { color: #f59e0b; }
.jail-total { font-size: 11px; color: var(--muted); margin-top: 4px; }
</style>
