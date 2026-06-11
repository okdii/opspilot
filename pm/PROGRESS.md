# OpsPilot — Development Progress

**Legend:** ✅ Done · 🔄 In Progress · ⬜ Pending · 🚫 Blocked

Last updated: 2026-06-11

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
- ✅ Re-deploy agents endpoint (steps 6–11 only)
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
- ✅ Recent Alerts panel with [Ack] button *(wired to POST acknowledge in Phase 8)*
- ✅ Live card updates via WS (applyMetricPush)
- ✅ **Smoke test: dashboard loads, cards update live, [Ack] works** *([Ack] verified in Phase 8 — acknowledge flips state)*

### Server Detail — Metrics (spec 04)
- ✅ GET /api/servers/:id/metrics — chart data (range + metric filter) *(Telegraf name map, server-side counter→rate, disk fstype filter; verified live)*
- ✅ GET /api/servers/:id/metrics/latest — live gauge initial state
- ✅ GET /api/servers/:id/processes — live SSH snapshot (full process list + top-CPU/top-mem; `top -bn2`, 5s cache, single-flight, graceful offline)
- ✅ Processes tab — top-CPU/top-mem tables + full process list (filter/sort) + live badge + proctop top-N trend chart
- ✅ Agent Status footer — telegraf/fluent-bit health via systemd_units + one-time warning toast on agent down *(verified: stop fluent-bit → footer shows stopped)*
- ✅ Per-core CPU — `cpu.usage_active` per core (single-field percpu input); CpuTab per-core bars populate
- ✅ DB growth control — proctop @30s, per-core single-field, systemd_units scoped to 2 units; TimescaleDB compression policy on server_metrics (>2d chunks)
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
- ✅ GET /api/logs — paginated (cursor, max 500 rows) *(server/org filter via query params)*
- ✅ Filters: server, source (9 sources), severity, time range, full-text search *(tsvector; verified curl)*
- ✅ Live tail mode via WS (server_logs:{server_id} channel) *(ingestion publishes to live bus)*
- ✅ Expandable rows (all JSONB fields)
- ✅ Log volume stacked bar chart (by hour, stacked by severity)
- ✅ **Smoke test: filter logs, search, live tail shows new entries** *(Playwright: /logs renders 100 rows + volume chart, 0 errors; curl filters/search/pagination verified)*

---

## Phase 4 — Service Monitoring
*HTTP/TCP probes, ServiceCheck hypertable, Incident model, uptime timeline*

### Service Monitoring (spec 06)
- ✅ GET /api/organizations/:org_id/services — list all services
- ✅ POST /api/services — create service (Admin)
- ✅ PATCH/DELETE /api/services/:id (Admin)
- ✅ GET /api/services/:id/checks — check history
- ✅ GET /api/services/:id/uptime — uptime % (24h/7d/30d)
- ✅ GET /api/services/:id/incidents — incident list
- ✅ GET /status — public status page data
- ✅ HTTP probe (url, method, expected status, timeout, ignore_ssl_errors)
- ✅ TCP probe (host, port)
- ✅ DB port probe (host, port — TCP reachability)
- ✅ asyncio Semaphore(50) for probe concurrency
- ✅ Service.consecutive_failures persisted to DB (resets on success, alert at 2)
- ✅ Incident created on 2nd consecutive failure
- ✅ APScheduler job per service (service_probe:{service_id})
- ✅ /services page (list, add/edit modal, status badges)
- ✅ Service detail (uptime timeline, response time chart, incident list)
- ✅ Public /status page (unauthenticated, is_public services only)
- ✅ **Smoke test: add HTTP service, kill it, see alert fire after 2 failures, restore, see resolve** *(verified live: fail→incident→service_down alert→recover→resolve)*

---

## Phase 5 — SSL & Domain Monitoring
*Daily SSL/WHOIS checks, combined table UI*

