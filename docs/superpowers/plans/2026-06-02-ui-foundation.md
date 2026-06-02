# UI Foundation (Vuestic + AG Grid) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a reusable UI foundation — a Vuestic dark theme module, six shared components (`PageHeader`, `StatusBadge`, `SlideOver`, `StatCard`, `EmptyState`, `DataGrid`), and a `useNotify` toast composable — so Phases 2–11 are assembled from themed building blocks instead of copy-pasted CSS.

**Architecture:** Lean into Vuestic UI themed to the existing dark palette; add a small set of app-specific components Vuestic doesn't cover; wrap AG Grid Community (Infinite Row Model) for server-paginated tables. New screens adopt this layer; the 8 existing views are left untouched. Verified through a dev-only `/_ui-kit` gallery in the browser (the project uses smoke/browser verification, not unit tests).

**Tech Stack:** Vue 3.5 (`<script setup>`, SFC generics), TypeScript, Pinia, Vuestic UI 1.9, AG Grid Community + `ag-grid-vue3`, Vite.

**Spec:** `docs/superpowers/specs/2026-06-02-ui-foundation-design.md`

---

## Conventions for this plan

- **Verification loop (HMR):** Run the dev stack once and leave it up:
  ```
  docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
  ```
  Vite HMR serves at **http://localhost:5173**. Edits under `frontend/src/` reflect instantly — no rebuild. Log in once at `http://localhost:5173/login` with **admin / SmokeTest123!** (dev admin). The gallery lives at **http://localhost:5173/_ui-kit**.
- **No unit tests:** the frontend has no test runner, and the approved spec + CLAUDE.md prescribe browser smoke verification. Each task's verification = "open the gallery, confirm the described states render." This intentionally replaces the writing-plans default TDD steps (user instructions override the skill).
- **Type-check before done:** `vue-tsc` runs inside the build. The final task runs a production build to confirm all new TS/Vue compiles.
- **Git:** this repo is **not** git-initialized. `git` commit steps below are checkpoints — run `git init` first if you want them to execute, otherwise treat each "Commit" as a manual save point.
- **Path alias:** `@/` → `frontend/src/` (configured in `vite.config.ts` + `tsconfig.json`).

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/src/plugins/vuestic.ts` (create) | Vuestic dark theme config (palette preset), single source of color truth with `App.vue`. |
| `frontend/src/main.ts` (modify) | Use the extracted Vuestic plugin instead of inline config. |
| `frontend/src/composables/useNotify.ts` (create) | Toast helper over Vuestic `useToast` (`success/error/info/warning`). |
| `frontend/src/components/ui/EmptyState.vue` (create) | Empty/placeholder block. |
| `frontend/src/components/ui/PageHeader.vue` (create) | Page title + subtitle + actions slot. |
| `frontend/src/components/ui/StatusBadge.vue` (create) | `(kind,status)` → themed pill. |
| `frontend/src/components/ui/StatCard.vue` (create) | Summary tile. |
| `frontend/src/components/ui/SlideOver.vue` (create) | Right-drawer shell. |
| `frontend/src/components/ui/DataGrid.vue` (create) | AG Grid Community wrapper (Infinite Row Model). |
| `frontend/src/components/ui/index.ts` (create) | Barrel exports. |
| `frontend/src/components/ui/README.md` (create) | Palette mapping + usage rules. |
| `frontend/src/views/dev/UiKitView.vue` (create) | Dev-only gallery (verification + living reference). |
| `frontend/src/router/index.ts` (modify) | Register `/_ui-kit` route only when `import.meta.env.DEV`. |

---

## Task 1: Extract Vuestic theme into a plugin module

**Files:**
- Create: `frontend/src/plugins/vuestic.ts`
- Modify: `frontend/src/main.ts`

- [ ] **Step 1: Create `frontend/src/plugins/vuestic.ts`**

This relocates the working color config currently inline in `main.ts` into one reusable module (single source of color truth, mirrored from `App.vue`'s `:root` vars).

```ts
import { createVuestic } from 'vuestic-ui'

// Single source of color truth for Vuestic components.
// These hex values MUST stay in lockstep with the CSS custom properties in
// App.vue (:root). Changing a brand color means editing BOTH places.
export const vuestic = createVuestic({
  config: {
    colors: {
      currentPresetName: 'dark',
      variables: {
        primary: '#6366f1',          // --accent
        secondary: '#818cf8',        // --accent-2
        success: '#22c55e',          // --green
        warning: '#f59e0b',          // --amber
        danger: '#ef4444',           // --red
        info: '#3b82f6',             // --blue
        backgroundPrimary: '#0f1117', // --bg
        backgroundSecondary: '#1a1d27', // --surface
        backgroundElement: '#22263a', // --surface-2
        backgroundBorder: '#2e3354',  // --border
        textPrimary: '#e2e8f0',       // --text
        textInverted: '#0f1117',
      },
    },
  },
})
```

- [ ] **Step 2: Update `frontend/src/main.ts` to use the plugin**

Replace the inline `createVuestic({...})` with the imported instance. New full file:

```ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'vuestic-ui/css'
import App from './App.vue'
import { router } from './router'
import { vuestic } from './plugins/vuestic'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(vuestic)

