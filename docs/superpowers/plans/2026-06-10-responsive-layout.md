# Responsive Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OpsPilot fully responsive across mobile (<768px), tablet (768–1023px), small laptop (1024–1279px), and desktop (≥1280px) by fixing the AppLayout sidebar and adding @media breakpoints to each view.

**Architecture:** All changes are scoped CSS `@media` blocks + minor Vue template additions for the mobile drawer. No backend changes, no store changes, no new components. Desktop layout (≥1280px) is completely unchanged.

**Tech Stack:** Vue 3 SFC scoped CSS, CSS custom properties (`var(--*)` already defined in App.vue), CSS `@media` queries

---

## Dev server

Always test against the dev stack:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```
Frontend: `http://localhost:5173` (Vite HMR) or `http://localhost:9090` (nginx proxy)

Use browser DevTools → toggle device toolbar and test at: **375px** (mobile), **768px** (tablet), **1024px** (small laptop).

---

## Task 1: AppLayout — small laptop + tablet sidebar collapse

**Files:**
- Modify: `frontend/src/components/common/AppLayout.vue` (template + scoped CSS)

### What to change

The sidebar is fixed at 240px with no breakpoints. At 1024–1279px it should narrow to 200px with labels visible. At 768–1023px it should collapse to a 52px icon-only strip with hover tooltips via the native `title` attribute.

- [ ] **Step 1: Add `title` attribute to nav-link for tooltip on tablet**

In `AppLayout.vue`, find the nav `<router-link>` (around line 171) and add `:title="item.name"`:

```html
<router-link
  v-for="item in visibleNav"
  :key="item.route"
  :to="item.route"
  :title="item.name"
  class="nav-link"
  active-class=""
  :class="{ active: item.route === '/' ? route.path === '/' : route.path.startsWith(item.route) }"
>
  <span class="nav-icon" v-html="navIcons[item.route]"></span>
  <span>{{ item.name }}</span>
</router-link>
```

- [ ] **Step 2: Add laptop + tablet @media blocks to AppLayout.vue scoped styles**

Append to the end of the `<style scoped>` block in `AppLayout.vue`:

```css
/* ─── Small laptop (1024–1279px): narrow sidebar, labels still visible ─── */
@media (max-width: 1279px) {
  .sidebar { width: 200px; }
  .nav-link { font-size: 12px; padding: 8px 10px; }
  .brand .name { font-size: 14px; }
}

/* ─── Tablet (768–1023px): icon-only sidebar ──────────────────────────── */
@media (max-width: 1023px) {
  .sidebar { width: 52px; overflow: visible; }
  .brand { padding: 14px 0; justify-content: center; }
  .brand-text { display: none; }
  .nav-link { justify-content: center; padding: 10px 0; }
  .nav-link span:last-child { display: none; }
  .nav-icon { width: 20px; height: 20px; }
  .bell-wrap { padding: 8px 0; display: flex; justify-content: center; }
  .user-card { padding: 8px 4px; }
  .user-btn { padding: 8px; justify-content: center; }
  .user-info, .chev { display: none; }
  :deep(.org-switcher) { padding: 0 6px; }
  :deep(.org-switcher .trigger .name),
  :deep(.org-switcher .trigger .chev) { display: none; }
  :deep(.org-switcher .trigger) { padding: 8px; justify-content: center; }
}
```

- [ ] **Step 3: Smoke test — tablet + laptop breakpoints**

Open `http://localhost:9090`. Open DevTools → device toolbar.

At **1024px width**: sidebar should be 200px with labels. At **768px width**: sidebar collapses to 52px showing only icons. Hover a nav icon — browser native tooltip shows the label.