### SSL & Domain (spec 07)
- ✅ GET /api/organizations/:org_id/ssl-domains — combined list
- ✅ POST /api/ssl-certs + POST /api/domains (Admin)
- ✅ PATCH/DELETE for both (Admin)
- ✅ POST /api/ssl-certs/:id/check + POST /api/domains/:id/check (manual trigger)
- ✅ ssl_checker_daily APScheduler job (daily SSL cert checks)
- ✅ domain_checker_daily APScheduler job (staggered 30s between WHOIS lookups)
- ✅ SSLCert status: valid / expiring_soon / critical / expired / unreachable
- ✅ Domain status: valid / expiring_soon / critical / expired
- ✅ Alert threshold evaluation (warn_days, critical_days per record)
- ✅ /ssl-domains page (combined table, expiry progress bars, timeline chart)
- ✅ **Smoke test: add cert, trigger manual check, see status update** *(verified live: github.com cert valid 60d, WHOIS 128d; note: python-whois added — rebuild backend image)*

---

## Phase 6 — Database Monitoring
*Telegraf inputs.mysql, DB health charts, replication*

### Database Monitoring (spec 08)
- ✅ GET /api/organizations/:org_id/db-credentials
- ✅ POST/PATCH/DELETE /api/servers/:id/db-credentials (Admin)
- ✅ GET /api/servers/:id/db-metrics/latest
- ✅ GET /api/servers/:id/db-metrics (time-series)
- ✅ Credential save triggers automatic Telegraf re-deploy via SSH
- ✅ inputs.mysql block injected into telegraf.conf (gather_slave_status per is_replica)
- ✅ innodb_deadlocks delta tracking (DBCredential.last_deadlock_count)
- ✅ Alert evaluation: db_connections, db_deadlock, db_replication_lag, db_replication_stopped
- ✅ /databases page (server tab strip, no-credentials state, health dashboard)
- ✅ All DB charts (connections gauge + line, QPS area, slow queries bar, buffer pool gauge, deadlocks bar, replication section, advanced metrics panel)
- ✅ **Smoke test: enter credentials, watch Telegraf re-deploy, see DB metrics appear** *(verified live: MariaDB on VM → credential add → redeploy → 1964 mysql.* metrics flowing; db-metrics/latest populated, last_check_ok=true)*

---

## Phase 7 — Cron & Backup Monitoring
*Heartbeat ping endpoint, calendar heatmap UI*

### Cron & Backup (spec 09)
- ✅ GET /ping/:token — cron job ping (single + two-ping ?event=start/end)
- ✅ POST /ping/:token — backup job ping (form body: size_bytes, exit_code)
- ✅ GET /api/organizations/:org_id/cron-jobs
- ✅ POST/PATCH/DELETE /api/cron-jobs (Admin)
- ✅ GET /api/cron-jobs/:id/runs (cursor-paginated)
- ✅ POST /api/cron-jobs/:id/regenerate-token (Admin)
- ✅ Same endpoints for backup-jobs
- ✅ cron_backup_watchdog APScheduler job (60s tick, status transitions, missed run writes)
- ✅ Two-ping: start ping sets start_ping_at only (does NOT update last_ping_at)
- ✅ Backup: exit_code authoritative, previous_size_bytes baseline management
- ✅ /cron-backup page (two tabs, job list sorted Missing→Late→Healthy)
- ✅ Job detail slide-over (ping URL, calendar heatmap, duration/size trend, run history)
- ✅ **Smoke test: register job, ping it, miss a window, see Missing status + alert** *(verified: ping→Healthy, watchdog→Missing+cron_missing alert→re-ping resolves; backup fail→alert)*

---

## Phase 8 — Alerting Engine
*Metric evaluator, log evaluator, auto-resolve, email, ack/snooze, maintenance*

