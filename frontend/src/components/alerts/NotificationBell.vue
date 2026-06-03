<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAlertStore } from '@/stores/alerts'

const store = useAlertStore()
const router = useRouter()
const open = ref(false)

const badge = computed(() => {
  const n = store.firingCount
  if (n <= 0) return null
  return n > 99 ? '99+' : String(n)
})

const top = computed(() => store.active.filter((a) => a.state === 'firing').slice(0, 5))

function rel(ts: string | null): string {
  if (!ts) return ''
  const secs = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

function goToAlerts() {
  open.value = false
  router.push('/alerts')
}
</script>

<template>
  <div class="bell-wrap">
    <button class="bell-btn" :class="{ active: open }" aria-label="Notifications" @click="open = !open">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
        <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
      </svg>
      <span v-if="badge" class="bell-badge" data-testid="bell-badge">{{ badge }}</span>
    </button>

    <Transition name="bell-fade">
      <div v-if="open" class="bell-pop" @click.stop>
        <header class="bp-head">
          <span>Active Alerts</span>
          <button class="bp-viewall" @click="goToAlerts">View all</button>
        </header>
        <div v-if="!top.length" class="bp-empty">No active alerts</div>
        <ul v-else class="bp-list">
          <li v-for="a in top" :key="a.id" class="bp-item" @click="goToAlerts">
            <span class="bp-dot" :class="a.severity"></span>
            <div class="bp-text">
              <div class="bp-subject">{{ a.server_name || a.type }}</div>
              <div class="bp-msg">{{ a.message }}</div>
            </div>
            <time class="bp-time">{{ rel(a.sent_at) }}</time>
          </li>
        </ul>
      </div>
    </Transition>

    <div v-if="open" class="bell-scrim" @click="open = false"></div>
  </div>
</template>

<style scoped>
.bell-wrap { position: relative; }
.bell-btn {
  position: relative; width: 36px; height: 36px; border-radius: 8px;
  background: var(--surface-2); border: 1px solid var(--border); color: var(--muted);
  display: flex; align-items: center; justify-content: center; cursor: pointer; transition: all 0.15s;
}
.bell-btn:hover, .bell-btn.active { border-color: var(--accent); color: var(--text); }
.bell-badge {
  position: absolute; top: -5px; right: -5px; min-width: 17px; height: 17px; padding: 0 4px;
  background: var(--red); color: #fff; font-size: 10px; font-weight: 700; border-radius: 9px;
  display: flex; align-items: center; justify-content: center; border: 2px solid var(--surface);
}
.bell-pop {
  position: absolute; top: calc(100% + 8px); right: 0; width: 320px; z-index: 1200;
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5); overflow: hidden;
}
.bell-scrim { position: fixed; inset: 0; z-index: 1199; }
.bp-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border); font-size: 13px; font-weight: 600; color: #fff;
}
.bp-viewall { background: none; border: none; color: var(--accent-2); font-size: 11px; cursor: pointer; }
.bp-viewall:hover { color: #fff; }
.bp-empty { padding: 28px 16px; text-align: center; color: var(--muted); font-size: 13px; }
.bp-list { list-style: none; margin: 0; padding: 0; max-height: 380px; overflow-y: auto; }
.bp-item {
  display: flex; align-items: flex-start; gap: 10px; padding: 11px 16px;
  border-bottom: 1px solid var(--border); cursor: pointer;
}
.bp-item:last-child { border-bottom: none; }
.bp-item:hover { background: rgba(255, 255, 255, 0.03); }
.bp-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin-top: 4px; background: var(--muted); }
.bp-dot.critical { background: #ef4444; }
.bp-dot.warning { background: #f59e0b; }
.bp-text { flex: 1; min-width: 0; }
.bp-subject { font-size: 12px; font-weight: 500; color: #e2e8f0; }
.bp-msg { font-size: 12px; color: var(--muted); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.bp-time { font-size: 10px; color: var(--muted); flex-shrink: 0; }
.bell-fade-enter-active, .bell-fade-leave-active { transition: opacity 0.15s, transform 0.15s; }
.bell-fade-enter-from, .bell-fade-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
