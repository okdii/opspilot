<script setup lang="ts">
import { watch, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAlertStore } from '@/stores/alerts'

const store = useAlertStore()
const router = useRouter()

// Auto-dismiss each toast after 8s.
const timers = new Map<string, number>()

watch(
  () => store.recentFired.map((t) => t.id),
  (ids) => {
    for (const id of ids) {
      if (!timers.has(id)) {
        timers.set(id, window.setTimeout(() => dismiss(id), 8000))
      }
    }
    // Clear timers for toasts that are gone.
    for (const [id, handle] of timers) {
      if (!ids.includes(id)) {
        window.clearTimeout(handle)
        timers.delete(id)
      }
    }
  },
  { deep: true },
)

function dismiss(id: string) {
  store.dismissToast(id)
}

function view(id: string) {
  dismiss(id)
  router.push('/alerts')
}

onUnmounted(() => {
  for (const handle of timers.values()) window.clearTimeout(handle)
  timers.clear()
})
</script>

<template>
  <Teleport to="body">
    <div class="toast-stack" aria-live="polite">
      <TransitionGroup name="toast">
        <div
          v-for="t in store.recentFired"
          :key="t.id"
          class="toast"
          :class="t.severity"
          data-testid="alert-toast"
        >
          <span class="toast-dot" :class="t.severity"></span>
          <div class="toast-body">
            <div class="toast-title">{{ t.server_name || t.type }}</div>
            <div class="toast-msg">{{ t.message }}</div>
          </div>
          <div class="toast-actions">
            <button class="toast-view" @click="view(t.id)">View</button>
            <button class="toast-x" aria-label="Dismiss" @click="dismiss(t.id)">✕</button>
          </div>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-stack {
  position: fixed; top: 18px; right: 18px; z-index: 1300;
  display: flex; flex-direction: column; gap: 10px; width: 340px; max-width: calc(100vw - 36px);
}
.toast {
  display: flex; align-items: flex-start; gap: 10px; padding: 14px 16px;
  background: var(--surface); border: 1px solid var(--border); border-left: 3px solid var(--muted);
  border-radius: 10px; box-shadow: 0 12px 30px rgba(0, 0, 0, 0.5);
}
.toast.critical { border-left-color: #ef4444; }
.toast.warning { border-left-color: #f59e0b; }
.toast-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin-top: 4px; background: var(--muted); }
.toast-dot.critical { background: #ef4444; }
.toast-dot.warning { background: #f59e0b; }
.toast-body { flex: 1; min-width: 0; }
.toast-title { font-size: 13px; font-weight: 600; color: #fff; }
.toast-msg { font-size: 12px; color: var(--muted); margin-top: 2px; }
.toast-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; flex-shrink: 0; }
.toast-view { background: none; border: none; color: var(--accent-2); font-size: 12px; font-weight: 600; cursor: pointer; padding: 0; }
.toast-view:hover { color: #fff; }
.toast-x { background: none; border: none; color: var(--muted); font-size: 12px; cursor: pointer; padding: 0; line-height: 1; }
.toast-x:hover { color: var(--text); }
.toast-enter-active, .toast-leave-active { transition: all 0.25s ease; }
.toast-enter-from { opacity: 0; transform: translateX(20px); }
.toast-leave-to { opacity: 0; transform: translateX(20px); }
</style>
