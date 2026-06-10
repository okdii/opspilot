# Notification Settings Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an SMTP enable/disable toggle and a "Send Test Notification" button for Discord to the settings page.

**Architecture:** `smtp_enabled` is a new boolean column on `app_settings` (default TRUE) checked in `alert_email.py` before sending. The Discord test endpoint mirrors the existing `POST /api/settings/smtp/test` pattern — it POSTs a blurple test embed to the configured webhook and returns ok/error. Both features are wired through the existing settings schema, store, and GeneralTab UI.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, httpx, Vue 3, Pinia, TypeScript

---

### Task 1: Migration — Add smtp_enabled Column

**Files:**
- Create: `backend/migrations/versions/0021_smtp_enabled.py`

- [ ] **Step 1: Create the migration file**

```python
# backend/migrations/versions/0021_smtp_enabled.py
"""Add smtp_enabled column to app_settings

Revision ID: 0021_smtp_enabled
Revises: 0020_discord_settings
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0021_smtp_enabled"
down_revision = "0020_discord_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("smtp_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "smtp_enabled")
```

- [ ] **Step 2: Run the migration**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend alembic upgrade head
```

Expected output: `Running upgrade 0020_discord_settings -> 0021_smtp_enabled, Add smtp_enabled column to app_settings`

- [ ] **Step 3: Verify column exists**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres psql -U opspilot -d opspilot -c "\d app_settings" | grep smtp_enabled
```

Expected: ` smtp_enabled | boolean | not null | true`

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/versions/0021_smtp_enabled.py
git commit -m "feat: add smtp_enabled migration"
```

---

### Task 2: Update Settings ORM Model

**Files:**
- Modify: `backend/app/models/other.py`

- [ ] **Step 1: Add `smtp_enabled` to the `Settings` class**

In `backend/app/models/other.py`, find the `Settings` class (at the bottom of the file). After the `timezone` field and before the `discord_webhook_url` field, insert:

```python
    smtp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
```

The Settings class fields should now read:
```
...
timezone
smtp_enabled    ← new
discord_webhook_url
discord_enabled
```

- [ ] **Step 2: Restart backend and verify no errors**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend --tail=20
```

Expected: `Application startup complete.` with no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/other.py
git commit -m "feat: add smtp_enabled to Settings ORM model"
```

---

### Task 3: Guard Email Sending With smtp_enabled

**Files:**
- Modify: `backend/app/services/alert_email.py`

- [ ] **Step 1: Add smtp_enabled guard in `send_alert_email`**

In `backend/app/services/alert_email.py`, find `send_alert_email` (line 187). After the `if s is None:` block (line 202–204) and before `recipients = parse_recipients(...)` (line 206), insert:

```python
    if not s.smtp_enabled:
        return False
```

The updated function body should read:

```python
    try:
        s = await db.scalar(select(Settings).where(Settings.id == 1))
    except Exception:  # noqa: BLE001
        logger.warning("alert email skipped: could not load settings", exc_info=True)
        return False
    if s is None:
        logger.warning("alert email skipped: no settings row")
        return False

    if not s.smtp_enabled:
        return False

    recipients = parse_recipients(s.smtp_recipients)
    base_url = s.base_url or "http://localhost"
    ...
```

- [ ] **Step 2: Restart backend and verify no errors**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend --tail=20
```

Expected: `Application startup complete.`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/alert_email.py
git commit -m "feat: guard alert email with smtp_enabled flag"
```

---

### Task 4: Expose smtp_enabled in Settings Schema and Router

**Files:**
- Modify: `backend/app/schemas/settings.py`
- Modify: `backend/app/routers/settings.py`

- [ ] **Step 1: Add `smtp_enabled` to `SettingsResponse` in schemas/settings.py**

After the `smtp_has_password: bool` field (line 15), add:

```python
    smtp_enabled: bool
```

- [ ] **Step 2: Add `smtp_enabled` to `SettingsPatch` in schemas/settings.py**

After the `smtp_recipients: str | None = None` field, add:

```python
    smtp_enabled: bool | None = None
```

- [ ] **Step 3: Add `smtp_enabled` to `_to_response` in routers/settings.py**

In the `_to_response` function, after `smtp_has_password=s.smtp_password_encrypted is not None`, add:

```python
        smtp_enabled=s.smtp_enabled,
