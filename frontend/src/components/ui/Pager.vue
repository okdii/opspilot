<script setup lang="ts">
import { computed } from 'vue'

/**
 * Compact pager for server-side paginated lists. `page` is 0-based.
 * Renders nothing when everything fits on one page (total <= pageSize).
 */
const props = defineProps<{ page: number; pageSize: number; total: number; disabled?: boolean }>()
const emit = defineEmits<{ (e: 'update:page', p: number): void }>()

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const from = computed(() => (props.total === 0 ? 0 : props.page * props.pageSize + 1))
const to = computed(() => Math.min(props.total, (props.page + 1) * props.pageSize))
const canPrev = computed(() => props.page > 0 && !props.disabled)
const canNext = computed(() => props.page + 1 < totalPages.value && !props.disabled)
</script>

<template>
  <div v-if="total > pageSize" class="pager">
    <span class="pager__info">{{ from }}–{{ to }} of {{ total }}</span>
    <div class="pager__btns">
      <button class="pager__btn" :disabled="!canPrev"
              @click="emit('update:page', page - 1)" aria-label="Previous page">‹ Prev</button>
      <span class="pager__page">{{ page + 1 }} / {{ totalPages }}</span>
      <button class="pager__btn" :disabled="!canNext"
              @click="emit('update:page', page + 1)" aria-label="Next page">Next ›</button>
    </div>
  </div>
</template>

<style scoped>
.pager {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 16px; border-top: 1px solid var(--border, #1c2638);
}
.pager__info { font-size: 11.5px; color: var(--muted, #94a3b8); font-variant-numeric: tabular-nums; }
.pager__btns { display: flex; align-items: center; gap: 8px; }
.pager__page { font-size: 11.5px; color: var(--muted, #94a3b8); font-variant-numeric: tabular-nums; }
.pager__btn {
  background: var(--surface-2, #1a2336); border: 1px solid var(--border, #243049);
  color: var(--text, #e8edf6); font-size: 12px; font-weight: 600;
  padding: 5px 11px; border-radius: 7px; cursor: pointer; transition: background 0.15s ease;
}
.pager__btn:hover:not(:disabled) { background: var(--surface-3, #222c44); }
.pager__btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
