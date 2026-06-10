# Notification Settings Enhancements — Design Spec
**Date:** 2026-06-10
**Status:** Approved

## Overview

Two small enhancements to the notification settings page:
1. **Test Discord button** — send a test embed to the configured Discord webhook, mirroring the existing "Send Test Email" UX.
2. **SMTP enable/disable toggle** — allow email notifications to be globally disabled without removing SMTP configuration.

---

## Feature 1: Test Discord Button

### Backend

**New endpoint:** `POST /api/settings/discord/test`

- Admin-only (same `AdminUser` dependency as all other settings routes).
- Loads `GlobalSettings` (id=1).
- Returns `400` with `{"error": "not_configured", "message": "..."}` if `discord_webhook_url` is null or empty.
- POSTs a test embed to the webhook URL via `httpx.AsyncClient` (same pattern as `discord.py`):
  - Title: `"🔔 OpsPilot Test Notification"`
  - Description: `"If you received this, your Discord webhook is configured correctly."`
  - Color: `0x5865F2` (Discord blurple — neutral, distinct from fire/resolve colors)
  - Footer: `"{instance_name} · {timestamp}"`
- On non-200/204 webhook response: returns `502` with `{"error": "webhook_error", "message": "<raw response text>"}`.
- On any other exception: returns `502` with `{"error": "webhook_error", "message": "<exception str>"}`.
- On success: returns `{"ok": True}`.
- Note: `discord_enabled` is NOT checked — the test button works even when Discord is toggled off, so admins can verify a URL before enabling.

### Frontend

**Settings store (`settings.ts`):** Add `testDiscord()` action:
```typescript
async function testDiscord() {
  const { data } = await api.post('/api/settings/discord/test')
  return data as { ok: boolean }
}
```
Export in return object.

**GeneralTab.vue — Discord card:**
- Add `testing` ref: `const testingDiscord = ref(false)`
- Add `sendDiscordTest()` function (mirrors `sendTest()` for SMTP)
- Add "Send Test Notification" button next to the existing Save button:
  - Disabled when `testingDiscord || loading || !discordWebhookUrl.trim()`
  - Uses same `.ghost` button style as "Send Test Email"

---

## Feature 2: SMTP Enable/Disable Toggle

### Backend

**Migration 0021:** Add `smtp_enabled BOOLEAN NOT NULL DEFAULT TRUE` to `app_settings`.
- Default `TRUE` — existing instances keep sending email unchanged.

**Settings ORM model (`models/other.py`):** Add to `Settings` class:
```python
smtp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
```

**`alert_email.py`:** In `send_alert_email`, after loading settings, add early return:
```python
if not s.smtp_enabled:
    return False
```
This goes after the `if s is None` check and before building recipients/body.

**Schema (`schemas/settings.py`):**
- `SettingsResponse`: add `smtp_enabled: bool`
- `SettingsPatch`: add `smtp_enabled: bool | None = None`

**Router (`routers/settings.py`):** Add `smtp_enabled=s.smtp_enabled` to `_to_response()`.

### Frontend

**Settings store (`settings.ts`):** Add `enabled: true` to the `smtp` ref:
```typescript
const smtp = ref({
  host: '', port: 587, encryption: 'tls' as ...,
  username: '', fromAddress: '', recipients: '',
  hasPassword: false,
  enabled: true,   // ← new
})
```
Populate from `data.smtp_enabled ?? true` in `fetchSettings`. Include `smtp_enabled: smtp.value.enabled` in the `saveSmtp` payload.

**GeneralTab.vue — SMTP card:**
- Add toggle at the top of the SMTP card (before the host/port/encryption row), using the same `.switch` / `.slider` CSS already present in the file.
- `v-model` bound to a local `smtpEnabled` ref, populated in `load()`.
- Label: "Send alert notifications via email"
- The toggle is saved as part of the existing `saveSmtp()` call — no new save action needed.

---

## Out of Scope
- Per-alert-rule channel overrides
- Disabling Discord/SMTP hides the config fields (config is always shown)
- Test button for SMTP already exists; no changes to it
