<!-- frontend/src/components/services/tabs/SecurityTab.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import SecurityGrade from '@/components/SecurityGrade.vue'
import type { SecurityScan } from '@/stores/services'

const props = defineProps<{
  scan: SecurityScan | null
  loading?: boolean
}>()

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

function statusIcon(passed: boolean): string {
  return passed ? '✅' : '⚠️'
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
      Security scan not yet run — will run within 24 h of first probe.
    </div>

    <template v-else>
      <div class="sec-header">
        <div class="sec-grade-block">
          <SecurityGrade :grade="scan.grade" :score="scan.score" size="lg" />
          <div class="sec-score-detail">
            <span class="sec-score-num">{{ scan.score }}<span class="sec-score-max">/100</span></span>
            <span class="sec-scan-time">Scanned {{ fmt(scan.scanned_at) }}</span>
          </div>
        </div>
      </div>

      <div class="sec-categories">
        <details class="sec-cat" open>
          <summary class="sec-cat-hd">
            <span>TLS Protocol</span>
            <span :class="tlsPts.earned === tlsPts.max ? 'cat-ok' : 'cat-warn'">
              {{ tlsPts.earned === tlsPts.max ? '✅' : '⚠️' }} {{ tlsPts.earned }}/{{ tlsPts.max }}
            </span>
          </summary>
          <div class="sec-rows">
            <template v-for="f in scan.findings" :key="f.check">
              <div v-if="TLS_CHECKS.includes(f.check)" class="sec-row">
                <span class="sec-icon">{{ statusIcon(f.passed) }}</span>
                <span class="sec-check-name">{{ f.check }}</span>
                <span class="sec-detail" :class="severityClass(f.severity)">{{ f.detail }}</span>
              </div>
            </template>
          </div>
        </details>

        <details class="sec-cat">
          <summary class="sec-cat-hd">
            <span>Certificate</span>
            <span :class="certPts.earned === certPts.max ? 'cat-ok' : 'cat-warn'">
              {{ certPts.earned === certPts.max ? '✅' : '⚠️' }} {{ certPts.earned }}/{{ certPts.max }}
            </span>
          </summary>
          <div class="sec-rows">
            <template v-for="f in scan.findings" :key="f.check">
              <div v-if="CERT_CHECKS.includes(f.check)" class="sec-row">
                <span class="sec-icon">{{ statusIcon(f.passed) }}</span>
                <span class="sec-check-name">{{ f.check }}</span>
                <span class="sec-detail" :class="severityClass(f.severity)">{{ f.detail }}</span>
              </div>
            </template>
          </div>
        </details>

        <details class="sec-cat">
          <summary class="sec-cat-hd">
            <span>HTTP Headers</span>
            <span :class="headerPts.earned === headerPts.max ? 'cat-ok' : 'cat-warn'">
              {{ headerPts.earned === headerPts.max ? '✅' : '⚠️' }} {{ headerPts.earned }}/{{ headerPts.max }}
            </span>
          </summary>
          <div class="sec-rows">
            <template v-for="f in scan.findings" :key="f.check">
              <div v-if="HEADER_CHECKS.includes(f.check)" class="sec-row">
                <span class="sec-icon">{{ statusIcon(f.passed) }}</span>
                <span class="sec-check-name">{{ f.check }}</span>
                <span class="sec-detail" :class="severityClass(f.severity)">{{ f.detail }}</span>
              </div>
            </template>
          </div>
        </details>

        <details class="sec-cat">
          <summary class="sec-cat-hd">
            <span>Protocol</span>
            <span :class="protoPts.earned === protoPts.max ? 'cat-ok' : 'cat-warn'">
              {{ protoPts.earned === protoPts.max ? '✅' : '⚠️' }} {{ protoPts.earned }}/{{ protoPts.max }}
            </span>
          </summary>
          <div class="sec-rows">
            <template v-for="f in scan.findings" :key="f.check">
              <div v-if="PROTOCOL_CHECKS.includes(f.check)" class="sec-row">
                <span class="sec-icon">{{ statusIcon(f.passed) }}</span>
                <span class="sec-check-name">{{ f.check }}</span>
                <span class="sec-detail" :class="severityClass(f.severity)">{{ f.detail }}</span>
              </div>
            </template>
          </div>
        </details>
      </div>

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
.sec-header { display: flex; align-items: center; gap: 20px; margin-bottom: 20px; padding: 16px; background: var(--surface-2); border-radius: 10px; border: 1px solid var(--border); }
.sec-grade-block { display: flex; align-items: center; gap: 16px; }
.sec-score-detail { display: flex; flex-direction: column; gap: 2px; }
.sec-score-num { font-size: 22px; font-weight: 700; color: var(--text); font-family: ui-monospace, monospace; }
.sec-score-max { font-size: 13px; color: var(--muted); font-weight: 400; }
.sec-scan-time { font-size: 11px; color: var(--muted); }
.sec-categories { display: flex; flex-direction: column; gap: 8px; margin-bottom: 20px; }
.sec-cat { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.sec-cat-hd { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; cursor: pointer; font-size: 13px; font-weight: 600; color: var(--text); list-style: none; }
.sec-cat-hd::-webkit-details-marker { display: none; }
.sec-cat-hd::before { content: '▶ '; font-size: 10px; color: var(--muted); }
details[open] .sec-cat-hd::before { content: '▼ '; }
.cat-ok { color: var(--green, #22c55e); font-size: 12px; }
.cat-warn { color: var(--amber, #f59e0b); font-size: 12px; }
.sec-rows { padding: 4px 16px 12px; display: flex; flex-direction: column; gap: 6px; }
.sec-row { display: grid; grid-template-columns: 20px 180px 1fr; gap: 8px; align-items: start; font-size: 12px; }
.sec-icon { font-size: 12px; }
.sec-check-name { color: var(--text); font-weight: 500; }
.sec-detail { color: var(--muted); }
.sev-critical { color: var(--red, #ef4444); font-weight: 600; }
.sev-warning { color: var(--amber, #f59e0b); }
.sev-info { color: var(--muted); }
.sec-legend { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }
.sec-legend-title { font-size: 12px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px; }
.legend-grid { display: grid; grid-template-columns: 28px 1fr; gap: 4px 12px; align-items: center; }
.lg-grade { font-size: 12px; font-weight: 700; font-family: ui-monospace, monospace; }
.lg-desc { font-size: 12px; color: var(--muted); }
</style>
