# Design Spec — Reusable UI Foundation (Vuestic + AG Grid)

**Date:** 2026-06-02
**Status:** Approved (design) — pending spec review
**Scope owner:** Frontend
**Related:** CLAUDE.md (Vuestic Admin dark theme, UI/UX Pro Max rule), all module specs 04–11 (consumers)

---

## 1. Motivation

The frontend has grown to 11 `.vue` files at the end of Phase 1, with heavy style/markup duplication:

| Pattern | Re-defined in |
|---|---|
| `.primary` button | 7 files |
| spinner `@keyframes` | 7 files |
| `.card` | 6 files |
| `.err` error text | 6 files |
| `.btn` | 3 files |
| `.modal` / form inputs / `.badge` / empty state | 2 files each |

~521 lines of `<style>` are scattered across views. Phases 2–11 add ~20+ more screens (dashboard, log viewer, services, SSL, DB, cron, alerts, settings, status page), so duplication compounds and every cross-cutting fix (e.g. the Vuestic `.layout` collision) must be hunted down in N places.

This spec establishes a reusable UI layer so new screens are assembled from shared, themed building blocks.

## 2. Decisions (locked during brainstorming)

1. **Lean into Vuestic UI** — standard controls use Vuestic components themed to our dark palette, rather than a from-scratch component library. Matches the prescribed stack (CLAUDE.md).
2. **Setup + going-forward only** — no retrofit of the 8 existing views. New screens (Phases 2–11) adopt this layer; existing views are migrated only if/when otherwise touched.
3. **Components/theme layer only** — charting is a separate design, tackled when Phase 2 begins.
4. **Toast** — a thin `useNotify` composable wrapping Vuestic's `useToast`, not a bespoke toast component.
5. **AG Grid Community + Infinite Row Model** (free, MIT) for server-paginated tables. **Not** Enterprise/SSRM (no server-side grouping/aggregation needed).

## 3. Architecture & File Layout

```
frontend/src/
  plugins/
    vuestic.ts            # createVuestic() dark theme preset + global component defaults
  components/ui/
    PageHeader.vue
    StatusBadge.vue
    SlideOver.vue
    StatCard.vue
    EmptyState.vue
    DataGrid.vue          # AG Grid Community wrapper (Infinite Row Model)
    index.ts              # barrel exports
    README.md             # palette mapping + usage rules (the style reference)
  composables/
    useNotify.ts          # toast wrapper over Vuestic useToast
  views/dev/
    UiKitView.vue         # dev-only /_ui-kit gallery (verification + living reference)
```

Each unit has one purpose, a documented prop/slot/event interface, and is usable without reading its internals.

## 4. Theme Configuration — `plugins/vuestic.ts`

A single source of color truth shared between custom CSS (`App.vue` `:root` vars) and Vuestic components. `main.ts` registers the plugin instead of the bare `createVuestic()`.

**Palette mapping** (existing CSS var → Vuestic preset key → AG Grid theme param):

| Our token | Hex | Vuestic preset key | AG Grid param |
|---|---|---|---|
| `--bg` | `#0f1117` | `backgroundPrimary` | `backgroundColor` |
| `--surface` | `#1a1d27` | `backgroundSecondary` | `chromeBackgroundColor` |
| `--surface-2` | `#22263a` | `backgroundElement` | `headerBackgroundColor` |
| `--border` | `#2e3354` | `borderColor` | `borderColor` |
| `--accent` | `#6366f1` | `primary` | `accentColor` |
| `--accent-2` | `#818cf8` | `secondary` | — |
| `--green` | `#22c55e` | `success` | — |
| `--blue` | `#3b82f6` | `info` | — |
| `--amber` | `#f59e0b` | `warning` | — |
| `--red` | `#ef4444` | `danger` | — |
| `--text` | `#e2e8f0` | `textPrimary` | `foregroundColor` |
| `--muted` | `#94a3b8` | `textSecondary` | — |

- Preset registered under name `dark`; `currentPresetName: 'dark'` so Vuestic renders dark by default.
- `config.components` sets sensible global defaults (e.g. `VaButton { round: false }`, consistent input preset) to reduce per-use props — exact defaults finalized during implementation.
- The `:root` vars in `App.vue` stay authoritative for custom CSS; the preset mirrors the same hex values. Changing a brand color means editing both in lockstep (documented in `README.md`).

