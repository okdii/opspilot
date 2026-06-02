# Spec 09 — Cron & Backup Job Monitoring

**Version:** 1.0  
**Date:** 2026-06-01  
**Status:** Approved

---

## 1. Overview

Cron and backup job monitoring uses a **heartbeat / dead man's switch** approach — jobs ping a unique URL at the end of each run. OpsPilot tracks whether the ping arrived on schedule. If it's late or missing, an alert fires. No agent installation required; the curl command is appended to existing scripts.

Two job types share the same page and similar UX but differ in payload:
- **Cron jobs** — general-purpose scheduled scripts; optional two-ping mode for duration tracking
- **Backup jobs** — same heartbeat + additional `size_bytes` and `exit_code` payload; extra alert conditions (size drop >20%, size zero, non-zero exit code)

PRD references: §5.10, §5.11, §5.16.10, §9 (CronJob, CronJobRun, BackupJob, BackupRun models)

---

## 2. Routes

| Route | Access | Description |
|---|---|---|
| `/cron-backup` | All roles | Combined cron + backup job monitoring for active org |

Single page with two tabs: **Cron Jobs** and **Backup Jobs**. No separate detail URL — job detail expands inline or in a slide-over.

---

## 3. Page Layout

```
┌────────────────────────────────────────────────────────────────┐
│ Cron & Backup Jobs                                             │
│                                                                │
│  [Cron Jobs (8)]   [Backup Jobs (4)]                          │
│                                                                │
│  ── Cron Jobs tab content ──────────────────────────────────  │
│                                                                │
│  Filter: [All Servers ▼]  [All Status ▼]   [+ Add Cron Job] │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  ● database-backup    web-01   0 3 * * *   ✓ Healthy   │ │
│  │    Last: 3h ago  Duration: 14s  Next: in 21h    [⋮]    │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  ⚡ php-session-gc    web-01   */5 * * * *  ⚠ Late     │ │
│  │    Last: 6m ago  Duration: —   Next: overdue    [⋮]    │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │  ✕ log-rotate        app-02   0 * * * *    ✕ Missing   │ │
│  │    Last: 3d ago  Duration: —   Next: overdue    [⋮]    │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

Tab counts show the total number of jobs (not filtered). Count badge turns red if any job is in `missing` status.

---

## 4. Job List

### 4.1 Job Row

Each job displays as a card row:

| Element | Cron Job | Backup Job |
|---|---|---|
| Status dot | Green (healthy) / Amber (late) / Red (missing) | Same |
| Job name | Text | Text |
| Server | Server name | Server name |
| Schedule | Human-readable cron (e.g., "Every day at 3am") | Same |
| Status badge | `✓ Healthy` / `⚠ Late` / `✕ Missing` | Same + `✕ Failed` |
| Last ping | Relative time ("3h ago") | Same |
| Duration | Last `last_duration_sec` formatted ("14s", "2m 4s") or `—` | Same + last size ("1.2 GB") |
| Next expected | "in 21h" or "Overdue" (amber/red) | Same |
| Kebab [⋮] | Edit, View Detail, Delete | Edit, View Detail, Delete |

**`✕ Failed`** badge (backup only): when `last_exit_code != 0` on the most recent run — shown in addition to or instead of the schedule-based status.

Sort order: Missing jobs float to top, then Late, then Healthy. Within each group: sorted by server name then job name.

### 4.2 Human-Readable Cron Labels

The cron expression is translated to a short human label shown in the row. Examples:

| Expression | Label |
|---|---|
| `0 3 * * *` | Every day at 3:00am |
| `*/5 * * * *` | Every 5 minutes |
| `0 */6 * * *` | Every 6 hours |
| `0 0 * * 0` | Every Sunday at midnight |
| `30 2 * * 1-5` | Weekdays at 2:30am |
| Complex or unrecognised | Show raw expression only |

Translation is client-side using a small helper. If the expression is invalid, show raw expression in amber with a tooltip: "Invalid cron expression."

### 4.3 Empty State (no jobs)

```
┌──────────────────────────────────────────────────┐
│                                                  │
│       No cron jobs registered yet               │
│                                                  │
│   Monitor your scheduled scripts by adding a    │
│   heartbeat check. OpsPilot will alert you if   │
│   a job stops running on schedule.              │
│                                                  │
│         [+ Register Your First Cron Job]        │
│                                                  │
└──────────────────────────────────────────────────┘
```

---

## 5. Add / Edit Cron Job Modal

### 5.1 Trigger

`[+ Add Cron Job]` in page header, or `[⋮] → Edit` on a row.

### 5.2 Form Fields

| Field | Type | Default | Validation |
|---|---|---|---|
| Server | Dropdown | First server in active org | Required |
| Job Name | Text | — | Required; 2–100 chars |
| Schedule | Text (cron expression) | `0 * * * *` | Required; validated via croniter; human label preview shown below field |
| Grace Period | Select | 10 min | 5 min / 10 min / 15 min / 30 min / 1h / 2h |
| Two-ping mode | Toggle | Off | Shows/hides usage instructions |

**Schedule field preview:** Below the cron input, shows "Runs: Every hour at :00" live as the expression is edited. If expression is invalid: "Invalid cron expression" in red.

**Two-ping mode toggle:** When enabled, reveals a secondary info block:
```
Two-ping mode enabled — add both calls to your script:

At the top:
curl -s "{ping_url}?event=start" > /dev/null

At the end:
curl -s "{ping_url}?event=end" > /dev/null
```

On create, this section shows placeholder `{ping_url}` since the token doesn't exist yet — the actual URL is shown in the detail view after save. On edit of an existing job, the real URL is shown immediately.

### 5.3 Submit Behaviour

- **Create**: POST `/api/cron-jobs` → modal closes → new row inserted at top with green "Healthy" status (job is considered healthy until the first scheduled window passes without a ping)
- **Edit**: PATCH `/api/cron-jobs/:id` → row updates in place
- Loading spinner on submit button

---

## 6. Add / Edit Backup Job Modal

### 6.1 Form Fields

Same as cron job, plus backup-specific fields:

| Field | Type | Default | Validation |
|---|---|---|---|
| Server | Dropdown | First server | Required |
| Job Name | Text | — | Required; 2–100 chars |
| Schedule | Cron expression | `0 2 * * *` | Required; same validation |
| Grace Period | Select | 30 min | 5 min / 10 min / 15 min / 30 min / 1h / 2h / 4h |
| Expected Min Size (bytes) | Number | — | Optional; if set, size-zero alert uses this as the threshold |

No "two-ping mode" toggle for backup jobs — the full payload is always a POST with form data.

### 6.2 Backup Ping Instructions

Shown below the form (always, not toggled):

```
Add to the end of your backup script:

curl -s -X POST {ping_url} \
  -d "status=success&size_bytes=<BYTES>&exit_code=$?"

Replace <BYTES> with the actual backup file size in bytes.
The exit_code=$? captures your script's exit status automatically.
```

---

## 7. Job Detail Slide-Over

Triggered by `[⋮] → View Detail` or clicking the job name. A 640px slide-over panel from the right.

### 7.1 Header

```
┌──────────────────────────────────────────────────────┐
│  database-backup                              [Edit] │
│  web-01  ·  Every day at 3:00am  ·  Grace: 10 min   │
│  Status: ✓ Healthy  ·  Last ping: 3h ago             │
│  Next expected: 2026-06-02 03:00 (in 21h)            │
└──────────────────────────────────────────────────────┘
```

### 7.2 Ping URL Block

Prominent section, always at the top:

```
┌──────────────────────────────────────────────────────┐
│  Ping URL                                            │
│                                                      │
│  curl -s https://opspilot.example.com/ping/abc123 \ │
│    > /dev/null                                       │
│                                [Copy]  [Copy as POST]│
│                                                      │
│  ℹ Append this to the end of your cron script.      │
│    The UUID in the URL is the only authentication.  │
└──────────────────────────────────────────────────────┘
```

For backup jobs, `[Copy as POST]` copies the full POST command with placeholders.
For two-ping mode cron jobs, shows both start and end curl commands with a toggle to switch views.

**Regenerate token:** `[⋮] → Regenerate Ping URL` available in the slide-over header. Shows warning modal: "Regenerating the URL will break existing scripts — update all scripts before the next scheduled run." Confirmation required.

### 7.3 Calendar Heatmap (30 Days)

```
      Mon  Tue  Wed  Thu  Fri  Sat  Sun
