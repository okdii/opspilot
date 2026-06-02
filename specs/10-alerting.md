# Spec 10 — Alerting

**Version:** 1.0  
**Date:** 2026-06-01  
**Status:** Approved

---

## 1. Overview

The alerting system covers three concerns:

1. **Active Alerts** — live view of all firing, acknowledged, and snoozed alerts; Ack/Snooze actions
2. **Alert History** — full resolved alert log with filters
3. **Alert Rules** — per-server metric rules (`AlertRule`) and log pattern rules (`LogAlertRule`), auto-created at onboarding and editable by admin

Alerts are scoped to the active organisation. The notification bell in the top bar shows a badge count of firing alerts. Alerts are pushed to the frontend via WebSocket so the UI stays live without polling.

PRD references: §5.13, §5.14, §5.16.11, §9 (Alert, AlertRule, LogAlertRule models)

> **Data model note:** The `Alert` table requires one additional column not in PRD §9: `consecutive_clear_count INTEGER DEFAULT 0`. This persists the auto-resolve counter across backend restarts — without it, a restart resets the counter and the 2-consecutive-clean rule never triggers. Add via Alembic migration.

---

## 2. Routes

| Route | Access | Description |
|---|---|---|
| `/alerts` | All roles | Active alerts + alert history |
| `/alerts/rules` | Admin only | Alert rule management (metric + log rules) |

`/alerts/rules` is Admin-only. Operators and Viewers can view and act on alerts but cannot edit rules.

---

## 3. Top-Bar Notification Bell

```
┌──────────────────────────────────────────────────────┐
│  OpsPilot                                🔔³  Admin  │
└──────────────────────────────────────────────────────┘
```

- Badge shows count of alerts in `firing` state for the active org
- Acknowledged and snoozed alerts do not count toward the badge
- Clicking the bell opens a dropdown panel (not a page navigation)

### 3.1 Bell Dropdown Panel

```
┌────────────────────────────────────────┐
│  Active Alerts (3)                     │
├────────────────────────────────────────┤
│ ✕ web-01   CPU > 85%       2 min ago  │
│ ✕ web-02   Service down    14 min ago │
│ ⚠ web-03   SSL expiring    1 hr ago   │
├────────────────────────────────────────┤
│            View All Alerts →           │
└────────────────────────────────────────┘
```

- Shows up to 5 most recent firing alerts
- Each row: severity dot, server/subject name, short message, relative time
- "View All Alerts →" navigates to `/alerts`
- Panel closes on click-outside or Escape
- If zero firing alerts: "No active alerts ✓" with a green checkmark

---

## 4. Alerts Page (`/alerts`)

### 4.1 Layout

Two-tab structure on the same page:

```
┌──────────────────────────────────────────────────────────────────┐
│  Alerts                                                          │
│                                                                  │
│  [Active (3)]   [History]                                        │
│                                                                  │
│  ── Active tab ─────────────────────────────────────────────── │
│                                                                  │
│  Filter: [All Servers ▼]  [All Types ▼]  [All States ▼]        │
│                                                                  │
│  Alert Frequency (last 30 days)                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │    ██                                          ██        │   │
│  │  ████ ██    █  ██  █                        ████ ██     │   │
│  │ ─────────────────────────────────────────────────────── │   │
│  │ May 2                                              Jun 1 │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ ✕ web-01  CPU > 85%     Firing     2m ago  [Ack] [Snz ▼]│   │
│  │ ✕ web-02  Service down  Firing    14m ago  [Ack] [Snz ▼]│   │
│  │ ⚠ web-03  SSL 14 days   Firing     1h ago  [Ack] [Snz ▼]│   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 5. Alert Frequency Chart

Bar chart: alerts per day over the last 30 days, stacked by severity.

- X-axis: dates (last 30 days)
- Y-axis: alert count
- Two stacked colours: red = `critical`, amber = `warning`
- Bars are clickable — clicking a bar filters the table below to show only alerts from that day
- Tooltip on hover: date, critical count, warning count, total
- Rendered above the active alerts list and visible on both tabs (always shown on the Alerts page)

---

## 6. Active Alerts Tab

### 6.1 Filter Bar

| Control | Type | Behaviour |
|---|---|---|
| All Servers | Dropdown | Lists servers in active org with status dots |
| All Types | Dropdown | CPU / RAM / Disk / Service / SSL / Domain / Cron / Backup / DB / Log / All |
| All States | Dropdown | Firing / Acknowledged / Snoozed / All |

Default view: All States (shows firing + acknowledged + snoozed — everything not resolved).

### 6.2 Alert Row

Each alert displayed as a card row:

| Element | Description |
|---|---|
| Severity dot | Red (critical) / Amber (warning) |
| Subject | Server name, or service name, or domain name depending on alert type |
| Message | Short description (e.g., "CPU 91% — threshold 85%", "SSL expiring in 14 days") |
| State badge | `Firing` (red) / `Acknowledged` (blue) / `Snoozed` (amber, with "until 16:00") / `Suppressed` (grey — server is in maintenance) |
| Time | When alert first fired — relative ("2m ago", "1h ago", "3d ago") |
| `[Ack]` button | Acknowledge action — visible on Firing alerts; hidden on Acknowledged/Snoozed |
| `[Snooze ▼]` button | Snooze duration picker — visible on Firing and Acknowledged alerts; hidden when already snoozed |
| `[⋮]` | View detail, View source (navigates to server/service/domain page) |

**Snoozed rows** show the snooze expiry inline: "Snoozed until 16:30" with a small clock icon.

**Acknowledged rows** show `[Snooze ▼]` only (no `[Ack]` again; already acked).

Sort order: Firing first, then Acknowledged, then Snoozed. Within each group: most recent first.

### 6.3 Snooze Duration Picker

Clicking `[Snooze ▼]` opens a small dropdown popover:

```
┌──────────────┐
│ 15 minutes   │
│ 30 minutes   │
│ 1 hour       │
│ 4 hours      │
│ Custom...    │
└──────────────┘
```

Selecting a duration calls `POST /api/alerts/:id/snooze` with `{ "minutes": 60 }`.

"Custom..." opens a time picker modal:
```
Snooze until:
[Date: 2026-06-01]  [Time: 18:00]