app.mount('#app')
```

- [ ] **Step 3: Verify existing app is unchanged**

With the dev stack up, open `http://localhost:5173/servers` (log in if needed). Expected: the app renders exactly as before — dark sidebar, themed page. No visual regression, no console errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/plugins/vuestic.ts frontend/src/main.ts
git commit -m "refactor(ui): extract Vuestic dark theme into plugins/vuestic.ts"
```

---

## Task 2: Dev-only `/_ui-kit` gallery route + scaffold

**Files:**
- Create: `frontend/src/views/dev/UiKitView.vue`
- Modify: `frontend/src/router/index.ts`

- [ ] **Step 1: Create the gallery scaffold `frontend/src/views/dev/UiKitView.vue`**

```vue
<script setup lang="ts">
// Dev-only gallery. Each subsequent task adds a <section> here.
</script>

<template>
  <div class="ui-kit">
    <h1>OpsPilot UI Kit</h1>
    <p class="subtitle">Reusable components &amp; theme reference (dev only)</p>
    <!-- sections added per task -->
  </div>
</template>

<style scoped>
.ui-kit { padding: 32px 40px; max-width: 1200px; margin: 0 auto; color: var(--text); }
.ui-kit h1 { font-size: 24px; color: #fff; }
.subtitle { color: var(--muted); margin: 4px 0 28px; font-size: 13px; }
.ui-kit :deep(section) { margin-bottom: 40px; }
.ui-kit :deep(h2.sec) { font-size: 14px; color: var(--accent-2); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 14px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
.ui-kit :deep(.row-demo) { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
</style>
```

- [ ] **Step 2: Register the route (dev-only) in `frontend/src/router/index.ts`**

Add this block immediately before `export const router = createRouter({` (after the `routes` array is defined):

```ts
if (import.meta.env.DEV) {
  routes.unshift({
    path: '/_ui-kit',
    name: 'ui-kit',
    component: () => import('@/views/dev/UiKitView.vue'),
    meta: { layout: 'auth', public: true },
  })
}
```

(`unshift` ensures it matches before the `/:pathMatch(.*)*` catch-all; `public: true` skips the auth guard so the gallery loads without login.)

- [ ] **Step 3: Verify**

Open `http://localhost:5173/_ui-kit`. Expected: "OpsPilot UI Kit" heading on the dark background. Confirm the route does **not** exist in a production build later (it's behind `import.meta.env.DEV`).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/dev/UiKitView.vue frontend/src/router/index.ts
git commit -m "feat(ui): add dev-only /_ui-kit gallery route"
```

---

## Task 3: `useNotify` toast composable

**Files:**
- Create: `frontend/src/composables/useNotify.ts`
- Modify: `frontend/src/views/dev/UiKitView.vue`

- [ ] **Step 1: Create `frontend/src/composables/useNotify.ts`**

```ts
import { useToast } from 'vuestic-ui'

export interface NotifyOpts {
  title?: string
  duration?: number
}

type ErrorLike = string | Error | { message?: string }

function extractMessage(input: ErrorLike): string {
  if (typeof input === 'string') return input
  if (input && typeof input === 'object' && 'message' in input && input.message) {
    return String(input.message)
  }
  return 'Something went wrong.'
}

/**
 * App-wide notifications, themed via Vuestic semantic colors.
 *   const notify = useNotify()
 *   notify.success('Saved')
 *   notify.error(err)   // accepts Error / ApiError, extracts .message
 */
export function useNotify() {
  const { init } = useToast()
  const base = { position: 'top-right' as const, closeable: true }

  return {
    success: (message: string, o: NotifyOpts = {}) =>
      init({ ...base, color: 'success', message, title: o.title, duration: o.duration ?? 4000 }),
    info: (message: string, o: NotifyOpts = {}) =>
      init({ ...base, color: 'info', message, title: o.title, duration: o.duration ?? 4000 }),
    warning: (message: string, o: NotifyOpts = {}) =>
      init({ ...base, color: 'warning', message, title: o.title, duration: o.duration ?? 4000 }),
    error: (input: ErrorLike, o: NotifyOpts = {}) =>
      init({ ...base, color: 'danger', message: extractMessage(input), title: o.title, duration: o.duration ?? 6000 }),
  }
}
```

- [ ] **Step 2: Add a toast demo section to the gallery**

In `UiKitView.vue`, add to `<script setup>`:

```ts
import { useNotify } from '@/composables/useNotify'
const notify = useNotify()
```

And add this section inside the template (after the intro `<p>`):

```html
<section>
  <h2 class="sec">Notifications (useNotify)</h2>
  <div class="row-demo">
    <VaButton color="success" @click="notify.success('Server saved successfully')">success</VaButton>
    <VaButton color="info" @click="notify.info('Onboarding queued')">info</VaButton>
    <VaButton color="warning" @click="notify.warning('SSL expires in 7 days')">warning</VaButton>
    <VaButton color="danger" @click="notify.error({ message: 'Failed to connect to host' })">error</VaButton>
  </div>
</section>
```

- [ ] **Step 3: Verify**

Reload `/_ui-kit`. Click each button. Expected: a toast appears top-right in the matching color (green/blue/amber/red); success/info/warning auto-dismiss ~4s, error ~6s; each is closeable. Confirms `useToast` + theme.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/composables/useNotify.ts frontend/src/views/dev/UiKitView.vue
git commit -m "feat(ui): add useNotify toast composable"
```

---

## Task 4: `EmptyState` component

**Files:**
- Create: `frontend/src/components/ui/EmptyState.vue`
- Modify: `frontend/src/views/dev/UiKitView.vue`

- [ ] **Step 1: Create `frontend/src/components/ui/EmptyState.vue`**

```vue
<script setup lang="ts">
// icon is an inline SVG string (consistent with AppLayout nav icons). Avoid emojis.
defineProps<{ icon?: string; title: string; message?: string }>()
</script>

<template>
  <div class="empty-state">
    <div v-if="icon" class="es-icon" v-html="icon"></div>
    <h2 class="es-title">{{ title }}</h2>
    <p v-if="message" class="es-msg">{{ message }}</p>
    <div class="es-action"><slot name="action" /></div>
  </div>
</template>

<style scoped>
.empty-state { text-align: center; padding: 80px 20px; }
.es-icon { margin-bottom: 12px; color: var(--muted); display: flex; justify-content: center; }
.es-title { font-size: 18px; color: #fff; margin-bottom: 6px; }
.es-msg { color: var(--muted); margin-bottom: 20px; }
</style>
```

- [ ] **Step 2: Add to the gallery**

In `<script setup>`:

```ts
import EmptyState from '@/components/ui/EmptyState.vue'
const serverIcon = `<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>`
```

Template section:

```html
<section>
  <h2 class="sec">EmptyState</h2>
  <div style="border:1px dashed var(--border); border-radius:12px;">
    <EmptyState :icon="serverIcon" title="No servers yet" message="Add your first server to start monitoring.">
      <template #action><VaButton>+ Add Server</VaButton></template>
    </EmptyState>
  </div>
</section>
```

- [ ] **Step 3: Verify**

Reload `/_ui-kit`. Expected: centered icon, title, message, and an "+ Add Server" button.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/EmptyState.vue frontend/src/views/dev/UiKitView.vue
git commit -m "feat(ui): add EmptyState component"
```

---

## Task 5: `PageHeader` component

**Files:**
- Create: `frontend/src/components/ui/PageHeader.vue`
- Modify: `frontend/src/views/dev/UiKitView.vue`

- [ ] **Step 1: Create `frontend/src/components/ui/PageHeader.vue`**

```vue
<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <header class="page-header">
    <div class="ph-text">
      <h1 class="ph-title">{{ title }}</h1>
      <p v-if="subtitle" class="ph-sub">{{ subtitle }}</p>
    </div>
    <div class="ph-actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }
.ph-title { font-size: 22px; color: #fff; letter-spacing: -0.3px; }
.ph-sub { color: var(--muted); font-size: 13px; margin-top: 4px; }
.ph-actions { display: flex; gap: 10px; align-items: center; }
</style>
```

- [ ] **Step 2: Add to the gallery**

`<script setup>`:

```ts
import PageHeader from '@/components/ui/PageHeader.vue'
```

Template section:

```html
<section>
  <h2 class="sec">PageHeader</h2>
  <PageHeader title="Servers — Acme Corp" subtitle="12 servers • 9 online • 1 pending">
    <template #actions><VaButton>+ Add Server</VaButton></template>
  </PageHeader>
</section>
```

- [ ] **Step 3: Verify**

Reload `/_ui-kit`. Expected: large title, muted subtitle on the left, button right-aligned; on a narrow window the button wraps below.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/PageHeader.vue frontend/src/views/dev/UiKitView.vue
git commit -m "feat(ui): add PageHeader component"
```

---

## Task 6: `StatusBadge` component

**Files:**
- Create: `frontend/src/components/ui/StatusBadge.vue`
- Modify: `frontend/src/views/dev/UiKitView.vue`

- [ ] **Step 1: Create `frontend/src/components/ui/StatusBadge.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'

type Kind = 'server' | 'service' | 'alert' | 'ssl' | 'domain' | 'job'
type Tone = 'success' | 'danger' | 'warning' | 'info' | 'muted'

const props = defineProps<{ status: string; kind: Kind }>()

const MAP: Record<Kind, Record<string, { label: string; tone: Tone }>> = {
  server: {
    pending: { label: 'Pending', tone: 'muted' },
    online: { label: 'Online', tone: 'success' },
    offline: { label: 'Offline', tone: 'danger' },
    maintenance: { label: 'Maintenance', tone: 'warning' },
  },
  service: {
    up: { label: 'Up', tone: 'success' },
    down: { label: 'Down', tone: 'danger' },
    maintenance: { label: 'Maintenance', tone: 'warning' },
  },
  alert: {
    firing: { label: 'Firing', tone: 'danger' },
    acknowledged: { label: 'Acknowledged', tone: 'warning' },
    snoozed: { label: 'Snoozed', tone: 'info' },
    resolved: { label: 'Resolved', tone: 'success' },
    suppressed: { label: 'Suppressed', tone: 'muted' },
  },
  ssl: {
    valid: { label: 'Valid', tone: 'success' },
    expiring_soon: { label: 'Expiring Soon', tone: 'warning' },
    critical: { label: 'Critical', tone: 'danger' },
    expired: { label: 'Expired', tone: 'danger' },
    unreachable: { label: 'Unreachable', tone: 'muted' },
  },
  domain: {
    valid: { label: 'Valid', tone: 'success' },
    expiring_soon: { label: 'Expiring Soon', tone: 'warning' },
    critical: { label: 'Critical', tone: 'danger' },
    expired: { label: 'Expired', tone: 'danger' },
  },
  job: {
    healthy: { label: 'Healthy', tone: 'success' },
    late: { label: 'Late', tone: 'warning' },
    missing: { label: 'Missing', tone: 'danger' },
    paused: { label: 'Paused', tone: 'muted' },
  },
}

const entry = computed(
  () => MAP[props.kind]?.[props.status] ?? { label: props.status, tone: 'muted' as Tone },
)
</script>

<template>
  <span class="status-badge" :class="`tone-${entry.tone}`">
    <span class="sb-dot"></span>{{ entry.label }}
  </span>
</template>

<style scoped>
.status-badge { display: inline-flex; align-items: center; gap: 6px; font-size: 10px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; padding: 3px 8px; border-radius: 4px; }
.sb-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.tone-success { background: rgba(34,197,94,0.15); color: var(--green); }
.tone-danger  { background: rgba(239,68,68,0.15); color: var(--red); }
.tone-warning { background: rgba(245,158,11,0.15); color: var(--amber); }
.tone-info    { background: rgba(99,102,241,0.15); color: var(--accent-2); }
.tone-muted   { background: rgba(107,114,128,0.2); color: var(--muted); }
</style>
```

- [ ] **Step 2: Add to the gallery (all kinds × statuses)**

`<script setup>`:

```ts
import StatusBadge from '@/components/ui/StatusBadge.vue'
const badgeKinds: { kind: any; statuses: string[] }[] = [
  { kind: 'server', statuses: ['pending', 'online', 'offline', 'maintenance'] },
  { kind: 'service', statuses: ['up', 'down', 'maintenance'] },
  { kind: 'alert', statuses: ['firing', 'acknowledged', 'snoozed', 'resolved', 'suppressed'] },
  { kind: 'ssl', statuses: ['valid', 'expiring_soon', 'critical', 'expired', 'unreachable'] },
  { kind: 'domain', statuses: ['valid', 'expiring_soon', 'critical', 'expired'] },
  { kind: 'job', statuses: ['healthy', 'late', 'missing', 'paused'] },
]
```

Template section:

```html
<section>
  <h2 class="sec">StatusBadge</h2>
  <div v-for="g in badgeKinds" :key="g.kind" style="margin-bottom:12px;">
    <div style="color:var(--muted); font-size:11px; margin-bottom:6px;">{{ g.kind }}</div>
    <div class="row-demo">
      <StatusBadge v-for="s in g.statuses" :key="s" :kind="g.kind" :status="s" />
    </div>
  </div>
</section>
```

- [ ] **Step 3: Verify**

Reload `/_ui-kit`. Expected: each kind shows its statuses as colored pills (green/red/amber/blue/grey) with a leading dot and label. Every pill has text (not color-only).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/StatusBadge.vue frontend/src/views/dev/UiKitView.vue
git commit -m "feat(ui): add StatusBadge component with status map"
```

---

## Task 7: `StatCard` component

**Files:**
- Create: `frontend/src/components/ui/StatCard.vue`
- Modify: `frontend/src/views/dev/UiKitView.vue`

- [ ] **Step 1: Create `frontend/src/components/ui/StatCard.vue`**

```vue
<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
  icon?: string
  delta?: { value: string; direction: 'up' | 'down' | 'flat' }
  accent?: 'primary' | 'success' | 'danger' | 'warning' | 'info'
}>()
</script>

<template>
  <div class="stat-card">
    <div class="sc-top">
      <span class="sc-label">{{ label }}</span>
      <span v-if="icon" class="sc-icon" :class="accent ? `ac-${accent}` : ''" v-html="icon"></span>
    </div>
    <div class="sc-value">{{ value }}</div>
    <div v-if="delta" class="sc-delta" :class="`d-${delta.direction}`">
      <span class="d-arrow">{{ delta.direction === 'up' ? '↑' : delta.direction === 'down' ? '↓' : '→' }}</span>
      {{ delta.value }}
    </div>
  </div>
</template>

<style scoped>
.stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px; min-width: 200px; }
.sc-top { display: flex; justify-content: space-between; align-items: center; }
.sc-label { font-size: 12px; color: var(--muted); }
.sc-icon { color: var(--muted); display: flex; }
.sc-icon.ac-primary { color: var(--accent-2); }
.sc-icon.ac-success { color: var(--green); }
.sc-icon.ac-danger { color: var(--red); }
.sc-icon.ac-warning { color: var(--amber); }
.sc-icon.ac-info { color: var(--blue); }
.sc-value { font-size: 26px; font-weight: 700; color: #fff; margin-top: 8px; font-variant-numeric: tabular-nums; }
.sc-delta { font-size: 12px; margin-top: 6px; display: inline-flex; align-items: center; gap: 4px; }
.d-up { color: var(--green); }
.d-down { color: var(--red); }
.d-flat { color: var(--muted); }
</style>
```

- [ ] **Step 2: Add to the gallery**

`<script setup>`:

```ts
import StatCard from '@/components/ui/StatCard.vue'
```

Template section:

```html
<section>
  <h2 class="sec">StatCard</h2>
  <div class="row-demo">
    <StatCard label="Servers" :value="12" :icon="serverIcon" accent="primary" />
    <StatCard label="Active Alerts" :value="3" :delta="{ value: '+2 today', direction: 'up' }" />
    <StatCard label="Avg Uptime" value="99.98%" :delta="{ value: '0.0%', direction: 'flat' }" />
  </div>
</section>
```

- [ ] **Step 3: Verify**

Reload `/_ui-kit`. Expected: three tiles — label, large tabular value, optional delta with colored up/down/flat arrow; first tile shows the accented icon.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/StatCard.vue frontend/src/views/dev/UiKitView.vue
git commit -m "feat(ui): add StatCard component"
```

---

## Task 8: `SlideOver` component

**Files:**
- Create: `frontend/src/components/ui/SlideOver.vue`
- Modify: `frontend/src/views/dev/UiKitView.vue`

- [ ] **Step 1: Create `frontend/src/components/ui/SlideOver.vue`**

```vue
<script setup lang="ts">
import { watch, onUnmounted } from 'vue'

const props = defineProps<{
  modelValue: boolean
  title?: string
  subtitle?: string
  width?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

function close() { emit('update:modelValue', false) }

// Lock body scroll while open.
watch(
  () => props.modelValue,
  (open) => { document.body.style.overflow = open ? 'hidden' : '' },
)
onUnmounted(() => { document.body.style.overflow = '' })
</script>

<template>
  <Teleport to="body">
    <Transition name="so-fade">
      <div v-if="modelValue" class="so-scrim" @click.self="close">
        <Transition name="so-slide" appear>
          <aside class="so-drawer" role="dialog" :aria-label="title || 'Panel'" :style="{ width: width || '600px' }">
            <header class="so-hdr">
              <div>
                <h2 v-if="title">{{ title }}</h2>
                <p v-if="subtitle" class="so-sub">{{ subtitle }}</p>
                <slot name="header" />
              </div>
              <button class="so-close" aria-label="Close" @click="close">✕</button>
            </header>
            <div class="so-body"><slot /></div>
            <footer v-if="$slots.footer" class="so-footer"><slot name="footer" /></footer>
          </aside>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.so-scrim { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 1100; display: flex; justify-content: flex-end; }
.so-fade-enter-active, .so-fade-leave-active { transition: opacity .25s ease; }
.so-fade-enter-from, .so-fade-leave-to { opacity: 0; }
.so-slide-enter-active, .so-slide-leave-active { transition: transform .25s ease-out; }
.so-slide-enter-from, .so-slide-leave-to { transform: translateX(100%); }
.so-drawer { max-width: 100vw; height: 100%; background: var(--surface); border-left: 1px solid var(--border); display: flex; flex-direction: column; box-shadow: -20px 0 50px rgba(0,0,0,0.4); }
.so-hdr { padding: 18px 22px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: flex-start; flex-shrink: 0; }
.so-hdr h2 { font-size: 16px; color: #fff; }
.so-sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
.so-close { background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; padding: 4px; line-height: 1; }
.so-close:hover { color: var(--text); }
.so-body { flex: 1; overflow-y: auto; padding: 20px 22px; }
.so-footer { flex-shrink: 0; border-top: 1px solid var(--border); padding: 14px 22px; display: flex; gap: 10px; flex-wrap: wrap; }
@media (max-width: 640px) { .so-drawer { width: 100vw !important; } }
</style>
```

- [ ] **Step 2: Add to the gallery**

`<script setup>`:

```ts
import { ref } from 'vue'
import SlideOver from '@/components/ui/SlideOver.vue'
const slideOpen = ref(false)
```

Template section:

```html
<section>
  <h2 class="sec">SlideOver</h2>
  <VaButton @click="slideOpen = true">Open SlideOver</VaButton>
  <SlideOver v-model="slideOpen" title="Panel Title" subtitle="example · subtitle">
    <p style="color:var(--text);">Body content goes here. Scrolls if long.</p>
    <template #footer>
      <VaButton preset="secondary" @click="slideOpen = false">Cancel</VaButton>
      <VaButton @click="slideOpen = false">Confirm</VaButton>
    </template>
  </SlideOver>
</section>
```

- [ ] **Step 3: Verify**

Reload `/_ui-kit`. Click "Open SlideOver". Expected: scrim fades in, drawer slides from the right (600px), header shows title/subtitle + ✕, footer has Cancel/Confirm. Clicking the scrim or ✕ or a footer button closes it (slide/fade out). Resize narrow → drawer goes full-width. Body scroll is locked while open.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/SlideOver.vue frontend/src/views/dev/UiKitView.vue
git commit -m "feat(ui): add SlideOver drawer component"
```

---

## Task 9: AG Grid dependencies + `DataGrid` wrapper

**Files:**
- Modify: `frontend/package.json` (via npm install)
- Create: `frontend/src/components/ui/DataGrid.vue`
- Modify: `frontend/src/views/dev/UiKitView.vue`

- [ ] **Step 1: Install AG Grid (into the running dev container's node_modules)**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npm install ag-grid-community ag-grid-vue3
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart frontend
```

Expected: both packages added to `package.json` dependencies; Vite restarts and re-optimizes deps.

- [ ] **Step 2: Create `frontend/src/components/ui/DataGrid.vue`**

```vue
<script setup lang="ts" generic="T = any">
import { ref, shallowRef, onBeforeUnmount } from 'vue'
import { AgGridVue } from 'ag-grid-vue3'
import {
  ModuleRegistry,
  AllCommunityModule,
  themeQuartz,
  type ColDef,
  type GridApi,
  type GridReadyEvent,
  type IDatasource,
  type IGetRowsParams,
} from 'ag-grid-community'

ModuleRegistry.registerModules([AllCommunityModule])

export interface FetchPageParams {
  startRow: number
  endRow: number
  blockSize: number
  sortModel: { colId: string; sort: 'asc' | 'desc' }[]
  filterModel: Record<string, unknown>
  cursor: string | null
}
export interface FetchPageResult<R> {
  rows: R[]
  nextCursor?: string | null
  lastRow?: number
}

const props = withDefaults(
  defineProps<{
    columns: ColDef[]
    fetchPage: (p: FetchPageParams) => Promise<FetchPageResult<T>>
    getRowId?: (row: T) => string
    blockSize?: number
    rowHeight?: number
  }>(),
  { blockSize: 100, rowHeight: 40 },
)

const emit = defineEmits<{ (e: 'row-click', row: T): void }>()

// Dark theme matching the Vuestic palette / App.vue :root vars.
const theme = themeQuartz.withParams({
  backgroundColor: '#1a1d27',
  foregroundColor: '#e2e8f0',
  chromeBackgroundColor: '#22263a',
  headerBackgroundColor: '#22263a',
  borderColor: '#2e3354',
  accentColor: '#6366f1',
  rowHoverColor: '#22263a',
  fontSize: 13,
})

const gridApi = shallowRef<GridApi | null>(null)
// cursor cache: maps a block's startRow -> the cursor needed to fetch it.
const cursors = new Map<number, string | null>()

const datasource: IDatasource = {
  getRows: async (params: IGetRowsParams) => {
    try {
      const res = await props.fetchPage({
        startRow: params.startRow,
        endRow: params.endRow,
        blockSize: props.blockSize,
        sortModel: params.sortModel as { colId: string; sort: 'asc' | 'desc' }[],
        filterModel: params.filterModel,
        cursor: cursors.get(params.startRow) ?? null,
      })
      // Store the cursor that the NEXT contiguous block will need.
      if (res.nextCursor !== undefined) cursors.set(params.endRow, res.nextCursor)
      const lastRow =
        res.lastRow ??
        (res.rows.length < props.blockSize ? params.startRow + res.rows.length : undefined)
      params.successCallback(res.rows, lastRow)
    } catch {
      params.failCallback()
    }
  },
}

const defaultColDef = ref<ColDef>({ sortable: true, resizable: true, flex: 1, minWidth: 100 })

function onGridReady(e: GridReadyEvent) {
  gridApi.value = e.api
  e.api.setGridOption('datasource', datasource)
}
function onRowClicked(e: { data?: T }) {
  if (e.data) emit('row-click', e.data)
}

/** Clear the cursor cache and reload from the first block (e.g. after a filter change). */
function refresh() {
  cursors.clear()
  gridApi.value?.purgeInfiniteCache()
}
defineExpose({ refresh })

onBeforeUnmount(() => { gridApi.value = null })
</script>

<template>
  <AgGridVue
    class="data-grid"
    :theme="theme"
    :columnDefs="columns"
    :defaultColDef="defaultColDef"
    :rowModelType="'infinite'"
    :cacheBlockSize="blockSize"
    :rowHeight="rowHeight"
    :getRowId="getRowId ? (p: { data: T }) => getRowId!(p.data) : undefined"
    @grid-ready="onGridReady"
    @row-clicked="onRowClicked"
  />
</template>

<style scoped>
.data-grid { width: 100%; height: 100%; min-height: 420px; }
</style>
```

- [ ] **Step 3: Add a live DataGrid demo to the gallery**

This demo adapts the non-paginated `/api/servers` endpoint by slicing client-side, purely to prove the datasource wiring + theme end-to-end. (Real server-paginated endpoints arrive in Phases 3/7/8/10.)

`<script setup>`:

```ts
import DataGrid, { type FetchPageParams, type FetchPageResult } from '@/components/ui/DataGrid.vue'
import type { ColDef } from 'ag-grid-community'
import { api } from '@/services/api'
import type { Server } from '@/types'

const gridColumns: ColDef[] = [
  { field: 'name', headerName: 'Name' },
  { field: 'host', headerName: 'Host' },
  { field: 'status', headerName: 'Status' },
  { field: 'os_distro', headerName: 'OS' },
]

async function fetchServers(p: FetchPageParams): Promise<FetchPageResult<Server>> {
  const { data } = await api.get<Server[]>('/api/servers')
  const slice = data.slice(p.startRow, p.endRow)
  return { rows: slice, lastRow: data.length }
}
```

Template section:

```html
<section>
  <h2 class="sec">DataGrid (AG Grid Community · Infinite Row Model)</h2>
  <p style="color:var(--muted);font-size:12px;margin-bottom:10px;">Demo adapts /api/servers (client-sliced). Log in first.</p>
  <div style="height:420px;">
    <DataGrid :columns="gridColumns" :fetch-page="fetchServers" :get-row-id="(r:any)=>r.id" />
  </div>
</section>
```

- [ ] **Step 4: Verify**

Log in at `http://localhost:5173/login` (admin / SmokeTest123!), then open `/_ui-kit`. Expected: the grid renders dark-themed (matching surfaces/borders), shows server rows (name/host/status/OS), column headers are sortable/resizable, and the datasource callback fired (Network tab shows `/api/servers`). No console errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/components/ui/DataGrid.vue frontend/src/views/dev/UiKitView.vue
git commit -m "feat(ui): add AG Grid Community DataGrid wrapper (infinite row model)"
```

---

## Task 10: Barrel exports, README, and final production-build smoke test

**Files:**
- Create: `frontend/src/components/ui/index.ts`
- Create: `frontend/src/components/ui/README.md`

- [ ] **Step 1: Create `frontend/src/components/ui/index.ts`**

```ts
export { default as PageHeader } from './PageHeader.vue'
export { default as StatusBadge } from './StatusBadge.vue'
export { default as SlideOver } from './SlideOver.vue'
export { default as StatCard } from './StatCard.vue'
export { default as EmptyState } from './EmptyState.vue'
export { default as DataGrid } from './DataGrid.vue'
export type { FetchPageParams, FetchPageResult } from './DataGrid.vue'
```

- [ ] **Step 2: Create `frontend/src/components/ui/README.md`**

```markdown
# OpsPilot UI Foundation

Reusable, dark-themed UI layer. See the live gallery at `/_ui-kit` (dev only).

## Usage rules (going forward)
- Standard controls (buttons, inputs, selects, modals, cards, tabs) → Vuestic `Va*` (themed by default).
- Small/static table → `VaDataTable`. Large/server-paginated table → `<DataGrid>`.
- Page title + actions → `<PageHeader>`. Status pill → `<StatusBadge>`. Right drawer → `<SlideOver>`.
- Summary tile → `<StatCard>`. Empty/placeholder → `<EmptyState>`. Toasts → `useNotify()`.
- Loading → `VaProgressCircle indeterminate` / `VaInnerLoading` (do not re-add bespoke spin keyframes).
- Import shared components from `@/components/ui`; the composable from `@/composables/useNotify`.

## Color source of truth
The dark palette lives in TWO places that MUST stay in lockstep:
- `src/App.vue` `:root` CSS custom properties (used by custom `<style scoped>`).
- `src/plugins/vuestic.ts` Vuestic preset (used by `Va*` + AG Grid theme params).

| Token | Hex | Vuestic key | AG Grid param |
|---|---|---|---|
| `--bg` | `#0f1117` | `backgroundPrimary` | `backgroundColor` |
| `--surface` | `#1a1d27` | `backgroundSecondary` | `chromeBackgroundColor` |
| `--surface-2` | `#22263a` | `backgroundElement` | `headerBackgroundColor` |
| `--border` | `#2e3354` | `backgroundBorder` | `borderColor` |
| `--accent` | `#6366f1` | `primary` | `accentColor` |
| `--accent-2` | `#818cf8` | `secondary` | — |
| `--green` | `#22c55e` | `success` | — |
| `--blue` | `#3b82f6` | `info` | — |
| `--amber` | `#f59e0b` | `warning` | — |
| `--red` | `#ef4444` | `danger` | — |
| `--text` | `#e2e8f0` | `textPrimary` | `foregroundColor` |

## DataGrid note
Uses AG Grid Community **Infinite Row Model**. The `fetchPage` callback receives both
`startRow`/`endRow` (offset style) and a forward `cursor`. Offset-style APIs support
scrollbar jumping; cursor-only APIs (logs, alert history) load sequentially on scroll.
```

- [ ] **Step 3: Final smoke test — production build passes & existing app intact**

Run the production build (type-checks all new code) and confirm the existing app still works:

```bash
docker compose build frontend
docker compose up -d frontend
```

Expected: `vue-tsc --noEmit && vite build` completes with no type errors (all new `.vue`/`.ts` compile). Then open `http://localhost:8766/servers` (prod container) and confirm the existing app renders normally and `/_ui-kit` returns the SPA fallback (route absent in prod build — it's `import.meta.env.DEV`-gated).

> After verifying the prod build, switch back to the dev stack for any further work:
> `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/index.ts frontend/src/components/ui/README.md
git commit -m "docs(ui): add ui barrel exports + foundation README"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- §4 theme config → Task 1 ✓ · §5.1 PageHeader → Task 5 ✓ · §5.2 StatusBadge → Task 6 ✓ · §5.3 SlideOver → Task 8 ✓ · §5.4 StatCard → Task 7 ✓ · §5.5 EmptyState → Task 4 ✓ · §5.6 DataGrid → Task 9 ✓ · §6 useNotify → Task 3 ✓ · §7 conventions → Task 10 README ✓ · §8 `/_ui-kit` gallery → Task 2 + incremental ✓ · §9 out-of-scope (no retrofit/charts/Tailwind/Enterprise) respected ✓.
- Deviation: spec §4 mentioned global `config.components` defaults; deferred (YAGNI — avoids guessing Vuestic preset names; the working color config is what ships). Noted here intentionally; not a gap.

**Placeholder scan:** No TBD/TODO; every code step contains complete, runnable code; every command has an expected result.

**Type consistency:** `FetchPageParams`/`FetchPageResult` defined in Task 9 and re-exported in Task 10 match. `Kind`/`Tone` internal to StatusBadge. `NotifyOpts` consistent in useNotify. `refresh()` exposed name consistent. Gallery imports match created component default exports.
