# Discord Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional Discord webhook notification channel that fires alongside email on every alert fire and resolve, toggleable via a global setting.

**Architecture:** Two new columns on `app_settings` (`discord_webhook_url`, `discord_enabled`) drive a new `discord.py` service that mirrors the `alert_email.py` pattern — fetches settings from DB, POSTs a rich embed to the webhook, swallows all errors. `alerting.py` calls it after the existing email call in both `fire_alert` and `resolve_alert`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, httpx (already in requirements), Vue 3, Pinia, TypeScript

---

### Task 1: Database Migration

**Files:**
- Create: `backend/migrations/versions/0020_discord_settings.py`

- [ ] **Step 1: Create the migration file**

```python
# backend/migrations/versions/0020_discord_settings.py
"""add discord notification columns to app_settings

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = '0020_discord_settings'
down_revision = '0019_service_mutes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('app_settings', sa.Column('discord_webhook_url', sa.Text(), nullable=True))
    op.add_column('app_settings', sa.Column('discord_enabled', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('app_settings', 'discord_enabled')
    op.drop_column('app_settings', 'discord_webhook_url')
```

- [ ] **Step 2: Run the migration**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend alembic upgrade head
```

Expected output: `Running upgrade 0019 -> 0020, add discord notification columns to app_settings`

- [ ] **Step 3: Verify columns exist**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres psql -U opspilot -d opspilot -c "\d app_settings" | grep discord
```

Expected output:
```
 discord_webhook_url | text    |           |          |
 discord_enabled     | boolean |           | not null | false
```

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/versions/0020_discord_settings.py
git commit -m "feat: add discord_webhook_url and discord_enabled migration"
```

---

### Task 2: Update Settings ORM Model

**Files:**
- Modify: `backend/app/models/other.py` (the `Settings` class at the bottom of the file)

- [ ] **Step 1: Add the two new fields to the `Settings` class**

In `backend/app/models/other.py`, append these two lines to the `Settings` class (after the `timezone` field at line 283):

```python
    discord_webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    discord_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
```

- [ ] **Step 2: Restart backend and confirm no import errors**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend --tail=20
```

Expected: no `ImportError` or `AttributeError` lines. Log ends with `Application startup complete.`

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/other.py
git commit -m "feat: add discord fields to Settings ORM model"
```

---

### Task 3: Create Discord Notification Service

**Files:**
- Create: `backend/app/services/discord.py`

- [ ] **Step 1: Create the service file**

```python
# backend/app/services/discord.py
"""Best-effort Discord webhook notification for alert fire/resolve events."""
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.other import Alert, Settings

logger = logging.getLogger(__name__)

# alert type → human-readable title (mirrors alert_email.TYPE_DISPLAY)
_TYPE_DISPLAY: dict[str, str] = {
    "cpu": "CPU Usage High",
    "ram": "RAM Usage High",
    "disk": "Disk Usage High",
    "disk_inode": "Disk Inode Usage High",
    "agent_offline": "Agent Offline",
    "service_down": "Service Down",
    "ssl_expiry": "SSL Certificate Expiring",
    "domain_expiry": "Domain Registration Expiring",
    "job_missing": "Job Missing",
    "job_failure": "Job Failed",
    "job_size_drop": "Backup Size Anomaly",
    "db_connections": "MariaDB Connections High",
    "db_replication_lag": "MariaDB Replication Lag",
    "db_replication_stopped": "MariaDB Replication Stopped",
    "db_deadlock": "MariaDB Deadlock Detected",
    "php_fatal": "PHP Fatal Error",
    "nginx_5xx": "Nginx 5xx Spike",
    "ssh_brute_force": "SSH Brute Force Attempt",
    "mariadb_error": "MariaDB Error",
    "slow_query_spike": "Slow Query Spike",
}

_COLOR_FIRE = 0xE74C3C    # red
_COLOR_RESOLVE = 0x2ECC71  # green