At **1440px**: no change from before.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/common/AppLayout.vue
git commit -m "feat: responsive sidebar — laptop 200px, tablet icon-only 52px"
```

---

## Task 2: AppLayout — mobile hamburger + slide-out drawer

**Files:**
- Modify: `frontend/src/components/common/AppLayout.vue` (script, template, scoped CSS)

### What to change

Below 768px the sidebar is taken out of flow (position: fixed; transform: translateX(-100%)) and a sticky top bar with a hamburger button appears. Tapping the hamburger slides the drawer in from the left. Tapping the backdrop or navigating closes it.

- [ ] **Step 1: Add `mobileOpen` ref and route watcher to script**

In `AppLayout.vue`, find the existing refs near the top of `<script setup>` (around line 18: `const userMenuOpen = ref(false)`). Add after it:

```ts
const mobileOpen = ref(false)
```

Find the existing `watch(() => auth.isAuthenticated, ...)` block. Add a separate watcher after it:

```ts
watch(() => route.path, () => { mobileOpen.value = false })
```

- [ ] **Step 2: Update the template**

Find the `<div class="app-shell">` opening tag in the template. The structure becomes:

```html
<div class="app-shell">
  <aside class="sidebar" :class="{ 'drawer-open': mobileOpen }">
    <!-- existing sidebar content — no changes inside -->
    <div class="brand">...</div>
    <OrgSwitcher />
    <div class="bell-wrap">...</div>
    <nav class="nav">...</nav>
    <div class="user-card" ...>...</div>
  </aside>

  <div v-if="mobileOpen" class="drawer-backdrop" @click="mobileOpen = false" />

  <main class="content">
    <div class="mobile-topbar">
      <button class="hamburger" aria-label="Open menu" @click="mobileOpen = !mobileOpen">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <line x1="3" y1="6" x2="21" y2="6"/>
          <line x1="3" y1="12" x2="21" y2="12"/>
          <line x1="3" y1="18" x2="21" y2="18"/>
        </svg>
      </button>
      <span class="mobile-brand-name">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" style="color: var(--accent-2)">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
        </svg>
        OpsPilot
      </span>
      <div class="mobile-bell">
        <NotificationBell />
      </div>
    </div>
    <router-view />
  </main>

  <AlertToast />
</div>
```

Only these changes to the existing template:
1. Add `:class="{ 'drawer-open': mobileOpen }"` to `<aside class="sidebar">`
2. Add `<div v-if="mobileOpen" class="drawer-backdrop" ...>` after `</aside>`
3. Add `<div class="mobile-topbar">` as the first child of `<main class="content">` (before `<router-view />`)

- [ ] **Step 3: Add mobile CSS to scoped styles**

Append to the end of the `<style scoped>` block (after the tablet block added in Task 1):

```css
/* ─── Mobile (<768px): hidden sidebar + top bar + slide-out drawer ──────── */
.mobile-topbar { display: none; }
.drawer-backdrop {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.5);
  z-index: 199;
}
.hamburger {
  background: none; border: none; color: var(--text); cursor: pointer;
  padding: 6px; border-radius: 6px; display: flex; align-items: center;
  flex-shrink: 0;
}
.hamburger:hover { background: var(--surface-2); }
.mobile-brand-name {
  font-size: 15px; font-weight: 700; color: #fff; flex: 1;
  display: flex; align-items: center; gap: 8px;
}
.mobile-bell { display: flex; align-items: center; }

@media (max-width: 767px) {
  .sidebar {
    position: fixed;
    top: 0; left: 0; bottom: 0;
    width: 280px;
    z-index: 200;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
  }
  .sidebar.drawer-open { transform: translateX(0); }
  .mobile-topbar {
    display: flex;
    align-items: center;
    gap: 12px;
    height: 52px;
    padding: 0 14px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 100;
    flex-shrink: 0;
  }
}
```

- [ ] **Step 4: Smoke test — mobile drawer**

At **375px width** in DevTools:
- Sidebar is hidden
- Top bar shows: hamburger icon on left, "OpsPilot" branding in center, bell on right
- Tap hamburger → sidebar slides in from the left
- Tap the dark overlay → drawer closes
- Click a nav item → drawer closes and route changes
- At **768px**: mobile topbar hidden, icon sidebar shows (from Task 1)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/common/AppLayout.vue
git commit -m "feat: mobile hamburger + slide-out drawer navigation"
```

---

## Task 3: Dashboard views — stat-grid breakpoints

**Files:**
- Modify: `frontend/src/views/dashboard/DashboardView.vue`
- Modify: `frontend/src/components/dashboard/GlobalDashboard.vue`

### What to change

`DashboardView` has `.stat-grid { grid-template-columns: repeat(4, 1fr) }` with a partial `@media (max-width: 900px)` fix already present. `GlobalDashboard` has `.stat-grid { grid-template-columns: repeat(3, 1fr) }` with no breakpoints at all. Both need mobile padding and proper column collapse.

- [ ] **Step 1: Fix DashboardView.vue responsive styles**

Find the existing scoped CSS (around line 177):
```css
.page { padding: 28px; }
```
Change to:
```css
.page { padding: 28px; }
@media (max-width: 1023px) { .page { padding: 20px; } }
@media (max-width: 767px)  { .page { padding: 14px; } }
```

The existing `@media (max-width: 900px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }` is already correct — leave it. Add mobile single-column:

```css
@media (max-width: 479px) { .stat-grid { grid-template-columns: 1fr; } }
```

- [ ] **Step 2: Fix GlobalDashboard.vue responsive styles**

Find the `.stat-grid` rule in `GlobalDashboard.vue` (around line 71):
```css
.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}
```

