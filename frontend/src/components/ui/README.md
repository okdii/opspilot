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
