import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/setup',
    name: 'setup',
    component: () => import('@/views/auth/SetupView.vue'),
    meta: { layout: 'auth', public: true },
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/auth/LoginView.vue'),
    meta: { layout: 'auth', public: true },
  },
  {
    path: '/invite/:token',
    name: 'invite',
    component: () => import('@/views/auth/InviteView.vue'),
    meta: { layout: 'auth', public: true, allowAuthenticated: true },
  },
  {
    path: '/status',
    name: 'status',
    component: () => import('@/views/status/StatusView.vue'),
    meta: { layout: 'auth', public: true, allowAuthenticated: true },
  },
  {
    path: '/',
    component: () => import('@/components/common/AppLayout.vue'),
    children: [
      { path: '', name: 'dashboard', component: () => import('@/views/dashboard/DashboardView.vue') },
      { path: 'organizations', name: 'organizations', component: () => import('@/views/organizations/OrganizationsView.vue'), meta: { adminOnly: true } },
      { path: 'servers', name: 'servers', component: () => import('@/views/servers/ServersView.vue') },
      { path: 'servers/:id', name: 'server-detail', component: () => import('@/views/servers/ServerDetail.vue') },
      { path: 'logs', name: 'logs', component: () => import('@/views/logs/LogsView.vue') },
      { path: 'alerts', name: 'alerts', component: () => import('@/views/alerts/AlertsView.vue') },
      { path: 'alerts/rules', name: 'alert-rules', component: () => import('@/views/alerts/AlertRulesView.vue'), meta: { adminOnly: true } },
      { path: 'services', name: 'services', component: () => import('@/views/services/ServicesView.vue') },
      { path: 'services/:id', name: 'service-detail', component: () => import('@/views/services/ServiceDetail.vue') },
      { path: 'ssl-domains', name: 'ssl-domains', component: () => import('@/views/ssl-domains/SslDomainsView.vue') },
      { path: 'databases', name: 'databases', component: () => import('@/views/databases/DatabasesView.vue') },
      { path: 'cron-backup', name: 'cron-backup', component: () => import('@/views/cron-backup/CronBackupView.vue') },
      { path: 'profile', name: 'profile', component: () => import('@/views/auth/ProfileView.vue') },
      {
        path: 'settings',
        component: () => import('@/views/settings/SettingsLayout.vue'),
        meta: { adminOnly: true },
        children: [
          { path: '', redirect: '/settings/general' },
          { path: 'general', name: 'settings-general', component: () => import('@/views/settings/GeneralTab.vue') },
          { path: 'team', name: 'settings-team', component: () => import('@/views/settings/TeamTab.vue') },
          { path: 'retention', name: 'settings-retention', component: () => import('@/views/settings/RetentionTab.vue') },
          { path: 'security', name: 'settings-security', component: () => import('@/views/settings/SecurityTab.vue') },
          { path: 'infrastructure', name: 'settings-infrastructure', component: () => import('@/views/settings/InfrastructureTab.vue') },
        ],
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

if (import.meta.env.DEV) {
  routes.unshift({
    path: '/_ui-kit',
    name: 'ui-kit',
    component: () => import('@/views/dev/UiKitView.vue'),
    meta: { layout: 'auth', public: true },
  })
}

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (!auth.initialized) {
    await auth.checkSetupStatus()
    // Public routes (e.g. /status) must render logged-out. Skip the /api/auth/me
    // probe for them so the global 401 interceptor never redirects to /login.
    if (auth.setupRequired || !to.meta.public) {
      if (!auth.setupRequired) await auth.fetchMe()
      auth.initialized = true // leave false for public-only nav so a later protected nav probes
    }
  }

  // Setup required → force /setup
  if (auth.setupRequired && to.name !== 'setup') {
    return { name: 'setup' }
  }
  // Setup complete but visiting /setup
  if (!auth.setupRequired && to.name === 'setup') {
    return { name: 'login' }
  }

  // Public routes
  if (to.meta.public) {
    // Authenticated visiting login → home
    if (auth.isAuthenticated && to.name === 'login') return { name: 'dashboard' }
    return true
  }

  // Protected routes require auth
  if (!auth.isAuthenticated) return { name: 'login' }

  // Admin-only
  if (to.meta.adminOnly && !auth.isAdmin) return { name: 'dashboard' }

  return true
})
