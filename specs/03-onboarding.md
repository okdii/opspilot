# Module Spec 03 — Server Onboarding

**Version:** 1.0  
**Date:** 2026-06-01  
**PRD Reference:** §5.17  
**Status:** Ready for Development

---

## 1. Overview

Onboarding is the automated process that runs immediately after a server is added. It SSHes into the target server, installs Telegraf and Fluent Bit, generates configs, starts the services, and verifies data is flowing — all without the admin touching the remote server.

This spec covers:
- What triggers onboarding
- The 10-step backend execution flow
- The real-time progress UI (inline card + full progress panel)
- Error handling at each step
- Retry flow
- Re-deploy (same flow, post-onboarding)
- Onboarding log (persistent, viewable after the fact)

Onboarding is **not a page** — it is a live panel (slide-over drawer) that opens over the server list or server detail page.

---

## 2. When Onboarding Runs

| Trigger | Who | What runs |
|---|---|---|
| Server added (POST /api/organizations/:org_id/servers) | System (automatic) | Full 10-step flow |
| Admin clicks `Re-deploy Agents` from server `[⋮]` menu | Admin | Steps 3–10 (skips SSH test + OS detect, reuses stored values) |
| DB credentials saved for a server post-onboarding | System (automatic) | Steps 6–10 only (reconfigure + restart) |
| Admin clicks `Retry Onboarding` on a failed server | Admin | Full 10-step flow from scratch |

---

## 3. Onboarding Steps

| # | Step ID | Description | Failure behaviour |
|---|---|---|---|
| 1 | `ssh_connect` | Open SSH connection — verify credentials, test sudo access | Hard stop. Shows credential fix instructions. |
| 2 | `detect_os` | Read `/etc/os-release` — detect distro (Ubuntu/Debian vs RHEL/CentOS) and version | Hard stop if OS unsupported. |
| 3 | `add_repos` | Add InfluxData (Telegraf) and Chronosphere (Fluent Bit) package repos | Hard stop. Usually a network issue. |
| 4 | `install_telegraf` | `apt-get install telegraf` or `yum install telegraf` | Hard stop. |
| 5 | `install_fluent_bit` | `apt-get install fluent-bit` or `yum install fluent-bit` | Hard stop. |
| 6 | `configure_telegraf` | Generate `telegraf.conf` from Jinja2 template (server UUID, DB creds, plugins) | Hard stop. |
| 7 | `configure_fluent_bit` | Generate `fluent-bit.conf` from Jinja2 template (server UUID, DB creds, log paths per distro) | Hard stop. |
| 8 | `enable_mariadb_slowlog` | Detect MariaDB → set `slow_query_log=1`, `long_query_time=1`, restart MariaDB | **Soft skip** — if MariaDB not found, step is skipped silently. If found but fails, logged as warning (non-blocking). |
| 9 | `start_services` | `systemctl enable --now telegraf fluent-bit` | Hard stop. |
| 10 | `verify_data_flow` | Poll `server_metrics` for this `server_id` — wait up to 30s for first row | Soft failure — logged as warning; server still marked active. Metrics may appear shortly after. |

**Hard stop** = onboarding halts at this step, server stays `pending`, admin sees error and can retry.  
**Soft skip / warning** = onboarding continues regardless; step result logged but does not block completion.

### 3.1 Supported OS

| Distro | Package manager | Supported |
|---|---|---|
| Ubuntu 20.04, 22.04, 24.04 | apt | ✓ |
| Debian 10, 11, 12 | apt | ✓ |
| RHEL / CentOS 7, 8, 9 | yum / dnf | ✓ |
| Other | — | ✗ — hard stop at step 2 with message: *"Unsupported OS: [name]. Only Ubuntu, Debian, and RHEL/CentOS are supported."* |

### 3.2 SSH Sudo Check (Step 1 Detail)

Before continuing, step 1 runs:
```bash
sudo -n true
```
If this exits non-zero (sudo requires a password), onboarding halts immediately with:
> *"SSH user `ubuntu` does not have passwordless sudo. Add a NOPASSWD entry to sudoers and retry."*