May   ■    ■    ■    ■    ■    ■    ■
      ■    ■    ■    ■    ■    ■    □
      ■    ■    □    ■    ■    ■    ■
Jun   ■    ■    ■    ■    ■    ■    ■
      ■    ■    ■    ■    ■    ■    ■  ← today
```

- **Green** (■): outcome = `success`
- **Red** (■): outcome = `missed` (cron) or `missed`/`failed` (backup)
- **Grey** (□): no data for that day (job not yet created, or no run expected that day)
- Tooltip on hover: date, outcome, run time, duration (if available)
- For backup jobs: tooltip also shows `size_bytes` formatted ("1.2 GB")

Days with multiple runs (e.g., every 5-minute job): cell colour reflects worst outcome of the day (any failure → red).

### 7.4 Duration Trend Chart (Cron Jobs)

Line chart: run duration in seconds on y-axis, time on x-axis.

- Only shown when `last_duration_sec` is non-null (i.e., two-ping mode is active)
- Shows last 30 days of `CronJobRun.duration_sec` values
- Dot per run; horizontal line shows 7-day average
- Tooltip: date/time, duration
- If two-ping mode is off and no duration data exists: "Enable two-ping mode to track run duration"

### 7.5 Backup Size Trend Chart (Backup Jobs)

Line chart: backup size in bytes (Y-axis shows formatted units: MB/GB), time on x-axis.

- Shows last 30 days of `BackupRun.size_bytes` values
- Each dot = one run; missing (size=null) dots shown as empty circles at y=0
- Horizontal dotted line: 7-day average size
- Red dot / red segment: runs where `outcome = 'failed'` or size dropped >20% vs previous
- Tooltip: date/time, size, exit code, outcome

### 7.6 Run History Table

Paginated table at the bottom of the slide-over. Title: "Run History"

**Cron Job columns:**

| Column | Description |
|---|---|
| Time | `YYYY-MM-DD HH:mm:ss` |
| Outcome | `✓ Success` (green) / `✕ Missed` (red) |
| Duration | Formatted seconds, or `—` |

**Backup Job columns:**

| Column | Description |
|---|---|
| Time | `YYYY-MM-DD HH:mm:ss` |
| Outcome | `✓ Success` / `✕ Failed` / `✕ Missed` |
| Size | Formatted bytes (e.g., "1.2 GB"), or `—` |
| Exit Code | Integer, or `—` |

- 20 rows per page, cursor-based pagination
- Most recent first

---

## 8. Delete Job

`[⋮] → Delete` on any job row.

Confirmation modal:

```
Delete "database-backup"?

This will permanently delete:
  • All run history (30 days)
  • The ping URL will stop accepting pings

The cron script on web-01 will NOT be modified automatically.
Remember to remove the curl line from your script.

[Cancel]  [Delete Job]
```

---

## 9. Ping Endpoint (Backend)

### 9.1 Cron Job Ping

```
GET /ping/{token}
GET /ping/{token}?event=start
GET /ping/{token}?event=end
```

Unauthenticated. The `token` is the `ping_token` UUID stored on `CronJob`.

**No `?event=` param or `?event=end`:**
1. Look up `CronJob` by `ping_token`
2. Compute `duration_sec = now() - start_ping_at` if `start_ping_at` is set; else NULL
3. Set `last_ping_at = now()`, `last_duration_sec = duration_sec`, `start_ping_at = NULL`
4. Write `CronJobRun(ran_at=now, duration_sec=duration_sec, outcome='success')`
5. Set `status = 'healthy'`
6. If an open `cron_missing` alert exists for this job → resolve it
7. Return `200 OK` with body `{"ok": true}`

**`?event=start`:**
1. Look up `CronJob` by `ping_token`
2. Set `start_ping_at = now()`
3. Do NOT update `last_ping_at`; do NOT write CronJobRun
4. Return `200 OK` with body `{"ok": true}`

**Token not found:** `404 Not Found` — `{"error": "unknown token"}`

### 9.2 Backup Job Ping

```
POST /ping/{token}
Content-Type: application/x-www-form-urlencoded

