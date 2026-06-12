<script setup lang="ts">
import { onMounted, onUnmounted, computed } from 'vue'
import { useFail2banStore } from '@/stores/fail2ban'
import Fail2banStatusBar from './fail2ban/Fail2banStatusBar.vue'
import Fail2banChart from './fail2ban/Fail2banChart.vue'
import Fail2banJailCards from './fail2ban/Fail2banJailCards.vue'
import Fail2banTopCountries from './fail2ban/Fail2banTopCountries.vue'
import Fail2banBannedTable from './fail2ban/Fail2banBannedTable.vue'

const props = defineProps<{ serverId: string }>()
const store = useFail2banStore()

let pollInterval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  store.fetchAll(props.serverId)
  pollInterval = setInterval(() => store.fetchAll(props.serverId), 5 * 60 * 1000)
})
onUnmounted(() => {
  if (pollInterval) clearInterval(pollInterval)
})

const permissionDenied = computed(() =>
  store.error?.toLowerCase().includes('permission') ?? false
)
const noData = computed(() =>
  !store.loading && !store.error && store.status?.last_checked === null
)
const hasData = computed(() =>
  !store.loading && !store.error && store.status?.last_checked !== null
)
</script>

<template>
  <div class="security-tab">
    <div v-if="store.loading && !store.status" class="empty-state">
      <p class="muted">Loading fail2ban data…</p>
    </div>

    <div v-else-if="permissionDenied" class="empty-state">
      <p class="state-title">Permission denied</p>
      <p class="muted">Add the SSH user to the fail2ban group on this server:</p>
      <code class="setup-cmd">sudo usermod -aG fail2ban opspilot</code>
    </div>

    <div v-else-if="noData" class="empty-state">
      <p class="state-title">fail2ban not detected</p>
      <p class="muted">Install fail2ban and add the SSH user to its group:</p>
      <code class="setup-cmd">sudo apt install fail2ban &amp;&amp; sudo usermod -aG fail2ban opspilot</code>
    </div>

    <template v-else-if="hasData">
      <Fail2banStatusBar :status="store.status!" />
      <div class="chart-row">
        <Fail2banChart :events="store.events" class="chart-col" />
        <Fail2banTopCountries :countries="store.topCountries" class="country-col" />
      </div>
      <Fail2banJailCards :jails="store.jails" />
      <Fail2banBannedTable :server-id="props.serverId" />
    </template>
  </div>
</template>

<style scoped>
.security-tab { display: flex; flex-direction: column; gap: 18px; }
.empty-state {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; min-height: 300px; gap: 12px; text-align: center;
}
.state-title { font-size: 16px; font-weight: 600; color: var(--text); }
.muted { color: var(--muted); font-size: 13px; }
.setup-cmd {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 6px; padding: 8px 16px; font-size: 12px; color: var(--text);
}
.chart-row { display: flex; gap: 18px; }
.chart-col { flex: 2; min-width: 0; }
.country-col { flex: 1; min-width: 0; }
</style>