Append after it:
```css
@media (max-width: 767px) { .stat-grid { grid-template-columns: 1fr; } }
```

Also add to `.org-grid` (if it exists) a `min-width: 0` on children to prevent ECharts overflow. Find the `.org-grid` rule and ensure it has `min-width: 0` on grid children:
```css
.org-card { min-width: 0; }
```

(Add this if not already present.)

- [ ] **Step 3: Smoke test**

At **375px** in DevTools, navigate to `/`. Stat cards should stack to 1 column. At **768px** they should be 2-wide. No horizontal overflow.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/dashboard/DashboardView.vue frontend/src/components/dashboard/GlobalDashboard.vue
git commit -m "feat: responsive dashboard — stat-grid collapse + mobile padding"
```

---

## Task 4: ServersView — stat-grid + mobile padding

**Files:**
- Modify: `frontend/src/views/servers/ServersView.vue`

### What to change

`ServersView` has `.stat-grid { grid-template-columns: repeat(4, 1fr) }` with `@media (max-width: 900px) { grid-template-columns: repeat(2, 1fr) }` already present. The server cards grid (`repeat(auto-fill, minmax(260px, 1fr))`) is already responsive. Only page padding and a mobile single-column for the stat-grid are missing.

- [ ] **Step 1: Add responsive padding to ServersView.vue**

Find the `.page { padding: 28px; }` rule in the scoped CSS (around line 177). Append:

```css
@media (max-width: 1023px) { .page { padding: 20px; } }
@media (max-width: 767px)  { .page { padding: 14px; } }
```

- [ ] **Step 2: Add mobile single-column for stat-grid**

The existing breakpoint at 900px → 2 cols is fine. Add:

```css
@media (max-width: 479px) { .stat-grid { grid-template-columns: 1fr; } }
```

- [ ] **Step 3: Smoke test**

At **375px**, navigate to `/servers`. Page padding should be 14px. Stat cards should be full-width stacked. Server cards grid auto-adapts (already works). No horizontal scroll.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/servers/ServersView.vue
git commit -m "feat: responsive servers view — padding + stat-grid mobile collapse"
```

---

## Task 5: AlertsView + AlertRulesView — mobile padding

**Files:**
- Modify: `frontend/src/views/alerts/AlertsView.vue`
- Modify: `frontend/src/views/alerts/AlertRulesView.vue`

### What to change

`AlertsView`: `.page { padding: 28px; }` (line 197). The `.history-bar { display: flex; gap: 8px; }` should wrap on mobile. Alert list rows are flex with `overflow: hidden; text-overflow: ellipsis` already applied — they truncate gracefully.

`AlertRulesView`: `.page { padding: 28px; }` (line 256). The `.panel { overflow-x: auto; }` is already set (line 274) — the rules table already scrolls. Only padding is missing.

- [ ] **Step 1: Fix AlertsView.vue**

Find `.page { padding: 28px; }` (line 197) and append:
```css
@media (max-width: 1023px) { .page { padding: 20px; } }
@media (max-width: 767px)  { .page { padding: 14px; } }
```

Find `.history-bar { display: flex; gap: 8px; padding: 10px 0; }` and add `flex-wrap: wrap;`:
```css
.history-bar { display: flex; gap: 8px; padding: 10px 0; flex-wrap: wrap; }
```

- [ ] **Step 2: Fix AlertRulesView.vue**

Find `.page { padding: 28px; }` (line 256) and append:
```css
@media (max-width: 1023px) { .page { padding: 20px; } }
@media (max-width: 767px)  { .page { padding: 14px; } }
```

(The `.panel { overflow-x: auto; }` is already correct — no change needed.)

- [ ] **Step 3: Smoke test**

