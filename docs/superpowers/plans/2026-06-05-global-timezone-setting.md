# Global Timezone Setting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a global timezone setting to OpsPilot (stored in `app_settings`) so that the uptime 90-day bar, incident timestamps, and all other time displays roll over and format according to the configured timezone instead of hardcoded UTC.

**Architecture:** `timezone` VARCHAR column is added to the existing single-row `app_settings` table (default `'UTC'`). The backend reads it in the uptime-timeline endpoint to apply `time_bucket('1 day', time AT TIME ZONE :tz)`. The frontend fetches settings once in `AppLayout.vue` on mount (so timezone is available everywhere), then all date-formatting paths use a shared `useDateFormat` composable that reads from the settings store reactively. `UptimeTimeline.vue` uses the composable directly — no prop needed.

**Tech Stack:** Python/SQLAlchemy/Alembic (backend), TimescaleDB `time_bucket` with AT TIME ZONE, Vue 3 / Pinia (frontend), `Intl.DateTimeFormat` for browser-side formatting.

---

### Task 1: DB Migration + Settings Model

**Files:**
- Create: `backend/migrations/versions/0009_settings_timezone.py`
- Modify: `backend/app/models/other.py` (Settings class)

- [ ] **Step 1: Create the migration file**

Create `backend/migrations/versions/0009_settings_timezone.py`:

```python
"""Add timezone column to app_settings.

Revision ID: 0009_settings_timezone
Revises: 0008_service_ssl_columns
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_settings_timezone"
down_revision = "0008_service_ssl_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("timezone", sa.String(60), nullable=False, server_default="UTC"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "timezone")
```

- [ ] **Step 2: Add `timezone` field to the Settings ORM model**

In `backend/app/models/other.py`, find the `Settings` class and add after `writer_password_encrypted`:

```python
    timezone: Mapped[str] = mapped_column(String(60), nullable=False, server_default="UTC")
```

- [ ] **Step 3: Run the migration**

```bash
docker compose exec backend alembic upgrade head
```

Expected output ends with: `Running upgrade 0008_service_ssl_columns -> 0009_settings_timezone`

- [ ] **Step 4: Verify column exists**

```bash
docker compose exec backend python -c "
import asyncio
from app.database import AsyncSessionLocal
from app.models.other import Settings
from sqlalchemy import select

async def check():
    async with AsyncSessionLocal() as db:
        s = await db.scalar(select(Settings).where(Settings.id == 1))
        print('timezone:', s.timezone if s else 'no row yet')
asyncio.run(check())
"
```

Expected: `timezone: UTC`

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/0009_settings_timezone.py backend/app/models/other.py
git commit -m "feat(timezone): add timezone column to app_settings (migration 0009)"
```

---

### Task 2: Backend Schema + Settings Router

**Files:**
- Modify: `backend/app/schemas/settings.py`
- Modify: `backend/app/routers/settings.py`

- [ ] **Step 1: Add `timezone` to SettingsResponse and SettingsPatch**

In `backend/app/schemas/settings.py`, update the two classes:

```python
class SettingsResponse(BaseModel):
    instance_name: str
    base_url: str | None
    smtp_host: str | None
    smtp_port: int | None
    smtp_encryption: str
    smtp_username: str | None
    smtp_from_address: str | None
    smtp_recipients: str | None
    smtp_has_password: bool
    metrics_retention_days: int
    logs_retention_days: int
    service_checks_retention_days: int
    alerts_retention_days: int
    timezone: str


class SettingsPatch(BaseModel):
    instance_name: str | None = None
    base_url: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_encryption: str | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None
    smtp_recipients: str | None = None
    metrics_retention_days: int | None = Field(default=None, ge=7, le=365)
    logs_retention_days: int | None = Field(default=None, ge=7, le=365)
    service_checks_retention_days: int | None = Field(default=None, ge=30, le=365)
    alerts_retention_days: int | None = Field(default=None, ge=30, le=730)
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def valid_iana_tz(cls, v: str | None) -> str | None:
        if v is None:
            return v
        import zoneinfo
        try:
            zoneinfo.ZoneInfo(v)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            raise ValueError(f"'{v}' is not a valid IANA timezone name")
        return v
