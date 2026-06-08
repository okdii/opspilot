# Today's Runs Pinned in Job Detail Slide-Over

**Date:** 2026-06-09
**Status:** Approved
**Feature:** Show today's runs for a specific job at the top of its Run History table in `JobDetailSlideOver.vue`

---

## Context

The global "Today's Backups" panel (added in the previous spec) shows all jobs' runs for the current day on the main Cron & Backup Jobs page. This is useful as a cross-job overview but gives no per-job today summary when an operator opens a specific job's detail slide-over.

This spec adds a **"▸ Today" pinned group** at the top of the Run History table inside `JobDetailSlideOver.vue`, showing only the current job's runs for today, filtered from `store.todayRuns`. The global panel on `CronBackupView.vue` is unchanged.

---

## Design

### Run History section — new layout

The existing Run History section (`<section class="block">`) gains two changes:

**1. Section header** — gains a date chip, run count badge, and red failed badge (same chip/badge styles as the global panel):

```
Run History  [Mon Jun 9]  [3 runs today]  [1 failed]   ← badges only when todayCount > 0
```

Badges are hidden when there are no today runs for this job (i.e. the section renders exactly as before with just the "Run History" title).

**2. Table body** — when `jobTodayRuns.length > 0`, the table gains two group separator rows before the paginated rows:

| Row type | Appearance |
|----------|-----------|
| **▸ Today** group header | `colspan=8`, indigo text + very faint indigo background, `font-size: 10px`, `text-transform: uppercase` |
| Today's run rows | Same 8-column layout; faint indigo bg for success rows, faint red bg for failed rows |
| **Earlier** group header | `colspan=8`, muted text, double top border to visually separate from today group |
| Existing paginated rows | Unchanged |

The "Earlier" label row is only rendered when `jobTodayRuns.length > 0` **and** `runs.length > 0` (i.e. there are older runs to label).

---

## Data

**Source:** `store.todayRuns` (already fetched in `load()` from `CronBackupView`).

**Filter:** computed ref inside `JobDetailSlideOver.vue`:

```ts
const jobTodayRuns = computed(() =>
  store.todayRuns.filter((r) => r.job_id === props.job?.id)
)
```

`todayRuns` already contains `job_id`, `ran_at`, `started_at`, `outcome`, `duration_sec`, `size_bytes`, `size_formatted`, `files_count`, `exit_code`, `label` — all columns needed for the 8-column table.

**No new API call.** The slide-over uses the already-fetched `store.todayRuns`. If the slide-over is opened and `store.todayRuns` is empty (e.g. navigated directly without going through `CronBackupView`), the today group is simply hidden — no fetch is triggered from the slide-over itself.

---

## Computed helpers (new)

```ts
const jobTodayRuns = computed(() =>
  store.todayRuns.filter((r) => r.job_id === props.job?.id)
)

const jobTodayIds = computed(() =>
  new Set(jobTodayRuns.value.map((r) => r.id))
)

const jobTodayFailedCount = computed(() =>
  jobTodayRuns.value.filter((r) => r.outcome !== 'success').length
)

const todayLabel = computed(() =>
  new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
)
```

---

## Behaviour

- **Today group hidden** when `jobTodayRuns.length === 0` — section renders exactly as before.
- **Earlier label hidden** when no paginated rows exist yet (empty run history or still loading).
- **Date chip** shows the local calendar date (same `todayLabel` helper already in `CronBackupView`; duplicate the one-liner in `JobDetailSlideOver`).
- **Failed badge** shown only when `jobTodayFailedCount > 0`.
- **No pagination** for today rows — today's runs are bounded by definition and never exceed a meaningful count.
- **No duplicate rows** — the "Earlier" section renders `runs` filtered to exclude IDs already shown in `jobTodayRuns`. In the template: `v-for="r in runs.filter(r => !jobTodayIds.has(r.id))"`. A companion computed `jobTodayIds` is a `Set<string>` of today run IDs for O(1) exclusion.
- The paginated `runs` ref is still fetched on slide-over open (unchanged). Runs from today that appear in `runs` are simply skipped in the "Earlier" render loop.

---

## Files changed

| File | Change |
|------|--------|
| `frontend/src/components/cron-backup/JobDetailSlideOver.vue` | Add `jobTodayRuns`, `jobTodayFailedCount`, `todayLabel` computed; update section header; add group rows to table |

No backend changes. No store changes. No migration.

---

## Out of scope

- Fetching `todayRuns` from within `JobDetailSlideOver` (it relies on the parent having called `fetchTodayRuns`).
- Removing or modifying the global "Today's Backups" panel on `CronBackupView.vue`.
- Deduplicating today's rows from the paginated history (overlap is acceptable).
