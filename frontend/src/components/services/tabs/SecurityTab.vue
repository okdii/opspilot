<!-- frontend/src/components/services/tabs/SecurityTab.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import SecurityGrade from '@/components/SecurityGrade.vue'
import type { SecurityScan } from '@/stores/services'

const props = defineProps<{
  scan: SecurityScan | null
  loading?: boolean
  scanning?: boolean
}>()

const emit = defineEmits<{ (e: 'run-scan'): void }>()

const TLS_CHECKS = ['TLS Protocol', 'Deprecated Protocol Accepted', 'Cipher Suite']
const CERT_CHECKS = ['Key Size', 'Self-Signed Certificate', 'OCSP Stapling']
const HEADER_CHECKS = ['HSTS', 'Content-Security-Policy', 'X-Frame-Options', 'X-Content-Type-Options', 'Referrer-Policy', 'Permissions-Policy']
const PROTOCOL_CHECKS = ['HTTPS Redirect', 'Server Header Disclosure', 'X-Powered-By Disclosure']

const WEIGHT_MAP: Record<string, number> = {
  'TLS Protocol': 25,
  'Cipher Suite': 20,
  'Key Size': 5,
  'Self-Signed Certificate': 5,
  // OCSP Stapling excluded — always 0 pts (Python stdlib limitation)
  'HSTS': 10,
  'Content-Security-Policy': 8,
  'X-Frame-Options': 4,
  'X-Content-Type-Options': 3,
  'Referrer-Policy': 3,
  'Permissions-Policy': 2,
  'HTTPS Redirect': 5,
  'Server Header Disclosure': 3,
  'X-Powered-By Disclosure': 2,
}

function categoryPts(checks: string[]): { earned: number; max: number } {
  if (!props.scan) return { earned: 0, max: 0 }
  let earned = 0
  let max = 0
  for (const f of props.scan.findings) {
    if (checks.includes(f.check)) {
      const w = WEIGHT_MAP[f.check] ?? 0
      max += w
      if (f.passed) earned += w
    }
  }
  return { earned, max }
}

const tlsPts = computed(() => categoryPts(TLS_CHECKS))
const certPts = computed(() => categoryPts(CERT_CHECKS))
const headerPts = computed(() => categoryPts(HEADER_CHECKS))
const protoPts = computed(() => categoryPts(PROTOCOL_CHECKS))

const categories = computed(() => [
  { label: 'TLS Protocol', checks: TLS_CHECKS, pts: tlsPts.value },
  { label: 'Certificate',  checks: CERT_CHECKS,  pts: certPts.value },
  { label: 'HTTP Headers', checks: HEADER_CHECKS, pts: headerPts.value },
  { label: 'Protocol',     checks: PROTOCOL_CHECKS, pts: protoPts.value },
])

function findingsFor(checks: string[]) {
  return props.scan?.findings.filter(f => checks.includes(f.check)) ?? []
}

function severityClass(severity: string): string {
  if (severity === 'critical') return 'sev-critical'
  if (severity === 'warning') return 'sev-warning'
  return 'sev-info'
}

function fmt(d: string): string {
  return new Date(d).toISOString().replace('T', ' ').slice(0, 19) + ' UTC'
}
</script>