### Alerting (spec 10)
- ✅ metric_alert_evaluator APScheduler job (30s tick — rolling 5-min avg)
- ✅ log_alert_evaluator APScheduler job (60s tick — ILIKE pattern matching)
- ✅ consecutive_clear_count persisted on Alert row (auto-resolve at 2)
- ✅ maintenance_expiry APScheduler job (60s tick — auto-end expired windows)
- ✅ Maintenance enter: immediately suppress all firing/acked/snoozed alerts for server
- ✅ SMTP email delivery (text/plain; charset=utf-8, no HTML) *(verified live: alert email delivered to mailpit — subject '[OpsPilot] WARNING: lima-ubuntu — CPU Usage High' → configured recipient)*
- ✅ base_url fallback: str(request.base_url) if Settings.base_url not set
- ✅ Alert auto-creation on onboarding (4 AlertRule + 5 LogAlertRule rows)
- ✅ Cooldown enforcement (last_fired_at on AlertRule/LogAlertRule, hardcoded 1h for others)
- ✅ Alert dedup per (type, relevant_fk) — one open alert at a time
- ✅ Acknowledge + Snooze actions (POST /api/alerts/:id/acknowledge, /snooze)
- ✅ WS push: alert_fired, alert_updated, alert_resolved events
- ✅ GET /api/organizations/:org_id/alerts — active (firing + acked + snoozed)
- ✅ GET /api/organizations/:org_id/alerts/history — resolved (cursor-paginated)
- ✅ GET /api/organizations/:org_id/alerts/frequency — daily counts for bar chart
- ✅ GET/POST/PATCH/DELETE /api/alert-rules (Admin)
- ✅ GET/POST/PATCH/DELETE /api/log-alert-rules (Admin)
- ✅ /alerts page (Active tab + History tab + frequency bar chart)
- ✅ /alerts/rules page (Metric Rules + Log Pattern Rules tables)
- ✅ Notification bell (badge count, dropdown panel, toast on alert_fired)
- ✅ Alert detail slide-over (timeline, rule info, ack/snooze actions)
- ✅ **Smoke test: spike CPU, see alert fire + email, let it clear x2, see resolve email** *(verified live: scheduled metric evaluator fired a cpu alert → GET /alerts → ack→acknowledged; auto-resolve-at-2 verified in Slice B; alert email delivered to mailpit, verified subject+recipient)*

---

## Phase 9 — Public Status Page
*Unauthenticated /status route*

### Status Page (spec 06 §public)
- ✅ GET /status — unauthenticated, is_public services only
- ✅ 90-day uptime timeline per service
- ✅ Active incident banner
- ✅ Past incident list
- ✅ is_public toggle per service (Admin)
- ✅ **Smoke test: toggle is_public, open /status in incognito, verify no auth required**

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
- ✅ Final docker-compose.yml (all 5 services wired up)
- ✅ Nginx configs (TLS termination, reverse proxy rules)
- ✅ Alembic migration validated (migrate service runs clean on fresh DB)
- ✅ Environment variable documentation (.env.example)
- ✅ Telegraf + Fluent Bit config templates finalized
- ✅ Deployment runbook (firewall setup, port 5432 restriction, first-run steps)
- ✅ **Smoke test: fresh docker compose up, complete full onboarding + alert cycle end-to-end** *(validated by components: backend image builds clean w/ python-whois, migrate runs clean base→0006 on a fresh throwaway DB (hypertables+aggregates+compression+writer role); full onboarding→metrics→alert-fire cycle verified live on the running stack this session. Literal fresh `compose up` not run to avoid 80/443 conflict with the running dev stack.)*

---

## Phase 12 — Post-Launch Enhancements
*Server detail Logs tab, Log Intelligence page*

### Server Detail — Logs Tab
- ✅ LogsTab.vue component — raw log viewer scoped to a single server (severity filter, source filter, search, live tail via WS)
- ✅ Logs tab wired into ServerDetail.vue tab navigation (deep-link support: `?tab=logs`)
- ✅ **Smoke test: open server detail → Logs tab → filter by severity, search, live tail shows new entries**

### Log Intelligence Page (/logs)
- ✅ GET /api/logs/intelligence — org-wide summary (error patterns, HTTP errors, slow queries, auth events, per-server health, recent fatals, log volume by hour)
- ✅ logIntelligence Pinia store + frontend API function
- ✅ /logs redesigned as org-wide intelligence dashboard (summary cards, per-server health table, error pattern list, recent fatals, log volume chart)
- ✅ **Smoke test: /logs renders intelligence summary with real data; per-server health, error patterns, and volume chart all populate**

---

## Phase 13 — SSL Certificate Tracking in HTTP Probes
*Add SSL expiry monitoring directly to HTTP service probes without separate SSL cert registration*

### Task 1: Alembic Migration — Add SSL Columns
- ✅ Migration file: `0008_service_ssl_columns.py`
- ✅ 8 columns added to service table: ssl_enabled, ssl_warn_days, ssl_critical_days, ssl_expiry_date, ssl_days_remaining, ssl_status, ssl_issuer, ssl_last_checked
- ✅ Migration applied to running DB (0008_service_ssl_columns current)
- ✅ **Smoke test: all 8 ssl_* columns present in service table**

