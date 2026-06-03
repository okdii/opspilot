<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useOrgStore } from '@/stores/org'
import { useOnboardingStore } from '@/stores/onboarding'
import { useAlertStore } from '@/stores/alerts'
import { wsClient } from '@/utils/ws'
import OrgSwitcher from './OrgSwitcher.vue'
import NotificationBell from '@/components/alerts/NotificationBell.vue'
import AlertToast from '@/components/alerts/AlertToast.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const orgStore = useOrgStore()
const onboarding = useOnboardingStore()
const alertStore = useAlertStore()
const userMenuOpen = ref(false)

const ALERT_EVENTS = ['alert_fired', 'alert_updated', 'alert_resolved'] as const

// Single app-wide WS connection. Onboarding-channel messages are dispatched
// to the onboarding store; alert events (flat {event,data}) drive the bell +
// toast app-wide; other channels are handled by their own views.
let unbindWs: (() => void) | null = null
let subscribedOrg: string | null = null

function startWs() {
  unbindWs = wsClient.on((msg: any) => {
    const channel: string | undefined = msg?.channel
    if (typeof channel === 'string' && channel.startsWith('onboarding:')) {
      const serverId = channel.slice('onboarding:'.length)
      onboarding.applyEvent(serverId, msg.event, msg.data ?? {})
      return
    }
    if (typeof msg?.event === 'string' && (ALERT_EVENTS as readonly string[]).includes(msg.event)) {
      alertStore.applyAlertEvent(msg.event, msg.data ?? {})
    }
  })
  void wsClient.connect()
  subscribeActiveOrg()
}

// Subscribe to the active org channel so alert_fired arrives app-wide (the bell
// + toast must update on any page, not only the dashboard).
function subscribeActiveOrg() {
  const orgId = orgStore.activeOrgId
  if (!orgId || subscribedOrg === orgId) return
  if (subscribedOrg) wsClient.send({ action: 'unsubscribe_org', org_id: subscribedOrg })
  wsClient.send({ action: 'subscribe_org', org_id: orgId })
  subscribedOrg = orgId
  // Prime the bell count for the active org.
  void alertStore.fetchActive(orgId)
}

function stopWs() {
  unbindWs?.()
  unbindWs = null
  subscribedOrg = null
  wsClient.disconnect()
}

interface NavItem { name: string; route: string; adminOnly?: boolean }
const nav: NavItem[] = [
  { name: 'Dashboard',     route: '/' },
  { name: 'Servers',       route: '/servers' },
  { name: 'Alerts',        route: '/alerts' },
  { name: 'Logs',          route: '/logs' },
  { name: 'Organizations', route: '/organizations', adminOnly: true },
  { name: 'Settings',      route: '/settings/general', adminOnly: true },
]

const navIcons: Record<string, string> = {
  '/': `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/></svg>`,
  '/servers': `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>`,
  '/organizations': `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/></svg>`,
  '/logs': `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg>`,
  '/alerts': `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>`,
  '/settings/general': `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>`,
}

const visibleNav = computed(() => nav.filter((n) => !n.adminOnly || auth.isAdmin))

onMounted(async () => {
  if (auth.isAuthenticated) {
    await orgStore.fetchOrgs()
    startWs()
  }
})

onUnmounted(stopWs)

watch(() => auth.isAuthenticated, async (v) => {
  if (v) {
    await orgStore.fetchOrgs()
    startWs()
  } else {
    alertStore.reset()
    stopWs()
  }
})

// Re-subscribe the bell to the newly-active org and refresh its count.
watch(() => orgStore.activeOrgId, () => {
  if (auth.isAuthenticated) subscribeActiveOrg()
})

