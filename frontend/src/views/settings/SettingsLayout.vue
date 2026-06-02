<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PageHeader } from '@/components/ui'

const route = useRoute()
const router = useRouter()

interface Tab {
  key: string
  label: string
  path: string
}

const tabs: Tab[] = [
  { key: 'general', label: 'General', path: '/settings/general' },
  { key: 'team', label: 'Team', path: '/settings/team' },
  { key: 'retention', label: 'Retention', path: '/settings/retention' },
  { key: 'security', label: 'Security', path: '/settings/security' },
  { key: 'infrastructure', label: 'Infrastructure', path: '/settings/infrastructure' },
]

const activeKey = computed(() => {
  const seg = route.path.split('/')[2] ?? 'general'
  return tabs.some((t) => t.key === seg) ? seg : 'general'
})

function select(tab: Tab) {
  if (route.path !== tab.path) void router.push(tab.path)
}

// Keyboard shortcuts: 1–5 switch tabs (ignored while typing in a field).
function onKey(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null
  if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return
  const idx = Number(e.key)
  if (Number.isInteger(idx) && idx >= 1 && idx <= tabs.length) {
    select(tabs[idx - 1])
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="settings">
    <PageHeader title="Settings" subtitle="Manage your OpsPilot instance, team, and infrastructure" />

    <nav class="tabs" role="tablist">
      <button
        v-for="(tab, i) in tabs"
        :key="tab.key"
        class="tab"
        role="tab"
        :class="{ active: activeKey === tab.key }"
        :aria-selected="activeKey === tab.key"
        @click="select(tab)"
      >
        <span class="tab-num">{{ i + 1 }}</span>
        {{ tab.label }}
      </button>
    </nav>

    <section class="tab-body">
      <router-view />
    </section>
  </div>
</template>

<style scoped>
.settings {
  max-width: 1100px;
}
.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 24px;
  flex-wrap: wrap;
}
.tab {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 9px 16px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  margin-bottom: -1px;
}
.tab:hover {
  color: var(--text);
}
.tab.active {
  color: var(--accent-2);
  border-bottom-color: var(--accent-2);
}
.tab-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 4px;
  background: var(--surface-2);
  font-size: 10px;
  font-weight: 600;
  color: var(--muted);
}
.tab.active .tab-num {
  background: rgba(99, 102, 241, 0.15);
  color: var(--accent-2);
}
</style>