### 3.3 Telegraf Config (Step 6 Detail)

Generated from Jinja2 template. Key parameters injected:
- `server_id` — UUID from the Server record (written as a Telegraf global tag)
- `ingest_url` — `{OPSPILOT_BASE_URL}/api/ingest/metrics` (HTTPS, OpsPilot backend)
- `ingestion_token` — per-server bearer token (stored on `Server.ingestion_token`)
- Enabled input plugins: `cpu`, `mem`, `disk`, `diskio`, `net`, `system`, `processes`, `procstat`, `systemd_units`
- `inputs.mysql` block injected if `DBCredential` already exists for this server at onboarding time

Collection interval: `10s` (hardcoded in template).

**Output**: `outputs.http` plugin sends InfluxDB Line Protocol to the OpsPilot backend's ingestion endpoint. The backend parses line protocol and INSERTs normalized rows into the `server_metrics` hypertable. This keeps PostgreSQL internal-only (no port 5432 exposure) and enables server-side validation, per-server tokens, and clean schema control. (Implementation note: Telegraf's `outputs.postgresql` plugin can't produce the normalized `(time, server_id, metric_name, value, labels)` shape directly — every metric flows through the backend's ingestion endpoint instead.)

### 3.4 Fluent Bit Config (Step 7 Detail)

Generated from Jinja2 template. Log input paths are distro-specific:

| Log source | Debian/Ubuntu path | RHEL/CentOS path |
|---|---|---|
| System | `/var/log/syslog` | `/var/log/messages` |
| Auth | `/var/log/auth.log` | `/var/log/secure` |
| Nginx access | `/var/log/nginx/access.log` | `/var/log/nginx/access.log` |
| Nginx error | `/var/log/nginx/error.log` | `/var/log/nginx/error.log` |
| PHP-FPM | `/var/log/php-fpm/*.log` | `/var/log/php-fpm/*.log` |
| PHP app | `/var/log/php_errors.log` | `/var/log/php_errors.log` |
| MariaDB error | `/var/log/mysql/error.log` | `/var/log/mariadb/mariadb.log` |
| MariaDB slow | `/var/log/mysql/slow.log` | `/var/log/mariadb/slow.log` |

Output: PostgreSQL plugin pointing to `server_logs` hypertable using `opspilot_writer` credentials.

### 3.5 MariaDB Detection (Step 8 Detail)

```bash
systemctl is-active mariadb 2>/dev/null || systemctl is-active mysqld 2>/dev/null
```

If active → inject into `/etc/mysql/conf.d/opspilot.cnf` (Debian) or `/etc/my.cnf.d/opspilot.cnf` (RHEL):
```ini
[mysqld]
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow.log
long_query_time = 1
```
Then: `sudo systemctl restart mariadb`

If not active → step logged as `skipped`, onboarding continues.

---

## 4. Backend Execution

### 4.1 Job Trigger

After `Server` record is created, the API handler enqueues an APScheduler one-shot job:

```
POST /api/organizations/:org_id/servers
  → creates Server record (status: pending)
  → scheduler.add_job(run_onboarding, args=[server_id], id=f"onboard_{server_id}")
  → returns 201 immediately (does not wait for onboarding)
```

Only one onboarding job per server can run at a time. If a retry is requested while a job is already running, the request is rejected with `409`.

### 4.2 Step Execution

For each step, the backend:
1. Writes `OnboardingLog` row: `{ server_id, step, status: 'running', message: '', timestamp: now }`
2. Publishes NOTIFY on channel `onboarding:{server_id}` with the step event
3. Executes the SSH command(s)
4. Updates the `OnboardingLog` row: `status: 'done'|'failed'|'skipped'`, appends SSH stdout/stderr to `message`
5. Publishes NOTIFY with updated step result

### 4.3 On Success

After step 10:
- `Server.os_distro` and `Server.kernel_version` written from step 2 results
- Server `status` transitions to `online` (computed from metrics flowing)
- Final NOTIFY: `{ event: 'onboarding_complete', server_id }`

