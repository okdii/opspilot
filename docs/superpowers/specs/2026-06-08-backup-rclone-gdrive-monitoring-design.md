# Backup Job Monitoring — rclone + GDrive Enhancement

**Date:** 2026-06-08
**Status:** Approved
**Feature:** Option B — Smart rclone script generator with `files_count` tracking

---

## Context

The admin runs rsync-style backup scripts via `rclone sync` on 10+ servers, each uploading to Google Drive on a system cron schedule. The Cron & Backup page (`/cron-backup`) and its backend (spec 09) are already implemented. This spec adds:

1. A `files_count` field to capture the number of files in the backup destination per run.
2. An enhanced ping endpoint that accepts `files_count` from the script.
3. A **rclone wrapper snippet generator** in the job detail slide-over so admins can copy a ready-to-use bash snippet per server.
4. UI updates to display `files_count` alongside size in the job row and run history.

No changes to the watchdog, alert logic, heatmap, or job creation form.

---

## 1. Data Model

### 1.1 Migration: `0015_backup_files_count`

**`backup_runs`** — add column:
```sql
ALTER TABLE backup_runs ADD COLUMN files_count INTEGER NULL;
```

**`backup_jobs`** — add column:
```sql
ALTER TABLE backup_jobs ADD COLUMN last_files_count INTEGER NULL;
```

Both columns are nullable. Existing rows remain NULL and display as `—` in the UI. No backfill needed.

### 1.2 SQLAlchemy Model Changes

`BackupRun` model — add:
```python
files_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

`BackupJob` model — add:
```python
last_files_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

---

## 2. Backend — Ping Endpoint Enhancement

### 2.1 `POST /ping/{token}` — New Optional Field

The existing backup ping handler (`_handle_backup_ping`) gains a `files_count` parameter:

**Request body (form-encoded):**
```
status=success&size_bytes=4551231488&exit_code=0&files_count=1234
```

- `files_count` is optional. If absent or non-integer, defaults to `None`.
- Existing scripts without `files_count` continue to work unchanged.

**Handler changes:**
- Parse `files_count` from form body alongside existing fields.
- Store `files_count` on the new `BackupRun` row.
- Update `BackupJob.last_files_count = files_count` on every successful ping (same pattern as `last_size_bytes`).
- `files_count` is stored regardless of outcome (success or failed) — it reflects what was observed at ping time.

### 2.2 Schema Changes

`BackupRunOut` — add:
```python
files_count: int | None = None
```

`BackupJobOut` — add:
```python
last_files_count: int | None = None
```

`_backup_out()` serializer — include `last_files_count=job.last_files_count`.

---

## 3. rclone Snippet Generator

### 3.1 Location

The **Ping URL block** inside `JobDetailSlideOver.vue` is enhanced for backup jobs. Instead of showing a generic `curl` line, it shows a tabbed block:

| Tab | Content |
|---|---|
| **rclone snippet** (default) | Full bash wrapper (see §3.2) |
| **curl only** | Just the curl ping line for manual append |

The tab selection is client-side state, not persisted.

### 3.2 rclone Wrapper Snippet

```bash
#!/bin/bash
# OpsPilot backup monitoring wrapper
# Edit REMOTE and SOURCE, then replace your existing rclone call with this script.

REMOTE="gdrive:YOUR_REMOTE_PATH"    # ← set your rclone remote:path
SOURCE="/your/source/path"           # ← set your local source directory

# Run rclone sync
rclone sync "$SOURCE" "$REMOTE"
EXIT_CODE=$?

# Query destination size and file count
JSON=$(rclone size "$REMOTE" --json 2>/dev/null)
SIZE_BYTES=$(echo "$JSON" | grep -o '"bytes":[0-9]*' | grep -o '[0-9]*$')
FILES_COUNT=$(echo "$JSON" | grep -o '"count":[0-9]*' | grep -o '[0-9]*$')

# Ping OpsPilot
curl -s -X POST "__PING_URL__" \
  -d "status=success&size_bytes=${SIZE_BYTES:-0}&exit_code=${EXIT_CODE}&files_count=${FILES_COUNT:-0}" \
  > /dev/null

exit $EXIT_CODE
```

**Notes:**
- `__PING_URL__` is substituted server-side with the real ping URL before sending to the frontend. The frontend never constructs this URL itself.
- `rclone size --json` returns `{"count": N, "bytes": M}` — no Python or jq dependency.
- `${SIZE_BYTES:-0}` and `${FILES_COUNT:-0}` guard against empty strings if `rclone size` fails.
- `exit $EXIT_CODE` preserves the rclone exit code so cron/mail-on-error still works.
- The script does NOT pipe rclone stdout/stderr — the admin's existing logging setup is unchanged.