[Cancel]  [Snooze]
```

Custom snooze sends an absolute `snoozed_until` timestamp.

### 6.4 Empty State (no active alerts)

```
┌───────────────────────────────────────┐
│                                       │
│     ✓ No active alerts                │
│                                       │
│   All systems are operating           │
│   normally.                           │
│                                       │
└───────────────────────────────────────┘
```

---

## 7. Alert History Tab

### 7.1 Filter Bar

| Control | Type | Behaviour |
|---|---|---|
| All Servers | Dropdown | Same as active tab |
| All Types | Dropdown | Same as active tab |
| Date Range | Date range picker | Default: last 7 days; custom range via calendar |
| Search | Text input | Searches alert message, debounced 300ms |

### 7.2 History Table

Columns:

| Column | Description |
|---|---|
| Fired At | `YYYY-MM-DD HH:mm:ss` — when alert entered `firing` state |
| Resolved At | `YYYY-MM-DD HH:mm:ss` or `—` if still active |
| Duration | "14 min", "2h 4min", or `—` |
| Server / Subject | Name of server / service / domain |
| Type | Alert type badge (e.g., `cpu`, `service_down`, `ssl_expiry`) |
| Severity | Chip: `critical` (red) / `warning` (amber) |
| State | `Resolved` (green) / `Acknowledged` (blue) / `Snoozed` (amber) |
| Message | Alert message text |

- Sorted by `sent_at DESC` by default
- Pagination: 50 rows per page, cursor-based
- Clicking a row expands inline detail (same as alert detail view)

---

## 8. Alert Detail

Triggered by `[⋮] → View Detail` or row click. Opens a slide-over panel (520px).

### 8.1 Detail Layout

```
┌────────────────────────────────────────────────────┐
│  ✕ CPU Usage Critical                              │
│  web-01  ·  Fired 14 min ago                       │
│  State: Firing                                     │
├────────────────────────────────────────────────────┤
│  Alert Message                                     │
│  CPU rolling 5-min average reached 91.2% —        │
│  threshold is 85%. Server: web-01.                 │
├────────────────────────────────────────────────────┤
│  Timeline                                          │
│  ● Fired      2026-06-01 14:08:22                  │
│  ○ Acknowledged  —                                 │
│  ○ Resolved      —                                 │
├────────────────────────────────────────────────────┤
│  Alert Rule                                        │
│  Metric: cpu_usage_total   Threshold: > 85%        │
│  Rolling window: 5 min     Cooldown: 60 min        │
│                                                    │
│           [Edit Rule →]  [View on Dashboard →]     │
├────────────────────────────────────────────────────┤
│  Actions                                           │
│  [Acknowledge]  [Snooze ▼]                         │
└────────────────────────────────────────────────────┘
```

For log-based alerts (e.g., PHP Fatal):
- "Alert Rule" section shows: Source, Pattern, Threshold, Window
- A "View in Log Viewer" link navigates to `/logs` pre-filtered to that server + source + time range

For service/SSL/domain/cron/backup alerts (no AlertRule):
- "Alert Rule" section shows the hardcoded condition and cooldown
- No "Edit Rule" link (these rules are not user-editable in v1)

### 8.2 State Timeline

The timeline shows the lifecycle of the alert in chronological order:

- Fired at
- Acknowledged at (if acked; blank if not)
- Snoozed until (if snoozed; blank if not)
- Resolved at (if resolved; blank if still active)

Multiple snooze events on the same alert: show each snooze as a timeline entry.

---

## 9. Alert Rules Page (`/alerts/rules`)

Admin-only route. Two sections: **Metric Rules** and **Log Pattern Rules**.

### 9.1 Layout

```
┌────────────────────────────────────────────────────────────┐
│ Alert Rules                                                │
│                                                            │
│  [Metric Rules]   [Log Pattern Rules]                      │
│                                                            │
│  Server: [All Servers ▼]                                   │
│                                                            │
│  Metric Rules                                              │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Server   Metric         Threshold  Window  Enabled │   │
│  ├────────────────────────────────────────────────────┤   │
│  │ web-01   cpu_usage      > 85%      5 min   ● [⋮]  │   │
│  │ web-01   ram_usage      > 90%      5 min   ● [⋮]  │   │
│  │ web-01   disk_usage     > 85%      5 min   ● [⋮]  │   │
│  │ web-01   disk_inode     > 90%      5 min   ● [⋮]  │   │
│  └────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────┘
```

Server filter scopes the table to rules for a single server or shows all servers' rules together.

### 9.2 Metric Rules Table

Columns:

| Column | Description |
|---|---|
| Server | Server name |
| Metric | `cpu_usage_total`, `ram_usage_pct`, `disk_usage_pct`, etc. |
| Threshold | e.g., `> 85%` |
| Rolling Window | `5 min` |
| Cooldown | `60 min` |
| Enabled | Toggle (green = active) |
| `[⋮]` | Edit, Disable, Delete |

Rules auto-created at onboarding are marked with a grey "Auto" chip in the Metric column.

**Edit metric rule modal:**

| Field | Type | Default | Validation |
|---|---|---|---|
| Threshold | Number | current value | > 0 |
| Rolling Window | Select | 5 min | 1 / 3 / 5 / 10 / 15 min |
| Cooldown | Select | 60 min | 15 min / 30 min / 1h / 2h / 4h |

Server and metric fields are read-only in edit mode. Title shows "Edit: cpu_usage — web-01".

**Disable:** Inline toggle. When disabled, the evaluator skips this rule. Toggle label changes to grey with "Disabled" text.

**Delete:** Confirmation modal — "Delete this alert rule? No email will be sent if this metric exceeds the threshold." Single confirm click.

### 9.3 Log Pattern Rules Table

Columns:

| Column | Description |
|---|---|
| Server | Server name |
| Source | `php_app`, `nginx_access`, `auth`, `mariadb_error`, `mariadb_slow`, etc. |
| Pattern | SQL LIKE string, e.g., `%Fatal error%` |
| Threshold | Count within window (e.g., `≥ 1`) |
| Window | `60s` |
| Severity | `critical` / `warning` chip |
| Cooldown | `60 min` |
| Enabled | Toggle |
| `[⋮]` | Edit, Disable, Delete |

**Edit log rule modal:**

| Field | Type | Default | Validation |
|---|---|---|---|
| Source | Select (from 9 sources) | current | Required |
| Pattern | Text | current | Required; SQL LIKE syntax; max 500 chars; preview shows a sample match |
| Threshold | Number | current | ≥ 1 |
| Window (sec) | Number | 60 | 10–3600 |
| Severity | Radio | current | `warning` / `critical` |
| Cooldown | Select | 60 min | Same as metric rules |

Pattern field hint: "Use SQL LIKE syntax: `%text%` matches any message containing 'text'."

### 9.4 Add Custom Rule

`[+ Add Metric Rule]` and `[+ Add Log Rule]` buttons appear at the top of each section. These open the same modals as edit but with empty defaults. The server dropdown is editable on create.

**Note:** Adding a metric rule for a metric/server combination that already has a rule shows an inline error: "A rule for cpu_usage on web-01 already exists."

---

## 10. WebSocket Integration

Alert events are pushed to the frontend over the existing WebSocket connection.

### 10.1 Subscription

Alert events are sent to any connected session — no explicit subscription needed. The backend broadcasts to all authenticated sessions for the active org when an alert fires, is acknowledged, snoozed, or resolved.

### 10.2 Push Event Shapes

```json
{
  "event": "alert_fired",
  "data": {
    "id": "uuid",
    "type": "cpu",
    "severity": "critical",
    "message": "CPU rolling 5-min average reached 91.2% — threshold is 85%",
    "server_id": "uuid",
    "server_name": "web-01",
    "sent_at": "2026-06-01T14:08:22Z",
    "state": "firing"
  }
}