### 4.4 On Hard Stop

At any hard-stop step:
- Remaining steps not attempted
- Final NOTIFY: `{ event: 'onboarding_failed', server_id, step, message }`
- Server stays `pending`

---

## 5. Real-Time Progress UI

### 5.1 Inline Card Indicator (Server List)

While onboarding is running, the server card in the server list shows:

```
┌────────────────────────────────────────────┐
│  ⟳ web-01                             [⋮] │
│  192.168.1.10                              │
│                                            │
│  ONBOARDING                  Step 4 of 10  │
│  Installing Telegraf...                    │
│  [████████░░░░░░░░░░░░] 40%               │
│                                            │
│  View Progress →                           │
└────────────────────────────────────────────┘
```

- Spinning icon next to the server name
- Step label from the current running step
- Progress bar: `(current_step / total_steps) * 100`
- `View Progress →` link — opens the Onboarding Panel

On success:
```
│  ● web-01                             [⋮] │  ← green dot
│  ONLINE                      Just now     │
```

On failure:
```
│  ✗ web-01                             [⋮] │  ← red X icon
│  ONBOARDING FAILED      Step 3 failed     │
│  View Error →                             │
```

### 5.2 Onboarding Panel (Slide-Over Drawer)

Clicking `View Progress →` opens a right-side slide-over panel (600px wide on desktop, full-screen on mobile). The panel can be opened without leaving the server list.

**Route:** `/servers` (panel is overlaid, not a separate route). Deep-link: `/servers?onboarding=:server_id` — opening this URL directly opens the server list with the panel open for that server.

#### 5.2.1 Running State Layout

```
┌────────────────────────────────────────────────────────────────┐
│  Onboarding Progress                              [ ✕ Close ]  │
│  web-01 · 192.168.1.10                                         │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ✓  SSH Connection               0.8s                         │
│  ✓  OS Detection                 Ubuntu 22.04 LTS  · 0.3s     │
│  ✓  Package Repositories         1.2s                         │
│  ⟳  Installing Telegraf          12s elapsed...               │  ← pulsing
│  ○  Installing Fluent Bit                                      │
│  ○  Configure Telegraf                                         │
│  ○  Configure Fluent Bit                                       │
│  ○  MariaDB Slow Query Log                                     │
│  ○  Start Services                                             │
│  ○  Verify Data Flow                                           │
│                                                                │
├────────────────────────────────────────────────────────────────┤
│  SSH Output                                          [Expand]  │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │ $ sudo apt-get install -y telegraf                         │ │
│ │ Reading package lists... Done                              │ │
│ │ Building dependency tree... Done                           │ │
│ │ Reading state information... Done                          │ │
│ │ The following NEW packages will be installed:              │ │
│ │   telegraf                                                 │ │
│ │ ...                                                        │ │
│ └────────────────────────────────────────────────────────────┘ │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

- Step list on the left with status icons: `✓` (done, green), `⟳` (running, animated), `○` (pending, grey), `✗` (failed, red), `—` (skipped, grey dash)
- Duration shown next to completed steps
- SSH output panel at the bottom — auto-scrolls to latest line
- SSH output is **collapsible** (collapsed by default, expanded if a failure occurs)

#### 5.2.2 Success State

```
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ✓  SSH Connection               0.8s                         │
│  ✓  OS Detection                 Ubuntu 22.04 LTS · 0.3s      │
│  ✓  Package Repositories         1.2s                         │
│  ✓  Installing Telegraf          24s                          │
│  ✓  Installing Fluent Bit        18s                          │
│  ✓  Configure Telegraf           0.1s                         │
│  ✓  Configure Fluent Bit         0.1s                         │
│  —  MariaDB Slow Query Log       skipped (not detected)       │
│  ✓  Start Services               1.4s                         │
│  ✓  Verify Data Flow             first metric in 8s           │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  ✅  Onboarding complete — web-01 is now online!       │   │
│  │  Total time: 47s                                       │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                │
│                             [ View Server Dashboard → ]        │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

