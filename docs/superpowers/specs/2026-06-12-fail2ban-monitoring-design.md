# Fail2ban Monitoring — Design Spec
Date: 2026-06-12

## Overview

Add a **Security tab** to the OpsPilot server detail page that monitors fail2ban activity: daemon status, per-jail stats, banned IPs with geolocation, a 24h ban timeline chart, and a top-countries breakdown. Data is collected every 5 minutes via SSH using `fail2ban-client` and log parsing.

---

## Decisions Made

| Question | Decision |
|---|---|
| UI placement | New "Security" tab on server detail (alongside Info, Overview, CPU…) |
| Tab layout | Stats + 24h timeline chart + top countries + banned IPs table |
| Geolocation | ip-api.com, results cached permanently in `ip_geodata` table |
| Poll interval | Every 5 minutes |
| Collection method | SSH — `fail2ban-client status <jail>` + tail `/var/log/fail2ban.log` |

---

## Data Model

### `fail2ban_jails`
Current snapshot per jail per server, refreshed every 5 minutes.

| Column | Type | Notes |
|---|---|---|
| server_id | uuid | FK → servers |
| jail_name | text | e.g. "sshd", "nginx-http-auth" |
| currently_banned | int | current live ban count |
| total_banned | int | all-time cumulative |
| currently_failed | int | attempts not yet banned |
| checked_at | timestamptz | when this row was written |

Primary key: `(server_id, jail_name)` — upserted on each poll.

### `fail2ban_ban_events`
Timestamped log of every ban and unban event, parsed from `/var/log/fail2ban.log`. Powers the timeline chart.

| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | |
| server_id | uuid | FK → servers |
| ip | text | attacker IP address |
| jail | text | which jail fired |
| action | text | "ban" or "unban" |
| event_at | timestamptz | timestamp from log file |

Unique constraint on `(server_id, ip, jail, event_at, action)` — prevents duplicate inserts on re-reads.

### `fail2ban_banned_ips`
Authoritative snapshot of currently banned IPs per jail, overwritten on every poll. This is the source of truth for the banned IPs table — derived from `fail2ban-client status <jail>` directly, not from log events (events are unreliable after fail2ban restarts).

| Column | Type | Notes |
|---|---|---|
| server_id | uuid | FK → servers |
| jail | text | jail name |
| ip | text | currently banned IP |
| banned_since | timestamptz | as reported by fail2ban-client, nullable |
| checked_at | timestamptz | when this snapshot was taken |

Primary key: `(server_id, jail, ip)` — upserted each poll. Rows for IPs no longer in the live list are deleted each poll cycle.

### `ip_geodata`
Geolocation cache. Each IP is resolved once from ip-api.com and never re-fetched.

| Column | Type | Notes |
|---|---|---|
| ip | text PK | IP address |
| country_code | text | e.g. "CN", "RU" |
| country_name | text | e.g. "China" |
| city | text | optional |
| isp | text | e.g. "Alibaba Cloud" |
| cached_at | timestamptz | for freshness tracking |

---

## Backend

### Collector: `fail2ban_collector.py`

Runs every 5 minutes per active server via APScheduler. Steps:

1. SSH → `fail2ban-client status` → extract jail name list
2. For each jail → `fail2ban-client status <jail>` → upsert row into `fail2ban_jails`; upsert/delete rows in `fail2ban_banned_ips` to match the live banned IP list exactly
3. SSH → `tail -n 5000 /var/log/fail2ban.log` → parse Ban/Unban lines → insert new rows into `fail2ban_ban_events` (UNIQUE constraint deduplicates); used only for the chart
4. Collect all new IPs not yet in `ip_geodata` → batch call ip-api.com (respecting 45 req/min free tier, sleep between batches if needed) → insert into `ip_geodata`

"Bans today" stat card = count of `fail2ban_ban_events` rows where `action='ban'` and `event_at >= UTC midnight today`.

**Permission requirement:** The SSH user (`opspilot`) must be a member of the `fail2ban` group on the target server:
```bash
sudo usermod -aG fail2ban opspilot
```
If `fail2ban-client` returns a permission error or fail2ban is not installed, the collector logs the failure and the UI shows a clear setup-instructions empty state.

**Log parsing format:**
```
2026-06-12 07:23:45,678 fail2ban.actions [1234]: NOTICE  [sshd] Ban 103.107.60.45
2026-06-12 07:45:12,345 fail2ban.actions [1234]: NOTICE  [sshd] Unban 103.107.60.45
```

### Router: `fail2ban.py`

All endpoints require authentication and server membership. Mounted at `/api/servers/{server_id}/fail2ban`.

