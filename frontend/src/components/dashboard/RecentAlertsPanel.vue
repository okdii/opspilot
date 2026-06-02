<script setup lang="ts">
import { StatusBadge, EmptyState } from '@/components/ui'
import type { RecentAlert } from '@/types'

defineProps<{ alerts: RecentAlert[] }>()

function rel(ts: string | null): string {
  if (!ts) return ''
  const secs = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

// Inline SVG for empty state — bell with slash, no emoji (ui-ux-pro-max: no-emoji-icons)
const BELL_SLASH_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
  <path d="M18.63 13A17.9 17.9 0 0 1 18 8"/>
  <path d="M6.26 6.26A5.86 5.86 0 0 0 6 8c0 7-3 9-3 9h14"/>
  <path d="M18 8a6 6 0 0 0-9.33-5"/>
  <line x1="1" y1="1" x2="23" y2="23"/>
</svg>`
</script>

<template>
  <section class="alerts-panel" aria-label="Recent Alerts">
    <header class="ap-head">
      <h2 class="ap-title">Recent Alerts</h2>
      <router-link to="/alerts" class="ap-viewall" aria-label="View all alerts">
        View All
        <!-- Inline SVG arrow — no emoji (ui-ux-pro-max: no-emoji-icons) -->
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <polyline points="9 18 15 12 9 6"/>
        </svg>
      </router-link>
    </header>

    <EmptyState
      v-if="!alerts.length"
      :icon="BELL_SLASH_SVG"
      title="No recent alerts"
      message="Alerts will appear here once alerting is active."
    />

    <ul v-else class="ap-list" role="list">
      <li
        v-for="a in alerts"
        :key="a.id"
        class="ap-row"
      >
        <!-- Severity dot: critical=red, warning=amber, info=blue, fallback=muted -->
        <span
          class="ap-dot"
          :class="a.severity"
          :aria-label="`${a.severity} severity`"
          role="img"
        ></span>

        <span class="ap-desc">
          <span class="ap-server">{{ a.server_name }}</span>
          <span class="ap-sep" aria-hidden="true"> — </span>
          <span class="ap-msg">{{ a.message }}</span>
        </span>

        <StatusBadge :status="a.state" kind="alert" />

        <time
          class="ap-time"
          :datetime="a.sent_at ?? undefined"
          :title="a.sent_at ?? undefined"
        >{{ rel(a.sent_at) }}</time>
      </li>
    </ul>
  </section>
</template>

<style scoped>
/* ── Panel shell ─────────────────────────────────────────────────────────── */
.alerts-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 18px 4px;    /* bottom reduced: last row has its own 9px padding */
  margin-top: 16px;
}

/* ── Header ──────────────────────────────────────────────────────────────── */
.ap-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.ap-title {
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  letter-spacing: 0.01em;
}

/* ui-ux-pro-max: weight-hierarchy — secondary actions are subordinate */
.ap-viewall {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--accent-2);
  text-decoration: none;
  opacity: 0.8;
  transition: opacity 150ms ease-out, color 150ms ease-out;
  border-radius: 4px;
  padding: 2px 4px;
  /* ui-ux-pro-max: focus-states */
  outline-offset: 2px;
}

.ap-viewall:hover {
  opacity: 1;
  color: #fff;
}

/* ui-ux-pro-max: focus-states — visible focus ring for keyboard nav */
.ap-viewall:focus-visible {
  outline: 2px solid var(--accent-2);
}

/* ── List ────────────────────────────────────────────────────────────────── */
.ap-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  padding: 0;
  margin: 0;
}

/* ui-ux-pro-max: state-clarity — hover state with smooth transition, no layout shift */
.ap-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 6px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  border-radius: 6px;
  transition: background 150ms ease-out;
  cursor: default;
}

.ap-row:last-child {
  border-bottom: none;
}

.ap-row:hover {
  /* ui-ux-pro-max: press-feedback / hover — subtle surface lift, no layout shift */
  background: rgba(255, 255, 255, 0.03);
}

/* ── Severity dot ────────────────────────────────────────────────────────── */
/* ui-ux-pro-max: color-not-only — dot uses color + aria-label for a11y */
.ap-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--muted);
  /* Subtle glow on colored states for dark-mode legibility */
  box-shadow: 0 0 0 2px transparent;
  transition: box-shadow 150ms ease-out;
}

.ap-dot.critical {
  background: #ef4444;
  box-shadow: 0 0 4px rgba(239, 68, 68, 0.5);
}

.ap-dot.warning {
  background: #f59e0b;
  box-shadow: 0 0 4px rgba(245, 158, 11, 0.45);
}

.ap-dot.info {
  background: #3b82f6;
  box-shadow: 0 0 4px rgba(59, 130, 246, 0.45);
}

/* ── Description ─────────────────────────────────────────────────────────── */
.ap-desc {
  flex: 1;
  color: var(--text);
  /* ui-ux-pro-max: truncation-strategy — single-line truncate with ellipsis */
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  min-width: 0;
}

/* ui-ux-pro-max: weight-hierarchy — server name slightly more prominent */
.ap-server {
  font-weight: 500;
  color: #e2e8f0;
}

.ap-sep {
  color: var(--muted);
  font-weight: 400;
}

.ap-msg {
  color: var(--muted);
  font-weight: 400;
}

/* ── Timestamp ───────────────────────────────────────────────────────────── */
/* ui-ux-pro-max: number-tabular — fixed-width monospaced figures for time values */
.ap-time {
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--muted);
  white-space: nowrap;
  flex-shrink: 0;
}
</style>