- `View Server Dashboard →` navigates to `/servers/:id` (server detail — spec 04)
- Panel stays open until admin closes it or navigates away

#### 5.2.3 Failed State

```
│  ✓  SSH Connection               0.8s                         │
│  ✓  OS Detection                 Ubuntu 22.04 LTS · 0.3s      │
│  ✗  Package Repositories         FAILED                       │
│     Error: curl: (6) Could not resolve host: repos.influxdata.com  │
│     Ensure the server has outbound internet access to:        │
│       • repos.influxdata.com (Telegraf)                       │
│       • packages.fluentbit.io (Fluent Bit)                    │
│  ○  Installing Telegraf          (not attempted)              │
│  ○  ...                                                       │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  ✗  Onboarding failed at step 3: Package Repositories  │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                │
│   [ Retry Onboarding ]     [ Edit Server ]     [ Delete ]     │
│                                                                │
```

- Failed step shown in red with full error message
- Friendly fix hint shown below the error (step-specific — see section 7)
- SSH output panel automatically expanded to show the raw output at failure
- `Retry Onboarding` — runs full flow from scratch
- `Edit Server` — opens Edit Server modal (to fix SSH credentials if that was the issue)
- `Delete` — remove the server entirely

---

## 6. WebSocket Events

Onboarding progress is pushed via LISTEN/NOTIFY on channel `onboarding:{server_id}`.

### 6.1 Event Shape

```json
{
  "channel": "onboarding:550e8400-...",
  "event": "step_update",
  "data": {
    "step": "install_telegraf",
    "step_number": 4,
    "total_steps": 10,
    "status": "running",
    "message": "",
    "duration_ms": null,
    "timestamp": "2026-06-01T12:00:05Z"
  }
}
```

| `event` value | Meaning |
|---|---|
| `step_update` | A step changed state (running → done/failed/skipped) |
| `onboarding_complete` | All steps done — server now active |
| `onboarding_failed` | A hard-stop step failed |
| `ssh_output` | Chunk of SSH stdout/stderr for the terminal panel |

### 6.2 `onboarding_complete` and `onboarding_failed` Event Shapes

```json
{
  "event": "onboarding_complete",
  "data": {
    "server_id": "uuid",
    "duration_sec": 84
  }
}

{
  "event": "onboarding_failed",
  "data": {
    "server_id": "uuid",
    "step": "install_telegraf",
    "message": "E: Unable to locate package telegraf"
  }
}
```

### 6.3 `ssh_output` Event

SSH output is streamed in real time as it arrives:
```json
{
  "event": "ssh_output",
  "data": {
    "step": "install_telegraf",
    "chunk": "Reading package lists... Done\n"
  }
}
```

Frontend appends each chunk to the SSH output panel.

### 6.4 Frontend Subscription

Frontend subscribes to `onboarding:{server_id}` when:
- The onboarding panel is opened
- A `PENDING` server card is visible on screen (to keep the inline card indicator live)

Unsubscribes when:
- Panel is closed AND the server is no longer in `pending` state
- User navigates away from the server list

---

## 7. Step-Specific Error Hints

When a step fails, the UI shows a human-readable fix hint below the error:

| Failed step | Hint shown |
|---|---|
| `ssh_connect` — connection refused | *"Could not connect to 192.168.1.10:22. Check the IP address and ensure port 22 is open."* |
| `ssh_connect` — auth failure | *"Authentication failed. Check the SSH username and credentials, then edit the server and retry."* |
| `ssh_connect` — sudo check failed | *"User `ubuntu` requires a password for sudo. Add NOPASSWD to sudoers: `ubuntu ALL=(ALL) NOPASSWD:ALL`"* |
| `detect_os` — unsupported OS | *"Unsupported OS: [name]. Only Ubuntu 20.04+, Debian 10+, and RHEL/CentOS 7+ are supported."* |
| `add_repos` — network error | *"Could not reach package repositories. Ensure the server has outbound internet access to `repos.influxdata.com` and `packages.fluentbit.io`."* |
| `install_telegraf` / `install_fluent_bit` — package not found | *"Package not found. This may be a repo configuration issue. Check the SSH output for details."* |
| `start_services` — systemd failure | *"Failed to start services. Check the SSH output for systemd error details."* |
| `verify_data_flow` — timeout (30s) | *"No metrics received within 30 seconds. The server may still come online — check again in a few minutes. If it doesn't appear, verify Telegraf is running: `sudo systemctl status telegraf`"* |

