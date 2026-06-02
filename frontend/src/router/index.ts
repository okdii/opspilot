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
    path: '/',
    component: () => import('@/components/common/AppLayout.vue'),
    children: [
      { path: '', name: 'dashboard', component: () => import('@/views/dashboard/DashboardView.vue') },
      { path: 'organizations', name: 'organizations', component: () => import('@/views/organizations/OrganizationsView.vue'), meta: { adminOnly: true } },
      { path: 'servers', name: 'servers', component: () => import('@/views/servers/ServersView.vue') },
      { path: 'profile', name: 'profile', component: () => import('@/views/auth/ProfileView.vue') },
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
    if (!auth.setupRequired) await auth.fetchMe()
    auth.initialized = true
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
