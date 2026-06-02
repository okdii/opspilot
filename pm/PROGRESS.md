# OpsPilot — Development Progress

**Legend:** ✅ Done · 🔄 In Progress · ⬜ Pending · 🚫 Blocked

Last updated: 2026-06-02

---

## Phase 1 — Foundation
*Project setup, Docker, DB schema, auth, server CRUD, onboarding SSH*

### Infrastructure
- ✅ Docker Compose stack (migrate, backend, frontend, postgres, nginx)
- ✅ PostgreSQL + TimescaleDB container configured
- ✅ `migrate` one-shot service (alembic upgrade head before backend starts)
- ✅ Environment variables validated on startup (abort if missing)
- ✅ Nginx reverse proxy config (route /api → backend, / → frontend)

### Database — Alembic Migrations
- ✅ All relational tables created (Organization, User, UserOrganization, Invite, Session, Server, Service, Incident, Domain, SSLCert, Alert, AlertRule, LogAlertRule, MaintenanceWindow, CronJob, CronJobRun, BackupJob, BackupRun, DBCredential, Settings, OnboardingLog)
- ✅ TimescaleDB hypertables created (server_metrics, server_logs, service_checks)
- ✅ Continuous aggregate views (server_metrics_hourly, server_metrics_daily)
- ✅ Indexes created (server_metrics: server_id + metric_name + time DESC, server_logs: source/severity + time DESC, tsvector on message)
- ✅ Retention policies applied (metrics 30d, logs 30d, service_checks 90d)
- ✅ `opspilot_writer` user created with INSERT-only grants on hypertables

### Authentication (spec 01)
- ✅ POST /api/setup/register — first-run admin account creation
- ✅ GET /api/setup/status — returns setup_required flag
- ✅ POST /api/auth/login — JWT httpOnly cookie issued
- ✅ POST /api/auth/logout — session revoked, cookie cleared
- ✅ GET /api/auth/me — current user + orgs
- ✅ GET /api/ws-ticket — one-time WS upgrade ticket
- ✅ GET /api/invite/:token — validate invite token
- ✅ POST /api/invite/:token/accept — accept invite, create user, issue cookie
- ✅ PATCH /api/auth/password — change own password
- ✅ Session table jti revocation on every request
- ✅ Login rate limiting (10 attempts / IP / 15 min)
- ✅ Nightly session cleanup APScheduler job
- ✅ **Smoke test: login, logout, 401 redirect, WS ticket flow**

### Frontend — Auth Screens (spec 01)
- ✅ /setup page (first-run admin registration)
- ✅ /login page (username + password, show/hide, error states)
- ✅ /invite/:token page (validate token, create account)
- ✅ /profile page (all roles — password change)
- ✅ Route guards (setup → login → app flow)
- ✅ Global 401 interceptor → redirect to /login?reason=expired
- ✅ WS reconnect logic (exponential backoff, re-subscribe)
- ✅ Pinia auth store (isAdmin, canEdit, canActOnAlerts getters)
- ✅ **Smoke test: full login/logout, session expiry, invite acceptance**

### Organizations (spec 02)
- ✅ GET/POST/PATCH/DELETE /api/organizations
- ✅ Org switcher in sidebar (Admin sees all + aggregate; Members see assigned)
- ✅ Org delete blocked if resources exist
- ✅ **Smoke test: create, edit, switch org, delete guard**

### Server Management (spec 03)
- ✅ GET/POST/PATCH/DELETE /api/servers
- ✅ Server list/grid page (/servers)
- ✅ Add/edit server form (SSH key or password auth)
- ✅ SSH credentials stored AES-256 encrypted
- ✅ Server soft-delete (cascade to services, alert rules, etc.)

