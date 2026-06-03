<script setup lang="ts">
/** Persistent agent-health strip for the Server Detail page (Slice 5).
 *  Reads systemd_units.active_code from the metrics store (one labeled entry
 *  per unit; value === 0 means the unit is active/running) and shows whether
 *  Telegraf and Fluent Bit are up. Fires a one-time warning toast when an
 *  agent transitions to down so operators know metrics may be stale. */
import { computed, ref, watch } from 'vue'
import { useNotify } from '@/composables/useNotify'
import { useMetricsStore } from '@/stores/metrics'
import { labeledList } from '@/utils/metrics'

const metrics = useMetricsStore()
const notify = useNotify()

/** Running when systemd_units.active_code === 0 for the unit; null when no
 *  reading has arrived yet (unknown). */
function unitActive(unit: string): boolean | null {
  // systemd_units carries unit state (active/sub) as *tags*, so stopped and
  // running readings are different label sets that both linger in latestValues.
  // Pick the most recent entry by time, not the first match.
  const entries = labeledList(metrics.latestValues, 'systemd_units.active_code').filter(
    (e) => e.labels.name === unit,
  )
  if (!entries.length) return null
  const latest = entries.reduce((a, b) => (Date.parse(b.time) > Date.parse(a.time) ? b : a))
  if (latest.value == null) return null
  return latest.value === 0
}

const telegrafUp = computed(() => unitActive('telegraf.service'))
const fluentUp = computed(() => unitActive('fluent-bit.service'))

/** Active network interface name (nice-to-have), from the first net.bytes_recv
 *  labeled reading if present. */
const iface = computed(
  () => labeledList(metrics.latestValues, 'net.bytes_recv')[0]?.labels.interface ?? null,
)

interface AgentView {
  name: string
  up: boolean | null
  toneClass: string
  text: string
}

function view(name: string, up: boolean | null): AgentView {
  if (up == null) return { name, up, toneClass: 'unknown', text: 'unknown' }
  return up
    ? { name, up, toneClass: 'running', text: 'running' }
    : { name, up, toneClass: 'stopped', text: 'stopped' }
}

const agents = computed<AgentView[]>(() => [
  view('Telegraf', telegrafUp.value),
  view('Fluent Bit', fluentUp.value),
])

// One-time down toast: track the previous value so the warning fires only on
// the up/unknown → down transition, not on every store update while down.
const prevTelegraf = ref<boolean | null>(telegrafUp.value)
const prevFluent = ref<boolean | null>(fluentUp.value)

function checkTransition(
  name: string,
  prev: ReturnType<typeof ref<boolean | null>>,
  next: boolean | null,
): void {
  // Toast only when we just learned the agent is down (false) and it wasn't
  // already known-down. Never toast on the initial unknown → up case.
  if (next === false && prev.value !== false) {
    notify.warning(`${name} is not running on this server — metrics may be stale`)
  }
  prev.value = next
}

watch(telegrafUp, (v) => checkTransition('Telegraf', prevTelegraf, v))
watch(fluentUp, (v) => checkTransition('Fluent Bit', prevFluent, v))
</script>

<template>
  <footer class="agent-footer">
    <span class="af-label">Agents</span>
    <span v-for="a in agents" :key="a.name" class="af-agent" :class="a.toneClass">
      <span class="af-name">{{ a.name }}</span>
      <span class="af-dot" aria-hidden="true"></span>
      <span class="af-state">{{ a.text }}</span>
    </span>
    <span v-if="iface" class="af-iface">
      <span class="af-iface-key">iface</span>
      {{ iface }}
    </span>
  </footer>
</template>

<style scoped>
.agent-footer {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 8px 16px;
  font-size: 12px;
  color: var(--muted);
  background: var(--surface);
  border-top: 1px solid var(--border);
}
.af-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}
.af-agent {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.af-name {
  color: var(--text);
  font-weight: 500;
}
.af-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--muted);
}
.af-state {
  text-transform: capitalize;
  color: var(--muted);
}
.af-agent.running .af-dot {
  background: var(--green);
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.18);
}
.af-agent.running .af-state {
  color: var(--green);
}
.af-agent.stopped .af-dot {
  background: var(--red);
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.18);
}
.af-agent.stopped .af-state {
  color: var(--red);
}
.af-iface {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text);
}
.af-iface-key {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
}
</style>