## 5. Components — `components/ui/`

### 5.1 `PageHeader.vue`
- **Props:** `title: string`, `subtitle?: string`.
- **Slots:** `actions` (right-aligned, e.g. "+ Add Server" button).
- **Behavior:** responsive — actions wrap below title on narrow widths. Renders the title/subtitle pattern every page currently re-implements.

### 5.2 `StatusBadge.vue`
- **Props:** `status: string`, `kind: 'server' | 'service' | 'alert' | 'ssl' | 'domain' | 'job'`.
- **Behavior:** maps `(kind, status)` → `{ label, color, icon }` via an internal config map. Colored pill (Vuestic semantic color) + SVG icon + label. Unknown status → neutral grey fallback. Color is never the only signal (icon + text always present — accessibility).
- **Status map (initial):**
  - `server`: pending(grey), online(success), offline(danger), maintenance(warning)
  - `service`: up(success), down(danger), maintenance(warning)
  - `alert`: firing(danger), acknowledged(warning), snoozed(info), resolved(success), suppressed(grey)
  - `ssl`: valid(success), expiring_soon(warning), critical(danger), expired(danger), unreachable(grey)
  - `domain`: valid(success), expiring_soon(warning), critical(danger), expired(danger)
  - `job`: healthy(success), late(warning), missing(danger), paused(grey)
- The map is the single place to add new states as later phases land.