### Server Onboarding — SSH Auto-Deploy (spec 03)
- ✅ Reusable async SSH executor service (asyncssh) — `app/services/ssh.py`
- ✅ SSH connection validation endpoint (POST /api/servers/:id/ssh-test)
- ✅ OS detection (Ubuntu/Debian vs RHEL/CentOS)
- ✅ Add vendor repos (InfluxData for Telegraf, Chronosphere for Fluent Bit)
- ✅ Install Telegraf via apt/yum
- ✅ Install Fluent Bit via apt/yum
- ✅ Generate telegraf.conf from Jinja2 template (server_id, writer credentials, plugins)
- ✅ Generate fluent-bit.conf from Jinja2 template (server_id, log paths per distro)
- ✅ Enable slow_query_log if MariaDB detected
- ✅ Write configs to /etc/telegraf/ and /etc/fluent-bit/
- ✅ Enable + start both services via systemctl
- ✅ Wait up to 30s for first metric row in TimescaleDB *(verified on Lima Ubuntu 24.04 VM — "first metric in 6s")*
- ✅ Mark server active, push onboarding_complete WS event *(verified live over WS — onboarding_complete received, duration_sec 8)*
- ✅ OnboardingLog rows written per step
- ✅ Re-deploy agents endpoint (steps 6–10 only)
- ✅ WS channel: onboarding:{server_id} — progress events pushed live
- ✅ Onboarding UI: progress steps, error display, SSH log output
- ✅ **Smoke test: add server, watch onboarding complete, see first metric in DB** *(verified end-to-end on Lima Ubuntu 24.04 VM — all 10 steps done over WS, onboarding_complete received, server `online`, ~633 metric rows flowing. Fixed a gzip-ingestion bug found during the test: `/api/ingest/metrics` now decompresses gzip/deflate bodies, see ingest.py.)*

---

## Phase 2 — Live Dashboard & Charts
*WebSocket live dashboard, historical metric charts*

### WebSocket Infrastructure (spec 01, spec 04)
- ✅ FastAPI WS fan-out *(implemented as in-process live bus, not LISTEN/NOTIFY — see PRD §5.4.8; verified live on lima-ubuntu)*
- ✅ 500ms event batching before WS push *(verified: 211-row Telegraf flush coalesced into one WS message)*
- ✅ WS channel authorization per subscribe message *(verified: non-member denied with `forbidden` frame)*
- ✅ subscribe_org / subscribe (server) / unsubscribe + unsubscribe_org actions
- ✅ **Smoke test: open dashboard, verify live metric updates arrive** *(verified on lima-ubuntu via Playwright — CPU bar rose 0%→100% live with no reload when the VM was load-spiked)*

### Global Dashboard (spec 04)
- ✅ GET /api/organizations/:org_id/dashboard — summary + server latest metrics
- ✅ GET /api/organizations/:org_id/alerts/recent — last 10 alerts *(returns [] until Phase 8 populates alerts)*
- ✅ Summary stat cards (Servers, Services, Alerts, SSL/Domains) *(Servers live; Services/Alerts/SSL return 0 until their phases)*
- ✅ Server card grid with live metric bars (CPU/RAM/Disk progress bars)
- 🔄 Recent Alerts panel with [Ack] button *(panel + empty state shipped; [Ack] deferred to Phase 8 per design)*
- ✅ Live card updates via WS (applyMetricPush)
- 🔄 **Smoke test: dashboard loads, cards update live, [Ack] works** *(dashboard loads + live CPU/RAM/Disk bars verified on lima-ubuntu via Playwright; [Ack] deferred to Phase 8)*