status=success&size_bytes=1073741824&exit_code=0
```

Unauthenticated. Token maps to `BackupJob`.

1. Parse form body: `status` (informational), `size_bytes` (integer, default 0), `exit_code` (integer, default 0)
2. Determine outcome:
   - `exit_code != 0` → outcome = `'failed'`, fire `backup_failure` alert
   - `size_bytes == 0` → outcome = `'failed'`, fire `backup_size_drop` alert (size is zero)
   - `size_bytes < previous_size_bytes * 0.80` AND `previous_size_bytes IS NOT NULL` → outcome = `'success'` (run completed) but fire `backup_size_drop` alert
   - Otherwise → outcome = `'success'`
3. Update `BackupJob`: `last_ping_at = now()`, `last_size_bytes = size_bytes`, `last_exit_code = exit_code`, `last_status_text = status`, `status = 'healthy'`
4. If outcome = `'success'`: set `previous_size_bytes = size_bytes` (only on success — failed runs don't update the baseline)
5. Write `BackupRun(ran_at=now, size_bytes=size_bytes, exit_code=exit_code, outcome=outcome)`
6. If open `backup_missing` alert exists → resolve it
7. Return `200 OK` with body `{"ok": true}`

**Note:** GET requests also accepted on backup ping URLs (some backup tools use GET). If method is GET, all payload fields default to their zero values.

### 9.3 Watchdog Evaluator

APScheduler job, runs every 60 seconds. Job ID: `cron_backup_watchdog`.

For each `CronJob` and `BackupJob` where `status != 'missing'`:

```
1. Compute next_expected_at:
   - Use croniter(schedule, last_ping_at).get_next(datetime)
   - If last_ping_at is NULL: use created_at as the base
2. Compare to now():
   - now() < next_expected_at → status = 'healthy'
   - next_expected_at ≤ now() < next_expected_at + grace_period → status = 'late'
   - now() ≥ next_expected_at + grace_period → status = 'missing':
     * Write CronJobRun/BackupRun with outcome = 'missed', ran_at = next_expected_at
     * Fire alert (cron_missing or backup_missing)
     * Set status = 'missing' (prevents repeated alert fires on subsequent ticks)
3. Write updated status to DB
```

Once a job enters `missing` status, the watchdog stops firing new alerts for that job until the next successful ping resets `status = 'healthy'`.

**Two-ping mode — start-only edge case:** The `?event=start` ping does NOT update `last_ping_at`; only a plain ping or `?event=end` ping updates it. If `?event=start` arrives but `?event=end` never arrives, the watchdog computes `next_expected_at` from the unchanged `last_ping_at`. The job will eventually enter `missing` status based on the original schedule — the start ping does not extend the deadline.

---

## 10. Pinia Store — `useCronBackupStore`

```ts
// State
cronJobs: CronJob[]
backupJobs: BackupJob[]
activeCronJob: CronJob | null          // for slide-over detail
activeBackupJob: BackupJob | null
cronRuns: CronJobRun[]                 // for active job detail
backupRuns: BackupRun[]
isLoadingList: boolean
isLoadingDetail: boolean
error: string | null

// Getters
cronJobsByServer: (server_id: string) => CronJob[]
backupJobsByServer: (server_id: string) => BackupJob[]
missingCronCount: number               // jobs with status = 'missing'
missingBackupCount: number
totalMissingCount: number              // badge on nav sidebar