def _display_name(alert_type: str) -> str:
    return _TYPE_DISPLAY.get(alert_type, alert_type.replace("_", " ").title())


def _fmt_ts(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    return aware.strftime("%Y-%m-%d %H:%M UTC")


def _build_payload(alert: Alert, *, kind: str, server_name: str | None) -> dict:
    type_label = _display_name(alert.type)
    footer_text = f"{server_name} · " if server_name else ""
    ts = alert.sent_at if kind == "fire" else alert.resolved_at

    if kind == "fire":
        title = f"🔴 {type_label}"
        color = _COLOR_FIRE
    else:
        title = f"✅ {type_label} — Resolved"
        color = _COLOR_RESOLVE

    return {
        "embeds": [
            {
                "title": title,
                "description": alert.message,
                "color": color,
                "footer": {"text": f"{footer_text}{_fmt_ts(ts)}"},
            }
        ]
    }


async def send_discord_alert(
    db: AsyncSession,
    alert: Alert,
    *,
    kind: str,
    server_name: str | None = None,
) -> None:
    """Post a Discord embed for a fire or resolve event. Never raises."""
    try:
        s = await db.scalar(select(Settings).where(Settings.id == 1))
    except Exception:  # noqa: BLE001
        logger.warning("discord alert skipped: could not load settings", exc_info=True)
        return

    if s is None or not s.discord_enabled or not s.discord_webhook_url:
        return

    payload = _build_payload(alert, kind=kind, server_name=server_name)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(s.discord_webhook_url, json=payload)
            if resp.status_code not in (200, 204):
                logger.warning(
                    "discord webhook returned %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
    except Exception:  # noqa: BLE001
        logger.warning("discord alert send failed", exc_info=True)
```

- [ ] **Step 2: Verify the module imports cleanly**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend python -c "from app.services.discord import send_discord_alert; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/discord.py
git commit -m "feat: add discord notification service"
```

---

### Task 4: Wire Discord Into Alerting Pipeline

**Files:**
- Modify: `backend/app/services/alerting.py`

- [ ] **Step 1: Add the import at the top of alerting.py**

After the existing `from app.services import alert_email` line (line 29), add:

```python
from app.services import discord as discord_service
```

- [ ] **Step 2: Add Discord call in `fire_alert` after the email call**

Find this block in `fire_alert` (around line 232–235):

```python
    await alert_email.send_alert_email(
        db, alert, kind="fire", server_name=server_name, email_meta=email_meta
    )
    await _broadcast("alert_fired", alert, org_id, server_name)
```

Replace it with:

```python
    await alert_email.send_alert_email(
        db, alert, kind="fire", server_name=server_name, email_meta=email_meta
    )
    await discord_service.send_discord_alert(
        db, alert, kind="fire", server_name=server_name
    )
    await _broadcast("alert_fired", alert, org_id, server_name)
```

- [ ] **Step 3: Add Discord call in `resolve_alert` after the email call**

Find this block in `resolve_alert` (around line 262–264):

```python
    if send_email:
        await alert_email.send_alert_email(
            db, alert, kind="resolve", server_name=server_name
        )
    await _broadcast("alert_resolved", alert, org_id, server_name)
```

Replace it with:

```python
    if send_email:
        await alert_email.send_alert_email(
            db, alert, kind="resolve", server_name=server_name
        )
    await discord_service.send_discord_alert(
        db, alert, kind="resolve", server_name=server_name
    )
    await _broadcast("alert_resolved", alert, org_id, server_name)
```

- [ ] **Step 4: Restart backend and verify no errors**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend --tail=20
```

Expected: `Application startup complete.` with no import errors.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/alerting.py
git commit -m "feat: wire discord notifications into alert fire/resolve pipeline"
```

---

### Task 5: Update Settings Schema and Router

**Files:**
- Modify: `backend/app/schemas/settings.py`
- Modify: `backend/app/routers/settings.py`

- [ ] **Step 1: Add discord fields to `SettingsResponse` in schemas/settings.py**

After the `timezone: str` field in `SettingsResponse`, add:

```python
    discord_webhook_url: str | None
    discord_enabled: bool
```

- [ ] **Step 2: Add discord fields to `SettingsPatch` in schemas/settings.py**

After the `timezone: str | None = None` field in `SettingsPatch`, add:

```python
    discord_webhook_url: str | None = None
    discord_enabled: bool | None = None
```

- [ ] **Step 3: Update `_to_response` in routers/settings.py**

Find the `_to_response` function and add the two new fields. The full updated function:

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
        discord_webhook_url=s.discord_webhook_url,
        discord_enabled=s.discord_enabled,
    )
```

- [ ] **Step 4: Smoke test the settings endpoint**

```bash
TOKEN=$(curl -s -X POST http://localhost:9090/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"YOUR_ADMIN_EMAIL","password":"YOUR_ADMIN_PASSWORD"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -H "Authorization: Bearer $TOKEN" http://localhost:9090/api/settings | python3 -m json.tool | grep discord
```

Expected output:
```json
"discord_webhook_url": null,
"discord_enabled": false,
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/settings.py backend/app/routers/settings.py
git commit -m "feat: expose discord fields in settings schema and router"
```

---

### Task 6: Update Frontend Settings Store

**Files:**
- Modify: `frontend/src/stores/settings.ts`

- [ ] **Step 1: Add `discord` ref to the store**

After the `retention` ref definition (around line 17), add:

```typescript
  const discord = ref({
    webhookUrl: '',
    enabled: false,
  })
```

- [ ] **Step 2: Populate `discord` ref in `fetchSettings`**

After the `retention.value = { ... }` block (around line 52), add:

```typescript
    discord.value = {
      webhookUrl: data.discord_webhook_url ?? '',
      enabled: data.discord_enabled ?? false,
    }
```

- [ ] **Step 3: Add `saveDiscord` action**

After the `saveRetention` function (around line 70), add:

```typescript
  async function saveDiscord(p: { discord_webhook_url: string; discord_enabled: boolean }) {
    await api.patch('/api/settings', p)
    await fetchSettings()
  }
```

- [ ] **Step 4: Export `discord` and `saveDiscord` in the return object**

In the `return { ... }` block, add `discord` and `saveDiscord` to the list:

```typescript
    discord,
    saveDiscord,
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/settings.ts
git commit -m "feat: add discord ref and saveDiscord action to settings store"
```

---

### Task 7: Add Discord Section to Settings UI

**Files:**
- Modify: `frontend/src/views/settings/GeneralTab.vue`

- [ ] **Step 1: Add Discord reactive state in `<script setup>`**

After the `smtpPassword`, `hasPassword` refs (around line 49), add:

```typescript
const discordWebhookUrl = ref('')
const discordEnabled = ref(false)
const savingDiscord = ref(false)
```

- [ ] **Step 2: Populate Discord state in the `load` function**

After `hasPassword.value = settings.smtp.hasPassword` (around line 70), add:

```typescript
    discordWebhookUrl.value = settings.discord.webhookUrl
    discordEnabled.value = settings.discord.enabled
```

- [ ] **Step 3: Add `saveDiscord` function**

After the closing `}` of `sendTest` (around line 132), add:

```typescript
async function saveDiscord() {
  savingDiscord.value = true
  try {
    await settings.saveDiscord({
      discord_webhook_url: discordWebhookUrl.value.trim(),
      discord_enabled: discordEnabled.value,
    })
    notify.success('Discord settings saved.')
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to save Discord settings.')
  } finally {
    savingDiscord.value = false
  }
}
```

- [ ] **Step 4: Add Discord section to the template**

After the closing `</section>` of the SMTP card (after line 222), add:

```html
    <!-- Discord -->
    <section class="card">
      <h2>Discord Notifications</h2>
      <div class="field toggle-row">
        <div>
          <span class="toggle-label">Send alert notifications to Discord</span>
          <p class="hint">Fires a message to your Discord channel on every alert and resolve.</p>
        </div>
        <label class="switch">
          <input v-model="discordEnabled" type="checkbox" :disabled="loading" />
          <span class="slider"></span>
        </label>
      </div>
      <div class="field">
        <label>Webhook URL</label>
        <input
          v-model="discordWebhookUrl"
          type="url"
          placeholder="https://discord.com/api/webhooks/…"
          :disabled="loading"
        />
        <p class="hint">
          In Discord: channel settings → Integrations → Webhooks → New Webhook → Copy Webhook URL.
        </p>
      </div>
      <button class="primary" :disabled="savingDiscord || loading" @click="saveDiscord">
        <span v-if="savingDiscord" class="spin"></span><span v-else>Save</span>
      </button>
    </section>
```

- [ ] **Step 5: Add toggle switch styles to `<style scoped>`**

At the end of the `<style scoped>` block, add:

```css
.toggle-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.toggle-label { font-size: 14px; color: var(--text); }
.switch { position: relative; display: inline-block; width: 44px; height: 24px; flex-shrink: 0; margin-top: 2px; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider { position: absolute; cursor: pointer; inset: 0; background: var(--border); border-radius: 24px; transition: 0.2s; }
.slider::before { content: ''; position: absolute; width: 18px; height: 18px; left: 3px; top: 3px; background: #fff; border-radius: 50%; transition: 0.2s; }
input:checked + .slider { background: var(--accent); }
input:checked + .slider::before { transform: translateX(20px); }
input:disabled + .slider { opacity: 0.5; cursor: not-allowed; }
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/settings/GeneralTab.vue
git commit -m "feat: add Discord Notifications section to settings UI"
```

---

### Task 8: Smoke Test and Release

- [ ] **Step 1: Open the settings page**

Navigate to `http://localhost:9090/settings`. Verify the new "Discord Notifications" card appears below the SMTP card with a toggle and URL input.

- [ ] **Step 2: Configure a test Discord webhook**

Create a test webhook in a Discord channel (channel settings → Integrations → Webhooks → New Webhook → Copy Webhook URL).

Enter the URL into the Webhook URL field. Toggle **enabled**. Click **Save**. Verify "Discord settings saved." toast appears.

- [ ] **Step 3: Verify the setting persists**

Refresh the page. Confirm the toggle is still on and the URL is still populated.

- [ ] **Step 4: Trigger a test alert**

In the backend, temporarily lower a CPU alert threshold so it fires, or use curl to manually trigger a state change. Confirm a Discord embed appears in your channel:
- Red embed titled `🔴 CPU Usage High` (or whichever type fired)
- Alert message as description
- Server name and timestamp in footer

- [ ] **Step 5: Verify resolve message**

When the alert resolves, confirm a green `✅ ... — Resolved` embed appears in Discord.

- [ ] **Step 6: Test with Discord disabled**

Toggle Discord off, save, trigger another alert — confirm no Discord message is sent (email still works normally).

- [ ] **Step 7: Update PROGRESS.md and DASHBOARD.html**

In `PROGRESS.md`, mark the Discord notifications task as `✅`.
In `DASHBOARD.html`, update the matching task's `status` from `'pending'` to `'done'` and update `LAST_UPDATED`.

- [ ] **Step 8: Commit dashboard updates**

```bash
git add PROGRESS.md DASHBOARD.html
git commit -m "feat: Discord notification channel complete — smoke test passed"
```

- [ ] **Step 9: Tag and push the release**

```bash
# Check latest tag first
git describe --tags --abbrev=0

# Bump patch (e.g. if latest is v1.2.9, use v1.2.10)
git tag v1.2.10
git push origin main
git push origin v1.2.10
```
