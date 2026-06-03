<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{
  (e: 'snooze', payload: { minutes?: number; until?: string }): void
  (e: 'close'): void
}>()

const PRESETS: { label: string; minutes: number }[] = [
  { label: '15 minutes', minutes: 15 },
  { label: '30 minutes', minutes: 30 },
  { label: '1 hour', minutes: 60 },
  { label: '4 hours', minutes: 240 },
]

const customOpen = ref(false)
const customValue = ref('')
const customError = ref<string | null>(null)

function pick(minutes: number) {
  emit('snooze', { minutes })
}

function applyCustom() {
  customError.value = null
  if (!customValue.value) {
    customError.value = 'Pick a date and time.'
    return
  }
  const dt = new Date(customValue.value)
  if (Number.isNaN(dt.getTime())) {
    customError.value = 'Invalid date.'
    return
  }
  if (dt.getTime() <= Date.now()) {
    customError.value = 'Time must be in the future.'
    return
  }
  emit('snooze', { until: dt.toISOString() })
}
</script>

<template>
  <div class="snooze-pop" @click.stop>
    <div class="sp-head">Snooze until</div>
    <button v-for="p in PRESETS" :key="p.minutes" class="sp-opt" @click="pick(p.minutes)">
      {{ p.label }}
    </button>
    <button class="sp-opt" :class="{ active: customOpen }" @click="customOpen = !customOpen">
      Custom…
    </button>
    <div v-if="customOpen" class="sp-custom">
      <input v-model="customValue" type="datetime-local" class="sp-input" />
      <p v-if="customError" class="sp-err">{{ customError }}</p>
      <button class="sp-apply" @click="applyCustom">Snooze</button>
    </div>
  </div>
</template>

<style scoped>
.snooze-pop {
  position: absolute;
  z-index: 50;
  top: calc(100% + 6px);
  right: 0;
  min-width: 180px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 6px;
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.45);
}
.sp-head {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  padding: 6px 8px 4px;
}
.sp-opt {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  color: var(--text);
  font-size: 13px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
}
.sp-opt:hover, .sp-opt.active { background: rgba(99, 102, 241, 0.12); color: var(--accent-2); }
.sp-custom { padding: 6px 8px 4px; border-top: 1px solid var(--border); margin-top: 4px; }
.sp-input {
  width: 100%;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  font-size: 12px;
  padding: 6px 8px;
}
.sp-err { color: var(--red); font-size: 11px; margin-top: 4px; }
.sp-apply {
  margin-top: 6px;
  width: 100%;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 7px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.sp-apply:hover { opacity: 0.9; }
</style>