### Server Detail — Metrics (spec 04)
- ✅ GET /api/servers/:id/metrics — chart data (range + metric filter) *(Telegraf name map, server-side counter→rate, disk fstype filter; verified live)*
- ✅ GET /api/servers/:id/metrics/latest — live gauge initial state
- 🔄 GET /api/servers/:id/processes — top_processes snapshot *(501 stub — deferred: needs agent procstat, Phase 1 Telegraf follow-up)*
- ✅ 4 live gauge cards (CPU, RAM, Disk, Network) *(verified: live WS, CPU rose 1%→100% on VM spike, no reload)*
- ✅ Tab navigation (Overview, CPU, Memory, Disk, Network, System, Processes) *(all 6 metric tabs built; Processes tab disabled — deferred to Phase 1 agent procstat)*
- ✅ Time range selector (1h/6h/24h/7d/30d) — correct data source per range *(raw 1h/6h, hourly 24h, daily 7d/30d)*
- ✅ All chart types (area, stacked area, line, dual-line, bar, radial gauge, donut, horizontal bar) *(all present across tabs via shared MetricChart)*
- ✅ 24h live WS update: rightmost hourly bucket updated in place (no re-fetch) *(implemented in useMetricsStore; live WS verified)*
- ✅ Maintenance mode badge + slide-over (enable, active state, end maintenance) *(verified: badge Maintenance↔Online)*
- ✅ POST/DELETE/GET /api/servers/:id/maintenance *(nullable ends_at, suppresses active alerts, 60s expiry job)*
- ✅ **Smoke test: all 7 tabs render, charts update live, 24h bucket behavior** *(Playwright on lima-ubuntu: all 6 tabs render, 0 page errors, Processes disabled; CPU gauge rose 1%→100% live via WS, no reload)*

---

## Phase 3 — Log Viewer
*Backend reads server_logs, Log Viewer UI*

### Log Viewer (spec 05)
- ⬜ GET /api/servers/:id/logs — paginated (cursor, max 500 rows)
- ⬜ Filters: server, source (9 sources), severity, time range, full-text search
- ⬜ Live tail mode via WS (server_logs:{server_id} channel)
- ⬜ Expandable rows (all JSONB fields)
- ⬜ Log volume stacked bar chart (by hour, stacked by severity)
- ⬜ **Smoke test: filter logs, search, live tail shows new entries**

---

## Phase 4 — Service Monitoring
*HTTP/TCP probes, ServiceCheck hypertable, Incident model, uptime timeline*

### Service Monitoring (spec 06)
- ⬜ GET /api/organizations/:org_id/services — list all services
- ⬜ POST /api/services — create service (Admin)
- ⬜ PATCH/DELETE /api/services/:id (Admin)
- ⬜ GET /api/services/:id/checks — check history
- ⬜ GET /api/services/:id/uptime — uptime % (24h/7d/30d)
- ⬜ GET /api/services/:id/incidents — incident list
- ⬜ GET /status — public status page data
- ⬜ HTTP probe (url, method, expected status, timeout, ignore_ssl_errors)
- ⬜ TCP probe (host, port)
- ⬜ DB port probe (host, port — TCP reachability)
- ⬜ asyncio Semaphore(50) for probe concurrency
- ⬜ Service.consecutive_failures persisted to DB (resets on success, alert at 2)
- ⬜ Incident created on 2nd consecutive failure
- ⬜ APScheduler job per service (service_probe:{service_id})
- ⬜ /services page (list, add/edit modal, status badges)
- ⬜ Service detail (uptime timeline, response time chart, incident list)
- ⬜ Public /status page (unauthenticated, is_public services only)
- ⬜ **Smoke test: add HTTP service, kill it, see alert fire after 2 failures, restore, see resolve**

---

## Phase 5 — SSL & Domain Monitoring
*Daily SSL/WHOIS checks, combined table UI*

### SSL & Domain (spec 07)
- ⬜ GET /api/organizations/:org_id/ssl-domains — combined list
- ⬜ POST /api/ssl-certs + POST /api/domains (Admin)
- ⬜ PATCH/DELETE for both (Admin)
- ⬜ POST /api/ssl-certs/:id/check + POST /api/domains/:id/check (manual trigger)
- ⬜ ssl_checker_daily APScheduler job (daily SSL cert checks)
- ⬜ domain_checker_daily APScheduler job (staggered 30s between WHOIS lookups)
- ⬜ SSLCert status: valid / expiring_soon / critical / expired / unreachable
- ⬜ Domain status: valid / expiring_soon / critical / expired
- ⬜ Alert threshold evaluation (warn_days, critical_days per record)
- ⬜ /ssl-domains page (combined table, expiry progress bars, timeline chart)
- ⬜ **Smoke test: add cert, trigger manual check, see status update**

