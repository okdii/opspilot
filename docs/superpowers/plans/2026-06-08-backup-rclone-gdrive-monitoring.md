# Backup rclone + GDrive Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `files_count` tracking to backup job pings, a rclone snippet generator in the job detail slide-over, and a reusable Backup tab on the server detail page — without duplicating any existing component logic.

**Architecture:** The existing `BackupJob`/`BackupRun` models and `/ping/{token}` endpoint are extended with a nullable `files_count` field. The backup Add/Edit modal is extracted from `CronBackupView.vue` into a standalone `BackupJobModal.vue`; both the `/cron-backup` page and the new server-detail `BackupTab.vue` import it. `JobRow` and `JobDetailSlideOver` are reused unchanged except for the two targeted display updates.

**Tech Stack:** Python 3.11 / SQLAlchemy / Alembic / FastAPI (backend); Vue 3 / Pinia / TypeScript (frontend); Docker Compose dev stack (`docker compose -f docker-compose.yml -f docker-compose.dev.yml`).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/migrations/versions/0015_backup_files_count.py` | Create | Alembic migration — add `files_count` to `backup_run`, `last_files_count` to `backup_job` |
| `backend/app/models/other.py` | Modify | Add ORM columns to `BackupRun` and `BackupJob` |
| `backend/app/schemas/cron_backup.py` | Modify | Add `files_count` to `BackupRunOut`, `last_files_count` to `BackupJobOut` |
| `backend/app/routers/cron_backup.py` | Modify | Parse `files_count` in ping handler; include in serializers |
| `frontend/src/stores/cronBackup.ts` | Modify | Add `last_files_count` to `BackupJob`, `files_count` to `JobRun` |
| `frontend/src/components/cron-backup/JobRow.vue` | Modify | Show `files_count` alongside size for backup jobs |
| `frontend/src/components/cron-backup/JobDetailSlideOver.vue` | Modify | rclone snippet tabs (replace generic curl block for backup); add Files column to run history |
| `frontend/src/components/cron-backup/BackupJobModal.vue` | Create | Extracted backup Add/Edit modal — accepts optional `serverId` to lock server dropdown |
| `frontend/src/views/cron-backup/CronBackupView.vue` | Modify | Swap inline backup modal for `<BackupJobModal>` |
| `frontend/src/components/servers/tabs/BackupTab.vue` | Create | Server detail Backup tab — filters store by `server_id`, renders `JobRow` + `JobDetailSlideOver` + `BackupJobModal` |
| `frontend/src/views/servers/ServerDetail.vue` | Modify | Add `'Backup'` to `TABS`, import and register `BackupTab` |

---

## Task 1: Database Migration + ORM Models

**Files:**
- Create: `backend/migrations/versions/0015_backup_files_count.py`
- Modify: `backend/app/models/other.py`

- [ ] **Step 1: Create the migration file**

```python
# backend/migrations/versions/0015_backup_files_count.py
"""Add files_count to backup_run and last_files_count to backup_job.

Revision ID: 0015_backup_files_count
Revises: 0014_db_credential_label
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_backup_files_count"
down_revision = "0014_db_credential_label"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backup_run", sa.Column("files_count", sa.Integer(), nullable=True))
    op.add_column("backup_job", sa.Column("last_files_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("backup_run", "files_count")
    op.drop_column("backup_job", "last_files_count")
```

- [ ] **Step 2: Add ORM columns to `BackupJob` and `BackupRun`**

In `backend/app/models/other.py`, find `class BackupRun` (line 258) and add after the `exit_code` column:

```python
    files_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

Find `class BackupJob` (line 237) and add after `previous_size_bytes`:

```python
    last_files_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 3: Run the migration**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend alembic upgrade head
```

Expected output ends with: `Running upgrade 0014_db_credential_label -> 0015_backup_files_count`

- [ ] **Step 4: Verify columns exist**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -d opspilot -c "\d backup_run" | grep files_count

docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -d opspilot -c "\d backup_job" | grep last_files_count
```

Expected: one line each showing the column name and `integer` type.

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/0015_backup_files_count.py backend/app/models/other.py
git commit -m "feat(backup): migration 0015 — add files_count to backup_run and backup_job"
```

---

## Task 2: Backend Schemas + Ping Handler

**Files:**
- Modify: `backend/app/schemas/cron_backup.py`
- Modify: `backend/app/routers/cron_backup.py`

- [ ] **Step 1: Add `files_count` to `BackupRunOut` schema**

In `backend/app/schemas/cron_backup.py`, update `BackupRunOut` (currently ends at line 187):

```python
class BackupRunOut(BaseModel):
    id: str
    ran_at: datetime
    size_bytes: int | None
    size_formatted: str | None
    exit_code: int | None
    outcome: str
    files_count: int | None = None
```

- [ ] **Step 2: Add `last_files_count` to `BackupJobOut` schema**

In `backend/app/schemas/cron_backup.py`, update `BackupJobOut` (currently ends at line 178):

```python
class BackupJobOut(BaseModel):
    id: str
    server_id: str
    server_name: str
    name: str
    description: str | None
    expected_interval_hours: int
    ping_url: str
    last_ping_at: datetime | None
    last_size_bytes: int | None
    last_size_formatted: str | None
    last_status_text: str | None
    previous_size_bytes: int | None
    last_files_count: int | None = None
    status: str
    next_expected_at: datetime | None
```

- [ ] **Step 3: Update `_backup_out` serializer to include `last_files_count`**

In `backend/app/routers/cron_backup.py`, find `_backup_out` (around line 163) and add `last_files_count`:

```python
def _backup_out(job: BackupJob, server_name: str, base: str) -> BackupJobOut:
    from datetime import timedelta

    last = _aware(job.last_ping_at)
    anchor = last or _aware(job.created_at) or _now()
    nxt = anchor + timedelta(hours=job.expected_interval_hours)
    return BackupJobOut(
        id=str(job.id),
        server_id=str(job.server_id),
        server_name=server_name,
        name=job.name,
        description=job.description,
        expected_interval_hours=job.expected_interval_hours,
        ping_url=_ping_url(base, job.ping_token),
        last_ping_at=last,
        last_size_bytes=job.last_size_bytes,
        last_size_formatted=_format_bytes(job.last_size_bytes),
        last_status_text=job.last_status_text,
        previous_size_bytes=job.previous_size_bytes,
        last_files_count=job.last_files_count,
        status=job.status,
        next_expected_at=nxt,
    )
```

- [ ] **Step 4: Update `_handle_backup_ping` to accept and store `files_count`**

Change the function signature (around line 292):

```python
async def _handle_backup_ping(
    db: AsyncSession,
    job: BackupJob,
    *,
    size_bytes: int,
    exit_code: int,
    status: str,
    files_count: int | None,
):
```

Inside the function, after `job.last_size_bytes = size_bytes`, add:

```python
    job.last_files_count = files_count
```

And update the `BackupRun` instantiation:

```python
    db.add(
        BackupRun(
            backup_job_id=job.id,
            ran_at=now,
            size_bytes=size_bytes,
            exit_code=exit_code,
            outcome=outcome,
            files_count=files_count,
        )
    )
```

- [ ] **Step 5: Parse `files_count` from POST body in `ping_post`**

In `ping_post` (around line 216), after the existing `_as_int` calls, add a `files_count` parser. Find the `backup = await db.scalar(...)` block and update the call to `_handle_backup_ping`:

```python
    backup = await db.scalar(select(BackupJob).where(BackupJob.ping_token == token_uuid))
    if backup is not None:
        fc_raw = form.get("files_count")
        files_count: int | None = None
        if fc_raw is not None and fc_raw != "":
            try:
                files_count = int(fc_raw)
            except (TypeError, ValueError):
                files_count = None
        return await _handle_backup_ping(
            db,
            backup,
            size_bytes=_as_int("size_bytes", 0),
            exit_code=_as_int("exit_code", 0),
            status=str(form.get("status") or "success"),
            files_count=files_count,
        )
```

- [ ] **Step 6: Update GET ping to pass `files_count=None`**

In `ping_get` (around line 210), the backup GET path:

```python
    if backup is not None:
        return await _handle_backup_ping(
            db, backup, size_bytes=0, exit_code=0, status="success", files_count=None
        )
```

- [ ] **Step 7: Update `list_backup_runs` to include `files_count` in `BackupRunOut`**

Find `list_backup_runs` (around line 555). Update the `BackupRunOut` construction:

```python
    return {
        "runs": [
            BackupRunOut(
                id=str(r.id),
                ran_at=_aware(r.ran_at),
                size_bytes=r.size_bytes,
                size_formatted=_format_bytes(r.size_bytes),
                exit_code=r.exit_code,
                outcome=r.outcome,
                files_count=r.files_count,
            )
            for r in rows
        ],
        "next_cursor": next_cursor,
    }
```

- [ ] **Step 8: Smoke test the ping endpoint**

First, get a backup job ping URL from the UI at `http://localhost:9090/cron-backup` (add a test backup job if none exists). Then send a ping:

```bash
curl -s -X POST http://localhost:9090/ping/<TOKEN> \
  -d "status=success&size_bytes=1073741824&exit_code=0&files_count=1234"
```

Expected response: `{"ok":true}`

Then check the run was recorded:

```bash
curl -s -H "Cookie: ..." http://localhost:9090/api/backup-jobs/<JOB_ID>/runs | \
  python3 -m json.tool | grep files_count
```

Expected: `"files_count": 1234`

- [ ] **Step 9: Commit**

```bash
git add backend/app/schemas/cron_backup.py backend/app/routers/cron_backup.py
git commit -m "feat(backup): accept and store files_count in backup ping endpoint"
```

---

## Task 3: Frontend Store Types

**Files:**
- Modify: `frontend/src/stores/cronBackup.ts`

- [ ] **Step 1: Add `last_files_count` to `BackupJob` interface**

Find the `BackupJob` interface (line 22) and add after `previous_size_bytes`:

```ts
export interface BackupJob {
  id: string
  server_id: string
  server_name: string
  name: string
  description: string | null
  expected_interval_hours: number
  ping_url: string
  last_ping_at: string | null
  last_size_bytes: number | null
  last_size_formatted: string | null
  last_status_text: string | null
  previous_size_bytes: number | null
  last_files_count: number | null
  status: string
  next_expected_at: string | null
}
```

- [ ] **Step 2: Add `files_count` to `JobRun` interface**

Find the `JobRun` interface (line 40) and add `files_count`:

```ts
export interface JobRun {
  id: string
  ran_at: string
  outcome: string
  duration_sec?: number | null
  size_bytes?: number | null
  size_formatted?: string | null
  exit_code?: number | null
  files_count?: number | null
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend \
  npx vue-tsc --noEmit 2>&1 | head -20
```

Expected: no errors (or only pre-existing unrelated errors).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/cronBackup.ts
git commit -m "feat(backup): add last_files_count to BackupJob and files_count to JobRun types"
```

---

## Task 4: JobRow.vue — Show `files_count` Alongside Size

**Files:**
- Modify: `frontend/src/components/cron-backup/JobRow.vue`

- [ ] **Step 1: Update `durationText` computed to include `files_count`**

Find `durationText` (line 40) and replace the backup branch:

```ts
const durationText = computed(() => {
  if (isCron.value) {
    const d = (props.job as CronJob).last_duration_sec
    if (d == null) return '—'
    if (d < 60) return `${d}s`
    const m = Math.floor(d / 60)
    const s = d % 60
    return s ? `${m}m ${s}s` : `${m}m`
  }
  const bj = props.job as BackupJob
  const size = bj.last_size_formatted ?? '—'
  if (bj.last_files_count != null) {
    return `${size} · ${bj.last_files_count.toLocaleString()} files`
  }
  return size
})
```

- [ ] **Step 2: Verify in browser**

Open `http://localhost:9090/cron-backup`, switch to **Backup Jobs** tab. After sending a ping with `files_count=1234`, the job row Size cell should read `1.00 GB · 1,234 files`. Jobs with no `files_count` show only the size (no regression).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/cron-backup/JobRow.vue
git commit -m "feat(backup): show files_count alongside size in job row"
```

---

## Task 5: JobDetailSlideOver.vue — rclone Snippet + Files Column

**Files:**
- Modify: `frontend/src/components/cron-backup/JobDetailSlideOver.vue`

- [ ] **Step 1: Add snippet tab state and computed snippets**

In the `<script setup>` block, after the `backupPostCommand` computed (line 149), add:

```ts
const snippetTab = ref<'snippet' | 'curl'>('snippet')

const rcloneSnippet = computed(() => {
  const url = pingUrl.value
  return [
    '#!/bin/bash',
    '# OpsPilot backup monitoring wrapper',
    '# Edit REMOTE and SOURCE, then replace your existing rclone call with this script.',
    '',
    'REMOTE="gdrive:YOUR_REMOTE_PATH"    # ← set your rclone remote:path',
    'SOURCE="/your/source/path"           # ← set your local source directory',
    'MAX_RETRIES=3',
    'RETRY_DELAY=60                       # seconds to wait between retries',
    '',
    '# Run rclone with auto-retry',
    'EXIT_CODE=1',
    'ATTEMPT=0',
    'while [ $ATTEMPT -lt $MAX_RETRIES ]; do',
    '  ATTEMPT=$((ATTEMPT + 1))',
    '  rclone sync "$SOURCE" "$REMOTE"',
    '  EXIT_CODE=$?',
    '  [ $EXIT_CODE -eq 0 ] && break',
    '  [ $ATTEMPT -lt $MAX_RETRIES ] && sleep $RETRY_DELAY',
    'done',
    '',
    '# Query destination size and file count',
    'JSON=$(rclone size "$REMOTE" --json 2>/dev/null)',
    "SIZE_BYTES=$(echo \"$JSON\" | grep -o '\"bytes\":[0-9]*' | grep -o '[0-9]*$')",
    "FILES_COUNT=$(echo \"$JSON\" | grep -o '\"count\":[0-9]*' | grep -o '[0-9]*$')",
    '',
    '# Ping OpsPilot — exit_code != 0 fires a backup_failure alert + email',
    `curl -s -X POST "${url}" \\`,
    '  -d "status=success&size_bytes=${SIZE_BYTES:-0}&exit_code=${EXIT_CODE}&files_count=${FILES_COUNT:-0}" \\',
    '  > /dev/null',
    '',
    'exit $EXIT_CODE',
  ].join('\n')
})

const curlOnlySnippet = computed(() => {
  const url = pingUrl.value
  return [
    '# Add these lines at the end of your backup script.',
    '# IMPORTANT: capture $? immediately after rclone, before any other command.',
    'EXIT_CODE=$?',
    'JSON=$(rclone size "gdrive:YOUR_REMOTE_PATH" --json 2>/dev/null)',
    "SIZE_BYTES=$(echo \"$JSON\" | grep -o '\"bytes\":[0-9]*' | grep -o '[0-9]*$')",
    "FILES_COUNT=$(echo \"$JSON\" | grep -o '\"count\":[0-9]*' | grep -o '[0-9]*$')",
    `curl -s -X POST "${url}" \\`,
    '  -d "status=success&size_bytes=${SIZE_BYTES:-0}&exit_code=${EXIT_CODE}&files_count=${FILES_COUNT:-0}" \\',
    '  > /dev/null',
  ].join('\n')
})

const activeSnippet = computed(() =>
  snippetTab.value === 'snippet' ? rcloneSnippet.value : curlOnlySnippet.value
)
```

- [ ] **Step 2: Replace the Ping URL block template for backup jobs**

Find the `<!-- Ping URL block -->` section (lines 208–231) and replace it:

```html
      <!-- Ping URL block -->
      <section class="block ping-block">
        <div class="block-hd">
          <h3>{{ isCron ? 'Ping URL' : 'rclone Snippet' }}</h3>
          <button v-if="canEdit" class="link-danger" @click="showRegenConfirm = true">Regenerate</button>
        </div>

        <!-- Cron: simple curl line (unchanged) -->
        <template v-if="isCron">
          <pre class="curl">{{ curlCommand }}</pre>
          <div class="ping-actions">
            <button class="btn ghost sm" @click="copy(pingUrl, 'Ping URL')">Copy URL</button>
            <button class="btn ghost sm" @click="copy(curlCommand, 'Command')">Copy Command</button>
          </div>
          <p class="hint">Append this to the end of your cron script. The UUID in the URL is the only authentication.</p>
        </template>

        <!-- Backup: rclone snippet with tab switcher -->
        <template v-else>
          <div class="snippet-tabs">
            <button
              class="stab"
              :class="{ active: snippetTab === 'snippet' }"
              @click="snippetTab = 'snippet'"
            >rclone snippet</button>
            <button
              class="stab"
              :class="{ active: snippetTab === 'curl' }"
              @click="snippetTab = 'curl'"
            >curl only</button>
          </div>
          <pre class="curl">{{ activeSnippet }}</pre>
          <div class="ping-actions">
            <button class="btn ghost sm" @click="copy(activeSnippet, 'Snippet')">Copy snippet</button>
            <button class="btn ghost sm" @click="copy(pingUrl, 'Ping URL')">Copy URL</button>
          </div>
          <p class="hint">
            Edit <code>REMOTE</code> and <code>SOURCE</code> before deploying.
            The UUID in the URL is the only authentication.
          </p>
        </template>
      </section>
```

- [ ] **Step 3: Add snippet tab styles**

In the `<style scoped>` block, add after `.hint`:

```css
.snippet-tabs { display: flex; gap: 4px; margin-bottom: 10px; }
.stab { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; color: var(--muted); font-size: 11px; padding: 4px 10px; cursor: pointer; }
.stab.active { background: rgba(99, 102, 241, 0.15); border-color: rgba(99, 102, 241, 0.4); color: var(--accent-2); }
```

- [ ] **Step 4: Add Files column to run history table**

Find the run history `<thead>` (line 265) and update:

```html
          <thead>
            <tr>
              <th>Time</th>
              <th>Outcome</th>
              <th v-if="isCron">Duration</th>
              <template v-else>
                <th>Size</th>
                <th>Files</th>
                <th>Exit</th>
              </template>
            </tr>
          </thead>
```

Find the backup run `<template v-else>` in `<tbody>` (line 284) and update:

```html
              <template v-else>
                <td>{{ r.size_formatted ?? '—' }}</td>
                <td class="num">{{ r.files_count != null ? r.files_count.toLocaleString() : '—' }}</td>
                <td>{{ r.exit_code ?? '—' }}</td>
              </template>
```

Add the `.num` style in `<style scoped>`:

```css
.num { text-align: right; font-variant-numeric: tabular-nums; }
```

- [ ] **Step 5: Verify in browser**

Open `http://localhost:9090/cron-backup` → Backup Jobs tab → click a job to open the slide-over.
- Ping URL block should show two tabs: **rclone snippet** (default) and **curl only**
- Switching tabs changes the code block content
- **Copy snippet** button copies to clipboard
- Run history table should have a **Files** column showing `1,234` or `—`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/cron-backup/JobDetailSlideOver.vue
git commit -m "feat(backup): rclone snippet generator and files_count column in slide-over"
```

---

## Task 6: BackupJobModal.vue — New Shared Component

**Files:**
- Create: `frontend/src/components/cron-backup/BackupJobModal.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useServerStore } from '@/stores/server'
import { useCronBackupStore } from '@/stores/cronBackup'
import type { BackupJob, BackupJobPayload } from '@/stores/cronBackup'
import { useNotify } from '@/composables/useNotify'

const props = defineProps<{
  job: BackupJob | null        // null = create mode
  serverId?: string            // if set: pre-fills and locks the server dropdown
}>()

const emit = defineEmits<{
  (e: 'saved', job: BackupJob): void
  (e: 'close'): void
}>()

const serverStore = useServerStore()
const store = useCronBackupStore()
const notify = useNotify()

const INTERVAL_OPTIONS = [1, 6, 12, 24, 48, 168, 720]
const intervalLabel = (h: number) =>
  h < 24 ? `${h} hour${h > 1 ? 's' : ''}` : h === 24 ? 'Daily (24h)' : h === 168 ? 'Weekly (168h)' : `${h} hours`

const form = ref({
  server_id: '',
  name: '',
  expected_interval_hours: 24,
  description: '',
})
const errors = ref<Record<string, string>>({})
const submitting = ref(false)

const editMode = computed(() => props.job != null)

const lockedServer = computed(() =>
  props.serverId
    ? serverStore.servers.find((s) => s.id === props.serverId)
    : null
)

function reset(): void {
  errors.value = {}
  if (props.job) {
    form.value = {
      server_id: props.job.server_id,
      name: props.job.name,
      expected_interval_hours: props.job.expected_interval_hours,
      description: props.job.description ?? '',
    }
  } else {
    form.value = {
      server_id: props.serverId ?? serverStore.servers[0]?.id ?? '',
      name: '',
      expected_interval_hours: 24,
      description: '',
    }
  }
}

watch(() => [props.job, props.serverId], reset, { immediate: true })

function validate(): boolean {
  errors.value = {}
  if (!form.value.server_id) errors.value.server_id = 'Select a server'
  const n = form.value.name.trim()
  if (n.length < 2 || n.length > 100) errors.value.name = 'Name must be 2–100 characters'
  return Object.keys(errors.value).length === 0
}

async function submit(): Promise<void> {
  if (!validate()) return
  submitting.value = true
  try {
    const payload: BackupJobPayload = {
      server_id: form.value.server_id,
      name: form.value.name.trim(),
      expected_interval_hours: form.value.expected_interval_hours,
      description: form.value.description.trim() || null,
    }
    let saved: BackupJob
    if (editMode.value && props.job) {
      saved = await store.updateBackupJob(props.job.id, payload)
      notify.success('Backup job updated')
    } else {
      saved = await store.createBackupJob(payload)
      notify.success('Backup job created')
    }
    emit('saved', saved)
  } catch (err) {
    const msg = (err as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail?.message
    errors.value._form = msg ?? 'Could not save the job.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal">
      <div class="modal-hdr">
        <h2>{{ editMode ? 'Edit' : 'Add' }} Backup Job</h2>
        <button class="close" @click="emit('close')">✕</button>
      </div>

      <form @submit.prevent="submit">
        <label>Server *</label>
        <select
          v-if="!lockedServer"
          v-model="form.server_id"
          :class="{ invalid: errors.server_id }"
        >
          <option v-for="s in serverStore.servers" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <input v-else :value="lockedServer.name" disabled class="locked" />
        <div v-if="errors.server_id" class="err">{{ errors.server_id }}</div>

        <label>Job Name *</label>
        <input v-model="form.name" placeholder="e.g. gdrive-nightly" :class="{ invalid: errors.name }" />
        <div v-if="errors.name" class="err">{{ errors.name }}</div>

        <label>Expected Interval</label>
        <select v-model.number="form.expected_interval_hours">
          <option v-for="h in INTERVAL_OPTIONS" :key="h" :value="h">{{ intervalLabel(h) }}</option>
        </select>

        <label>Description</label>
        <input v-model="form.description" placeholder="Optional notes" />

        <div v-if="errors._form" class="err">{{ errors._form }}</div>

        <div class="actions">
          <button type="button" class="btn ghost" @click="emit('close')">Cancel</button>
          <button type="submit" class="primary" :disabled="submitting">
            {{ submitting ? 'Saving…' : editMode ? 'Save Changes' : 'Create Job' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
.modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; width: 100%; max-width: 520px; max-height: 90vh; overflow-y: auto; }
.modal-hdr { padding: 18px 22px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
.modal-hdr h2 { font-size: 15px; color: #fff; }
.close { background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; }
form { padding: 20px 22px; }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; margin-top: 14px; }
input, select { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 13px; outline: none; font-family: inherit; }
input:focus, select:focus { border-color: var(--accent); }
input.invalid, select.invalid { border-color: var(--red); }
input.locked { opacity: 0.6; cursor: not-allowed; }
.err { color: var(--red); font-size: 11px; margin-top: 6px; }
.actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 22px; padding-top: 14px; border-top: 1px solid var(--border); }
.primary { padding: 9px 18px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.btn { padding: 8px 16px; border-radius: 8px; font-size: 12px; cursor: pointer; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); }
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
</style>
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend \
  npx vue-tsc --noEmit 2>&1 | head -20
```

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/cron-backup/BackupJobModal.vue
git commit -m "feat(backup): extract BackupJobModal as shared component"
```

---

## Task 7: CronBackupView.vue — Swap Inline Backup Modal

**Files:**
- Modify: `frontend/src/views/cron-backup/CronBackupView.vue`

- [ ] **Step 1: Import BackupJobModal**

At the top of `<script setup>` (after the existing imports), add:

```ts
import BackupJobModal from '@/components/cron-backup/BackupJobModal.vue'
```

- [ ] **Step 2: Remove backup-specific form state that is now owned by BackupJobModal**

`BackupJobModal` now owns `expected_interval_hours` and `description` internally. The shared `form` ref in `CronBackupView` only needs to serve the cron job modal. Remove these lines from the `form` ref definition (around line 83):

```ts
// Remove these two fields from the form ref:
//   expected_interval_hours: 24,
//   description: '',
```

Update the `form` ref to:

```ts
const form = ref({
  server_id: '',
  name: '',
  schedule: '0 * * * *',
  grace_period_min: 10,
})
```

- [ ] **Step 3: Simplify `resetForm` and `openEdit` for backup branch**

`resetForm` no longer needs `expected_interval_hours`/`description`. Update it:

```ts
function resetForm(): void {
  form.value = {
    server_id: serverStore.servers[0]?.id ?? '',
    name: '',
    schedule: '0 * * * *',
    grace_period_min: 10,
  }
  errors.value = {}
}
```

For `openEdit`, the backup branch no longer sets cron-only fields — remove the backup branch from `openEdit` entirely. BackupJobModal receives `job` as a prop and handles its own population.

Update `openEdit`:

```ts
function openEdit(job: CronJob | BackupJob): void {
  editMode.value = true
  editingId.value = job.id
  errors.value = {}
  openMenuId.value = null
  if (tab.value === 'cron') {
    const j = job as CronJob
    form.value = {
      server_id: j.server_id,
      name: j.name,
      schedule: j.schedule,
      grace_period_min: j.grace_period_min,
    }
    showModal.value = true
  } else {
    // BackupJobModal handles its own state — just open it
    showModal.value = true
  }
}
```

- [ ] **Step 4: Add computed ref for the backup job being edited**

Add after `editingId`:

```ts
const editingBackupJob = computed<BackupJob | null>(() => {
  if (tab.value !== 'backup' || !editingId.value) return null
  return store.backupJobs.find((j) => j.id === editingId.value) ?? null
})
```

- [ ] **Step 5: Replace the inline modal template with conditional rendering**

Find the `<!-- Add / Edit modal -->` section (around line 293) and replace it:

```html
    <!-- Add / Edit modal — Cron -->
    <div v-if="showModal && tab === 'cron'" class="modal-overlay" @click.self="showModal = false">
      <div class="modal">
        <div class="modal-hdr">
          <h2>{{ editMode ? 'Edit' : 'Add' }} Cron Job</h2>
          <button class="close" @click="showModal = false">✕</button>
        </div>

        <form @submit.prevent="submit">
          <label>Server *</label>
          <select v-model="form.server_id" :class="{ invalid: errors.server_id }">
            <option v-for="s in serverStore.servers" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
          <div v-if="errors.server_id" class="err">{{ errors.server_id }}</div>

          <label>Job Name *</label>
          <input v-model="form.name" placeholder="e.g. database-backup" :class="{ invalid: errors.name }" />
          <div v-if="errors.name" class="err">{{ errors.name }}</div>

          <label>Schedule (cron expression) *</label>
          <input v-model="form.schedule" placeholder="0 * * * *" class="mono" :class="{ invalid: errors.schedule }" />
          <div class="preview" :class="{ bad: !schedulePreview.valid }">
            {{ schedulePreview.valid ? `Runs: ${schedulePreview.label}` : 'Invalid cron expression' }}
          </div>
          <div v-if="errors.schedule" class="err">{{ errors.schedule }}</div>

          <label>Grace Period</label>
          <select v-model.number="form.grace_period_min">
            <option v-for="g in GRACE_OPTIONS" :key="g" :value="g">{{ gracePresetLabel(g) }}</option>
          </select>

          <div v-if="errors._form" class="err">{{ errors._form }}</div>

          <div class="actions">
            <button type="button" class="btn ghost" @click="showModal = false">Cancel</button>
            <button type="submit" class="primary" :disabled="submitting">
              {{ submitting ? 'Saving…' : editMode ? 'Save Changes' : 'Create Job' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Add / Edit modal — Backup (delegated to BackupJobModal) -->
    <BackupJobModal
      v-if="showModal && tab === 'backup'"
      :job="editingBackupJob"
      @saved="showModal = false"
      @close="showModal = false"
    />
```

- [ ] **Step 6: Remove the now-unused `submit` function's backup branch and related code**

The `submit` function's `else` branch (backup job creation/update) is no longer needed since `BackupJobModal` handles its own submission. Remove the `else` block from `submit`:

```ts
async function submit(): Promise<void> {
  if (!validate()) return
  submitting.value = true
  try {
    const payload: CronJobPayload = {
      server_id: form.value.server_id,
      name: form.value.name.trim(),
      schedule: form.value.schedule.trim(),
      grace_period_min: form.value.grace_period_min,
    }
    if (editMode.value && editingId.value) {
      await store.updateCronJob(editingId.value, payload)
      notify.success('Cron job updated')
    } else {
      await store.createCronJob(payload)
      notify.success('Cron job created')
    }
    showModal.value = false
  } catch (err) {
    const msg = (err as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail?.message
    errors.value._form = msg ?? 'Could not save the job.'
  } finally {
    submitting.value = false
  }
}
```

Also remove `INTERVAL_OPTIONS` and `intervalLabel` constants (now owned by `BackupJobModal`).

- [ ] **Step 7: Smoke test `/cron-backup`**

Open `http://localhost:9090/cron-backup`.
- Cron Jobs tab → **+ Add Cron Job** → modal opens, fills in, saves → new cron job appears.
- Backup Jobs tab → **+ Add Backup Job** → `BackupJobModal` opens, fills in, saves → new backup job appears.
- Edit a backup job → modal pre-fills with existing values → save updates in place.
- No console errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/cron-backup/CronBackupView.vue
git commit -m "refactor(cron-backup): use BackupJobModal for backup add/edit — remove inline backup form"
```

---

## Task 8: BackupTab.vue — Server Detail Tab

**Files:**
- Create: `frontend/src/components/servers/tabs/BackupTab.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useOrgStore } from '@/stores/org'
import { useCronBackupStore } from '@/stores/cronBackup'
import type { BackupJob } from '@/stores/cronBackup'
import { useNotify } from '@/composables/useNotify'
import { EmptyState } from '@/components/ui'
import JobRow from '@/components/cron-backup/JobRow.vue'
import JobDetailSlideOver from '@/components/cron-backup/JobDetailSlideOver.vue'
import BackupJobModal from '@/components/cron-backup/BackupJobModal.vue'

const route = useRoute()
const orgStore = useOrgStore()
const store = useCronBackupStore()
const notify = useNotify()

const serverId = computed(() => route.params.id as string)
const canEdit = computed(() => orgStore.canEdit)
const openMenuId = ref<string | null>(null)

// Jobs for this server only, inheriting sort order from the store getter.
const jobs = computed(() =>
  store.sortedBackupJobs.filter((j) => j.server_id === serverId.value)
)

// Load if the store is empty (e.g., arrived directly on this tab).
onMounted(async () => {
  if (!store.backupJobs.length && orgStore.activeOrgId) {
    await store.fetchBackupJobs(orgStore.activeOrgId)
  }
})

// Re-fetch when org changes.
watch(
  () => orgStore.activeOrgId,
  async (orgId) => {
    if (orgId) await store.fetchBackupJobs(orgId)
  },
)

// ── Detail slide-over ────────────────────────────────────────────────────────
const detailOpen = ref(false)
const detailJob = ref<BackupJob | null>(null)

function openDetail(job: BackupJob): void {
  detailJob.value = job
  detailOpen.value = true
  openMenuId.value = null
}

// Keep slide-over in sync after edits.
watch(
  () => store.backupJobs,
  () => {
    if (!detailJob.value) return
    const fresh = store.backupJobs.find((j) => j.id === detailJob.value!.id)
    if (fresh) detailJob.value = fresh
  },
  { deep: true },
)

// ── Add / Edit modal ─────────────────────────────────────────────────────────
const showModal = ref(false)
const editingJob = ref<BackupJob | null>(null)

function openAdd(): void {
  editingJob.value = null
  showModal.value = true
  openMenuId.value = null
}

function openEdit(job: BackupJob): void {
  editingJob.value = job
  showModal.value = true
  openMenuId.value = null
}

// ── Delete ───────────────────────────────────────────────────────────────────
async function remove(job: BackupJob): Promise<void> {
  openMenuId.value = null
  if (!window.confirm(`Delete "${job.name}"? This permanently removes its run history and stops the ping URL.`)) return
  try {
    await store.deleteBackupJob(job.id)
    notify.success('Job deleted')
    if (detailJob.value?.id === job.id) detailOpen.value = false
  } catch {
    notify.error('Could not delete the job.')
  }
}
</script>

<template>
  <div class="backup-tab" @click="openMenuId = null">
    <div class="tab-hdr">
      <span class="tab-title">Backup Jobs <span class="count">{{ jobs.length }}</span></span>
      <button v-if="canEdit" class="primary" @click="openAdd">+ Add Backup Job</button>
    </div>

    <div v-if="store.isLoadingList && !jobs.length" class="state-note">Loading…</div>

    <EmptyState
      v-else-if="!jobs.length"
      title="No backup jobs for this server"
      message="Track your rclone backups by adding a heartbeat check. OpsPilot alerts you if a job is missed or fails."
    >
      <template #action>
        <button v-if="canEdit" class="primary" @click="openAdd">+ Add Backup Job</button>
      </template>
    </EmptyState>

    <div v-else class="job-list">
      <JobRow
        v-for="job in jobs"
        :key="job.id"
        :job="job"
        type="backup"
        :can-edit="canEdit"
        :menu-open="openMenuId === job.id"
        @detail="openDetail(job)"
        @edit="openEdit(job)"
        @delete="remove(job)"
        @toggle-menu="openMenuId = openMenuId === job.id ? null : job.id"
      />
    </div>

    <JobDetailSlideOver
      v-model="detailOpen"
      :job="detailJob"
      type="backup"
      :can-edit="canEdit"
      @edit="detailJob && openEdit(detailJob)"
    />

    <BackupJobModal
      v-if="showModal"
      :job="editingJob"
      :server-id="serverId"
      @saved="showModal = false"
      @close="showModal = false"
    />
  </div>
</template>

<style scoped>
.backup-tab { padding: 4px 0; }
.tab-hdr { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.tab-title { font-size: 13px; font-weight: 600; color: var(--text); }
.count { background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; padding: 1px 8px; font-size: 11px; margin-left: 8px; font-variant-numeric: tabular-nums; }
.state-note { color: var(--muted); padding: 40px 0; text-align: center; font-size: 13px; }
.job-list { display: flex; flex-direction: column; gap: 10px; }
.primary { padding: 8px 16px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; border-radius: 8px; font-weight: 600; font-size: 12px; cursor: pointer; }
</style>
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend \
  npx vue-tsc --noEmit 2>&1 | head -20
```

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/servers/tabs/BackupTab.vue
git commit -m "feat(servers): add BackupTab component for server detail page"
```

---

## Task 9: ServerDetail.vue — Wire in Backup Tab

**Files:**
- Modify: `frontend/src/views/servers/ServerDetail.vue`

- [ ] **Step 1: Import BackupTab**

Add after the `MonitoringTab` import (line 18):

```ts
import BackupTab from '@/components/servers/tabs/BackupTab.vue'
```

- [ ] **Step 2: Add `'Backup'` to the TABS array**

Find line 43:

```ts
const TABS = ['Info', 'Overview', 'CPU', 'Memory', 'Disk', 'Network', 'System', 'Processes', 'Services', 'Monitoring', 'Alerts', 'Logs'] as const
```

Update to:

```ts
const TABS = ['Info', 'Overview', 'CPU', 'Memory', 'Disk', 'Network', 'System', 'Processes', 'Services', 'Monitoring', 'Alerts', 'Logs', 'Backup'] as const
```

- [ ] **Step 3: Add BackupTab to TAB_COMPONENTS**

Find lines 45–49:

```ts
const TAB_COMPONENTS = {
  Info: InfoTab, Overview: OverviewTab, CPU: CpuTab, Memory: MemoryTab,
  Disk: DiskTab, Network: NetworkTab, System: SystemTab, Processes: ProcessesTab,
  Services: ServicesTab, Monitoring: MonitoringTab, Alerts: AlertsTab, Logs: LogsTab,
}
```

Update to:

```ts
const TAB_COMPONENTS = {
  Info: InfoTab, Overview: OverviewTab, CPU: CpuTab, Memory: MemoryTab,
  Disk: DiskTab, Network: NetworkTab, System: SystemTab, Processes: ProcessesTab,
  Services: ServicesTab, Monitoring: MonitoringTab, Alerts: AlertsTab, Logs: LogsTab,
  Backup: BackupTab,
}
```

- [ ] **Step 4: Smoke test the Backup tab**

Open `http://localhost:9090/servers/<any-server-id>`. Scroll right in the tab bar — **Backup** tab should appear at the end.

Click **Backup**:
- If no backup jobs for this server → empty state with "+ Add Backup Job" CTA
- Click "+ Add Backup Job" → `BackupJobModal` opens with server dropdown locked (showing this server's name)
- Fill in name + interval → Create → job appears in the list
- Click job row → `JobDetailSlideOver` opens with rclone snippet
- **⋮ → Delete** → confirmation → job removed

- [ ] **Step 5: Verify `/cron-backup` still works**

Navigate to `http://localhost:9090/cron-backup` — both tabs should work, backup jobs created from the server detail tab appear here too (same store).

- [ ] **Step 6: Commit + push**

```bash
git add frontend/src/views/servers/ServerDetail.vue
git commit -m "feat(servers): add Backup tab to server detail page"
git push origin main
```

---

## Self-Review Checklist

**Spec coverage:**
- §1 Data model (`files_count`, `last_files_count`) → Task 1 ✓
- §2 Ping endpoint (`files_count` parse + store) → Task 2 ✓
- §3 rclone snippet with retry loop → Task 5 ✓
- §3.3 curl-only tab → Task 5 ✓
- §4.1 Job row `files_count` display → Task 4 ✓
- §4.2 Run history Files column → Task 5 ✓
- §5 Server detail Backup tab → Tasks 6–9 ✓
- §5.3 BackupJobModal with locked server → Task 6 ✓
- §5.5 ServerDetail.vue wiring → Task 9 ✓

**No placeholders:** All steps contain exact code. ✓

**Type consistency:**
- `BackupJob.last_files_count: number | null` defined in Task 3, used in Task 4. ✓
- `JobRun.files_count?: number | null` defined in Task 3, used in Task 5. ✓
- `BackupJobModal` props `job: BackupJob | null`, `serverId?: string` defined in Task 6, used identically in Tasks 7 and 8. ✓
- `_handle_backup_ping(... files_count: int | None)` signature updated in Task 2, called with `files_count=None` in GET path in same task. ✓
