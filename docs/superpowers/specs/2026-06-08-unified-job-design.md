# Unified Job Monitoring — Design Spec

**Date:** 2026-06-08
**Status:** Approved
**Approach:** Big-bang migration (Option A) — one new migration creates new tables, copies data, drops old tables.

---

## 1. Motivation

`CronJob` and `BackupJob` are conceptually the same thing: a scheduled script that pings OpsPilot to prove it ran. The only differences were display fields and alert types. Merging them into one `MonitoredJob` type removes a false distinction, halves the codebase surface, and gives all jobs the ability to report backup metrics without needing to pre-configure a type.

All jobs always have all fields. Size, files, and exit code are shown as `—` until a ping arrives with those values. No toggle, no type selector.

---

## 2. Data Model

### 2.1 `monitored_job` table

Replaces `cron_job` and `backup_job`.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | no | uuid4 | PK |
| `server_id` | UUID | no | — | FK → server (CASCADE) |
| `name` | varchar(120) | no | — | |
| `description` | text | yes | NULL | |
| `schedule` | varchar(120) | no | — | cron expression, required for all jobs |
| `grace_period_min` | int | no | 10 | |
| `ping_token` | UUID | no | uuid4 | unique |
| `status` | varchar(20) | no | `'healthy'` | healthy / late / missing |
| `last_ping_at` | timestamptz | yes | NULL | |
| `start_ping_at` | timestamptz | yes | NULL | two-ping mode start event |
| `last_duration_sec` | int | yes | NULL | |
| `last_size_bytes` | bigint | yes | NULL | null = never sent |
| `last_size_formatted` | text | yes | NULL | human-readable, computed on write |
| `last_files_count` | int | yes | NULL | |
| `last_exit_code` | int | yes | NULL | |
| `previous_size_bytes` | bigint | yes | NULL | for size-drop detection |
| `created_at` | timestamptz | no | NOW() | |

### 2.2 `job_run` table

Replaces `cron_job_run` and `backup_run`.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `job_id` | UUID | no | FK → monitored_job (CASCADE) |
| `ran_at` | timestamptz | no | |
| `outcome` | varchar(20) | no | success / missed / failed |
| `duration_sec` | int | yes | set when two-ping end arrives |
| `size_bytes` | bigint | yes | set when POST ping includes it |
| `files_count` | int | yes | |
| `exit_code` | int | yes | |

### 2.3 `alert` table changes

- Add `job_id` UUID FK → `monitored_job` (SET NULL on delete), nullable
- Remove `cron_job_id` and `backup_job_id` columns
- Update alert type strings (see §4)

---

## 3. Ping Endpoints

### 3.1 `GET /ping/{token}`

Token looks up `monitored_job.ping_token`.

**`?event=start`:**
- Sets `job.start_ping_at = now()`
- Returns `{"ok": true}`

**No event or `?event=end`:**
- Computes `duration_sec = now() - start_ping_at` if set
- Updates `job.last_ping_at`, `job.last_duration_sec`, clears `job.start_ping_at`
- Sets `job.status = "healthy"`
- Writes `JobRun(outcome="success", duration_sec=duration_sec)`
- Resolves any open `job_missing` alert
- Returns `{"ok": true}`

**Token not found:** `404 {"error": "unknown token"}`

### 3.2 `POST /ping/{token}`

Accepts optional form fields: `size_bytes`, `exit_code`, `files_count`, `event`, `status`.

All fields optional. If absent → `None`. `event` follows same start/end logic as GET.

**On a plain end ping (no event or event=end):**
1. Parse optional fields
2. If `exit_code` present and `!= 0` → outcome = `'failed'`, fire `job_failure` alert
3. Else if `size_bytes` present and `== 0` → outcome = `'failed'`, fire `job_size_drop` alert
4. Else if `size_bytes` present and `< previous_size_bytes * 0.80` → outcome = `'success'`, fire `job_size_drop` alert
5. Else → outcome = `'success'`
6. Update job: `last_ping_at`, `last_size_bytes`, `last_size_formatted`, `last_files_count`, `last_exit_code`
7. If `exit_code` not present: do not touch `last_exit_code`
8. If `size_bytes` not present: do not touch `last_size_bytes` or `previous_size_bytes`
9. If outcome = `'success'` and `size_bytes` present: update `previous_size_bytes`
10. Set `job.status = "healthy"`
11. Write `JobRun` row
12. Resolve any open `job_missing` alert
13. Return `{"ok": true}`

**Key invariant:** Backup alerts (`job_failure`, `job_size_drop`) only fire when the ping explicitly includes `size_bytes` / `exit_code`. A plain GET ping never triggers them.

---

## 4. Alert Types

| Old type | New type | Trigger |
|---|---|---|
| `cron_missing` | `job_missing` | job misses its cron window |
| `backup_missing` | `job_missing` | (same — now unified) |
| `backup_failure` | `job_failure` | ping arrives with `exit_code != 0` |
| `backup_size_drop` | `job_size_drop` | size is zero or drops >20% |