```

Full updated `_to_response`:

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
        smtp_enabled=s.smtp_enabled,
        metrics_retention_days=s.metrics_retention_days,
        logs_retention_days=s.logs_retention_days,
        service_checks_retention_days=s.service_checks_retention_days,
        alerts_retention_days=s.alerts_retention_days,
        timezone=s.timezone,
        discord_webhook_url=s.discord_webhook_url,
        discord_enabled=s.discord_enabled,
    )
```

- [ ] **Step 4: Smoke test the settings endpoint**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend --tail=5
```

Expected: `Application startup complete.` — schema validation will fail at startup if there's a mismatch.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/settings.py backend/app/routers/settings.py
git commit -m "feat: expose smtp_enabled in settings schema and router"
```

---

### Task 5: Add Test Discord Endpoint

**Files:**
- Modify: `backend/app/routers/settings.py`

- [ ] **Step 1: Add the test endpoint to routers/settings.py**

After the existing `@router.post("/smtp/test", ...)` endpoint (around line 82), add:

```python
@router.post("/discord/test", status_code=200)
async def discord_test(_: AdminUser, db: AsyncSession = Depends(get_db)):
    s = await _get_settings_row(db)
    if not s.discord_webhook_url:
        raise HTTPException(
            400,
            detail={"error": "not_configured", "message": "Configure a Discord webhook URL first."},
        )
    from datetime import datetime, timezone
    import httpx
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = {
        "embeds": [
            {
                "title": "🔔 OpsPilot Test Notification",
                "description": "If you received this, your Discord webhook is configured correctly.",
                "color": 0x5865F2,
                "footer": {"text": f"{s.instance_name} · {ts}"},
            }
        ]
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(s.discord_webhook_url, json=payload)
        if resp.status_code not in (200, 204):
            raise HTTPException(
                502,
                detail={"error": "webhook_error", "message": resp.text[:400]},
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail={"error": "webhook_error", "message": str(e)})
    return {"ok": True}
```

Note: `discord_enabled` is intentionally NOT checked — the test works even when Discord is toggled off, so admins can verify a URL before enabling.

