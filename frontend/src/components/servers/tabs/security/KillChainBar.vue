<script setup lang="ts">
import type { StageBreakdown } from '@/stores/security'

defineProps<{ stages: StageBreakdown[]; active: string | null }>()
const emit = defineEmits<{ (e: 'select', stage: string): void }>()

function sevClass(s: StageBreakdown): string {
  if (s.count === 0) return 'empty'
  return s.severity === 'critical' ? 'crit' : 'warn'
}
function sevLabel(s: StageBreakdown): string {
  if (s.count === 0) return 'clear'
  return s.severity === 'critical' ? 'critical' : 'warning'
}
</script>

<template>
  <section class="kc" aria-label="Kill chain — attacker progression">
    <div class="kc__head">
      <span class="kc__title">Kill Chain</span>
      <span class="kc__sub">attacker progression · click a stage to filter the feed</span>
    </div>
    <div class="kc__track">
      <template v-for="(s, i) in stages" :key="s.stage">
        <button
          class="kc__stage"
          :class="[sevClass(s), { active: active === s.stage, disabled: s.count === 0 }]"
          :disabled="s.count === 0"
          :aria-pressed="active === s.stage"
          @click="emit('select', s.stage)">
          <span class="kc__name">{{ s.stage }}</span>
          <span class="kc__count">{{ s.count }}</span>
          <span class="kc__sev">{{ sevLabel(s) }}</span>
        </button>
        <span v-if="i < stages.length - 1" class="kc__arrow" aria-hidden="true">›</span>
      </template>
    </div>
  </section>
</template>

<style scoped>
.kc {
  background: var(--surface, #161d2e); border: 1px solid var(--border, #243049);
  border-radius: 12px; padding: 12px 16px 14px;
}
.kc__head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.kc__title { font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase;
  color: var(--muted, #94a3b8); font-weight: 600; }
.kc__sub { font-size: 11px; color: var(--muted, #64748b); }

.kc__track { display: flex; align-items: stretch; gap: 6px; flex-wrap: wrap; }
.kc__stage {
  flex: 1 1 0; min-width: 92px; display: flex; flex-direction: column; align-items: center; gap: 3px;
  background: var(--surface-2, #1a2336); border: 1px solid var(--border, #243049); border-radius: 10px;
  padding: 10px 8px; cursor: pointer;
  transition: border-color .15s ease, background .15s ease, transform .15s ease;
}
.kc__stage:hover:not(.disabled) { transform: translateY(-1px); }
.kc__name { font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted, #94a3b8); }
.kc__count { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums;
  color: var(--text, #e8edf6); line-height: 1; }
.kc__sev { font-size: 10px; text-transform: uppercase; letter-spacing: .4px; color: var(--muted, #64748b); }
.kc__arrow { display: flex; align-items: center; color: var(--muted, #3a465f); font-size: 18px; flex: none; }

/* severity tints (only when the stage has events) */
.kc__stage.crit { border-color: rgba(239,68,68,.45); background: rgba(239,68,68,.08); }
.kc__stage.crit .kc__count { color: #fca5a5; }
.kc__stage.crit .kc__sev { color: #f87171; }
.kc__stage.warn { border-color: rgba(245,158,11,.4); background: rgba(245,158,11,.07); }
.kc__stage.warn .kc__count { color: #fcd34d; }
.kc__stage.warn .kc__sev { color: #fbbf24; }
.kc__stage.empty { opacity: .5; }
.kc__stage.disabled { cursor: default; }

/* active (selected) stage */
.kc__stage.active { border-color: var(--accent-2, #4f8cff); box-shadow: inset 0 0 0 1px var(--accent-2, #4f8cff); }

@media (max-width: 720px) {
  .kc__arrow { display: none; }
  .kc__stage { min-width: 80px; }
}
</style>