At **375px**, navigate to `/alerts` then `/alerts/rules`. Padding should be 14px. On the alerts page the history bar buttons should wrap if there are many. The rules table should scroll horizontally rather than overflow the viewport.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/alerts/AlertsView.vue frontend/src/views/alerts/AlertRulesView.vue
git commit -m "feat: responsive alerts views — mobile padding + history bar wrap"
```

---

## Task 6: ServicesView + LogsView — mobile padding

**Files:**
- Modify: `frontend/src/views/services/ServicesView.vue`
- Modify: `frontend/src/views/logs/LogsView.vue`

### What to change

`ServicesView`: `.page { padding: 28px; }` (line 229). Filters already have `flex-wrap: wrap`. The service list is `display: flex; flex-direction: column` — already stacks. Only padding is missing.

`LogsView`: `.page { padding: 28px; display: flex; flex-direction: column; gap: 20px; }` (line 260). The `.card-grid { grid-template-columns: repeat(2, 1fr) }` already has `@media (max-width: 800px) { grid-template-columns: 1fr; }` — already responsive. Only page padding is missing.

- [ ] **Step 1: Fix ServicesView.vue**

Find `.page { padding: 28px; }` (line 229) and append:
```css
@media (max-width: 1023px) { .page { padding: 20px; } }
@media (max-width: 767px)  { .page { padding: 14px; } }
```

- [ ] **Step 2: Fix LogsView.vue**

Find `.page { padding: 28px; ... }` (line 260) and add responsive overrides after its closing brace:
```css
@media (max-width: 1023px) { .page { padding: 20px; } }
@media (max-width: 767px)  { .page { padding: 14px; } }
```

- [ ] **Step 3: Smoke test**

At **375px**, navigate to `/services` and `/logs`. Page padding should be 14px. Service list and log intelligence cards should stack single-column. No horizontal scroll.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/services/ServicesView.vue frontend/src/views/logs/LogsView.vue
git commit -m "feat: responsive services + logs views — mobile padding"
```

---

## Task 7: SslDomainsView — table overflow + mobile padding

**Files:**
- Modify: `frontend/src/views/ssl-domains/SslDomainsView.vue`

### What to change

The SSL/domains page renders a `<table class="grid">` (around line 461) inside `.panel`. The table has no `overflow-x: auto` wrapper, so wide columns overflow the page on mobile. Also missing responsive padding.

- [ ] **Step 1: Wrap the table in an overflow-x container**

In the template of `SslDomainsView.vue`, find the `<table class="grid">` element (around line 461). Wrap it:

```html
<div class="table-scroll">
  <table class="grid">
    <!-- unchanged -->
  </table>
</div>
```

- [ ] **Step 2: Add .table-scroll and responsive padding CSS**

In the scoped `<style>` block, find `.page { padding: 28px; }` (line 648) and append:
```css
@media (max-width: 1023px) { .page { padding: 20px; } }
@media (max-width: 767px)  { .page { padding: 14px; } }
```

Add the scroll container rule (place near the `table.grid` CSS, around line 659):
```css
.table-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
```

- [ ] **Step 3: Smoke test**

At **375px**, navigate to `/ssl-domains`. The domain table should scroll horizontally rather than overflow. Padding should be 14px. At **1440px** the table displays exactly as before.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/ssl-domains/SslDomainsView.vue
git commit -m "feat: responsive ssl-domains — table scroll wrapper + mobile padding"
```

---

## Task 8: DatabasesView + CronBackupView — mobile padding

**Files:**
- Modify: `frontend/src/views/databases/DatabasesView.vue`
- Modify: `frontend/src/views/cron-backup/CronBackupView.vue`

### What to change

`DatabasesView`: `.page { padding: 28px; max-width: 1300px; }` (line 302). The `.tab-strip` already has `flex-wrap: wrap` (line 308) so server tabs wrap on small screens already. The metrics/info panels are rendered as tabs (one shown at a time), so no side-by-side stacking is needed. Only page padding is missing.

`CronBackupView`: `.page { padding: 28px; }` (line 221). The CalendarHeatmap is rendered inside `JobDetailSlideOver.vue` (not in this view directly), and that slide-over already goes full-width on mobile. The job list is `flex-direction: column` already. Only page padding is missing.

- [ ] **Step 1: Fix DatabasesView.vue responsive padding**

Find `.page { padding: 28px; max-width: 1300px; }` (line 302) and append after it:
```css
@media (max-width: 1023px) { .page { padding: 20px; } }
@media (max-width: 767px)  { .page { padding: 14px; } }
```

- [ ] **Step 2: Fix CronBackupView.vue responsive padding**

Find `.page { padding: 28px; }` (line 221) and append after it:
```css
@media (max-width: 1023px) { .page { padding: 20px; } }
@media (max-width: 767px)  { .page { padding: 14px; } }
```

- [ ] **Step 3: Smoke test — databases + cron**

At **375px**:
- Navigate to `/databases`: padding is 14px. Server tabs wrap to next line when many are present.
- Navigate to `/cron-backup`: padding is 14px. Job list stacks cleanly.

At **1440px**: both pages display exactly as before.

- [ ] **Step 4: Final commit + release**

```bash
git add frontend/src/views/databases/DatabasesView.vue frontend/src/views/cron-backup/CronBackupView.vue
git commit -m "feat: responsive databases + cron-backup — mobile padding"
```

Then tag the release:
```bash
git describe --tags --abbrev=0   # check latest tag, e.g. v1.2.7
git tag v1.2.8
git push origin main
git push origin v1.2.8
```

Also update `PROGRESS.md` and `DASHBOARD.html` when all 8 tasks are done.