- [ ] **Step 2: Restart backend and verify endpoint exists**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend --tail=5
```

Expected: `Application startup complete.`

- [ ] **Step 3: Test the endpoint returns 400 when unconfigured**

```bash
TOKEN=$(curl -s -X POST http://localhost:9090/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"clacode01@pocketdata.com.my","password":"admin"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token','NO_TOKEN'))")

curl -s -X POST http://localhost:9090/api/settings/discord/test \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

If a webhook URL is already configured in the DB, this will attempt to send to Discord (expected). If not configured, expected response:
```json
{"detail": {"error": "not_configured", "message": "Configure a Discord webhook URL first."}}
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/settings.py
git commit -m "feat: add POST /api/settings/discord/test endpoint"
```

---

### Task 6: Update Frontend Settings Store

**Files:**
- Modify: `frontend/src/stores/settings.ts`

- [ ] **Step 1: Add `enabled` field to the `smtp` ref**

Find the `smtp` ref definition (around line 8). Add `enabled: true` as the last field:

```typescript
  const smtp = ref({
    host: '',
    port: 587,
    encryption: 'tls' as 'none' | 'tls' | 'ssl',
    username: '',
    fromAddress: '',
    recipients: '',
    hasPassword: false,
    enabled: true,
  })
```

- [ ] **Step 2: Populate `smtp.enabled` in `fetchSettings`**

In the `fetchSettings` function, find the `smtp.value = { ... }` block (around line 42). Add `enabled` as the last field:

```typescript
    smtp.value = {
      host: data.smtp_host ?? '',
      port: data.smtp_port ?? 587,
      encryption: data.smtp_encryption,
      username: data.smtp_username ?? '',
      fromAddress: data.smtp_from_address ?? '',
      recipients: data.smtp_recipients ?? '',
      hasPassword: data.smtp_has_password,
      enabled: data.smtp_enabled ?? true,
    }
```

- [ ] **Step 3: Add `testDiscord` action**

After the existing `testSmtp` function (around line 72), add:

```typescript
  async function testDiscord() {
    const { data } = await api.post('/api/settings/discord/test')
    return data as { ok: boolean }
  }
```

- [ ] **Step 4: Export `testDiscord` in the return object**

In the `return { ... }` block, add `testDiscord` to the exported items (alongside the existing `testSmtp`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/settings.ts
git commit -m "feat: add smtp.enabled and testDiscord to settings store"
```

---

### Task 7: Update Settings UI — SMTP Toggle + Discord Test Button

**Files:**
- Modify: `frontend/src/views/settings/GeneralTab.vue`

- [ ] **Step 1: Add `smtpEnabled` ref and `testingDiscord` ref in `<script setup>`**

After the `hasPassword` ref (around line 49), add:

```typescript
const smtpEnabled = ref(true)
const testingDiscord = ref(false)
```

- [ ] **Step 2: Populate `smtpEnabled` in `load()`**

After `hasPassword.value = settings.smtp.hasPassword`, add:

```typescript
    smtpEnabled.value = settings.smtp.enabled
```

- [ ] **Step 3: Include `smtp_enabled` in the `saveSmtp` payload**

In `saveSmtp()`, find the `payload` object. Add `smtp_enabled` to it:

```typescript
    const payload: Record<string, unknown> = {
      smtp_host: smtpHost.value.trim(),
      smtp_port: smtpPort.value,
      smtp_encryption: smtpEncryption.value,
      smtp_username: smtpUsername.value.trim(),
      smtp_from_address: smtpFrom.value.trim(),
      smtp_recipients: smtpRecipients.value.trim(),
      smtp_enabled: smtpEnabled.value,
    }
```

- [ ] **Step 4: Add `sendDiscordTest` function**

After the closing `}` of `sendTest()` (the SMTP test function, around line 132), add:

```typescript
async function sendDiscordTest() {
  testingDiscord.value = true
  try {
    await settings.testDiscord()
    notify.success('Test notification sent to Discord.')
  } catch (err) {
    notify.error(getApiError(err) ?? 'Discord test failed.')
  } finally {
    testingDiscord.value = false
  }
}
```

- [ ] **Step 5: Add SMTP toggle to the SMTP card template**

In the template, find the SMTP card section. At the very top of the SMTP card, after `<h2>Email (SMTP)</h2>` and before the amber "not configured" banner, add:

```html
      <div class="field toggle-row">
        <div>
          <span class="toggle-label">Send alert notifications via email</span>
          <p class="hint">Uncheck to pause all email alerts without removing your SMTP configuration.</p>
        </div>
        <label class="switch">
          <input v-model="smtpEnabled" type="checkbox" :disabled="loading" />
          <span class="slider"></span>
        </label>
      </div>
```

- [ ] **Step 6: Add "Send Test Notification" button to the Discord card**

In the Discord card, find the actions area with the Save button. Replace:

```html
      <button class="primary" :disabled="savingDiscord || loading" @click="saveDiscord">
        <span v-if="savingDiscord" class="spin"></span><span v-else>Save</span>
      </button>
```

With:

```html
      <div class="actions">
        <button class="primary" :disabled="savingDiscord || loading" @click="saveDiscord">
          <span v-if="savingDiscord" class="spin"></span><span v-else>Save</span>
        </button>
        <button class="ghost" :disabled="testingDiscord || loading || !discordWebhookUrl.trim()" @click="sendDiscordTest">
          <span v-if="testingDiscord" class="spin dark"></span><span v-else>Send Test Notification</span>
        </button>
      </div>
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/settings/GeneralTab.vue
git commit -m "feat: add SMTP enable toggle and Discord test button to settings UI"
```

---

### Task 8: Smoke Test and Release

- [ ] **Step 1: Open settings page**

Navigate to `http://localhost:9090/settings`. Confirm:
- SMTP card now has a toggle at the top labelled "Send alert notifications via email" (checked by default)
- Discord card now has a "Send Test Notification" button next to Save

- [ ] **Step 2: Test SMTP toggle**

Uncheck the SMTP toggle and click Save in the SMTP card. Then re-check the DB:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres psql -U opspilot -d opspilot -c "SELECT smtp_enabled FROM app_settings WHERE id=1;"
```

Expected: ` f`

Re-enable and save again. Confirm it returns to `t`.

- [ ] **Step 3: Test Discord test button**

With a real Discord webhook URL configured and enabled, click "Send Test Notification". Confirm:
- A blurple embed titled "🔔 OpsPilot Test Notification" appears in the Discord channel
- Toast shows "Test notification sent to Discord."

- [ ] **Step 4: Test Discord test button without URL**

Clear the webhook URL field (don't save). Confirm the "Send Test Notification" button is disabled (`:disabled="... || !discordWebhookUrl.trim()"`).

- [ ] **Step 5: Tag and push the release**

```bash
git describe --tags --abbrev=0
# Expected: v1.2.10 — bump to v1.2.11
git tag v1.2.11
git push origin main
git push origin v1.2.11
```