---

## Phase 6 — Database Monitoring
*Telegraf inputs.mysql, DB health charts, replication*

### Database Monitoring (spec 08)
- ⬜ GET /api/organizations/:org_id/db-credentials
- ⬜ POST/PATCH/DELETE /api/servers/:id/db-credentials (Admin)
- ⬜ GET /api/servers/:id/db-metrics/latest
- ⬜ GET /api/servers/:id/db-metrics (time-series)
- ⬜ Credential save triggers automatic Telegraf re-deploy via SSH
- ⬜ inputs.mysql block injected into telegraf.conf (gather_slave_status per is_replica)
- ⬜ innodb_deadlocks delta tracking (DBCredential.last_deadlock_count)
- ⬜ Alert evaluation: db_connections, db_deadlock, db_replication_lag, db_replication_stopped
- ⬜ /databases page (server tab strip, no-credentials state, health dashboard)
- ⬜ All DB charts (connections gauge + line, QPS area, slow queries bar, buffer pool gauge, deadlocks bar, replication section, advanced metrics panel)
- ⬜ **Smoke test: enter credentials, watch Telegraf re-deploy, see DB metrics appear**

---

## Phase 7 — Cron & Backup Monitoring
*Heartbeat ping endpoint, calendar heatmap UI*

### Cron & Backup (spec 09)
- ⬜ GET /ping/:token — cron job ping (single + two-ping ?event=start/end)
- ⬜ POST /ping/:token — backup job ping (form body: size_bytes, exit_code)
- ⬜ GET /api/organizations/:org_id/cron-jobs
- ⬜ POST/PATCH/DELETE /api/cron-jobs (Admin)
- ⬜ GET /api/cron-jobs/:id/runs (cursor-paginated)
- ⬜ POST /api/cron-jobs/:id/regenerate-token (Admin)
- ⬜ Same endpoints for backup-jobs
- ⬜ cron_backup_watchdog APScheduler job (60s tick, status transitions, missed run writes)
- ⬜ Two-ping: start ping sets start_ping_at only (does NOT update last_ping_at)
- ⬜ Backup: exit_code authoritative, previous_size_bytes baseline management
- ⬜ /cron-backup page (two tabs, job list sorted Missing→Late→Healthy)
- ⬜ Job detail slide-over (ping URL, calendar heatmap, duration/size trend, run history)
- ⬜ **Smoke test: register job, ping it, miss a window, see Missing status + alert**

---

## Phase 8 — Alerting Engine
*Metric evaluator, log evaluator, auto-resolve, email, ack/snooze, maintenance*

### Alerting (spec 10)
- ⬜ metric_alert_evaluator APScheduler job (30s tick — rolling 5-min avg)
- ⬜ log_alert_evaluator APScheduler job (60s tick — ILIKE pattern matching)
- ⬜ consecutive_clear_count persisted on Alert row (auto-resolve at 2)
- ⬜ maintenance_expiry APScheduler job (60s tick — auto-end expired windows)
- ⬜ Maintenance enter: immediately suppress all firing/acked/snoozed alerts for server
- ⬜ SMTP email delivery (text/plain; charset=utf-8, no HTML)
- ⬜ base_url fallback: str(request.base_url) if Settings.base_url not set
- ⬜ Alert auto-creation on onboarding (4 AlertRule + 5 LogAlertRule rows)
- ⬜ Cooldown enforcement (last_fired_at on AlertRule/LogAlertRule, hardcoded 1h for others)
- ⬜ Alert dedup per (type, relevant_fk) — one open alert at a time
- ⬜ Acknowledge + Snooze actions (POST /api/alerts/:id/acknowledge, /snooze)
- ⬜ WS push: alert_fired, alert_updated, alert_resolved events
- ⬜ GET /api/organizations/:org_id/alerts — active (firing + acked + snoozed)
- ⬜ GET /api/organizations/:org_id/alerts/history — resolved (cursor-paginated)
- ⬜ GET /api/organizations/:org_id/alerts/frequency — daily counts for bar chart
- ⬜ GET/POST/PATCH/DELETE /api/alert-rules (Admin)
- ⬜ GET/POST/PATCH/DELETE /api/log-alert-rules (Admin)
- ⬜ /alerts page (Active tab + History tab + frequency bar chart)
- ⬜ /alerts/rules page (Metric Rules + Log Pattern Rules tables)
- ⬜ Notification bell (badge count, dropdown panel, toast on alert_fired)
- ⬜ Alert detail slide-over (timeline, rule info, ack/snooze actions)
- ⬜ **Smoke test: spike CPU, see alert fire + email, let it clear x2, see resolve email**