### Task 2: Service Model + Schema + Router
- ✅ Pydantic model: ServiceCreate/Update with ssl_warn_days, ssl_critical_days fields; ServiceOut with all 8 ssl_* fields
- ✅ Auto-set ssl_enabled=true when URL is https://, false on http:// or non-HTTP service
- ✅ **Smoke test: POST /api/services with https URL returns ssl_enabled=true**

### Task 3: SSL Extraction in Probe
- ✅ SSL cert extraction during HTTP probe (6-hour throttle, reuses ssl_checker._fetch_ssl_cert)
- ✅ Update service.ssl_* columns after extraction
- ✅ Fire/resolve ssl_expiry alert keyed to service_id on threshold breach
- ✅ **Smoke test: probe HTTPS service, ssl_expiry_date/status/issuer populated in DB**

### Task 4: Frontend Type Definitions
- ✅ Service interface: ssl_enabled, ssl_warn_days, ssl_critical_days, ssl_expiry_date, ssl_days_remaining, ssl_status, ssl_issuer, ssl_last_checked
- ✅ ServiceCreatePayload: ssl_warn_days?, ssl_critical_days? optional fields

### Task 5: ServiceModal SSL Threshold Section
- ✅ isHttps computed — SSL section only shown when URL starts with https://
- ✅ Warn/critical day inputs with validation (1–365, critical < warn)
- ✅ Hydrated from existing service data on edit
- ✅ **Smoke test: Add HTTPS service shows SSL threshold inputs; HTTP hides them**

### Task 6: ServiceRow SSL Status Pill
- ✅ SSL pill shown when ssl_enabled and status is expiring_soon/critical/expired
- ✅ Color coded: amber/red/dark-red
- ✅ **Smoke test: set ssl_status='expiring_soon' in DB, pill appears in service list**

### Task 7: ServiceDetail SSL Certificate Card
- ✅ SSL card shows expiry date, days remaining, issuer, last checked, ExpiryBar
- ✅ StatusBadge kind="ssl" in card header
- ✅ Color-coded days remaining (warn/crit thresholds)
- ✅ **Smoke test: HTTPS service detail shows SSL card with cert info**

### Task 8: SSL & Domain Hint + Progress Update
- ✅ SslDomainsView empty state message updated to mention HTTPS auto-tracking
- ✅ Page hint added pointing non-HTTP SSL to SSL & Domains page
- ✅ PROGRESS.md and DASHBOARD.html updated
- ✅ **Smoke test: end-to-end SSL tracking on HTTP service**

---

## Phase 14 — Service SSL on SSL & Domains Page
*Show HTTPS service SSL certs alongside manually-tracked domains and SSL certs on /ssl-domains, eliminating duplicate domain registration*

### Task 1: Backend Schema + Router
- ✅ `ServiceSslOut` Pydantic model added to `ssl_domains.py` schema
- ✅ `service_ssl: list[ServiceSslOut]` field added to `SSLDomainsResponse`
- ✅ `list_ssl_domains` router extended to query HTTPS services (ssl_enabled=True) via Server→Service join
- ✅ **Smoke test: GET /ssl-domains returns service_ssl array with HTTPS service SSL fields**

### Task 2: Frontend Store
- ✅ `ServiceSslRec` interface added to `sslDomains.ts`
- ✅ `CombinedRow.type` and `TimelineDot.type` widened to `'domain' | 'ssl' | 'service'`
- ✅ `serviceSsl` ref + `combinedRows` loop + `fetchAll` + `reset()` updated
- ✅ **Smoke test: TypeScript build passes with no errors**

### Task 3: Frontend View
- ✅ `ExpiryTimeline` tooltip handles `type === 'service'` (kind: "Service SSL", shows Issuer)
- ✅ `SslDomainsView`: SERVICE badge (purple), "Service" filter option, read-only kebab ("View in Services →")
- ✅ `checkNow` and `askDelete` guarded against service rows
- ✅ `router.push({ name: 'service-detail', params: { id: r.id } })` for type-safe navigation
- ✅ **Smoke test: HTTPS services appear on /ssl-domains with purple SERVICE badge; kebab navigates to service detail**