{
  "event": "alert_updated",
  "data": {
    "id": "uuid",
    "state": "acknowledged",
    "acknowledged_at": "2026-06-01T14:10:05Z"
  }
}

{
  "event": "alert_resolved",
  "data": {
    "id": "uuid",
    "state": "resolved",
    "resolved_at": "2026-06-01T14:22:00Z"
  }
}
```

### 10.3 Frontend Handling

- `alert_fired` → insert new row at top of active alerts list; increment bell badge count; show toast notification (see §10.4)
- `alert_updated` → update matching row's state badge (firing → acknowledged, or add snooze label); no toast
- `alert_resolved` → remove row from Active tab; move to History; decrement bell badge

### 10.4 Toast Notification

When `alert_fired` arrives via WS, a toast appears in the top-right:

```
┌───────────────────────────────────────────┐
│ ✕ Alert: web-01 — CPU 91%                 │
│   View →                      [Dismiss]   │
└───────────────────────────────────────────┘
```

- Toast stays visible for 8 seconds, then auto-dismisses
- Red border for `critical`, amber for `warning`
- "View →" navigates to `/alerts` with the alert detail slide-over pre-opened
- At most 3 toasts visible simultaneously — older ones are replaced

---

## 11. Backend — Alert Evaluator

### 11.1 Metric Alert Evaluator

APScheduler job, runs every 30 seconds. Job ID: `metric_alert_evaluator`.

For each `AlertRule` where `enabled = true`:

```
1. Query rolling window average from server_metrics:
   SELECT AVG(value) FROM server_metrics
   WHERE server_id = :server_id
     AND metric_name = :metric
     AND time > now() - INTERVAL ':window_min minutes'