The `alerting.py` `_JOB_ID_MAP` becomes:
```python
{
    "job_missing": "job_id",
    "job_failure": "job_id",
    "job_size_drop": "job_id",
}
```

`fire_alert` signature: replace `cron_job_id` / `backup_job_id` params with single `job_id`.

---

## 5. Watchdog

Single `_evaluate_job(db, job, now)` function using `croniter` on `job.schedule`.

```
next_expected = next_fire_after(job.schedule, job.last_ping_at or now())
grace = timedelta(minutes=job.grace_period_min)

if now < next_expected:          status = 'healthy'
elif now < next_expected + grace: status = 'late'
else:                             status = 'missing'
  → write JobRun(outcome='missed')
  → fire job_missing alert
  → set status = 'missing' (suppresses re-fire)
```

Replaces `_evaluate_cron` and `_evaluate_backup` entirely.

---

## 6. API Endpoints

Old `/api/cron-jobs` and `/api/backup-jobs` endpoints are **removed**.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/organizations/{org_id}/jobs` | Required | List all jobs for org |
| POST | `/api/jobs` | Admin | Create job |
| PATCH | `/api/jobs/{id}` | Admin | Update job |
| DELETE | `/api/jobs/{id}` | Admin | Delete job |
| GET | `/api/jobs/{id}/runs` | Required | Run history (cursor-paginated) |
| POST | `/api/jobs/{id}/regenerate-token` | Admin | Regenerate ping token |
| GET | `/ping/{token}` | Public | Heartbeat GET ping |
| POST | `/ping/{token}` | Public | Heartbeat POST ping with payload |

### 6.1 `GET /api/organizations/{org_id}/jobs` response shape

```json
[
  {
    "id": "uuid",
    "server_id": "uuid",
    "server_name": "web-01",
    "name": "gdrive-nightly",
    "description": null,
    "schedule": "0 2 * * *",
    "grace_period_min": 10,
    "ping_url": "https://opspilot.example.com/ping/abc123",
    "status": "healthy",
    "last_ping_at": "2026-06-08T02:01:09Z",
    "start_ping_at": null,
    "last_duration_sec": 45,
    "last_size_bytes": 4551231488,
    "last_size_formatted": "4.24 GB",
    "last_files_count": 1234,
    "last_exit_code": 0,
    "next_expected_at": "2026-06-09T02:00:00Z"
  }
]
```

### 6.2 `GET /api/jobs/{id}/runs` response shape

```json
{
  "runs": [
    {
      "id": "uuid",
      "ran_at": "2026-06-08T02:01:09Z",
      "outcome": "success",
      "duration_sec": 45,
      "size_bytes": 4551231488,
      "size_formatted": "4.24 GB",
      "files_count": 1234,
      "exit_code": 0
    }
  ],
  "next_cursor": null
}
```

---

## 7. Frontend

### 7.1 Store (`frontend/src/stores/jobs.ts`)

Replaces `cronBackup.ts`.

```ts
interface MonitoredJob {
  id: string
  server_id: string
  server_name: string
  name: string
  description: string | null
  schedule: string
  grace_period_min: number
  ping_url: string
  status: string
  last_ping_at: string | null
  start_ping_at: string | null
  last_duration_sec: number | null
  last_size_bytes: number | null
  last_size_formatted: string | null
  last_files_count: number | null
  last_exit_code: number | null
  next_expected_at: string | null
}

interface JobRun {
  id: string
  ran_at: string
  outcome: string
  duration_sec: number | null
  size_bytes: number | null
  size_formatted: string | null
  files_count: number | null
  exit_code: number | null
}

// Store state
jobs: MonitoredJob[]
isLoadingList: boolean
isLoadingDetail: boolean
error: string | null

// Getters
sortedJobs: MonitoredJob[]              // missing → late → healthy
jobsByServer(server_id): MonitoredJob[] // for server detail tab
missingCount: number                    // nav badge