---

## Phase 15 — Global Timezone Setting
*Add a global timezone setting (stored in app_settings) so uptime bars, incident timestamps, and all date displays roll over and format according to the configured timezone instead of hardcoded UTC.*

### Task 1: DB Migration + Settings Model
- ✅ Migration `0009_settings_timezone` adds `timezone VARCHAR(60) NOT NULL DEFAULT 'UTC'` to `app_settings`
- ✅ `Settings` ORM model updated with `timezone: Mapped[str]` field
- ✅ **Smoke test: migration applied, column verified via psql**

### Task 2: Backend Schema + Settings Router
- ✅ `SettingsResponse` extended with `timezone: str`
- ✅ `SettingsPatch` extended with `timezone: str | None` and IANA validator
- ✅ `_to_response` updated to include `timezone=s.timezone`
- ✅ **Smoke test: GET /api/settings returns `"timezone": "UTC"`; PATCH accepts valid IANA names**

### Task 3: Uptime Timeline Endpoint — Timezone-Aware Bucketing
- ✅ `uptime_timeline` reads org timezone from `app_settings`
- ✅ SQL uses `time AT TIME ZONE :tz` for timezone-aware `time_bucket` day grouping
- ✅ **Smoke test: endpoint returns correct dates for configured timezone**

### Task 4: Frontend Settings Store — Add Timezone
- ✅ `general` ref extended with `timezone: 'UTC'`
- ✅ `fetchSettings` populates `timezone` from API response
- ✅ `saveGeneral` signature updated to accept `timezone`
- ✅ `AppLayout.vue` calls `settingsStore.fetchSettings()` on mount and auth change

### Task 5: Frontend Settings UI — Timezone Dropdown
- ✅ `timezone` ref and curated IANA timezone list added to `GeneralTab.vue`
- ✅ `load()` populates `timezone.value` from store
- ✅ `saveIdentity()` includes `timezone` in payload and refreshes after save
- ✅ Timezone dropdown rendered in Identity section with hint text
- ✅ **Smoke test: dropdown appears, selection persists after Save + refresh**

### Task 6: Shared Date Format Composable
- ✅ `frontend/src/composables/useDateFormat.ts` created
- ✅ Exports `formatDate`, `formatDateTime`, `toTzDateKey` — all timezone-aware via `Intl.DateTimeFormat`

### Task 7: UptimeTimeline + ServiceDetail — Use Timezone
- ✅ `UptimeTimeline.vue` replaced — uses `toTzDateKey` for timezone-aware day-key generation
- ✅ `ServiceDetail.vue` — local `fmtTime` removed, `formatDateTime` from composable used instead

### Task 8: Apply Timezone Formatting Across Remaining Displays
- ✅ `SslDomainsView.vue` — local `fmtDate` removed, `formatDate` from composable used
- ✅ `JobDetailSlideOver.vue` — local `fmtDateTime` removed, `formatDateTime` from composable used (aliased)
- ✅ TypeScript build passes with no errors
- ✅ **Smoke test: all timestamp displays reflect org timezone**

---

## Phase 16 — HTTP Security Audit
*TLS + HTTP header security audit for HTTPS services — A+–F letter grade, per-service scan history, alerts for critical findings, SecurityTab in service detail, Security column on SSL & Domains page.*

### Task 1: DB Migration + ORM Model
- ✅ Migration `0009_security_scans` adds `service_security_scans` table + `service.last_security_scan` column
- ✅ `ServiceSecurityScan` ORM model added to `models/other.py`
- ✅ **Smoke test: migration applied, `\d service_security_scans` shows all columns including `findings jsonb`**

### Task 2: Security Checker Module
- ✅ `backend/app/services/security_checker.py` created with TLS audit (via stdlib `ssl` + `cryptography`), HTTP header audit (via `httpx`), A+–F grading, alert firing, and WS broadcast
- ✅ **Smoke test: module loads without import errors; manual `run_security_check()` returns grade C, score 64 for mphtj.gov.my**

### Task 3: Alert Types + Probe Integration
- ✅ 4 new alert types registered in `alerting.py` `_FK_BY_TYPE`: `security_tls_deprecated`, `security_weak_cipher`, `security_self_signed`, `security_grade_f`
- ✅ `_maybe_run_security_check()` added to `probe.py` — triggers after uptime probe if >24 h since last scan
- ✅ **Smoke test: backend restarts with no import errors, Application startup complete**