```

- [ ] **Step 2: Update `_to_response` in settings router**

In `backend/app/routers/settings.py`, update `_to_response`:

```python
def _to_response(s: Settings) -> SettingsResponse:
    return SettingsResponse(
        instance_name=s.instance_name,
        base_url=s.base_url,
        smtp_host=s.smtp_host,
        smtp_port=s.smtp_port,
        smtp_encryption=s.smtp_encryption,
        smtp_username=s.smtp_username,
        smtp_from_address=s.smtp_from_address,
        smtp_recipients=s.smtp_recipients,
        smtp_has_password=s.smtp_password_encrypted is not None,
        metrics_retention_days=s.metrics_retention_days,
        logs_retention_days=s.logs_retention_days,
        service_checks_retention_days=s.service_checks_retention_days,
        alerts_retention_days=s.alerts_retention_days,
        timezone=s.timezone,
    )
```

- [ ] **Step 3: Verify the GET /api/settings endpoint returns timezone**

```bash
# Get a token first
TOKEN=$(curl -s -X POST http://localhost:9090/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"clacode01@pocketdata.com.my","password":"admin"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")
curl -s http://localhost:9090/api/settings \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | grep timezone
```

Expected: `"timezone": "UTC"`

- [ ] **Step 4: Verify PATCH /api/settings with a valid timezone works**

```bash
curl -s -X PATCH http://localhost:9090/api/settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"timezone": "Asia/Kuala_Lumpur"}' | python3 -m json.tool | grep timezone
```

Expected: `"timezone": "Asia/Kuala_Lumpur"`

Reset back:
```bash
curl -s -X PATCH http://localhost:9090/api/settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"timezone": "UTC"}' > /dev/null
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/settings.py backend/app/routers/settings.py
git commit -m "feat(timezone): expose timezone in settings API (GET + PATCH with IANA validation)"
```

---

### Task 3: Uptime Timeline Endpoint — Timezone-Aware Bucketing

**Files:**
- Modify: `backend/app/routers/services.py` (the `uptime_timeline` function only)

- [ ] **Step 1: Update the uptime_timeline endpoint**

In `backend/app/routers/services.py`, replace the `uptime_timeline` function (lines ~446–481) with:

```python
@router.get("/api/services/{service_id}/uptime-timeline")
async def uptime_timeline(
    service_id: str,
    user: CurrentUser,
    days: int = Query(90, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    await _get_accessible_service(service_id, user, db)

    from app.models.other import Settings
    settings_row = await db.scalar(select(Settings).where(Settings.id == 1))
    tz = (settings_row.timezone if settings_row else None) or "UTC"

    rows = (
        await db.execute(
            text(
                "SELECT time_bucket('1 day', time AT TIME ZONE :tz)::date AS day, "
                "COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE status = 'up') AS up "
                "FROM service_checks "
                f"WHERE service_id = :sid AND time >= now() - INTERVAL '{days} days' "
                "GROUP BY day ORDER BY day ASC"
            ),
            {"sid": service_id, "tz": tz},
        )
    ).all()

    out = []
    for r in rows:
        total = r.total or 0
        up = r.up or 0
        uptime_pct = round(up / total * 100, 2) if total else 100.0
        down_minutes = total - up
        out.append(
            {
                "date": r.day.isoformat(),
                "uptime_pct": uptime_pct,
                "down_minutes": down_minutes,
            }
        )
    return out
```

- [ ] **Step 2: Verify the endpoint returns correct dates for MYT**

Set timezone to `Asia/Kuala_Lumpur`, then hit the endpoint:

```bash
curl -s -X PATCH http://localhost:9090/api/settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"timezone": "Asia/Kuala_Lumpur"}' > /dev/null

curl -s "http://localhost:9090/api/services/4716c855-82a9-4959-99b6-2ab9011c5b61/uptime-timeline?days=7" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: the date returned should be `2026-06-05` (MYT date) instead of `2026-06-04` (UTC date), since it is currently after midnight MYT.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/services.py
git commit -m "feat(timezone): uptime timeline uses org timezone for time_bucket day grouping"
```

---

### Task 4: Frontend Settings Store — Add Timezone

**Files:**
- Modify: `frontend/src/stores/settings.ts`

- [ ] **Step 1: Add `timezone` to the `general` ref and wire fetchSettings/saveGeneral**

In `frontend/src/stores/settings.ts`, update the `general` ref:

```typescript
const general = ref({ instanceName: 'OpsPilot', baseUrl: '', timezone: 'UTC' })
```

Update `fetchSettings` to read `timezone`:

```typescript
async function fetchSettings() {
  const { data } = await api.get('/api/settings')
  general.value = {
    instanceName: data.instance_name,
    baseUrl: data.base_url ?? '',
    timezone: data.timezone ?? 'UTC',
  }
  smtp.value = {
    host: data.smtp_host ?? '',
    port: data.smtp_port ?? 587,
    encryption: data.smtp_encryption,
    username: data.smtp_username ?? '',
    fromAddress: data.smtp_from_address ?? '',
    recipients: data.smtp_recipients ?? '',
    hasPassword: data.smtp_has_password,
  }
  retention.value = {
    metricsRetentionDays: data.metrics_retention_days,
    logsRetentionDays: data.logs_retention_days,
    serviceChecksRetentionDays: data.service_checks_retention_days,
    alertsRetentionDays: data.alerts_retention_days,
  }
}
```

Update `saveGeneral` signature to accept `timezone`:

```typescript
async function saveGeneral(p: { instance_name: string; base_url: string; timezone: string }) {
  await api.patch('/api/settings', p)
  await fetchSettings()
}
```

- [ ] **Step 2: Fetch settings globally in AppLayout.vue**

In `frontend/src/components/common/AppLayout.vue`, add the import:

```typescript
import { useSettingsStore } from '@/stores/settings'
```

Add near the other store calls:
```typescript
const settingsStore = useSettingsStore()
```

In the `onMounted` block, add `settingsStore.fetchSettings()` after `orgStore.fetchOrgs()`:

```typescript
onMounted(async () => {
  if (auth.isAuthenticated) {
    await orgStore.fetchOrgs()
    await settingsStore.fetchSettings()
    startWs()
  }
})
```

Also add it inside the `watch(() => auth.isAuthenticated, ...)` handler after `orgStore.fetchOrgs()`:

```typescript
watch(() => auth.isAuthenticated, async (v) => {
  if (v) {
    await orgStore.fetchOrgs()
    await settingsStore.fetchSettings()
    startWs()
  } else {
    alertStore.reset()
    stopWs()
  }
})
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/settings.ts frontend/src/components/common/AppLayout.vue
git commit -m "feat(timezone): add timezone to settings store; fetch settings globally in AppLayout"
```

---

### Task 5: Frontend Settings UI — Timezone Dropdown

**Files:**
- Modify: `frontend/src/views/settings/GeneralTab.vue`

- [ ] **Step 1: Add timezone ref and IANA timezone list**

In `GeneralTab.vue`, add inside `<script setup>` after the existing refs:

```typescript
const timezone = ref('UTC')

// Curated IANA timezone list covering the most common regions.
const TIMEZONES = [
  { value: 'UTC', label: 'UTC — Coordinated Universal Time' },
  { value: 'America/New_York', label: 'America/New_York — ET (UTC-5/-4)' },
  { value: 'America/Chicago', label: 'America/Chicago — CT (UTC-6/-5)' },
  { value: 'America/Denver', label: 'America/Denver — MT (UTC-7/-6)' },
  { value: 'America/Los_Angeles', label: 'America/Los_Angeles — PT (UTC-8/-7)' },
  { value: 'America/Sao_Paulo', label: 'America/Sao_Paulo — BRT (UTC-3)' },
  { value: 'Europe/London', label: 'Europe/London — GMT/BST (UTC+0/+1)' },
  { value: 'Europe/Paris', label: 'Europe/Paris — CET (UTC+1/+2)' },
  { value: 'Europe/Berlin', label: 'Europe/Berlin — CET (UTC+1/+2)' },
  { value: 'Europe/Moscow', label: 'Europe/Moscow — MSK (UTC+3)' },
  { value: 'Asia/Dubai', label: 'Asia/Dubai — GST (UTC+4)' },
  { value: 'Asia/Kolkata', label: 'Asia/Kolkata — IST (UTC+5:30)' },
  { value: 'Asia/Dhaka', label: 'Asia/Dhaka — BST (UTC+6)' },
  { value: 'Asia/Bangkok', label: 'Asia/Bangkok — ICT (UTC+7)' },
  { value: 'Asia/Jakarta', label: 'Asia/Jakarta — WIB (UTC+7)' },
  { value: 'Asia/Singapore', label: 'Asia/Singapore — SGT (UTC+8)' },
  { value: 'Asia/Kuala_Lumpur', label: 'Asia/Kuala_Lumpur — MYT (UTC+8)' },
  { value: 'Asia/Shanghai', label: 'Asia/Shanghai — CST (UTC+8)' },
  { value: 'Asia/Hong_Kong', label: 'Asia/Hong_Kong — HKT (UTC+8)' },
  { value: 'Asia/Tokyo', label: 'Asia/Tokyo — JST (UTC+9)' },
  { value: 'Asia/Seoul', label: 'Asia/Seoul — KST (UTC+9)' },
  { value: 'Australia/Perth', label: 'Australia/Perth — AWST (UTC+8)' },
  { value: 'Australia/Sydney', label: 'Australia/Sydney — AEST (UTC+10/+11)' },
  { value: 'Pacific/Auckland', label: 'Pacific/Auckland — NZST (UTC+12/+13)' },
]
```

- [ ] **Step 2: Populate `timezone` ref in the `load` function**

Inside the `load()` function, add after `baseUrl.value = settings.general.baseUrl`:

```typescript
timezone.value = settings.general.timezone
```

- [ ] **Step 3: Update `saveIdentity` to include timezone**

Replace the `saveIdentity` function:

```typescript
async function saveIdentity() {
  savingIdentity.value = true
  try {
    await settings.saveGeneral({
      instance_name: instanceName.value.trim() || 'OpsPilot',
      base_url: baseUrl.value.trim().replace(/\/+$/, ''),
      timezone: timezone.value,
    })
    baseUrl.value = settings.general.baseUrl
    timezone.value = settings.general.timezone
    notify.success('Settings saved.')
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to save settings.')
  } finally {
    savingIdentity.value = false
  }
}
```

- [ ] **Step 4: Add the timezone dropdown to the template**

In the template, inside the Identity `<section class="card">`, add after the Base URL `<div class="field">` block and before the amber banner:

```html
<div class="field">
  <label>Timezone</label>
  <select v-model="timezone" :disabled="loading">
    <option v-for="tz in TIMEZONES" :key="tz.value" :value="tz.value">{{ tz.label }}</option>
  </select>
  <p class="hint">All timestamps and daily uptime bars use this timezone.</p>
</div>
```

- [ ] **Step 5: Open browser and verify the dropdown appears**

Navigate to `http://localhost:9090/settings`, select **Asia/Kuala_Lumpur** from the Timezone dropdown, click **Save**, refresh the page — the dropdown should still show **Asia/Kuala_Lumpur**.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/settings/GeneralTab.vue
git commit -m "feat(timezone): add timezone dropdown to GeneralTab identity section"
```

---

### Task 6: Shared Date Format Composable

**Files:**
- Create: `frontend/src/composables/useDateFormat.ts`

- [ ] **Step 1: Create the composable**

Create `frontend/src/composables/useDateFormat.ts`:

```typescript
import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'

export function useDateFormat() {
  const settings = useSettingsStore()
  const tz = computed(() => settings.general.timezone || 'UTC')

  /** Format an ISO string as 'YYYY-MM-DD' in the org timezone. */
  function formatDate(iso: string | null | undefined): string {
    if (!iso) return '—'
    return new Intl.DateTimeFormat('en-CA', { timeZone: tz.value }).format(new Date(iso))
  }

  /** Format an ISO string as 'YYYY-MM-DD HH:mm:ss' in the org timezone. */
  function formatDateTime(iso: string | null | undefined): string {
    if (!iso) return '—'
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: tz.value,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
      .format(new Date(iso))
      .replace(',', '')
  }

  /** Get a YYYY-MM-DD date string for a Date object in the org timezone.
   *  Used by UptimeTimeline to generate day-bucket keys matching the backend. */
  function toTzDateKey(d: Date): string {
    return new Intl.DateTimeFormat('en-CA', { timeZone: tz.value }).format(d)
  }

  return { tz, formatDate, formatDateTime, toTzDateKey }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/composables/useDateFormat.ts
git commit -m "feat(timezone): add useDateFormat composable (formatDate, formatDateTime, toTzDateKey)"
```

---

### Task 7: UptimeTimeline + ServiceDetail — Use Timezone

**Files:**
- Modify: `frontend/src/components/services/UptimeTimeline.vue`
- Modify: `frontend/src/views/services/ServiceDetail.vue`

- [ ] **Step 1: Update UptimeTimeline to use `toTzDateKey` from the composable (no prop needed)**

Replace the full content of `frontend/src/components/services/UptimeTimeline.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import type { UptimePoint } from '@/stores/services'
import { useDateFormat } from '@/composables/useDateFormat'

const props = withDefaults(
  defineProps<{ points: UptimePoint[]; days?: number }>(),
  { days: 90 },
)

const { toTzDateKey } = useDateFormat()

interface Seg {
  date: string
  pct: number | null
  down: number
  tone: 'up' | 'partial' | 'down' | 'none'
}

const segments = computed<Seg[]>(() => {
  const byDate = new Map(props.points.map((p) => [p.date, p]))
  const out: Seg[] = []
  const now = new Date()
  for (let i = props.days - 1; i >= 0; i--) {
    const d = new Date(now)
    d.setDate(d.getDate() - i)
    const key = toTzDateKey(d)
    const p = byDate.get(key)
    if (!p) {
      out.push({ date: key, pct: null, down: 0, tone: 'none' })
      continue
    }
    const tone: Seg['tone'] = p.uptime_pct >= 99.9 ? 'up' : p.uptime_pct >= 95 ? 'partial' : 'down'
    out.push({ date: key, pct: p.uptime_pct, down: p.down_minutes, tone })
  }
  return out
})

const firstDate = computed(() => segments.value[0]?.date ?? '')

function tip(s: Seg): string {
  if (s.pct == null) return `${s.date} · no data`
  return `${s.date} · ${s.pct}% uptime${s.down ? ` · ${s.down}m down` : ''}`
}
</script>

<template>
  <div class="timeline">
    <div class="bar">
      <span
        v-for="s in segments"
        :key="s.date"
        class="seg"
        :class="`t-${s.tone}`"
        :title="tip(s)"
      ></span>
    </div>
    <div class="axis">
      <span>{{ firstDate }}</span>
      <span>Today</span>
    </div>
  </div>
</template>

<style scoped>
.timeline { width: 100%; }
.bar { display: flex; gap: 1px; height: 32px; align-items: stretch; }
.seg { flex: 1 1 0; min-width: 0; border-radius: 1px; transition: opacity 0.1s; }
.seg:hover { opacity: 0.7; }
.t-up { background: var(--green); }
.t-partial { background: var(--amber); }
.t-down { background: var(--red); }
.t-none { background: var(--surface-2); }
.axis { display: flex; justify-content: space-between; margin-top: 6px; font-size: 10px; color: var(--muted); font-variant-numeric: tabular-nums; }
</style>
```

- [ ] **Step 2: Update ServiceDetail.vue to use useDateFormat**

In `frontend/src/views/services/ServiceDetail.vue`, add the import at the top of `<script setup>`:

```typescript
import { useDateFormat } from '@/composables/useDateFormat'
```

Add near the other composable calls:

```typescript
const { formatDateTime } = useDateFormat()
```

Remove the local `fmtDate` function (line ~179):

```typescript
// DELETE this function entirely:
// function fmtDate(iso: string): string {
//   return new Date(iso).toISOString().replace('T', ' ').slice(0, 19)
// }
```

The `<UptimeTimeline>` tag needs no change — it reads timezone from the store via the composable internally:

```html
<UptimeTimeline :points="store.uptimeTimeline" :days="90" />
```

Update incident timestamp displays in the template — find `fmtDate(` and replace with `formatDateTime(`.

- [ ] **Step 3: Open browser and verify the uptime bar shows June 5 as "Today"**

With timezone set to `Asia/Kuala_Lumpur`:
1. Navigate to `http://localhost:9090/services/4716c855-82a9-4959-99b6-2ab9011c5b61`
2. The rightmost uptime bar tooltip should say `2026-06-05 · ...% uptime`
3. The first date label should shift to match the MYT window

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/services/UptimeTimeline.vue frontend/src/views/services/ServiceDetail.vue
git commit -m "feat(timezone): UptimeTimeline uses org timezone for day-key generation; ServiceDetail uses formatDateTime"
```

---

### Task 8: Apply Timezone Formatting Across Remaining Timestamp Displays

**Files:**
- Modify: `frontend/src/views/ssl-domains/SslDomainsView.vue`
- Modify: `frontend/src/components/cron-backup/JobDetailSlideOver.vue`

- [ ] **Step 1: Update SslDomainsView fmtDate to use useDateFormat**

In `frontend/src/views/ssl-domains/SslDomainsView.vue`:

Add import in `<script setup>`:
```typescript
import { useDateFormat } from '@/composables/useDateFormat'
```

Add near other composable calls:
```typescript
const { formatDate } = useDateFormat()
```

Find and remove the local `fmtDate` function (around line 115):
```typescript
// remove the local fmtDate function entirely
```

Replace all `fmtDate(` calls in the template with `formatDate(`.

- [ ] **Step 2: Update JobDetailSlideOver fmtDateTime to use useDateFormat**

In `frontend/src/components/cron-backup/JobDetailSlideOver.vue`:

Add import in `<script setup>`:
```typescript
import { useDateFormat } from '@/composables/useDateFormat'
```

Add near other composable calls:
```typescript
const { formatDateTime: fmtDateTime } = useDateFormat()
```

Remove the local `fmtDateTime` function that was declared there (the one at line ~63).

- [ ] **Step 3: Smoke test all affected pages**

1. `http://localhost:9090/ssl-domains` — expiry dates and last-checked timestamps should reflect MYT (e.g. `2026-06-05` not `2026-06-04`)
2. Navigate into any Cron/Backup job detail — `ran_at` timestamps should reflect MYT
3. Go back to the Services page and check a service detail — incident timestamps should be in MYT

- [ ] **Step 4: Update PROGRESS.md + DASHBOARD.html**

In `PROGRESS.md`, add a new entry for this feature under the appropriate phase.

In `DASHBOARD.html`, add a new task entry with `status: 'done'` and update `LAST_UPDATED`.

- [ ] **Step 5: Commit + push**

```bash
git add frontend/src/views/ssl-domains/SslDomainsView.vue \
        frontend/src/components/cron-backup/JobDetailSlideOver.vue \
        PROGRESS.md DASHBOARD.html
git commit -m "feat(timezone): apply org timezone to SSL domains and cron/backup timestamp displays"
git push origin main
```