// Actions
fetchCronJobs(org_id: string): Promise<void>
fetchBackupJobs(org_id: string): Promise<void>
fetchCronDetail(job_id: string): Promise<void>  // loads runs + heatmap data
fetchBackupDetail(job_id: string): Promise<void>
createCronJob(payload): Promise<CronJob>
updateCronJob(id: string, payload): Promise<CronJob>
deleteCronJob(id: string): Promise<void>
createBackupJob(payload): Promise<BackupJob>
updateBackupJob(id: string, payload): Promise<BackupJob>
deleteBackupJob(id: string): Promise<void>
regenerateToken(type: 'cron'|'backup', id: string): Promise<string>  // returns new ping_url
```

---

## 11. API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/organizations/:org_id/cron-jobs` | Required | List all cron jobs for org |
| POST | `/api/cron-jobs` | Required (Admin) | Create cron job |
| PATCH | `/api/cron-jobs/:id` | Required (Admin) | Update cron job |
| DELETE | `/api/cron-jobs/:id` | Required (Admin) | Delete cron job |
| GET | `/api/cron-jobs/:id/runs` | Required | Run history (cursor-paginated) |
| POST | `/api/cron-jobs/:id/regenerate-token` | Required (Admin) | Regenerate ping token |
| GET | `/api/organizations/:org_id/backup-jobs` | Required | List all backup jobs for org |
| POST | `/api/backup-jobs` | Required (Admin) | Create backup job |
| PATCH | `/api/backup-jobs/:id` | Required (Admin) | Update backup job |
| DELETE | `/api/backup-jobs/:id` | Required (Admin) | Delete backup job |
| GET | `/api/backup-jobs/:id/runs` | Required | Run history (cursor-paginated) |
| POST | `/api/backup-jobs/:id/regenerate-token` | Required (Admin) | Regenerate ping token |
| GET | `/ping/:token` | Public | Cron job ping (GET, no event or ?event=start/end) |
| POST | `/ping/:token` | Public | Backup job ping (POST with form body) |

### 11.1 GET `/api/organizations/:org_id/cron-jobs` Response

```json
[
  {
    "id": "uuid",
    "server_id": "uuid",
    "server_name": "web-01",
    "name": "database-backup",
    "schedule": "0 3 * * *",
    "grace_period_min": 10,
    "ping_url": "https://opspilot.example.com/ping/abc123",
    "last_ping_at": "2026-06-01T03:00:14Z",
    "start_ping_at": null,
    "last_duration_sec": 14,
    "status": "healthy",
    "next_expected_at": "2026-06-02T03:00:00Z"
  }
]
```

`next_expected_at` is computed server-side on each list request via `croniter` — not stored in DB.

### 11.2 GET `/api/backup-jobs/:id/runs` Response

```json
{
  "runs": [
    {
      "id": "uuid",
      "ran_at": "2026-06-01T02:00:09Z",
      "size_bytes": 1073741824,
      "size_formatted": "1.00 GB",
      "exit_code": 0,
      "outcome": "success"
    }
  ],
  "next_cursor": "base64token"
}
```

---

## 12. Edge States

| State | Behaviour |
|---|---|
| Job never received a ping | Status = `healthy` (assumed ok until first window passes); heatmap shows all grey; run history empty |
| `last_ping_at` is NULL (newly created) | `next_expected_at` computed from `created_at`; grace period starts from first expected run |
| Cron job fired at unexpected time (outside schedule) | Ping accepted; `last_ping_at` updated; CronJobRun written with outcome `success`; no alert; next `next_expected_at` computed forward from new `last_ping_at` |
| Two-ping mode: `?event=start` received, no `?event=end` within schedule | Watchdog treats it as missing (only end ping resets `last_ping_at`); start_ping_at remains set |
| Backup ping: size_bytes absent from payload | Defaults to 0; triggers `backup_size_drop` alert (size is zero) |
| Backup ping: first ever run (`previous_size_bytes` is NULL) | Size-drop check skipped; previous_size_bytes set to current size |
| Backup ping: exit_code != 0 but status=success in payload | `exit_code` is authoritative → fires `backup_failure` alert regardless of status field |
| Token regenerated | Old token immediately invalidated; existing scripts using old URL receive `404`; admin must update scripts |
| Job deleted while in `missing` status | Open alert linked to this job is auto-resolved on deletion |
| Same server has 20+ cron jobs | List page virtualised; heatmap and detail views still work normally |
| Cron expression becomes invalid after import/migration | Show amber warning on row: "Invalid schedule — monitoring paused"; admin must edit to fix |
| Job is in `missing` status for >7 days without a ping | No additional alerts after the first (watchdog suppresses re-fire); status stays `missing` until a ping arrives |
| Grace period shorter than cron interval | Warn on form save: "Grace period is shorter than the run interval — jobs may be marked missing prematurely" (allow save) |

---

## 13. Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `1` / `2` | Switch between Cron Jobs / Backup Jobs tabs |
| `n` | Open Add Job modal (for active tab type) |
| `Escape` | Close modal or slide-over |
| `r` | Refresh job list |
| `/` | Focus search bar |