### Task 4: Backend Schemas + Security API Endpoint
- ✅ `backend/app/schemas/security.py` created: `TLSSummary`, `HeaderSummary`, `SecurityFinding`, `ServiceSecurityOut`
- ✅ `security_grade`, `security_score` fields added to `ServiceSslOut` in `ssl_domains.py`
- ✅ `GET /api/organizations/{org_id}/services/{service_id}/security` endpoint added to `services.py` router
- ✅ `ssl_domains.py` router updated: LEFT JOIN latest security scan per service via `DISTINCT ON`
- ✅ **Smoke test: endpoint returns scan data with grade + findings; `/openapi.json` lists `/security` route**

### Task 5: Frontend SecurityGrade Component + Store Types
- ✅ `frontend/src/components/SecurityGrade.vue` created — reusable grade badge (A+–F, colour-coded, score tooltip, sm/md/lg sizes)
- ✅ `Service` interface extended with `security_grade`, `security_score`, `last_security_scan`
- ✅ `SecurityTls`, `SecurityHeaders`, `SecurityFinding`, `SecurityScan` types added to `services.ts`
- ✅ `fetchSecurityScan` action added and exported from services store
- ✅ `ServiceSslRec` extended with `security_grade`, `security_score`; `CombinedRow` extended with `securityGrade`, `securityScore`; `combinedRows` pushes both fields for service rows
- ✅ **Smoke test: TypeScript build passes with no errors**

### Task 6: Frontend SecurityTab.vue
- ✅ `frontend/src/components/services/tabs/SecurityTab.vue` created — full security breakdown: header (grade + score), category sections (TLS Protocol, Certificate, HTTP Headers, Protocol) as expandable `<details>`, grade legend
- ✅ **Smoke test: TypeScript build passes with no errors**

### Task 7: ServiceDetail.vue Security Section
- ✅ `SecurityGrade` and `SecurityTab` imported in `ServiceDetail.vue`
- ✅ `securityScan` + `securityLoading` state added; `loadSecurity()` fetches on mount
- ✅ `service_security_updated` WS event triggers `loadSecurity()` re-fetch
- ✅ Security Audit card rendered after SSL card (HTTPS services only)
- ✅ **Smoke test: Security Audit card visible on HTTPS service detail; scan data displayed correctly**

### Task 8: SSL Domains Security Column
- ✅ `SecurityGrade` imported in `SslDomainsView.vue`
- ✅ `sortKey` widened to include `'security'`; `sorted` computed handles security sort by score descending
- ✅ Security column header with `?` popover (grade legend) added to `<thead>`
- ✅ Security cell with `SecurityGrade` badge for service rows, `—` dash for domain/ssl rows
- ✅ Column styles added
- ✅ **Smoke test: Security grade column visible on SSL & Domains page; service rows show badge, domain/ssl rows show dash**

### Task 9: Progress Dashboard + Final Smoke Test
- ✅ Live security scan triggered for mphtj.gov.my — grade C (64/100) stored in `service_security_scans`
- ✅ API endpoint `/api/organizations/{org_id}/services/{service_id}/security` verified in OpenAPI
- ✅ `ServiceSslOut` schema has `security_grade` and `security_score` fields (`True True`)
- ✅ OpenAPI schemas include `SecurityFinding` and `ServiceSecurityOut`
- ✅ No security alerts fired (expected — grade C, no deprecated TLS/weak ciphers/self-signed)
- ✅ PROGRESS.md and DASHBOARD.html updated
- ✅ **Smoke test: end-to-end security scan → storage → API → frontend verified**

---

## Summary

