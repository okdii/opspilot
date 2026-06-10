# Responsive Layout — Design Spec
**Date:** 2026-06-10  
**Status:** Approved  
**Scope:** Shell (AppLayout.vue) + all page views  

---

## Problem

The entire UI is broken on anything smaller than a ~1400px desktop. The root cause is `AppLayout.vue`'s sidebar being fixed at `width: 240px; flex-shrink: 0` with zero `@media` queries. On a phone, the sidebar consumes 240px of horizontal space and the content area is crushed. Individual page views compound this with fixed multi-column grids, non-scrollable tables, and hardcoded padding.

---

## Breakpoints

| Label | Range | Sidebar behaviour |
|---|---|---|
| Mobile | `< 768px` | Sidebar hidden; hamburger top bar; drawer overlay |
| Tablet | `768px – 1023px` | Icon-only sidebar, 52px wide, hover tooltips |
| Small Laptop | `1024px – 1279px` | Sidebar narrows to 200px; labels still visible |
| Desktop | `≥ 1280px` | Full sidebar 240px — unchanged, current behaviour |

---

## Section 1: Shell (AppLayout.vue)

### Desktop (≥ 1280px) — no change
Current behaviour preserved exactly.

### Small Laptop (1024–1279px)
- Sidebar width reduces from 240px → 200px
- Nav link font-size: 12px (from 13px)
- Nav link padding: 8px 10px (from 9px 12px)
- Brand name stays visible

### Tablet (768–1023px)
- Sidebar width: 52px (icon-only)
- Brand: show only the logo icon, hide `.brand-text`
- Nav links: hide `<span>` label text, keep icon only
- Nav link padding: 10px 0, centered
- Nav icon: scale up slightly to 18px, centered
- User card: show only avatar, no name/role/chevron
- Hover tooltip: CSS-only `title` attribute tooltip (or `::after` pseudo-element) showing the nav label
- OrgSwitcher: hide the full switcher text, show only the active org's initial character (implementation may use `overflow: hidden` + reduced width, or a compact prop if OrgSwitcher supports it)

### Mobile (< 768px)
- `.sidebar` hidden (`display: none`)
- New `.mobile-topbar` appears at top of `.content` area:
  - Left: hamburger button (3-line icon, toggles `mobileOpen`)
  - Center: OpsPilot logo + name
  - Right: NotificationBell + user avatar (opens user menu)
  - Height: 52px, `position: sticky; top: 0; z-index: 100`
  - Background: `var(--surface)`, border-bottom: `var(--border)`
- `.mobile-drawer` is a full-height overlay sidebar:
  - `position: fixed; top: 0; left: 0; bottom: 0; width: 280px; z-index: 200`
  - Transforms: `translateX(-100%)` closed → `translateX(0)` open
  - CSS transition: `transform 0.25s ease`
  - Contains the full sidebar content (brand, nav, user card)
- `.drawer-backdrop`: `position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 199`
  - Only rendered when `mobileOpen === true`
  - Click closes drawer (`mobileOpen = false`)
- Route navigation closes drawer automatically (watch `route.path`)
- `mobileOpen` ref, type `boolean`, default `false`

---

## Section 2: Page Content

### Global utilities (App.vue `<style>`)
Add two utility classes usable across all views:

```css
/* Responsive page padding */
.page-pad { padding: 28px; }
@media (max-width: 1023px) { .page-pad { padding: 20px; } }
@media (max-width: 767px)  { .page-pad { padding: 14px; } }

/* Responsive auto-fill grid */
.responsive-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
@media (max-width: 767px) {
  .responsive-grid { grid-template-columns: 1fr; }
}
```

### Per-view changes

#### ServersView.vue
- `.stat-grid` (currently `repeat(4, 1fr)`):
  - Tablet/laptop: `repeat(2, 1fr)`
  - Mobile: `repeat(2, 1fr)` (4 small stats fit in 2 cols)
