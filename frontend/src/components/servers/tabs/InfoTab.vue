<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMetricsStore } from '@/stores/metrics'
import { useServerStore } from '@/stores/server'
import { useAuthStore } from '@/stores/auth'
import { getServer } from '@/services/api'
import { formatUptime, humanBytes, labeledList, realMounts, scalarValue, usageColor } from '@/utils/metrics'
import type { Server } from '@/types'

const metrics = useMetricsStore()
const serverStore = useServerStore()
const auth = useAuthStore()
const server = ref<Server | null>(null)
const redeploying = ref(false)
const redeployDone = ref(false)
const isAdmin = computed(() => auth.user?.role === 'admin')

async function redeployAgents() {
  const id = metrics.activeServerId
  if (!id) return
  redeploying.value = true
  redeployDone.value = false
  try {
    await serverStore.redeploy(id)
    redeployDone.value = true
  } finally {
    redeploying.value = false
  }
}

onMounted(async () => {
  const id = metrics.activeServerId
  if (id) {
    try { server.value = await getServer(id) } catch { /* degrade gracefully */ }
  }
})

// --- Identity ----------------------------------------------------------------
const identity = computed(() => ({
  name: server.value?.name ?? '—',
  host: server.value?.host ?? '—',
  sshPort: server.value?.ssh_port != null ? String(server.value.ssh_port) : '—',
  sshUser: server.value?.ssh_user ?? '—',
  authType: server.value?.ssh_auth_type === 'key' ? 'SSH Key' : server.value?.ssh_auth_type === 'password' ? 'Password' : '—',
  tags: server.value?.tags ?? [],
  addedAt: server.value?.created_at ? new Date(server.value.created_at).toLocaleString() : '—',
  lastSeen: server.value?.last_seen_at ? new Date(server.value.last_seen_at).toLocaleString() : 'Never',
}))

// --- OS & Runtime ------------------------------------------------------------
const osInfo = computed(() => {
  const bootEpoch = scalarValue(metrics.latestValues, 'kernel.boot_time')
  return {
    os: server.value?.os_distro ?? '—',
    kernel: server.value?.kernel_version ?? '—',
    uptime: formatUptime(scalarValue(metrics.latestValues, 'system.uptime')),
    bootTime: bootEpoch ? new Date(bootEpoch * 1000).toLocaleString() : '—',
    load1: scalarValue(metrics.latestValues, 'system.load1'),
    load5: scalarValue(metrics.latestValues, 'system.load5'),
    load15: scalarValue(metrics.latestValues, 'system.load15'),
    processes: scalarValue(metrics.latestValues, 'processes.total'),
    running: scalarValue(metrics.latestValues, 'processes.running'),
    zombies: scalarValue(metrics.latestValues, 'processes.zombies'),
  }
})

// linux_sysctl_fs.file-max reports INT64_MAX (≥ 2^62) when the kernel has no
// hard limit configured — display as "Unlimited" to avoid confusing users.
const FD_UNLIMITED = 4_611_686_018_427_387_904 // 2^62

// --- Hardware Spec -----------------------------------------------------------
const hardware = computed(() => {
  const swapTotal = scalarValue(metrics.latestValues, 'swap.total')
  const fdMax = scalarValue(metrics.latestValues, 'linux_sysctl_fs.file-max')
  const fdUsed = scalarValue(metrics.latestValues, 'linux_sysctl_fs.file-nr')
  const fdUnlimited = fdMax != null && fdMax >= FD_UNLIMITED
  return {
    vcpus: scalarValue(metrics.latestValues, 'system.n_cpus'),
    ram: humanBytes(scalarValue(metrics.latestValues, 'mem.total')),
    swap: swapTotal != null && swapTotal > 0 ? humanBytes(swapTotal) : 'None',
    fdMax: fdMax != null ? (fdUnlimited ? 'Unlimited' : fdMax.toLocaleString()) : '—',
    fdUsed: fdUsed != null ? fdUsed.toLocaleString() : '—',
    fdPct: !fdUnlimited && fdMax && fdUsed ? Math.round((fdUsed / fdMax) * 100) : null,
  }
})

// --- Disk Layout -------------------------------------------------------------
const diskRows = computed(() => {
  const totals = realMounts(labeledList(metrics.latestValues, 'disk.total'))
  const usedList = labeledList(metrics.latestValues, 'disk.used')
  const freeList = labeledList(metrics.latestValues, 'disk.free')
  const pctList = labeledList(metrics.latestValues, 'disk.used_percent')
  return totals.map((t) => {
    const path = t.labels.path ?? ''
    const used = usedList.find((e) => e.labels.path === path)?.value ?? null
    const free = freeList.find((e) => e.labels.path === path)?.value ?? null
    const pct = pctList.find((e) => e.labels.path === path)?.value ?? null
    return { path, fstype: t.labels.fstype ?? '—', total: t.value, used, free, pct }
  })
})

