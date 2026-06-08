# Backup Run Label, Start/End Time & Today's Panel

**Date:** 2026-06-09
**Status:** Approved
**Feature:** Richer per-run metadata (filename label + started_at) + "Today's Backups" panel on the Jobs page

---

## Context

The unified job monitoring system (spec 09) already records `ran_at` (end time), `duration_sec`, `size_bytes`, and `files_count` per run. Two gaps remain:

1. **No filename tracking** — there is no way to see which file was produced by a backup run.
2. **No start timestamp per run** — `started_at` is computed implicitly as `ran_at − duration_sec` but is not stored, making it unavailable for display without math.
3. **No at-a-glance daily summary** — operators must open each job's slide-over individually to see what ran today.

This spec adds a `label` field (free-text filename), a `started_at` timestamp to `JobRun`, a new "Today's Backups" panel on the Cron & Backup Jobs page, and updates the run history table in the slide-over to show all new columns.

---

## 1. Data Model

### 1.1 Migration: `0017_job_run_label_started_at`

**`job_runs`** — add two columns:

```sql
ALTER TABLE job_runs ADD COLUMN label VARCHAR(255) NULL;
ALTER TABLE job_runs ADD COLUMN started_at TIMESTAMPTZ NULL;
```

Both nullable — existing rows and runs without a start ping receive `NULL`.

---

## 2. Backend

### 2.1 `JobRun` model (`app/models/other.py`)

Add two fields to the `JobRun` ORM model:

```python
label: Mapped[str | None] = mapped_column(String(255), nullable=True)
started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

### 2.2 Ping endpoints (`app/routers/cron_backup.py`)

**POST `/ping/{token}`** — accept `label` as an optional form field:

```python
label: str | None = form.get("label") or None
```

When writing the `JobRun` at end-ping time, populate both new fields:

```python
db.add(JobRun(
    job_id=job.id,
    ran_at=now,
    outcome=outcome,
    duration_sec=duration,
    size_bytes=size_bytes,
    files_count=files_count,
    exit_code=exit_code,
    label=label,                          # ← new
    started_at=_aware(job.start_ping_at), # ← new (captured before clearing)
))
```

**GET `/ping/{token}`** (simple heartbeat) — also capture `started_at` from `start_ping_at` when available. `label` is not applicable for GET pings.

### 2.3 `JobRunOut` schema (`app/schemas/job.py`)

Add two fields to the response schema:

```python
label: str | None
started_at: datetime | None
```

### 2.4 New endpoint — Today's runs

```
GET /api/organizations/{org_id}/runs/today
```

Returns all `JobRun` rows whose `ran_at` falls within the current calendar day in UTC (midnight → now), joined with `MonitoredJob` and `Server` for display metadata.

Response shape:

```json
[
  {
    "id": "...",
    "ran_at": "2026-06-09T09:47:13Z",
    "started_at": "2026-06-09T09:42:01Z",
    "outcome": "success",
    "duration_sec": 312,
    "size_bytes": 524288000,
    "size_formatted": "500.00 MB",
    "files_count": 1234,
    "exit_code": 0,
    "label": "db_dump_2026-06-09.tar.gz",
    "job_id": "...",
    "job_name": "database backup",
    "server_name": "lima-ubuntu"
  }
]
```

Ordered by `ran_at DESC`. No pagination — today's runs are bounded by definition.

Access control: same `_assert_org_access` guard as the existing jobs list endpoint.

---

## 3. Frontend

### 3.1 `JobRun` type (`stores/jobs.ts`)

Add two fields:

```ts
label: string | null
started_at: string | null
```

### 3.2 Jobs store (`stores/jobs.ts`)

Add action `fetchTodayRuns(orgId)` — calls `GET /api/organizations/{orgId}/runs/today`, stores result in a new `todayRuns` ref.

### 3.3 "Today's Backups" panel — `CronBackupView.vue`

Insert a panel **above** the All Jobs list. It is shown only when `todayRuns.length > 0` (hidden otherwise — no empty state).

**Panel header:** `Today's Backups` · date chip (e.g. `Mon Jun 9`) · run count badge · failed count badge (red, only when > 0).

**Table columns:** Outcome icon · File (`label` or `—`) · Job name · Started (HH:mm) · Duration · Size.

Loaded on `onMounted` alongside `fetchJobs`. Refreshes when org changes.

### 3.4 Enhanced run history table — `JobDetailSlideOver.vue`

Replace the existing 6-column run history table with an 8-column layout:

| # | Column | Source | Notes |
|---|--------|--------|-------|
| 1 | Outcome icon | `r.outcome` | ✓ green / ✗ red |
| 2 | File | `r.label` | monospace, `—` if null |
| 3 | Started | `r.started_at` | HH:mm:ss, `—` if null |
| 4 | Ended | `r.ran_at` | HH:mm:ss |
| 5 | Duration | `r.duration_sec` | existing `fmtDuration()` |
| 6 | Size | `r.size_formatted` | existing |
| 7 | Files | `r.files_count` | existing |
| 8 | Exit | `r.exit_code` | existing |

### 3.5 Snippet update — `JobDetailSlideOver.vue`

Both the standalone script and the "add to existing" snippet gain a `label` line. In the rclone standalone snippet:

```bash
BACKUP_FILE="${REMOTE}"          # or set to the output archive path

# In the curl ping line, add:
curl -s -X POST "${url}" \
  -d "status=success&size_bytes=${SIZE_BYTES:-0}&exit_code=${EXIT_CODE}&files_count=${FILES_COUNT:-0}&label=$(basename ${BACKUP_FILE})"
```

In the curl-only snippet, document:

```bash
# Optional: pass the backup filename for display in OpsPilot
label="$(basename /path/to/your_backup.tar.gz)"
curl -s -X POST "$PING_URL" \
  -d "exit_code=$EXIT_CODE&size_bytes=${SIZE_BYTES:-0}&files_count=${FILES_COUNT:-0}&label=$label"
```

---

## 4. UI Behaviour

- **Today panel** is hidden if there are no runs today (no empty state needed — the job list is already visible below).
- **"Today" boundary** is UTC midnight → current UTC time. The panel date chip shows the local date for readability.
- **Null label**: displayed as `—` (em-dash) in both the Today panel and the run history table.
- **Null started_at**: displayed as `—`. This happens for runs ingested via GET ping or runs recorded before this feature ships.
- The Today panel does **not** replace the job list — both are visible on the same page.

---

## 5. Out of Scope

- Google Drive API integration.
- Filtering or searching the Today panel.
- Editing or overriding a run's label after the fact.
- Changing alert logic — no new alert types introduced.