async function logout() {
  stopWs()
  await auth.logout()
  await router.replace('/login')
}
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="logo">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
          </svg>
        </span>
        <span class="name">OpsPilot</span>
      </div>

      <OrgSwitcher />

      <nav class="nav">
        <router-link
          v-for="item in visibleNav"
          :key="item.route"
          :to="item.route"
          class="nav-link"
          active-class="active"
          :class="{ active: route.path === item.route }"
        >
          <span class="nav-icon" v-html="navIcons[item.route]"></span>
          <span>{{ item.name }}</span>
        </router-link>

        <div class="nav-spacer"></div>
      </nav>

      <div class="user-card" :class="{ open: userMenuOpen }">
        <button class="user-btn" @click="userMenuOpen = !userMenuOpen">
          <div class="avatar">{{ auth.user?.username?.charAt(0).toUpperCase() }}</div>
          <div class="user-info">
            <div class="user-name">{{ auth.user?.username }}</div>
            <div class="user-role">{{ auth.user?.role }}</div>
          </div>
          <span class="chev">▾</span>
        </button>
        <div v-if="userMenuOpen" class="user-menu">
          <router-link to="/profile" class="menu-item" @click="userMenuOpen = false">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            My Profile
          </router-link>
          <div class="menu-divider"></div>
          <button class="menu-item logout" @click="logout">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
            Sign Out
          </button>
        </div>
      </div>
    </aside>

    <main class="content">
      <div class="topbar">
        <NotificationBell />
      </div>
      <router-view />
    </main>

    <AlertToast />
  </div>
</template>

<style scoped>
/* .app-shell — namespaced to avoid colliding with Vuestic UI's global `.layout`
   grid-container class (which forces max-width:1125px + margin:auto, centering the app). */
.app-shell { display: flex; min-height: 100vh; }
.sidebar { width: 240px; background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; }
.brand { padding: 18px 20px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid var(--border); }
.brand .logo { width: 28px; height: 28px; background: linear-gradient(135deg, var(--accent), var(--accent-2)); border-radius: 7px; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; }
.brand .name { font-size: 16px; font-weight: 700; color: #fff; letter-spacing: -0.3px; }
.org-switcher { margin: 12px 0; }
.nav { flex: 1; padding: 12px; display: flex; flex-direction: column; gap: 2px; }
.nav-link { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 8px; color: var(--muted); text-decoration: none; font-size: 13px; transition: all 0.15s; }
.nav-link:hover { background: var(--surface-2); color: var(--text); }
.nav-link.active { background: rgba(99,102,241,0.15); color: var(--accent-2); }
.nav-icon { width: 18px; height: 18px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.nav-spacer { flex: 1; }
.user-card { padding: 12px; border-top: 1px solid var(--border); position: relative; }
.user-btn { width: 100%; display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; cursor: pointer; color: var(--text); transition: border-color 0.15s; }
.user-btn:hover, .user-card.open .user-btn { border-color: var(--accent); }
.avatar { width: 32px; height: 32px; border-radius: 50%; background: linear-gradient(135deg, var(--accent), var(--accent-2)); display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 600; font-size: 13px; }
.user-info { flex: 1; text-align: left; }
.user-name { font-size: 13px; color: var(--text); font-weight: 500; }
.user-role { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.chev { color: var(--muted); font-size: 10px; }
.user-menu { position: absolute; bottom: calc(100% + 4px); left: 12px; right: 12px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 4px 0; box-shadow: 0 -12px 30px rgba(0,0,0,0.4); }
.menu-item { display: flex; align-items: center; gap: 10px; padding: 8px 12px; font-size: 13px; color: var(--text); text-decoration: none; cursor: pointer; background: none; border: none; width: 100%; text-align: left; }
.menu-item:hover { background: rgba(99,102,241,0.1); color: var(--accent-2); }
.menu-item.logout:hover { background: rgba(239,68,68,0.1); color: var(--red); }
.menu-divider { height: 1px; background: var(--border); margin: 2px 0; }
.content { flex: 1; overflow-y: auto; position: relative; }
.topbar {
  position: absolute; top: 18px; right: 28px; z-index: 40;
  display: flex; align-items: center; gap: 12px;
}
</style>