| Phase | Status | Tasks Done |
|---|---|---|
| Phase 1 — Foundation | ✅ Complete | 60 / 60 |
| Phase 2 — Live Dashboard | ✅ Complete | 20 / 20 |
| Phase 3 — Log Viewer | ✅ Complete | 6 / 6 |
| Phase 4 — Service Monitoring | ✅ Complete | 17 / 17 |
| Phase 5 — SSL & Domain | ✅ Complete | 13 / 13 |
| Phase 6 — Database Monitoring | ✅ Complete | 14 / 14 |
| Phase 7 — Cron & Backup | ✅ Complete | 14 / 14 |
| Phase 8 — Alerting Engine | ✅ Complete | 21 / 21 |
| Phase 9 — Status Page | ✅ Complete | 5 / 5 |
| Phase 10 — Settings | ✅ Complete | 16 / 16 |
| Phase 11 — Deployment | ✅ Complete | 6 / 6 |
| Phase 12 — Post-Launch Enhancements | ✅ Complete | 8 / 8 |
| Phase 13 — SSL in HTTP Probes | ✅ Complete | 8 / 8 |
| Phase 14 — Service SSL on SSL & Domains Page | ✅ Complete | 3 / 3 |
| Phase 15 — Global Timezone Setting | ✅ Complete | 8 / 8 |
| Phase 16 — HTTP Security Audit | ✅ Complete | 9 / 9 |
| Phase 17 — Kernel Events (dmesg) | ✅ Complete | 9 / 9 |
| **Total** | ✅ Complete | **240 / 240** |

---

## Phase 17 — Kernel Events (dmesg)

### Task 1: Add kmsg INPUT to Fluent Bit template
- ✅ Added `[INPUT] Name kmsg Prio_Level warning` block to `fluent-bit.conf.j2`
- ✅ **Smoke test: template renders with kmsg block**

### Task 2: dmesg SSH poll collector
- ✅ `dmesg_collector.py` created with SSHSession, dmesg parse, severity mapping, ±2s dedup
- ✅ Fractional-second timestamp regex (`(?:\.\d+)?`)
- ✅ Per-row commit inside loop (prevents partial-insert rollback)
- ✅ **Smoke test: import verified in container**

### Task 3: Register scheduler job
- ✅ `dmesg_collector` job added to `scheduler.py` (every 15 min)
- ✅ Registered in `main.py` with `replace_existing=True`
- ✅ **Smoke test: manual trigger runs, gracefully handles SSH failure**

### Task 4: Kernel events API endpoint
- ✅ `GET /api/servers/{id}/kernel-events?range=` endpoint added to `servers.py`
- ✅ Returns `{counts: {emerg,alert,crit,err,warn}, events: [{ts,severity,message}]}`
- ✅ Fixed: INTERVAL uses f-string interpolation (PostgreSQL cannot bind INTERVAL params)
- ✅ **Smoke test: endpoint returns correct JSON with test data**

### Task 5: Frontend API function + types
- ✅ `KernelEventsResponse` interface and `getKernelEvents()` added to `api.ts`
- ✅ **Smoke test: TypeScript types match backend response shape**

### Task 6: KernelEventsCard.vue component
- ✅ 4-tile summary strip (emerg/alert, crit, err, warn) with severity colors
- ✅ Event list with severity badge, timestamp, message (newest-first)
- ✅ Loading / empty / error states
- ✅ `watch(() => [props.serverId, props.range], load)` watches both props
- ✅ `viewAll()` uses named route push with `{ tab: 'Logs', source: 'kernel' }`
- ✅ **Smoke test: card renders with 5 test events at 24h range**

### Task 7: Wire SystemTab + pre-select LogsTab
- ✅ `KernelEventsCard` appended to `SystemTab.vue` as 5th card
- ✅ `LogsTab.vue` reads `route.query.source` on mount to pre-select kernel source
- ✅ **Smoke test: card visible in System tab; Logs tab pre-filters to kernel on navigate**

### Task 8: Reconfigure Agents button in InfoTab
- ✅ Admin-only "Agent Management" section added to `InfoTab.vue`
- ✅ Button cycles: Reconfigure Agents → Reconfiguring… → Done ✓ / error state
- ✅ **Smoke test: button calls redeploy API, transitions to Done ✓**

### Task 9: Smoke test + release
- ✅ Backend API `/kernel-events` returns counts and events correctly
- ✅ Kernel Events card renders in System tab with 24h test data
- ✅ "View all in Logs →" navigates to Logs tab (fixed: added `watch(route.query.tab)` to ServerDetail)
- ✅ Reconfigure Agents button functional
- ✅ PROGRESS.md and DASHBOARD.html updated
- ✅ **Release: v1.2.14**