| Method | Path | Response |
|---|---|---|
| GET | `/status` | `{running: bool, jail_count: int, currently_banned: int, bans_today: int, last_checked: datetime}` |
| GET | `/jails` | `[{jail_name, currently_banned, total_banned, currently_failed, checked_at}]` |
| GET | `/banned-ips?page=1&per_page=50` | Paginated list from `fail2ban_banned_ips` joined with `ip_geodata`. Fields: ip, country_code, country_name, isp, jail, banned_since, checked_at. |
| GET | `/events?hours=24` | `[{hour: datetime, ban_count: int}]` — bans bucketed by hour for chart |
| GET | `/top-countries?hours=24` | `[{country_code, country_name, count}]` sorted desc |

`/status` derives `currently_banned` from `SUM(currently_banned)` across `fail2ban_jails`. `/banned-ips` reads from `fail2ban_banned_ips` (authoritative live snapshot). The timeline chart reads from `fail2ban_ban_events` (log-parsed history). These are separate data sources by design.

### Migration: `0024_fail2ban.py`
Creates `fail2ban_jails`, `fail2ban_banned_ips`, `fail2ban_ban_events`, `ip_geodata`. Adds index on `fail2ban_ban_events(server_id, event_at)` for chart queries.

### Scheduler registration
Register `collect_fail2ban` in `scheduler.py` alongside existing collectors. Interval: 300 seconds.

---

## Frontend

### New Tab Registration
`ServerDetail.vue`: import `SecurityTab.vue`, add `'Security'` to the `TABS` array and `TAB_COMPONENTS` map.

### `SecurityTab.vue`
Top-level tab component. Fetches all 5 endpoints on mount. Passes data down to sub-components. Shows a full-tab empty state with setup instructions if `status.running === false` or last_checked is null.

### Sub-components (in `components/servers/tabs/fail2ban/`)

**`Fail2banStatusBar.vue`**
Four stat cards in a row:
- Status: green `● Active` / red `● Inactive`
- Jails: count
- Banned Now: count (red if > 0)
- Bans Today: count

**`Fail2banChart.vue`**
24h ban timeline bar chart. Reuses the existing chart component pattern. X-axis: hours. Y-axis: ban count. Bars coloured red (`#ef4444`). Auto-refreshes every 5 minutes.

**`Fail2banJailCards.vue`**
One card per jail. Shows jail name, currently banned (red), currently failing (amber). Horizontally scrollable on small screens.

**`Fail2banTopCountries.vue`**
Ranked list of countries. Each row: flag emoji + country name + ban count + proportional mini bar. Max 10 entries, "+ N more" if exceeded.

**`Fail2banBannedTable.vue`**
Paginated table (50 per page) of currently banned IPs:
- IP address
- Country (flag emoji + code)
- ISP
- Jail
- Banned since (relative time, e.g. "2h ago")

Sortable by banned-since (newest first by default).

### Pinia Store: `fail2ban.ts`
State: `status`, `jails`, `bannedIps`, `events`, `topCountries`, `loading`, `error`.
Actions: `fetchAll(serverId)`, `fetchBannedIps(serverId, page)`.
Auto-refresh: poll all endpoints every 5 minutes (matches collector interval).

---

## Empty / Error States

| Condition | UI |
|---|---|
| fail2ban not installed | Full-tab message: "fail2ban not detected on this server" |
| SSH user lacks permission | Full-tab message: "Permission denied — add opspilot to fail2ban group: `sudo usermod -aG fail2ban opspilot`" |
| fail2ban installed but no bans | Normal tab with zero counts, empty table with "No IPs currently banned" |
| ip-api.com lookup fails for an IP | Show IP without flag/ISP — do not block the row |

---

## Files Created / Modified

### New
- `backend/migrations/versions/0024_fail2ban.py` — creates 4 tables: fail2ban_jails, fail2ban_banned_ips, fail2ban_ban_events, ip_geodata
- `backend/app/services/fail2ban_collector.py`
- `backend/app/routers/fail2ban.py`
- `frontend/src/components/servers/tabs/SecurityTab.vue`
- `frontend/src/components/servers/tabs/fail2ban/Fail2banStatusBar.vue`
- `frontend/src/components/servers/tabs/fail2ban/Fail2banChart.vue`
- `frontend/src/components/servers/tabs/fail2ban/Fail2banJailCards.vue`
- `frontend/src/components/servers/tabs/fail2ban/Fail2banTopCountries.vue`
- `frontend/src/components/servers/tabs/fail2ban/Fail2banBannedTable.vue`
- `frontend/src/stores/fail2ban.ts`

### Modified
- `backend/app/jobs/scheduler.py` — register fail2ban collector job
- `backend/app/main.py` — include fail2ban router
- `frontend/src/views/servers/ServerDetail.vue` — add Security tab