### 3.3 "curl only" Tab Content

For admins who want to append monitoring to an existing script without replacing it:

```bash
# Add these lines at the end of your existing backup script:
JSON=$(rclone size "gdrive:YOUR_REMOTE_PATH" --json 2>/dev/null)
SIZE_BYTES=$(echo "$JSON" | grep -o '"bytes":[0-9]*' | grep -o '[0-9]*$')
FILES_COUNT=$(echo "$JSON" | grep -o '"count":[0-9]*' | grep -o '[0-9]*$')

curl -s -X POST "__PING_URL__" \
  -d "status=success&size_bytes=${SIZE_BYTES:-0}&exit_code=$?&files_count=${FILES_COUNT:-0}" \
  > /dev/null
```

**Note:** `$?` must be captured before calling `rclone size` if using the curl-only approach. The UI shows a callout: _"Capture `$?` immediately after rclone runs, before any other command."_

### 3.4 Copy Buttons

- **"Copy snippet"** button — copies the full rclone wrapper to clipboard
- **"Copy curl"** button — copies just the curl line (active tab dependent)

Both use the existing `navigator.clipboard.writeText()` pattern already used in the slide-over.

---

## 4. UI Display Updates

### 4.1 Job Row (`JobRow.vue`)

The size/duration cell currently shows: `1.2 GB`

Updated to show (when `last_files_count` is not null): `1.2 GB · 1,234 files`

Format: `formatBytes(last_size_bytes) + ' · ' + last_files_count.toLocaleString() + ' files'`

When `last_files_count` is null: show only `1.2 GB` (no change from current).

### 4.2 Run History Table (`JobDetailSlideOver.vue`)

The backup run history table gains a **Files** column:

| Time | Outcome | Size | Files | Exit Code |
|---|---|---|---|---|
| 2026-06-08 02:01 | ✓ Success | 4.23 GB | 1,234 | 0 |
| 2026-06-07 02:00 | ✓ Success | 4.18 GB | 1,228 | 0 |
| 2026-06-06 02:01 | ✕ Failed | — | — | 1 |

- `files_count` null → display `—`
- Column header: `Files`
- Right-aligned, tabular numerals

### 4.3 Size Trend Chart

No changes. Adding files_count as a secondary axis would clutter the chart. Deferred to future enhancement if needed.

---

## 5. Edge Cases

| Case | Behaviour |
|---|---|
| `rclone size` fails (network timeout, auth error) | `SIZE_BYTES` and `FILES_COUNT` fall back to `0` via `:-0`; ping still fires; size-zero alert may fire if `exit_code=0` and size is 0 |
| Script runs but rclone had partial failure (exit_code != 0) | Ping fires with `exit_code=$EXIT_CODE`; outcome = `failed`; backup_failure alert fires |
| `files_count` absent from ping (old script) | `files_count = None`; displayed as `—`; no alert |
| Destination grows to millions of files | `rclone size` may be slow; this runs after the sync so it doesn't block the backup itself |
| Admin uses `rclone copy` instead of `rclone sync` | Snippet works unchanged — `REMOTE` in `rclone size` still queries the destination |
| Admin has multiple rclone remotes | Each server registers one backup job; snippet is generated per job with the correct ping URL |

---

## 6. What Is NOT Changed

- `BackupJob` creation form — no new fields
- Watchdog logic — no changes
- Alert types and thresholds — no changes
- Cron Jobs tab — no changes
- Calendar heatmap — no changes
- `GET /ping/{token}` (used by some tools) — no changes

---

## 7. Files Changed

| File | Change |
|---|---|
| `backend/app/migrations/0015_backup_files_count.py` | New migration |
| `backend/app/models/other.py` | Add `files_count` to `BackupRun`, `last_files_count` to `BackupJob` |
| `backend/app/routers/cron_backup.py` | Parse `files_count` in ping handler, include in serializers |
| `backend/app/schemas/cron_backup.py` | Add `files_count` to `BackupRunOut` and `BackupJobOut` |
| `frontend/src/stores/cronBackup.ts` | Add `files_count` / `last_files_count` to types |
| `frontend/src/components/cron-backup/JobDetailSlideOver.vue` | Replace ping URL block with rclone snippet generator tabs |
| `frontend/src/components/cron-backup/JobRow.vue` | Show `files_count` alongside size in job row |