// --- Network Interfaces ------------------------------------------------------
const netRows = computed(() => {
  const recvList = labeledList(metrics.latestValues, 'net.bytes_recv')
  const sentList = labeledList(metrics.latestValues, 'net.bytes_sent')
  const errInList = labeledList(metrics.latestValues, 'net.err_in')
  const errOutList = labeledList(metrics.latestValues, 'net.err_out')
  const dropInList = labeledList(metrics.latestValues, 'net.drop_in')
  const dropOutList = labeledList(metrics.latestValues, 'net.drop_out')
  return recvList
    .filter((e) => e.labels.interface !== 'lo')
    .map((e) => {
      const iface = e.labels.interface ?? ''
      return {
        iface,
        recv: humanBytes(e.value),
        sent: humanBytes(sentList.find((x) => x.labels.interface === iface)?.value ?? null),
        errIn: errInList.find((x) => x.labels.interface === iface)?.value ?? 0,
        errOut: errOutList.find((x) => x.labels.interface === iface)?.value ?? 0,
        dropIn: dropInList.find((x) => x.labels.interface === iface)?.value ?? 0,
        dropOut: dropOutList.find((x) => x.labels.interface === iface)?.value ?? 0,
      }
    })
})

function fmtLoad(v: number | null): string {
  return v != null ? v.toFixed(2) : '—'
}
</script>