### 5.3 `SlideOver.vue`
- **Props:** `modelValue: boolean` (open state, `v-model`), `title?: string`, `subtitle?: string`, `width?: string` (default `600px`).
- **Slots:** default (body), `footer` (action bar), optional `header` override.
- **Events:** `update:modelValue` (close).
- **Behavior:** right-anchored drawer via `<Teleport to="body">`; scrim at 50% black, click-scrim closes; slide-in transition 250ms ease-out; full-screen on `≤640px`. Mirrors the structure already proven in `OnboardingPanel.vue`. Consumers (onboarding, alert detail, job detail, maintenance) compose their content into the slots.
- **Note:** `OnboardingPanel.vue` is *not* retrofitted now (decision #2), but it is the reference implementation; future slide-overs use this shared shell.

### 5.4 `StatCard.vue`
- **Props:** `label: string`, `value: string | number`, `icon?: string` (SVG name/markup), `delta?: { value: string; direction: 'up' | 'down' | 'flat' }`, `accent?: semantic-color`.
- **Behavior:** summary tile (label, large value, optional delta with up/down color + arrow, optional icon). Used by dashboard summary row and DB dashboard.

### 5.5 `EmptyState.vue`
- **Props:** `icon?: string`, `title: string`, `message?: string`.
- **Slots:** `action` (e.g. a create button or router-link).
- **Behavior:** centered empty/placeholder block standardizing the pattern duplicated across list pages.

### 5.6 `DataGrid.vue` — AG Grid Community wrapper
Wraps `ag-grid-vue3` (Community) using the **Infinite Row Model** for server-paginated tables (logs, alert history, cron/backup runs, sessions).

- **Dependencies:** `ag-grid-community`, `ag-grid-vue3`.
- **Props:**
  - `columns: ColDef[]` — AG Grid column definitions.
  - `fetchPage: (params: FetchPageParams) => Promise<FetchPageResult<T>>` — datasource callback (see contract below).
  - `getRowId?: (row: T) => string` — stable row id.
  - `blockSize?: number` (default 100), `rowHeight?: number`.
- **Events:** `row-click` (payload: row data).
- **Datasource contract:**
  ```ts
  interface FetchPageParams {
    startRow: number
    endRow: number
    blockSize: number
    sortModel: { colId: string; sort: 'asc' | 'desc' }[]
    filterModel: Record<string, unknown>
    cursor: string | null   // nextCursor from the previous contiguous block, or null for the first block
  }
  interface FetchPageResult<T> {
    rows: T[]
    nextCursor?: string | null  // for cursor-paginated APIs
    lastRow?: number            // total count when known; else grid infers end when rows.length < blockSize
  }
  ```
- **Cursor adapter:** the wrapper maintains a `Map<startRow, cursor>`. For block N it passes the `nextCursor` returned by block N−1. Two API styles are supported via the single callback:
  - **Offset APIs** (preferred where available): caller uses `startRow`/`blockSize` as `offset`/`limit`; supports scrollbar jumping.
  - **Cursor-only APIs** (e.g. logs, alert history per specs 05/10): caller uses `cursor`; blocks load **sequentially** as the user scrolls. Scrollbar jump-to-arbitrary-row is constrained for cursor-only sources (acceptable for infinite log/history scrolling). Documented in `README.md`.
- **Theming:** AG Grid v33+ Theming API — `themeQuartz.withParams({...})` fed the palette values from §4 so the grid matches Vuestic. No legacy CSS theme import.
- **Convention:** small static tables keep using `VaDataTable`; `<DataGrid>` is for large/server-paginated data.

## 6. Composable — `composables/useNotify.ts`

Thin wrapper over Vuestic `useToast` for consistent app-wide notifications.

```ts
const notify = useNotify()
notify.success(message: string, opts?: NotifyOpts)
notify.error(messageOrError: string | Error | ApiError, opts?: NotifyOpts)  // extracts .message from Error/ApiError
notify.info(message: string, opts?: NotifyOpts)
notify.warning(message: string, opts?: NotifyOpts)
// NotifyOpts = { title?: string; duration?: number }
```

- Defaults: position top-right; `success`/`info`/`warning` 4000ms; `error` 6000ms. Vuestic toast `color` set to the matching semantic color.
- `error()` accepts an `ApiError`/`Error` and surfaces its `message`, so call sites can do `notify.error(err)` directly (pairs with `getApiError`).
- Direct consumer in Phase 8: toast on `alert_fired` WS event.

## 7. Conventions (going forward)

| Need | Use |
|---|---|
| Buttons, inputs, selects, modals, cards, tabs | Vuestic `Va*` (themed by default) |
| Small/static table | `VaDataTable` |
| Large/server-paginated table | `<DataGrid>` |
| Page title + actions | `<PageHeader>` |
| Status pill | `<StatusBadge>` |
| Right drawer / detail panel | `<SlideOver>` |
| Summary tile | `<StatCard>` |
| Empty list / placeholder | `<EmptyState>` |
| Toasts / notifications | `useNotify()` |
| Loading indicator | `VaProgressCircle indeterminate` / `VaInnerLoading` (drop bespoke spin keyframes) |

## 8. Verification — `/_ui-kit` gallery

A dev-only route (`views/dev/UiKitView.vue`, registered only in dev or behind a simple guard) renders:
- Each `components/ui` component in all meaningful states (every `StatusBadge` kind/status; `SlideOver` open; `StatCard` with/without delta; `EmptyState`).
- Buttons firing each `useNotify` variant.
- A live `<DataGrid>` backed by an existing paginated endpoint (e.g. `/api/servers`, adapting offset) to prove the infinite datasource + dark theme end-to-end.
- A row of representative themed `Va*` controls to confirm the preset.

Verified via browser screenshot (same method used for the onboarding UI). The gallery stays as a living reference; trivial to remove or guard out of production.

## 9. Out of Scope

- Retrofitting the 8 existing views (auth, dashboard, orgs, servers, onboarding panel).
- Charts / data-viz (separate design at Phase 2 start).
- Tailwind or any utility-CSS framework.
- AG Grid Enterprise, Server-Side Row Model, grouping/aggregation, master/detail, Excel export.
- New `ConfirmDialog` (use Vuestic's `useModal`/confirm).

## 10. Risks & Notes

- **Bundle size:** AG Grid Community adds a few hundred KB. Acceptable for a data-heavy ops dashboard; loaded only on routes that use `<DataGrid>` via route-level code splitting.
- **Cursor jumping:** cursor-only APIs can't random-access arbitrary blocks; `<DataGrid>` loads them sequentially. If a future table needs jump-to-row on a cursor API, add offset support server-side.
- **Two-palette lockstep:** brand color changes require editing both `App.vue :root` and the Vuestic preset; called out in `README.md`. (A future improvement could generate the preset from the vars, but YAGNI for now.)
- **Existing `.layout`/`.row` collision class:** already fixed (`.app-shell`, `.form-row`); the Vuestic theme work does not reintroduce them.
