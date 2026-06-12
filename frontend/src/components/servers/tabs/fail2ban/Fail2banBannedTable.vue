<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useFail2banStore } from '@/stores/fail2ban'
import { flagEmoji } from '@/utils/countryFlag'

const props = defineProps<{ serverId: string }>()
const store = useFail2banStore()
const page = ref(1)

onMounted(() => store.fetchBannedIps(props.serverId, 1))

async function goPage(p: number) {
  page.value = p
  await store.fetchBannedIps(props.serverId, p)
}

function relTime(ts: string | null): string {
  if (!ts) return '—'
  const diff = Date.now() - new Date(ts).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

const totalPages = computed(() => Math.ceil((store.bannedIps?.total ?? 0) / (store.bannedIps?.per_page ?? 50)))
</script>

<template>
  <section class="card">
    <div class="table-header">
      <h3>Currently Banned IPs</h3>
      <span class="total-badge">{{ store.bannedIps?.total ?? 0 }} total</span>
    </div>

    <div v-if="!store.bannedIps?.items?.length" class="no-data">
      No IPs currently banned
    </div>

    <table v-else class="ban-table">
      <thead>
        <tr>
          <th>IP Address</th>
          <th>Country</th>
          <th>ISP</th>
          <th>Jail</th>
          <th>Banned Since</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in store.bannedIps!.items" :key="item.ip + item.jail">
          <td class="mono">{{ item.ip }}</td>
          <td>
            <span class="flag-emoji">{{ flagEmoji(item.country_code) }}</span>
            {{ item.country_code ?? '—' }}
          </td>
          <td class="isp-cell">{{ item.isp ?? '—' }}</td>
          <td><span class="jail-badge">{{ item.jail }}</span></td>
          <td class="time-cell">{{ relTime(item.banned_since) }}</td>
        </tr>
      </tbody>
    </table>

    <div v-if="totalPages > 1" class="pagination">
      <button :disabled="page <= 1" @click="goPage(page - 1)">← Prev</button>
      <span>{{ page }} / {{ totalPages }}</span>
      <button :disabled="page >= totalPages" @click="goPage(page + 1)">Next →</button>
    </div>
  </section>
</template>

<style scoped>
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.table-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
h3 { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.total-badge { font-size: 11px; background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 2px 8px; color: var(--muted); }
.no-data { color: var(--muted); font-size: 13px; padding: 24px 0; text-align: center; }
.ban-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ban-table th { text-align: left; padding: 8px 10px; color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid var(--border); }
.ban-table td { padding: 8px 10px; border-bottom: 1px solid var(--border); color: var(--text); }
.ban-table tr:last-child td { border-bottom: none; }
.ban-table tr:hover td { background: var(--bg); }
.mono { font-family: monospace; font-size: 12px; }
.flag-emoji { margin-right: 4px; }
.isp-cell { color: var(--muted); max-width: 180px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.jail-badge { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 1px 6px; font-size: 11px; }
.time-cell { color: var(--muted); white-space: nowrap; }
.pagination { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 14px; }
.pagination button { background: var(--surface); border: 1px solid var(--border); border-radius: 5px; padding: 4px 12px; color: var(--text); cursor: pointer; font-size: 12px; }
.pagination button:disabled { opacity: 0.4; cursor: default; }
.pagination span { font-size: 12px; color: var(--muted); }
</style>