2. Check if threshold crossed:
   - If avg > threshold:
     a. Check maintenance mode — if active, skip
     b. Check cooldown: now() < last_fired_at + cooldown_min → skip
     c. Check existing firing/acked/snoozed alert for same server+type → skip new fire
     d. Otherwise: INSERT Alert, set state='firing', send email
     e. UPDATE AlertRule.last_fired_at = now()
     f. NOTIFY 'alerts' channel (backend fan-out to WS)

3. If avg ≤ threshold:
   - Find open alerts (firing/ack/snoozed) for same server+type
   - UPDATE Alert SET consecutive_clear_count = consecutive_clear_count + 1
   - If consecutive_clear_count ≥ 2: resolve alert, send resolve email,
     UPDATE Alert SET consecutive_clear_count = 0
```

### 11.2 Log Alert Evaluator

APScheduler job, runs every 60 seconds. Job ID: `log_alert_evaluator`.

For each `LogAlertRule` where `enabled = true`:

```
1. General query (all sources except auth):
   SELECT COUNT(*) FROM server_logs
   WHERE server_id = :server_id
     AND source LIKE :source_pattern
     AND message ILIKE :pattern
     AND time > now() - INTERVAL ':window_sec seconds'

2. SSH brute force (special case — per-IP grouping):
   SELECT source_ip, COUNT(*) as cnt
   FROM server_logs
   WHERE server_id = :server_id
     AND source = 'auth'
     AND message LIKE '%Failed password%'
     AND time > now() - INTERVAL ':window_sec seconds'
   GROUP BY source_ip
   HAVING COUNT(*) >= :threshold

3. If count ≥ threshold (or any IP group ≥ threshold for SSH):
   - Same maintenance / cooldown / dedup checks as metric evaluator
   - Fire alert with message including matched pattern and count

4. Auto-resolve: if count drops below threshold for 2 consecutive ticks → resolve
```

**Pattern matching:** User-defined `LogAlertRule.pattern` values are matched using `ILIKE` (case-insensitive) so `%fatal error%` matches `Fatal Error`, `FATAL ERROR`, etc. Hardcoded internal patterns (e.g., `%Failed password%` in the SSH brute-force query) use case-sensitive `LIKE`.

### 11.3 Other Alert Types (No AlertRule Entry)

These are evaluated directly in their respective service/job code (not in the generic evaluator):
- Service down: evaluated in `http_probe.py` / `tcp_probe.py` — after 2 consecutive failures
- SSL expiry: evaluated in `ssl_checker.py`
- Domain expiry: evaluated in `domain_checker.py`
- Cron/backup missing: evaluated in `cron_backup_watchdog.py`
- Backup failure/size drop: evaluated in `ping endpoint handler`
- DB metrics: evaluated in `metric_alert_evaluator` but reads from `server_metrics` (same flow)
- Replication stopped: evaluated immediately in the metric evaluator when `replication_running = false`

Cooldown for these: hardcoded 1h. The dedup/cooldown check queries the `Alert` table for the most recent alert matching the same `(type, <relevant_fk>)` tuple where `<relevant_fk>` is the non-null FK for that alert type:
- Service alerts: `(type='service_down', service_id=X)`
- SSL alerts: `(type='ssl_expiry', ssl_cert_id=X)`
- Domain alerts: `(type='domain_expiry', domain_id=X)`
- Cron/backup alerts: `(type='cron_missing', cron_job_id=X)` or `(type='backup_missing', backup_job_id=X)`

If the most recent matching alert was fired within the last 60 minutes AND is still open (not resolved), no new alert is created.

---

## 12. Email Notification Format

Plain-text email (`Content-Type: text/plain; charset=utf-8`) sent via SMTP (configured in Settings — see spec 11). No HTML is included.

```
Subject: [OpsPilot] CRITICAL: web-01 — CPU Usage High

-----------------------------------------------------
OpsPilot Alert
-----------------------------------------------------

