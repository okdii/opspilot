# Discord Notifications — Design Spec
**Date:** 2026-06-10
**Status:** Approved

## Overview

Add Discord webhook as an optional, globally-toggleable notification channel alongside the existing SMTP email. When enabled, every alert fire and resolve triggers a Discord embed message in addition to the existing email. Email behaviour is unchanged.

## Data Layer

Add two columns to the `GlobalSettings` table via a new Alembic migration:

| Column | Type | Default | Notes |
|---|---|---|---|
| `discord_webhook_url` | `TEXT` | `NULL` | Full Discord webhook URL |
| `discord_enabled` | `BOOLEAN` | `FALSE` | Master on/off toggle |

Discord notifications only fire when **both** `discord_enabled = TRUE` and `discord_webhook_url` is non-null.

## Backend

### Migration
New Alembic revision adding the two columns to `global_settings`.

### `app/services/discord.py` (new file)
Single public coroutine:

```
async def send_discord_alert(settings, alert, *, kind, server_name) -> None
```

- Reads `settings.discord_enabled` and `settings.discord_webhook_url`; returns immediately if either is falsy.
- POSTs to the webhook URL via `httpx.AsyncClient` with a Discord embed payload:
  - **Color:** `0xE74C3C` (red) for `kind="fire"`, `0x2ECC71` (green) for `kind="resolve"`
  - **Title:** human-readable alert type (e.g. `"CPU High"`, `"Service Down"`)
  - **Description:** `alert.message`
  - **Footer:** server name (if available) + ISO timestamp
- Wrapped in `try/except Exception` — a Discord failure is logged as a warning and never propagates to the caller.

### `app/services/alerting.py` (modify)
After the existing `await alert_email.send_alert_email(...)` call in both `fire_alert` and `resolve_alert`, add:

```python
await discord.send_discord_alert(
    settings, alert, kind=kind, server_name=server_name
)
```

`discord.send_discord_alert` accepts `db: AsyncSession` and fetches `GlobalSettings` internally — the same pattern used by `alert_email.py` today. The call is best-effort — failure does not affect the alert state or email delivery.

### `app/schemas/settings.py` (modify)
Add to `SettingsResponse`:
- `discord_webhook_url: str | None`
- `discord_enabled: bool`

Add to `SettingsPatch`:
- `discord_webhook_url: str | None = None`
- `discord_enabled: bool | None = None`

### `app/routers/settings.py` (modify)
Ensure the GET and PATCH handlers read/write the two new fields. The webhook URL is not sensitive (no masking needed — unlike SMTP password).

## Frontend

### Settings page — new section: "Discord Notifications"
Placed after the existing SMTP section. Contains:

1. **Enable Discord toggle** — `VaSwitch` bound to `discord_enabled`. Label: "Send alert notifications to Discord".
2. **Webhook URL input** — `VaInput` bound to `discord_webhook_url`. Shown regardless of toggle state (so the URL can be pre-filled before enabling). Placeholder: `https://discord.com/api/webhooks/…`. Full-width.

Save behaviour: same "Save Settings" button that covers the whole settings form — no separate save per section.

## Discord Embed Format

**Fire alert:**
```
[RED EMBED]
🔴 CPU High                          ← alert type, title-cased
CPU usage 94% on web-01 (threshold 85%)   ← alert.message
─────────────────────────────────────
web-01 · 2026-06-10 21:45 UTC        ← server_name · timestamp
```

**Resolve alert:**
```
[GREEN EMBED]
✅ CPU High — Resolved
CPU usage returned to normal on web-01
─────────────────────────────────────
web-01 · 2026-06-10 21:52 UTC
```

## Out of Scope
- Per-alert-rule Discord toggle (can be added later)
- Per-org webhook URLs (single global webhook only)
- Discord bot (webhook-only, no bot registration required)
- Test-webhook button in UI (can be added later)