---

## 8. Retry Onboarding

### 8.1 How Retry Works

1. Admin clicks `Retry Onboarding` from the failed state panel
2. Frontend calls `POST /api/servers/:id/onboard`
3. Backend:
   - Clears all existing `OnboardingLog` rows for this server
   - Re-runs the full 10-step flow from step 1
4. Panel resets to the initial state with all steps pending
5. Progress streams in as normal

### 8.2 Retry Blocked

If another onboarding job is already running for this server (e.g. user double-clicks), the API returns `409 Conflict`:
- Frontend shows toast: *"Onboarding is already in progress for this server."*

---

## 9. Onboarding Log (Historical)

After onboarding completes (success or failure), the log is persisted in the `OnboardingLog` table and accessible at any time.

### 9.1 Access Points

- Server `[⋮]` menu → `View Onboarding Log`
- Server detail page (spec 04) → `Onboarding` tab

### 9.2 Log View

Same panel layout as the progress view but in read-only mode:
- All step rows show final status + duration
- SSH output is fully captured and scrollable
- No live updates (static data)
- Shows a `Last onboarded: 3 days ago` timestamp at the top

---

## 10. API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/servers/:id/onboarding` | Required | Get current onboarding log (all steps + SSH output) |
| `POST` | `/api/servers/:id/onboard` | Admin | Start (or retry) onboarding |

### GET /api/servers/:id/onboarding

**Response (200):**
```json
{
  "server_id": "uuid",
  "started_at": "2026-06-01T12:00:00Z",
  "completed_at": "2026-06-01T12:00:47Z",
  "outcome": "success",
  "steps": [
    {
      "step": "ssh_connect",
      "step_number": 1,
      "status": "done",
      "message": "",
      "ssh_output": "",
      "duration_ms": 820,
      "timestamp": "2026-06-01T12:00:00Z"
    },
    {
      "step": "detect_os",
      "step_number": 2,
      "status": "done",
      "message": "Ubuntu 22.04 LTS",
      "ssh_output": "...",
      "duration_ms": 310,
      "timestamp": "2026-06-01T12:00:01Z"
    }
  ]
}
```

`outcome`: `'success'` | `'failed'` | `'running'` | `'pending'`

**If no onboarding has run yet:** `404`

### POST /api/servers/:id/onboard

Starts or retries onboarding. No request body needed.

**Responses:**
- `202 Accepted` — job enqueued
- `409 Conflict` — onboarding already running for this server
- `403` — not admin

---

## 11. Empty & Edge States Summary

| Scenario | Behaviour |
|---|---|
| Server added — onboarding auto-starts | Card immediately shows ONBOARDING with step 1 |
| Admin closes the panel mid-onboarding | Onboarding continues in background; inline card shows live step |
| Admin navigates away from servers page | Onboarding still runs; card updates when admin returns |
| Onboarding fails at SSH step | Edit Server modal pre-opens to fix credentials if admin clicks `Edit Server` |
| Verify step times out (30s) but soft-fails | Server marked active; warning shown in log; toast on dashboard when metrics eventually appear |
| MariaDB not present on server | Step 8 silently skipped — no error, no warning to admin |
| MariaDB present but slow log enable fails | Step 8 logged as warning (non-blocking) — admin can enable it manually |
| Re-deploy triggered (DB creds saved) | Runs steps 6–10 only; no new OnboardingLog — logged in server's activity log |
| Panel opened for already-online server | Shows historical log (read-only), `Retry Onboarding` still available |
| Two admins both click Retry simultaneously | Second request gets 409 — toast: "Onboarding already in progress" |
| Server deleted mid-onboarding | APScheduler job detects server no longer active and exits cleanly |
