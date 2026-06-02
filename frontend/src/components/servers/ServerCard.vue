<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { StatusBadge, MetricBar } from '@/components/ui'
import type { DashboardServer } from '@/types'

const props = defineProps<{ server: DashboardServer }>()
const router = useRouter()

const lastSeen = computed(() => {
  if (!props.server.last_seen_at) return 'never'
  const secs = Math.floor((Date.now() - new Date(props.server.last_seen_at).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
})

function open(): void {
  void router.push(`/servers/${props.server.id}`)
}
</script>

<template>
  <button
    class="server-card"
    :class="`status-${server.status}`"
    type="button"
    :aria-label="`Server ${server.name}, status ${server.status}`"
    @click="open"
  >
    <!-- Header: name + status badge -->
    <div class="sc-head">
      <div class="sc-name-row">
        <!-- Inline SVG server icon — no emoji -->
        <svg
          class="sc-server-icon"
          viewBox="0 0 16 16"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden="true"
        >
          <rect x="1" y="2" width="14" height="4" rx="1.5" stroke="currentColor" stroke-width="1.25" />
          <rect x="1" y="10" width="14" height="4" rx="1.5" stroke="currentColor" stroke-width="1.25" />
          <circle cx="12.5" cy="4" r="0.75" fill="currentColor" />
          <circle cx="12.5" cy="12" r="0.75" fill="currentColor" />
          <line x1="3.5" y1="4" x2="9" y2="4" stroke="currentColor" stroke-width="1.25" stroke-linecap="round" />
          <line x1="3.5" y1="12" x2="9" y2="12" stroke="currentColor" stroke-width="1.25" stroke-linecap="round" />
        </svg>
        <span class="sc-name">{{ server.name }}</span>
      </div>
      <StatusBadge :status="server.status" kind="server" />
    </div>

    <!-- Host -->
    <div class="sc-host">{{ server.host }}</div>

    <!-- Tags (only when present) -->
    <div v-if="server.tags.length" class="sc-tags" role="list" aria-label="Tags">
      <span
        v-for="t in server.tags"
        :key="t"
        class="sc-tag"
        role="listitem"
      >{{ t }}</span>
    </div>

    <!-- Metric bars -->
    <div class="sc-metrics" aria-label="Resource usage">
      <MetricBar label="CPU" :value="server.metrics.cpu" />
      <MetricBar label="RAM" :value="server.metrics.ram" />
      <MetricBar label="Disk" :value="server.metrics.disk" />
    </div>

    <!-- Footer: last seen -->
    <div class="sc-foot">
      <svg
        class="sc-clock-icon"
        viewBox="0 0 16 16"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        <circle cx="8" cy="8" r="6.25" stroke="currentColor" stroke-width="1.25" />
        <path d="M8 5v3.25l2 1.5" stroke="currentColor" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <span class="sc-foot-text">Last seen <time class="sc-lastseen">{{ lastSeen }}</time></span>
    </div>
  </button>
</template>

<style scoped>
/* ── Status accent border (left edge colour) ──────────────────────────────── */
.server-card {
  --sc-accent-color: var(--border);
}
.server-card.status-online     { --sc-accent-color: var(--green); }
.server-card.status-offline    { --sc-accent-color: var(--red); }
.server-card.status-maintenance { --sc-accent-color: var(--amber); }
.server-card.status-pending    { --sc-accent-color: var(--muted); }

/* ── Base card ────────────────────────────────────────────────────────────── */
.server-card {
  /* Reset button defaults */
  appearance: none;
  -webkit-appearance: none;
  border: none;
  font-family: inherit;

  display: block;
  width: 100%;
  min-height: 44px; /* touch-target minimum */
  text-align: left;
  cursor: pointer;
  touch-action: manipulation; /* remove 300ms tap delay */

  background: var(--surface);
  border-top: 1px solid var(--border);
  border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  /* Left accent border driven by status */
  border-left: 3px solid var(--sc-accent-color);
  border-radius: 10px;
  padding: 16px 16px 14px 15px; /* compensate for 3px left border */

  /* Elevation: subtle shadow so card lifts off the page grid */
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35), 0 1px 2px rgba(0, 0, 0, 0.25);

  transition:
    border-color 0.15s ease-out,
    box-shadow   0.15s ease-out,
    transform    0.12s ease-out;
}

/* ── Hover: lift + glow ───────────────────────────────────────────────────── */
.server-card:hover {
  border-top-color:    var(--accent);
  border-right-color:  var(--accent);
  border-bottom-color: var(--accent);
  /* Left stays the status colour for identity, but brightens */
  box-shadow:
    0 4px 12px rgba(0, 0, 0, 0.45),
    0 0 0 1px rgba(99, 102, 241, 0.2); /* faint accent halo */
  transform: translateY(-2px);
}

/* ── Active: press-down ───────────────────────────────────────────────────── */
.server-card:active {
  transform: translateY(0);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
}

/* ── Focus-visible ring (keyboard nav) ───────────────────────────────────── */
.server-card:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.server-card:focus:not(:focus-visible) {
  outline: none;
}

/* ── Respect reduced-motion preference ───────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
  .server-card {
    transition: border-color 0.15s ease-out;
  }
  .server-card:hover  { transform: none; }
  .server-card:active { transform: none; }
}

/* ── Header row ──────────────────────────────────────────────────────────── */
.sc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.sc-name-row {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0; /* allow text truncation */
}

.sc-server-icon {
  width: 14px;
  height: 14px;
  color: var(--muted);
  flex-shrink: 0;
}

.sc-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  /* Slightly brighter on hover — cascade from .server-card:hover */
}

/* ── Host ─────────────────────────────────────────────────────────────────── */
.sc-host {
  font-size: 11px;
  font-weight: 400;
  color: var(--muted);
  margin-top: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-variant-numeric: tabular-nums; /* stable IP/hostname layout */
}

/* ── Tags ─────────────────────────────────────────────────────────────────── */
.sc-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 10px;
}

.sc-tag {
  font-size: 10px;
  font-weight: 500;
  color: var(--muted);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 7px;
  letter-spacing: 0.02em;
  line-height: 1.6;
  white-space: nowrap;
}

/* ── Metrics section ──────────────────────────────────────────────────────── */
.sc-metrics {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid rgba(46, 51, 84, 0.7); /* --border at 70% opacity */
}

/* ── Footer ───────────────────────────────────────────────────────────────── */
.sc-foot {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid rgba(46, 51, 84, 0.7);
}

.sc-clock-icon {
  width: 12px;
  height: 12px;
  color: var(--muted);
  flex-shrink: 0;
  opacity: 0.7;
}

.sc-foot-text {
  font-size: 11px;
  color: var(--muted);
  opacity: 0.85;
}

.sc-lastseen {
  font-variant-numeric: tabular-nums;
  font-weight: 500;
  color: var(--muted);
}
</style>
