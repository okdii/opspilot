<script setup lang="ts">
import { computed } from 'vue'
import type { Fail2banCountry } from '@/stores/fail2ban'

const props = defineProps<{ countries: Fail2banCountry[] }>()

const top = computed(() => props.countries.slice(0, 10))
const maxCount = computed(() => Math.max(...top.value.map(c => c.count), 1))

function flagEmoji(code: string): string {
  if (!code || code === 'XX') return '🏳'
  return code.toUpperCase().replace(/./g, ch =>
    String.fromCodePoint(0x1F1E6 + ch.charCodeAt(0) - 65)
  )
}
</script>

<template>
  <section class="card">
    <h3>Top Countries (24h)</h3>
    <div v-if="top.length === 0" class="no-data">No data yet</div>
    <div v-else class="country-list">
      <div v-for="c in top" :key="c.country_code" class="country-row">
        <span class="flag">{{ flagEmoji(c.country_code) }}</span>
        <span class="name">{{ c.country_name }}</span>
        <div class="bar-wrap">
          <div class="bar" :style="{ width: (c.count / maxCount * 100) + '%' }" />
        </div>
        <span class="count">{{ c.count }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; height: 100%; }
h3 { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px; }
.no-data { color: var(--muted); font-size: 13px; padding: 24px 0; text-align: center; }
.country-list { display: flex; flex-direction: column; gap: 7px; }
.country-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.flag { font-size: 14px; width: 20px; }
.name { color: var(--text); width: 90px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-wrap { flex: 1; background: var(--bg); border-radius: 2px; height: 6px; overflow: hidden; }
.bar { height: 100%; background: #ef4444; border-radius: 2px; transition: width 0.3s; }
.count { color: var(--muted); width: 32px; text-align: right; font-variant-numeric: tabular-nums; }
</style>