---

## Phase 9 — Public Status Page
*Unauthenticated /status route*

### Status Page (spec 06 §public)
- ⬜ GET /status — unauthenticated, is_public services only
- ⬜ 90-day uptime timeline per service
- ⬜ Active incident banner
- ⬜ Past incident list
- ⬜ is_public toggle per service (Admin)
- ⬜ **Smoke test: toggle is_public, open /status in incognito, verify no auth required**

---

## Phase 10 — Settings
*SMTP, identity, retention, sessions, agent password rotation*

### Settings (spec 11)
- ✅ GET/PATCH /api/settings
- ✅ POST /api/settings/smtp/test
- ✅ GET /api/team — members + pending invites
- ✅ POST /api/invites + resend + revoke
- ✅ POST /api/users/:id/org-assignments + DELETE
- ✅ DELETE /api/users/:id (sole-operator guard → 409)
- ✅ GET/PATCH /api/sessions/:jti/revoke + revoke-others
- ✅ POST /api/settings/rotate-writer-password (rotation_id → poll status; WS deferred to Phase 2)
- ✅ /settings/general (instance name, base URL, SMTP)
- ✅ /settings/team (member list, pending invites, invite modal)
- ✅ /settings/retention (retention fields, TimescaleDB policy update)
- ✅ /settings/security (active sessions table, password change)
- ✅ /settings/infrastructure (writer password rotation + progress panel)
- ✅ **Smoke test: save SMTP, send test email, rotate writer password, watch progress** *(verified live: SMTP save + test email received in mailpit; writer rotation across 2 active servers with per-server progress ok, metrics resumed)*

---

## Phase 11 — Docker Packaging & Deployment
*Final packaging, deployment runbook*

### Deployment (spec — PRD §5.18)
- ⬜ Final docker-compose.yml (all 5 services wired up)
- ⬜ Nginx configs (TLS termination, reverse proxy rules)
- ⬜ Alembic migration validated (migrate service runs clean on fresh DB)
- ⬜ Environment variable documentation (.env.example)
- ⬜ Telegraf + Fluent Bit config templates finalized
- ⬜ Deployment runbook (firewall setup, port 5432 restriction, first-run steps)
- ⬜ **Smoke test: fresh docker compose up, complete full onboarding + alert cycle end-to-end**

---

## Summary

| Phase | Status | Tasks Done |
|---|---|---|
| Phase 1 — Foundation | ✅ Complete | 60 / 60 |
| Phase 2 — Live Dashboard | 🔄 In Progress | 10 / 20 |
| Phase 3 — Log Viewer | ⬜ Pending | 0 / 6 |
| Phase 4 — Service Monitoring | ⬜ Pending | 0 / 17 |
| Phase 5 — SSL & Domain | ⬜ Pending | 0 / 13 |
| Phase 6 — Database Monitoring | ⬜ Pending | 0 / 14 |
| Phase 7 — Cron & Backup | ⬜ Pending | 0 / 14 |
| Phase 8 — Alerting Engine | ⬜ Pending | 0 / 21 |
| Phase 9 — Status Page | ⬜ Pending | 0 / 5 |
| Phase 10 — Settings | ✅ Complete | 16 / 16 |
| Phase 11 — Deployment | ⬜ Pending | 0 / 6 |
| **Total** | 🔄 In Progress | **86 / 191** |