// Actions
fetchJobs(org_id): Promise<void>
createJob(payload): Promise<MonitoredJob>
updateJob(id, payload): Promise<MonitoredJob>
deleteJob(id): Promise<void>
fetchRuns(job_id, cursor?): Promise<RunsResponse>
regenerateToken(id): Promise<string>
reset(): void
```

### 7.2 `/cron-backup` page (`CronBackupView.vue`)

- No tabs. Single job list.
- `+ Add Job` button (top right)
- Empty state: "No jobs registered yet — add a heartbeat check to monitor any scheduled script."
- Sort: missing → late → healthy, then by server name, then job name

### 7.3 `JobModal.vue`

Replaces `BackupJobModal.vue` and the inline cron modal in `CronBackupView`.

**Fields:**
| Field | Type | Default | Validation |
|---|---|---|---|
| Server | Dropdown (locked if `serverId` prop) | First server | Required |
| Job Name | Text | — | 2–100 chars |
| Schedule | Cron expression | `0 2 * * *` | Required; validated; live preview |
| Grace Period | Select | 10 min | 5/10/15/30/60/120/240 min |
| Description | Text | — | Optional |

Slide-over style (matches `BackupJobModal` current style — swipes from the right).

### 7.4 `JobRow.vue`

Single row design — no type branching. Shows:
- Status dot + job name + server name + schedule label
- Status badge
- Last ping (relative)
- Size (formatted, or `—`)
- Next expected

### 7.5 `JobDetailSlideOver.vue`

- **Snippet block:** always shows two tabs — rclone snippet / curl only (same as current backup slide-over)
- **Run history table columns:** Time, Outcome, Duration, Size, Files, Exit — all columns always present, cells show `—` when null
- **Calendar heatmap:** unchanged
- **Size trend chart:** shown when any run has `size_bytes`; duration shown when any run has `duration_sec`; if neither, shows "No trend data yet"

### 7.6 `BackupTab.vue` (server detail)

Minimal changes — swap `useCronBackupStore` for `useJobsStore`, swap `BackupJobModal` for `JobModal`. Behavior unchanged.

---

## 8. Migration 0016

File: `backend/migrations/versions/0016_unified_job.py`
`down_revision = "0015_backup_files_count"`

**Upgrade steps (in order):**

1. Create `monitored_job` table
2. Create `job_run` table
3. Copy `cron_job` rows → `monitored_job` (backup fields NULL; `grace_period_min` from job; `description` NULL)
4. Copy `backup_job` rows → `monitored_job`:
   - `schedule`: convert `expected_interval_hours` → best-effort cron expression:
     - 24 → `'0 2 * * *'` (daily at 2am)
     - 168 → `'0 2 * * 0'` (weekly Sunday 2am)
     - all others → `'0 2 * * *'`
   - `grace_period_min`: 30 (was the backup default)
   - `last_size_bytes`, `last_files_count`, `previous_size_bytes` from source
   - `last_exit_code`: NULL (old model had no `last_exit_code` column — it was in run rows only)
5. Copy `cron_job_run` → `job_run` (backup fields NULL)
6. Copy `backup_run` → `job_run` (duration_sec NULL)
7. Add `job_id` column to `alert` (UUID, nullable, FK → monitored_job SET NULL)
8. Populate `alert.job_id` from `cron_job_id` then `backup_job_id` (coalesce)
9. Update alert type strings in `alert` table:
   - `'cron_missing'` → `'job_missing'`
   - `'backup_missing'` → `'job_missing'`
   - `'backup_failure'` → `'job_failure'`
   - `'backup_size_drop'` → `'job_size_drop'`
10. Drop `alert.cron_job_id` and `alert.backup_job_id` columns
11. Drop tables: `backup_run`, `cron_job_run`, `backup_job`, `cron_job`

**Downgrade:** Not provided (destructive — data cannot be cleanly split back into two tables).

---

## 9. Files Changed

| File | Action |
|---|---|
| `backend/migrations/versions/0016_unified_job.py` | Create |
| `backend/app/models/other.py` | Replace `CronJob`, `BackupJob`, `CronJobRun`, `BackupRun` with `MonitoredJob`, `JobRun`; update `Alert` FK |
| `backend/app/schemas/cron_backup.py` → `job.py` | Replace with unified `JobOut`, `JobCreate`, `JobUpdate`, `JobRunOut` |
| `backend/app/routers/cron_backup.py` | Replace with unified router using new models/schemas; remove old endpoints; add new `/api/jobs` endpoints |
| `backend/app/services/cron_watchdog.py` | Replace `_evaluate_cron`+`_evaluate_backup` with single `_evaluate_job` |
| `backend/app/services/alerting.py` | Replace `cron_job_id`+`backup_job_id` params with `job_id`; update `_JOB_ID_MAP` |
| `frontend/src/stores/cronBackup.ts` → `jobs.ts` | Replace with unified store |
| `frontend/src/components/cron-backup/BackupJobModal.vue` → `JobModal.vue` | Replace with unified modal (all fields) |
| `frontend/src/components/cron-backup/JobRow.vue` | Remove type branching; unified display |
| `frontend/src/components/cron-backup/JobDetailSlideOver.vue` | Remove type branching; unified snippet + run table |
| `frontend/src/views/cron-backup/CronBackupView.vue` | Remove tabs; single job list; use `JobModal` |
| `frontend/src/components/servers/tabs/BackupTab.vue` | Swap store + modal imports |
| `frontend/src/components/cron-backup/CalendarHeatmap.vue` | Update prop types |
| `frontend/src/components/cron-backup/cronLabel.ts` | No change |

---

## 10. What Is NOT Changed

- Ping URL format (`/ping/{token}`) — unchanged
- Token-based auth — unchanged
- Watchdog APScheduler schedule (every 60s) — unchanged
- Alert email format — unchanged
- Calendar heatmap logic — unchanged
- Server detail tab structure (Backup tab stays) — unchanged
- `CronBackupView` route (`/cron-backup`) — unchanged