<template>
  <div class="info-tab">

    <!-- Row 1: Identity + OS/Runtime side by side -->
    <div class="grid-2">
      <!-- Identity -->
      <section class="card">
        <h3>Identity</h3>
        <dl class="kv">
          <dt>Name</dt>         <dd>{{ identity.name }}</dd>
          <dt>Host / IP</dt>    <dd class="mono">{{ identity.host }}</dd>
          <dt>SSH Port</dt>     <dd class="mono">{{ identity.sshPort }}</dd>
          <dt>SSH User</dt>     <dd class="mono">{{ identity.sshUser }}</dd>
          <dt>Auth</dt>         <dd>{{ identity.authType }}</dd>
          <dt>Added</dt>        <dd>{{ identity.addedAt }}</dd>
          <dt>Last Seen</dt>    <dd>{{ identity.lastSeen }}</dd>
          <dt>Tags</dt>
          <dd>
            <span v-if="identity.tags.length" class="tags">
              <span v-for="tag in identity.tags" :key="tag" class="tag">{{ tag }}</span>
            </span>
            <span v-else class="muted">None</span>
          </dd>
        </dl>
      </section>

      <!-- OS & Runtime -->
      <section class="card">
        <h3>OS &amp; Runtime</h3>
        <dl class="kv">
          <dt>Distribution</dt> <dd>{{ osInfo.os }}</dd>
          <dt>Kernel</dt>       <dd class="mono">{{ osInfo.kernel }}</dd>
          <dt>Uptime</dt>       <dd>{{ osInfo.uptime }}</dd>
          <dt>Boot Time</dt>    <dd>{{ osInfo.bootTime }}</dd>
          <dt>Load (1m)</dt>    <dd class="mono">{{ fmtLoad(osInfo.load1) }}</dd>
          <dt>Load (5m)</dt>    <dd class="mono">{{ fmtLoad(osInfo.load5) }}</dd>
          <dt>Load (15m)</dt>   <dd class="mono">{{ fmtLoad(osInfo.load15) }}</dd>
          <dt>Processes</dt>
          <dd>
            {{ osInfo.processes ?? '—' }}
            <span v-if="osInfo.running != null" class="muted"> · {{ osInfo.running }} running</span>
            <span v-if="osInfo.zombies" class="warn"> · {{ osInfo.zombies }} zombie</span>
          </dd>
        </dl>
      </section>
    </div>

    <!-- Row 2: Hardware Spec (single full-width card) -->
    <section class="card">
      <h3>Hardware Spec</h3>
      <div class="hw-grid">
        <div class="hw-item">
          <span class="hw-label">vCPUs</span>
          <span class="hw-value">{{ hardware.vcpus ?? '—' }}</span>
        </div>
        <div class="hw-item">
          <span class="hw-label">Total RAM</span>
          <span class="hw-value">{{ hardware.ram }}</span>
        </div>
        <div class="hw-item">
          <span class="hw-label">Swap</span>
          <span class="hw-value">{{ hardware.swap }}</span>
        </div>
        <div class="hw-item">
          <span class="hw-label">Max FDs</span>
          <span class="hw-value">{{ hardware.fdMax }}</span>
        </div>
        <div class="hw-item">
          <span class="hw-label">Open FDs</span>
          <span class="hw-value">
            {{ hardware.fdUsed }}
            <span v-if="hardware.fdPct != null" class="muted"> ({{ hardware.fdPct }}%)</span>
          </span>
        </div>
      </div>
    </section>

    <!-- Row 3: Disk Layout -->
    <section class="card">
      <h3>Disk Layout</h3>
      <div v-if="diskRows.length" class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Mount Point</th>
              <th>FS Type</th>
              <th>Total</th>
              <th>Used</th>
              <th>Free</th>
              <th>Usage</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in diskRows" :key="row.path">
              <td class="mono">{{ row.path }}</td>
              <td class="muted">{{ row.fstype }}</td>
              <td>{{ humanBytes(row.total) }}</td>
              <td>{{ humanBytes(row.used) }}</td>
              <td>{{ humanBytes(row.free) }}</td>
              <td class="pct-cell">
                <div class="bar-wrap">
                  <div
                    class="bar-fill"
                    :style="{ width: (row.pct ?? 0) + '%', background: usageColor(row.pct) }"
                  />
                </div>
                <span class="pct-label" :style="{ color: usageColor(row.pct) }">
                  {{ row.pct != null ? row.pct.toFixed(1) + '%' : '—' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">No disk data available.</p>
    </section>

    <!-- Row 4: Network Interfaces -->
    <section class="card">
      <h3>Network Interfaces</h3>
      <div v-if="netRows.length" class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Interface</th>
              <th>Recv Total</th>
              <th>Sent Total</th>
              <th>Err In</th>
              <th>Err Out</th>
              <th>Drop In</th>
              <th>Drop Out</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in netRows" :key="row.iface">
              <td class="mono">{{ row.iface }}</td>
              <td>{{ row.recv }}</td>
              <td>{{ row.sent }}</td>
              <td :class="{ warn: Number(row.errIn) > 0 }">{{ row.errIn }}</td>
              <td :class="{ warn: Number(row.errOut) > 0 }">{{ row.errOut }}</td>
              <td :class="{ warn: Number(row.dropIn) > 0 }">{{ row.dropIn }}</td>
              <td :class="{ warn: Number(row.dropOut) > 0 }">{{ row.dropOut }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">No network interface data available.</p>
    </section>

    <section v-if="isAdmin" class="card">
      <h3>Agent Management</h3>
      <p class="agent-desc">Re-pushes Telegraf and Fluent Bit configuration to this server. Use after upgrading OpsPilot to enable new collection features (e.g. kernel log collection).</p>
      <button class="agent-btn" :disabled="redeploying" @click="redeployAgents">
        {{ redeploying ? 'Reconfiguring…' : redeployDone ? 'Done ✓' : 'Reconfigure Agents' }}
      </button>
    </section>

  </div>
</template>

<style scoped>
.info-tab { display: flex; flex-direction: column; gap: 16px; }

/* 2-column grid for top cards */
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 800px) { .grid-2 { grid-template-columns: 1fr; } }

.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.card h3 { font-size: 13px; color: var(--text); margin: 0 0 14px; font-weight: 600; }

/* Key-value definition list */
.kv {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 9px 20px;
  margin: 0;
  font-size: 13px;
}
.kv dt { color: var(--muted); font-weight: 500; white-space: nowrap; }
.kv dd { color: var(--text); margin: 0; }

/* Hardware spec pill grid */
.hw-grid { display: flex; flex-wrap: wrap; gap: 12px; }
.hw-item {
  background: var(--bg, #0f1117);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 110px;
}
.hw-label { font-size: 11px; color: var(--muted); font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; }
.hw-value { font-size: 16px; font-weight: 600; color: var(--text); }

/* Tables */
.table-wrap { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th {
  text-align: left;
  color: var(--muted);
  font-weight: 500;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0 12px 10px 0;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.data-table td {
  color: var(--text);
  padding: 9px 12px 9px 0;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 50%, transparent);
  vertical-align: middle;
}
.data-table tbody tr:last-child td { border-bottom: none; }

/* Disk usage bar */
.pct-cell { display: flex; align-items: center; gap: 10px; min-width: 120px; }
.bar-wrap { flex: 1; height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; min-width: 60px; }
.bar-fill { height: 100%; border-radius: 2px; transition: width 0.3s ease; }
.pct-label { font-size: 12px; font-weight: 500; min-width: 38px; text-align: right; font-variant-numeric: tabular-nums; }

/* Helpers */
.mono { font-family: ui-monospace, monospace; font-size: 12px; }
.muted { color: var(--muted); }
.warn { color: var(--amber, #f59e0b); }
.empty { color: var(--muted); font-size: 13px; margin: 0; }
.tags { display: flex; flex-wrap: wrap; gap: 4px; }
.tag {
  background: color-mix(in srgb, var(--accent-2, #6366f1) 15%, transparent);
  color: var(--accent-2, #6366f1);
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 11px;
  font-weight: 500;
}
.agent-desc { font-size: 12px; color: var(--muted); margin-bottom: 12px; line-height: 1.5; }
.agent-btn { background: var(--surface); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 7px 14px; font-size: 12px; cursor: pointer; }
.agent-btn:hover:not(:disabled) { border-color: var(--accent-2); color: var(--accent-2); }
.agent-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