<template>
  <div class="sec-tab">
    <div v-if="loading" class="sec-placeholder">Loading security scan…</div>

    <div v-else-if="!scan" class="sec-placeholder">
      <span>Security scan not yet run — will run within 24 h of first probe.</span>
      <button class="scan-btn scan-btn-center" :disabled="scanning" @click="emit('run-scan')">
        <svg v-if="scanning" class="spin-icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5" stroke-dasharray="28" stroke-dashoffset="10"/>
        </svg>
        <svg v-else viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" class="btn-icon">
          <path d="M13.5 8A5.5 5.5 0 1 1 8 2.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          <path d="M8 2.5V5l2-1.5L8 2.5Z" fill="currentColor"/>
        </svg>
        {{ scanning ? 'Scanning…' : 'Run Scan Now' }}
      </button>
    </div>

    <template v-else>
      <!-- Header: grade + score + manual scan button -->
      <div class="sec-header">
        <div class="sec-grade-block">
          <SecurityGrade :grade="scan.grade" :score="scan.score" size="lg" />
          <div class="sec-score-detail">
            <span class="sec-score-num">{{ scan.score }}<span class="sec-score-max">/100</span></span>
            <span class="sec-scan-time">Scanned {{ fmt(scan.scanned_at) }}</span>
          </div>
        </div>
        <button class="scan-btn" :disabled="scanning" @click="emit('run-scan')">
          <svg v-if="scanning" class="spin-icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5" stroke-dasharray="28" stroke-dashoffset="10"/>
          </svg>
          <svg v-else viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" class="btn-icon">
            <path d="M13.5 8A5.5 5.5 0 1 1 8 2.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            <path d="M8 2.5V5l2-1.5L8 2.5Z" fill="currentColor"/>
          </svg>
          {{ scanning ? 'Scanning…' : 'Run Scan' }}
        </button>
      </div>

      <!-- Category cards grid -->
      <div class="sec-grid">
        <div
          v-for="cat in categories"
          :key="cat.label"
          class="sec-card"
        >
          <div class="sec-card-hd">
            <span class="sec-card-title">{{ cat.label }}</span>
            <span :class="cat.pts.earned === cat.pts.max ? 'pts-ok' : 'pts-warn'">
              {{ cat.pts.earned }}/{{ cat.pts.max }}
            </span>
          </div>

          <div class="sec-card-rows">
            <div
              v-for="f in findingsFor(cat.checks)"
              :key="f.check"
              class="sec-row"
            >
              <span class="sec-status-icon">
                <!-- pass -->
                <svg v-if="f.passed" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" class="icon-pass">
                  <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.5"/>
                  <path d="M5 8l2 2 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <!-- fail -->
                <svg v-else viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" class="icon-fail">
                  <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.5"/>
                  <path d="M8 5v3.5M8 11h.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
              </span>
              <span class="sec-check-name">{{ f.check }}</span>
              <span class="sec-detail" :class="severityClass(f.severity)">{{ f.detail }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Grade legend -->
      <div class="sec-legend">
        <div class="sec-legend-title">Grade Legend</div>
        <div class="legend-grid">
          <span class="lg-grade" style="color:#22c55e">A+</span><span class="lg-desc">Excellent — score ≥ 95, all major checks pass</span>
          <span class="lg-grade" style="color:#22c55e">A</span><span class="lg-desc">Excellent — all critical checks pass</span>
          <span class="lg-grade" style="color:#14b8a6">B</span><span class="lg-desc">Good — minor issues only</span>
          <span class="lg-grade" style="color:#eab308">C</span><span class="lg-desc">Fair — some important headers missing</span>
          <span class="lg-grade" style="color:#f97316">D</span><span class="lg-desc">Poor — multiple issues including header gaps</span>
          <span class="lg-grade" style="color:#ef4444">E</span><span class="lg-desc">Bad — serious configuration problems</span>
          <span class="lg-grade" style="color:#ef4444">F</span><span class="lg-desc">Critical — deprecated TLS, broken ciphers, or severe misconfiguration</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sec-tab { padding: 4px 0; }
.sec-placeholder { color: var(--muted); font-size: 13px; text-align: center; padding: 40px 20px; }

/* Header */
.sec-header { display: flex; align-items: center; gap: 20px; margin-bottom: 20px; padding: 16px; background: var(--surface-2); border-radius: 10px; border: 1px solid var(--border); }
.sec-grade-block { display: flex; align-items: center; gap: 16px; }
.sec-score-detail { display: flex; flex-direction: column; gap: 2px; }
.sec-score-num { font-size: 22px; font-weight: 700; color: var(--text); font-family: ui-monospace, monospace; }
.sec-score-max { font-size: 13px; color: var(--muted); font-weight: 400; }
.sec-scan-time { font-size: 11px; color: var(--muted); }

/* Run Scan button */
.scan-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  background: var(--surface-3, rgba(255,255,255,0.06));
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  white-space: nowrap;
}
.scan-btn:hover:not(:disabled) { background: var(--surface-3, rgba(255,255,255,0.1)); border-color: var(--primary, #6366f1); }
.scan-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.scan-btn-center { margin: 12px auto 0; }
.btn-icon { width: 13px; height: 13px; }
.spin-icon { width: 13px; height: 13px; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* 2-column card grid */
.sec-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}

/* Individual category card */
.sec-card {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}

.sec-card-hd {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
}
.sec-card-title { font-size: 12px; font-weight: 600; color: var(--text); text-transform: uppercase; letter-spacing: 0.04em; }
.pts-ok  { font-size: 12px; font-weight: 600; color: var(--green, #22c55e); font-family: ui-monospace, monospace; }
.pts-warn { font-size: 12px; font-weight: 600; color: var(--amber, #f59e0b); font-family: ui-monospace, monospace; }

.sec-card-rows { padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; }

/* Finding row */
.sec-row { display: grid; grid-template-columns: 16px 1fr; gap: 8px 8px; align-items: start; font-size: 12px; }
.sec-check-name { color: var(--text); font-weight: 500; grid-column: 2; }
.sec-detail { color: var(--muted); font-size: 11px; grid-column: 2; line-height: 1.4; }

/* Status icons */
.sec-status-icon { display: flex; align-items: flex-start; padding-top: 1px; grid-row: 1 / 3; }
.icon-pass { width: 14px; height: 14px; color: var(--green, #22c55e); }
.icon-fail { width: 14px; height: 14px; color: var(--amber, #f59e0b); }

/* Severity overrides on detail text */
.sev-critical { color: var(--red, #ef4444) !important; font-weight: 600; }
.sev-warning  { color: var(--amber, #f59e0b) !important; }
.sev-info     { color: var(--muted); }

/* Grade legend */
.sec-legend { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }
.sec-legend-title { font-size: 12px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px; }
.legend-grid { display: grid; grid-template-columns: 28px 1fr; gap: 4px 12px; align-items: center; }
.lg-grade { font-size: 12px; font-weight: 700; font-family: ui-monospace, monospace; }
.lg-desc { font-size: 12px; color: var(--muted); }

/* Collapse to 1 column on narrow containers */
@media (max-width: 640px) {
  .sec-grid { grid-template-columns: 1fr; }
}
</style>