Severity:   CRITICAL
Server:     web-01
Condition:  CPU rolling 5-minute average > 85%
Value:      91.2%
Threshold:  85%
Fired at:   2026-06-01 14:08:22 UTC

Message:
CPU rolling 5-min average reached 91.2% on web-01.
Threshold: 85%. Rolling window: 5 minutes.

View dashboard: https://opspilot.example.com/servers/{id}

-----------------------------------------------------
To manage this alert:
https://opspilot.example.com/alerts

To edit alert rules:
https://opspilot.example.com/alerts/rules

This email was sent by OpsPilot.
-----------------------------------------------------
```

**Resolve email:**
```
Subject: [OpsPilot] RESOLVED: web-01 — CPU Usage returned to normal

Severity:   CRITICAL (resolved)
Server:     web-01
Resolved:   2026-06-01 14:22:00 UTC
Duration:   13 minutes 38 seconds
```

`base_url` is read from `Settings.base_url`. If not set, the backend falls back to `str(request.base_url)` from the FastAPI `Request` object — see spec 11 §4.1.

---

## 13. Pinia Store — `useAlertStore`

```ts
// State
activeAlerts: Alert[]          // firing + acked + snoozed
alertHistory: Alert[]          // resolved alerts (paginated)
historyCursor: string | null
alertFrequency: FrequencyBucket[]  // for bar chart
isLoadingActive: boolean
isLoadingHistory: boolean
error: string | null

// Getters
firingCount: number                          // for bell badge
firingAlerts: Alert[]                        // state = 'firing'
acknowledgedAlerts: Alert[]
snoozedAlerts: Alert[]
alertsByServer: (server_id: string) => Alert[]

// Actions
fetchActiveAlerts(org_id: string): Promise<void>
fetchAlertHistory(org_id: string, filters): Promise<void>
fetchFrequency(org_id: string): Promise<void>
acknowledgeAlert(id: string): Promise<void>
snoozeAlert(id: string, minutes?: number, until?: string): Promise<void>
handleAlertFired(event: AlertFiredEvent): void     // WS handler
handleAlertUpdated(event: AlertUpdatedEvent): void
handleAlertResolved(event: AlertResolvedEvent): void
```

---

## 14. API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/organizations/:org_id/alerts` | Required | List active alerts (firing + acked + snoozed) |
| GET | `/api/organizations/:org_id/alerts/history` | Required | Alert history (cursor-paginated) |
| GET | `/api/organizations/:org_id/alerts/frequency` | Required | Daily counts for bar chart (last 30 days) |
| POST | `/api/alerts/:id/acknowledge` | Required (Admin/Operator) | Acknowledge alert |
| POST | `/api/alerts/:id/snooze` | Required (Admin/Operator) | Snooze alert |
| GET | `/api/organizations/:org_id/alert-rules` | Required | List all metric + log rules for org |
| POST | `/api/alert-rules` | Required (Admin) | Create metric rule |
| PATCH | `/api/alert-rules/:id` | Required (Admin) | Update metric rule |
| DELETE | `/api/alert-rules/:id` | Required (Admin) | Delete metric rule |
| POST | `/api/log-alert-rules` | Required (Admin) | Create log pattern rule |
| PATCH | `/api/log-alert-rules/:id` | Required (Admin) | Update log pattern rule |
| DELETE | `/api/log-alert-rules/:id` | Required (Admin) | Delete log pattern rule |

### 14.1 GET `/api/organizations/:org_id/alerts` Response

```json
[
  {
    "id": "uuid",
    "type": "cpu",
    "severity": "critical",
    "message": "CPU rolling 5-min average reached 91.2% — threshold is 85%",
    "state": "firing",
    "server_id": "uuid",
    "server_name": "web-01",
    "service_id": null,
    "service_name": null,
    "domain_id": null,
    "domain_name": null,
    "sent_at": "2026-06-01T14:08:22Z",
    "acknowledged_at": null,
    "snoozed_until": null,
    "resolved_at": null
  }
]
```