- `.grid` (server cards, already `auto-fill minmax(260px,1fr)`): no change needed — already responsive
- Page outer padding: switch to `.page-pad`

#### DashboardView.vue (GlobalDashboard.vue)
- Audit layout; any fixed multi-column grid → `auto-fill` or stack
- Chart containers: add `min-width: 0` so ECharts doesn't overflow flex parent
- Page padding: `.page-pad`

#### DatabasesView.vue
- Tab strip: `overflow-x: auto; white-space: nowrap` so tabs scroll on mobile
- DB info panels (side-by-side on desktop): `flex-direction: column` on mobile
- Page padding: `.page-pad`

#### AlertsView.vue / AlertRulesView.vue
- Alert list rows: wrap on mobile; secondary columns (latency, last-seen) hidden via `display: none` at `< 768px` or wrapped into a second line
- Table wrappers: `overflow-x: auto` so wide tables scroll rather than break layout

#### ServicesView.vue
- Service table: `overflow-x: auto` wrapper
- Filter bar: `flex-wrap: wrap` so chips wrap to next line on mobile

#### LogsView.vue
- Log list: `overflow-x: auto`
- Filter controls: stack vertically on mobile

#### SslDomainsView.vue
- Domain list table: `overflow-x: auto`
- Expiry bar / timeline: already flex, add `min-width: 0`

#### CronBackupView.vue
- Heatmap + job list: change from side-by-side to `flex-direction: column` on mobile
- Heatmap: `overflow-x: auto` so wide months scroll
- Page padding: `.page-pad`

#### Modals (all modal-overlay classes)
- On mobile: `padding: 12px` on overlay (from 20px) so modal doesn't clip on small screens
- Modal itself: `max-height: 95vh`, add `padding-bottom: env(safe-area-inset-bottom)` for iOS

#### SlideOver (SlideOver.vue)
- Desktop: current side panel behaviour unchanged
- Mobile: slide-over goes full width (`width: 100vw`) instead of fixed `420px`

---

## Section 3: What Is NOT Changed

- No backend changes
- No Pinia store changes  
- No component logic changes
- No new components (mobile top bar is inline in AppLayout.vue)
- Desktop layout (≥ 1280px) is fully preserved — zero visual regression risk at desktop
- No Vuestic UI component changes (all fixes are scoped CSS)

---

## Files to Touch

| File | Change type |
|---|---|
| `frontend/src/App.vue` | Add global `.page-pad` and `.responsive-grid` utilities |
| `frontend/src/components/common/AppLayout.vue` | Sidebar breakpoints + mobile topbar + drawer |
| `frontend/src/views/servers/ServersView.vue` | stat-grid breakpoints, padding |
| `frontend/src/views/dashboard/DashboardView.vue` | chart min-width, grid stacking |
| `frontend/src/components/dashboard/GlobalDashboard.vue` | grid / flex layout fixes |
| `frontend/src/views/databases/DatabasesView.vue` | tab scroll, panel stack, padding |
| `frontend/src/views/alerts/AlertsView.vue` | table overflow, row wrap |
| `frontend/src/views/alerts/AlertRulesView.vue` | table overflow |
| `frontend/src/views/services/ServicesView.vue` | table overflow, filter wrap |
| `frontend/src/views/logs/LogsView.vue` | overflow, filter stack |
| `frontend/src/views/ssl-domains/SslDomainsView.vue` | table overflow, min-width |
| `frontend/src/views/cron-backup/CronBackupView.vue` | flex direction, heatmap overflow |
| `frontend/src/components/ui/SlideOver.vue` | full-width on mobile |

---

## Success Criteria

- At 375px (iPhone SE): sidebar hidden, hamburger works, all pages readable without horizontal scrolling
- At 768px (iPad portrait): icon sidebar visible, content fills screen
- At 1024px (small laptop): 200px sidebar, content comfortable
- At 1440px (desktop): zero visual change from current
- No JavaScript changes — all breakpoint logic is pure CSS `@media` queries
- Drawer closes on navigation
