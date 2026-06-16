<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useSecurityStore } from '@/stores/security'
import StatusBadge from '@/components/ui/StatusBadge.vue'

const props = defineProps<{ serverId: string }>()
const store = useSecurityStore()
let poll: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  store.fetchEvents(props.serverId)
  poll = setInterval(() => store.fetchEvents(props.serverId), 60 * 1000)
})
onUnmounted(() => {
  if (poll) clearInterval(poll)
})

function rel(ts: string): string {
  const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000)
  if (s < 60) return `${Math.floor(s)}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}
</script>

<template>
  <section class="sec-events">
    <header class="sec-events__head">
      <h3>Security Events</h3>
    </header>

    <div v-if="store.loading && !store.events.length" class="sec-events__skeleton">
      <div v-for="n in 3" :key="n" class="skeleton-row" />
    </div>

    <p v-else-if="store.error" class="sec-events__error" role="alert">{{ store.error }}</p>

    <div v-else-if="!store.events.length" class="sec-events__empty">
      <span aria-hidden="true">🛡️</span>
      <p>No security events detected.</p>
    </div>

    <ul v-else class="sec-events__list">
      <li v-for="e in store.events" :key="e.id" class="sec-row">
        <StatusBadge :status="e.severity" kind="severity" class="sec-row__sev" />
        <span class="sec-row__stage">{{ e.stage }}</span>
        <span class="sec-row__msg" :title="e.message">{{ e.message }}</span>
        <time class="sec-row__time" :datetime="e.at">{{ rel(e.at) }}</time>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.sec-events { margin-bottom: 1.5rem; }
.sec-events__head h3 { font-size: 1rem; font-weight: 600; margin: 0 0 0.75rem; }
.sec-events__list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.25rem; }
.sec-row { display: grid; grid-template-columns: auto auto 1fr auto; align-items: center; gap: 0.75rem;
  padding: 0.6rem 0.75rem; border-radius: 8px; background: var(--va-background-secondary, #1b1f2a); }
.sec-row__sev { flex: none; }
.sec-row__stage { font-size: 0.7rem; padding: 0.1rem 0.5rem; border-radius: 999px;
  background: var(--va-background-element, #2a3040); color: var(--va-text-secondary, #9aa4b2); }
.sec-row__msg { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--va-text-primary, #e6e9ef); }
.sec-row__time { font-variant-numeric: tabular-nums; font-size: 0.75rem; color: var(--va-text-secondary, #9aa4b2); }
.sec-events__error { color: var(--red, #ef4444); font-size: 0.85rem; }
.sec-events__empty { display: flex; flex-direction: column; align-items: center; gap: 0.4rem;
  padding: 1.5rem; color: var(--va-text-secondary, #9aa4b2); }
.skeleton-row { height: 40px; border-radius: 8px; margin-bottom: 0.4rem;
  background: linear-gradient(90deg, #1b1f2a 25%, #232838 37%, #1b1f2a 63%); background-size: 400% 100%;
  animation: shimmer 1.4s ease infinite; }
@keyframes shimmer { 0% { background-position: 100% 0; } 100% { background-position: 0 0; } }
@media (prefers-reduced-motion: reduce) { .skeleton-row { animation: none; } }
</style>