### 14.2 POST `/api/alerts/:id/snooze` Request

```json
{ "minutes": 60 }
// OR
{ "until": "2026-06-01T18:00:00Z" }
```

One of `minutes` or `until` is required. If both provided, `until` takes precedence.

### 14.3 GET `/api/organizations/:org_id/alerts/frequency` Response

```json
[
  { "date": "2026-05-02", "critical": 2, "warning": 1 },
  { "date": "2026-05-03", "critical": 0, "warning": 0 }
]
```

---

## 15. Alert Type Display Names

Used in alert rows, detail panels, emails, and rules tables:

| `type` value | Display Name |
|---|---|
| `cpu` | CPU Usage High |
| `ram` | RAM Usage High |
| `disk` | Disk Usage High |
| `disk_inode` | Disk Inode Usage High |
| `agent_offline` | Agent Offline |
| `service_down` | Service Down |
| `ssl_expiry` | SSL Certificate Expiring |
| `domain_expiry` | Domain Registration Expiring |
| `cron_missing` | Cron Job Missing |
| `backup_missing` | Backup Job Missing |
| `backup_failure` | Backup Job Failed |
| `backup_size_drop` | Backup Size Anomaly |
| `db_connections` | MariaDB Connections High |
| `db_replication_lag` | MariaDB Replication Lag |
| `db_replication_stopped` | MariaDB Replication Stopped |
| `db_deadlock` | MariaDB Deadlock Detected |
| `php_fatal` | PHP Fatal Error |
| `nginx_5xx` | Nginx 5xx Spike |
| `ssh_brute_force` | SSH Brute Force Attempt |
| `mariadb_error` | MariaDB Error |
| `slow_query_spike` | Slow Query Spike |
| `maintenance` | Maintenance Mode (audit entry only) |

---

## 16. Edge States

| State | Behaviour |
|---|---|
| No active alerts | Green empty state: "No active alerts ✓" |
| Bell badge > 99 | Show "99+" |
| Multiple alerts for the same server/type simultaneously | Deduped — only one open alert per server + type at a time; new fire suppressed until existing one resolves |
| Alert acknowledged by Operator, then snoozed by Admin | Both actions allowed; state = `snoozed`; timeline shows both events |
| Snooze expires, condition still present | Alert returns to `firing`; new email sent; bell badge increments again |
| Snooze expires, condition cleared | Alert auto-resolves; no email |
| Alert rule deleted while alert is firing | Alert remains open and visible; resolve/ack/snooze still work; alert row shows "Rule deleted" in the rule detail section |
| Maintenance mode active | When a server enters maintenance: (1) all `firing`, `acknowledged`, and `snoozed` alerts for that server are immediately moved to `state = 'suppressed'` — no emails sent; (2) new alerts are not created while maintenance is active. When maintenance ends, suppressed alerts whose condition has cleared are auto-resolved; those still breaching threshold fire a new alert (subject to cooldown). Requires `suppressed` added to the `Alert.state` enum via Alembic migration. |
| Alert history > 1000 rows | Cursor pagination; user can filter by date range to narrow results |
| WS disconnected | Bell badge and active list stop live-updating; grey "Reconnecting…" chip in top-right; list is stale — refresh button appears |
| Log alert rule pattern never matches | Rule enabled but no alert fires; no feedback needed until a match occurs |
| SSH brute-force alert: same IP triggers multiple windows | Cooldown prevents re-fire within 1h; `last_fired_at` on the alert (not the rule) is checked |
| Custom snooze time set in the past | Validation: "Snooze time must be in the future"; submit blocked |

---

## 17. Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `b` | Open / close notification bell dropdown |
| `a` | Acknowledge selected alert (when one row is focused) |
| `Escape` | Close bell dropdown / slide-over / modal |
| `r` | Refresh active alerts list |
| `/` | Focus filter search bar (history tab) |
| `1` / `2` | Switch between Active / History tabs |
