# OpsPilot — Project Structure

```
opspilot/
│
├── PRD.md                          # Product Requirements Document (v2.2)
├── STRUCTURE.md                    # This file
├── docker-compose.yml              # Full stack: migrate, backend, frontend, postgres, nginx
├── .env.example                    # All required env vars with descriptions
│
├── specs/                          # Module-level feature specs (UI + API + logic)
│   ├── 01-auth.md
│   ├── 02-server-management.md
│   ├── 03-onboarding.md
│   ├── 04-dashboard.md
│   ├── 05-log-viewer.md
│   ├── 06-service-monitoring.md
│   ├── 07-ssl-domains.md
│   ├── 08-database-monitoring.md
│   ├── 09-cron-backup.md
│   ├── 10-alerting.md
│   └── 11-settings.md
│
├── nginx/
│   └── nginx.conf                  # Outer TLS reverse proxy (routes /api → backend, / → frontend)
│
│
├── backend/                        # Python 3.11 + FastAPI
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   │
│   ├── migrations/                 # Alembic
│   │   ├── env.py
│   │   └── versions/               # One file per migration
│   │
│   └── app/
│       ├── main.py                 # FastAPI app factory, router registration, lifespan hooks
│       ├── config.py               # Settings — reads from env vars (Pydantic BaseSettings)
│       ├── database.py             # SQLAlchemy async engine, session factory, TimescaleDB setup
│       │
│       ├── core/                   # Cross-cutting concerns
│       │   ├── security.py         # JWT encode/decode, bcrypt, cookie helpers
│       │   ├── dependencies.py     # FastAPI Depends: get_current_user, get_db, etc.
│       │   └── exceptions.py       # Custom HTTP exception handlers
│       │
│       ├── models/                 # SQLAlchemy ORM models (one file per domain)
│       │   ├── user.py             # User, Session
│       │   ├── server.py           # Server, OnboardingLog
│       │   ├── service.py          # Service, ServiceCheck (hypertable), Incident
│       │   ├── metric.py           # server_metrics hypertable (TimescaleDB)
│       │   ├── log.py              # server_logs hypertable (TimescaleDB)
│       │   ├── domain.py           # Domain, SSLCert
│       │   ├── alert.py            # Alert, AlertRule, LogAlertRule
│       │   ├── maintenance.py      # MaintenanceWindow
│       │   ├── cron.py             # CronJob, CronJobRun
│       │   ├── backup.py           # BackupJob, BackupRun
│       │   ├── database_cred.py    # DBCredential
│       │   └── settings.py         # Settings (key-value store)
│       │
│       ├── schemas/                # Pydantic request/response schemas (one file per domain)
│       │   ├── auth.py             # LoginRequest, LoginResponse, MeResponse, PasswordChange
│       │   ├── server.py           # ServerCreate, ServerUpdate, ServerResponse
│       │   ├── service.py          # ServiceCreate, ServiceResponse, IncidentResponse
│       │   ├── metric.py           # MetricDataPoint, MetricHistory
│       │   ├── log.py              # LogEntry, LogSearchParams
│       │   ├── domain.py           # DomainCreate, SSLCertResponse
│       │   ├── alert.py            # AlertResponse, AlertRuleCreate, AlertRuleUpdate
│       │   ├── cron.py             # CronJobCreate, CronJobRunResponse
│       │   ├── backup.py           # BackupJobCreate, BackupRunResponse
│       │   ├── database_cred.py    # DBCredentialCreate, DBHealthResponse
│       │   └── settings.py         # SettingUpdate, SMTPSettings
│       │
│       ├── routers/                # FastAPI route handlers (one file per domain)
│       │   ├── auth.py             # /api/auth/*
│       │   ├── servers.py          # /api/servers/*
│       │   ├── services.py         # /api/services/*
│       │   ├── metrics.py          # /api/metrics/*
│       │   ├── logs.py             # /api/logs/*
│       │   ├── domains.py          # /api/domains/*
│       │   ├── ssl.py              # /api/ssl/*
│       │   ├── alerts.py           # /api/alerts/*
│       │   ├── cron.py             # /api/cron-jobs/*
│       │   ├── backup.py           # /api/backup-jobs/*
│       │   ├── ping.py             # /ping/{token} (heartbeat endpoint — unauthenticated)
│       │   ├── database.py         # /api/databases/*
│       │   ├── maintenance.py      # /api/maintenance/*
│       │   ├── settings.py         # /api/settings/*
│       │   └── status.py           # /status (public status page data — unauthenticated)
│       │
│       ├── services/               # Business logic layer (no HTTP context)
│       │   ├── auth_service.py     # Login, logout, password change, session management
│       │   ├── server_service.py   # Server CRUD, soft delete
│       │   ├── onboarding_service.py  # SSH onboarding, Telegraf/Fluent Bit deploy
│       │   ├── service_checker.py  # HTTP/TCP probe execution
│       │   ├── metric_service.py   # Query server_metrics hypertable
│       │   ├── log_service.py      # Query server_logs, cursor pagination
│       │   ├── ssl_service.py      # SSL cert check via Python ssl + cryptography
│       │   ├── domain_service.py   # WHOIS lookup via python-whois
│       │   ├── alert_service.py    # Fire/resolve/ack/snooze alerts, send email
│       │   ├── cron_service.py     # Ping handling, croniter evaluation
│       │   ├── backup_service.py   # Ping handling, size-drop evaluation
│       │   └── db_health_service.py  # DB credential validation, metric query
│       │
│       ├── jobs/                   # APScheduler background jobs
│       │   ├── scheduler.py        # APScheduler setup, job registration
│       │   ├── metric_evaluator.py # Rolling 5-min alert evaluation (every 30s)
│       │   ├── service_checker.py  # HTTP/TCP probe scheduler (per-service interval)
│       │   ├── ssl_checker.py      # Daily SSL cert checks (staggered)
│       │   ├── domain_checker.py   # Daily WHOIS checks (staggered, 30s between)
│       │   ├── cron_watchdog.py    # CronJob miss detection (every 60s)
│       │   ├── backup_watchdog.py  # BackupJob miss detection (every 60s)
│       │   ├── log_alert_evaluator.py  # LogAlertRule evaluation (every 60s)
│       │   ├── maintenance_expiry.py   # Auto-expire maintenance windows (every 60s)
│       │   └── session_cleanup.py  # Nightly expired session row deletion
│       │
│       ├── utils/
│       │   ├── encryption.py       # AES-256 encrypt/decrypt using OPSPILOT_ENCRYPTION_KEY
│       │   ├── ssh.py              # Paramiko SSH client wrapper
│       │   ├── email.py            # SMTP email sender
│       │   └── croniter_utils.py   # next_expected_at computation helpers
│       │
│       └── ws/
│           ├── manager.py          # WebSocket connection manager (per-server channel registry)
│           ├── listener.py         # PostgreSQL LISTEN/NOTIFY → WS push (500ms batching)
│           └── handler.py          # WS message handler (subscribe/unsubscribe protocol)
│
│
└── frontend/                       # Vue 3 + Vite + TypeScript + Pinia + Vuestic Admin
    ├── Dockerfile
    ├── nginx.conf                  # Frontend container Nginx (serves static files)
    ├── index.html
    ├── vite.config.ts
    ├── tsconfig.json
    ├── package.json
    │
    └── src/
        ├── main.ts                 # App entry — mounts Vue, registers plugins
        ├── App.vue                 # Root component — router-view + global modals
        │
        ├── assets/                 # Static assets (logo, icons, fonts)
        │
        ├── router/
        │   └── index.ts            # Vue Router — all routes + auth guard
        │
        ├── stores/                 # Pinia stores (one per domain)
        │   ├── auth.ts             # isAuthenticated, user, login, logout, fetchMe
        │   ├── servers.ts          # Server list, selected server, status
        │   ├── metrics.ts          # Live metric data, chart history
        │   ├── logs.ts             # Log entries, filters, live tail state
        │   ├── services.ts         # Service list, uptime state
        │   ├── alerts.ts           # Active alerts, counts by state
        │   ├── notifications.ts    # Toast/snack queue
        │   └── websocket.ts        # WS connection state, ticket, reconnect logic
        │
        ├── services/               # Axios API calls (one file per domain)
        │   ├── api.ts              # Axios instance — base URL, cookie, 401 interceptor
        │   ├── auth.api.ts
        │   ├── servers.api.ts
        │   ├── metrics.api.ts
        │   ├── logs.api.ts
        │   ├── services.api.ts
        │   ├── ssl.api.ts
        │   ├── domains.api.ts
        │   ├── alerts.api.ts
        │   ├── cron.api.ts
        │   ├── backup.api.ts
        │   ├── database.api.ts
        │   ├── maintenance.api.ts
        │   └── settings.api.ts
        │
        ├── composables/            # Reusable Vue composition functions
        │   ├── useWebSocket.ts     # WS connection, ticket flow, reconnect, channel sub
        │   ├── useToast.ts         # Toast notification helper
        │   ├── useConfirm.ts       # Confirmation dialog helper
        │   └── useRelativeTime.ts  # "2 minutes ago" formatting
        │
        ├── types/                  # TypeScript interfaces matching backend schemas
        │   ├── server.ts
        │   ├── service.ts
        │   ├── metric.ts
        │   ├── log.ts
        │   ├── alert.ts
        │   ├── domain.ts
        │   ├── cron.ts
        │   ├── backup.ts
        │   ├── database.ts
        │   └── settings.ts
        │
        ├── utils/
        │   ├── formatters.ts       # Bytes → human, seconds → "2h 4m", date formatting
        │   └── validators.ts       # Cron expression validation, URL validation
        │
        ├── components/
        │   ├── common/             # App shell + shared UI
        │   │   ├── AppLayout.vue   # Sidebar + top nav + main content slot
        │   │   ├── Sidebar.vue     # Nav links, server list, alert badge
        │   │   ├── TopNav.vue      # Instance name, user menu, logout
        │   │   ├── StatusBadge.vue # Reusable up/down/warning/critical badge
        │   │   ├── EmptyState.vue  # Consistent empty state with icon + message
        │   │   ├── ConfirmDialog.vue
        │   │   └── PageHeader.vue  # Title + action button slot
        │   │
        │   ├── charts/             # Reusable ApexCharts wrappers (via VaChart)
        │   │   ├── TimeSeriesChart.vue   # CPU, RAM, disk over time
        │   │   ├── GaugeChart.vue        # Current value gauge
        │   │   ├── UptimeTimeline.vue    # Service uptime bar
        │   │   └── CalendarHeatmap.vue   # Cron/backup 30-day calendar
        │   │
        │   ├── servers/
        │   │   ├── ServerCard.vue        # Grid card showing server status
        │   │   ├── ServerForm.vue        # Add/edit server modal form
        │   │   └── OnboardingProgress.vue  # Live step-by-step onboarding log
        │   │
        │   ├── services/
        │   │   ├── ServiceRow.vue        # Table row with status badge + actions
        │   │   └── ServiceForm.vue       # Add/edit service modal form
        │   │
        │   ├── alerts/
        │   │   ├── AlertRow.vue          # Alert list row with ack/snooze actions
        │   │   ├── SnoozeModal.vue       # Duration picker modal
        │   │   └── AlertRuleForm.vue     # Edit alert rule threshold/cooldown
        │   │
        │   └── logs/
        │       ├── LogEntry.vue          # Expandable log row with JSONB fields
        │       └── LogFilters.vue        # Source/severity/date filter bar
        │
        └── views/                  # Page-level components (one per route)
            ├── auth/
            │   └── LoginView.vue
            ├── dashboard/
            │   └── DashboardView.vue
            ├── servers/
            │   ├── ServerListView.vue
            │   └── ServerDetailView.vue
            ├── services/
            │   └── ServicesView.vue
            ├── logs/
            │   └── LogsView.vue
            ├── ssl-domains/
            │   └── SslDomainsView.vue
            ├── databases/
            │   └── DatabasesView.vue
            ├── cron-backup/
            │   └── CronBackupView.vue
            ├── alerts/
            │   ├── AlertsView.vue
            │   └── AlertRulesView.vue
            ├── settings/
            │   └── SettingsView.vue
            └── status/
                └── StatusPageView.vue  # Public — no auth required
```

---

# Architecture Map (Runtime Overview)

> The tree above is the **planned** end-state (all 11 phases). This section is the
> **as-built** architecture as of the current codebase. Where the two differ, the
> as-built names win (e.g. `core/deps.py` not `core/dependencies.py`; SSH uses
> `asyncssh` not Paramiko; many models live in `models/other.py`).
>
> **Build status:** Phases 1–2 implemented (auth, orgs, servers, SSH onboarding,
> ingestion, WebSocket). Most of the relational schema for alerts/services/SSL/
> cron/backup/DB is created by migration `0001` but the routers/jobs that drive it
> are still pending — `models/other.py` is explicitly "used in later phases".

## 1. Topology (Docker Compose)

```
Internet ──:80/:443──▶ nginx (alpine, TLS, CSP/HSTS, gzip, /ping rate-limit)
   ├─ location /            ──▶ frontend (Vue SPA, nginx :80, host :8766)
   ├─ location /api, /ws    ──▶ backend  (FastAPI/uvicorn :8000, host :8765)
   ├─ location /ping/       ──▶ backend  (planned dead-man-switch, rate-limited)
   └─ location /status      ──▶ backend  (planned public status page)
                                   │  asyncpg pool (10+20)
                                   ▼
                        postgres + TimescaleDB (pg16, host 127.0.0.1:5433)
                                   ▲  INSERT-only role: opspilot_writer
   Monitored Linux servers ───────┘
     • Telegraf   → POST /api/ingest/metrics (InfluxDB Line Protocol)
     • Fluent Bit → POST /api/ingest/logs    (JSON array)
```

**Compose start order:** `postgres` (healthcheck) → `migrate` (`alembic upgrade head`,
one-shot, must succeed) → `backend` (healthcheck `/api/health`) → `frontend` → `nginx`.
All host ports except nginx bind to `127.0.0.1` only.

| Container            | Image / Build                       | Host port           |
|----------------------|-------------------------------------|---------------------|
| opspilot-postgres    | timescale/timescaledb:latest-pg16   | 127.0.0.1:5433→5432 |
| migrate (one-shot)   | ./backend (alembic upgrade head)    | —                   |
| opspilot-backend     | ./backend (uvicorn)                 | 127.0.0.1:8765→8000 |
| opspilot-frontend    | ./frontend                          | 127.0.0.1:8766→80   |
| opspilot-nginx       | nginx:alpine                        | 80, 443             |

Dev override (`docker-compose.dev.yml`): backend `uvicorn --reload` (source-mounted);
frontend swaps to Vite HMR on :5173 proxying `backend:8000`.

## 2. Services (logical components)

- **Backend — FastAPI single async process** (`backend/app`)
  - `routers/`: `setup`, `auth` (+ `invite_router`, `ws_router`), `organizations`,
    `servers`, `ingest`. Registered in `main.py`.
  - `services/`: `ssh.py` (asyncssh — single channel for all remote ops, decrypts
    creds on demand), `onboarding.py` (10-step orchestrator, streams progress over WS),
    `ingestion.py` (Line-Protocol + JSON parsers → hypertable rows),
    `templates/` (`telegraf.conf.j2`, `fluent-bit.conf.j2`).
  - `core/`: `auth.py` (JWT via jose), `security.py` (bcrypt rounds=12),
    `crypto.py` (AES-256 for stored SSH keys / DB passwords), `rate_limit.py` (slowapi).
  - `ws/`: `manager.py` (in-memory connection registry + channel fanout),
    `tickets.py` (single-use 30s WS upgrade tickets).
  - `jobs/scheduler.py`: APScheduler (see §4).
- **Frontend — Vue 3 SPA** (`frontend/src`): Vue 3 + Vite + TS, Vuestic UI (dark),
  Pinia (`auth`/`org`/`server`/`onboarding`), vue-router, axios, ag-grid.
  Built routes: `/setup`, `/login`, `/invite/:token`, `/` (dashboard),
  `/organizations` (adminOnly), `/servers`, `/profile`, `/_ui-kit` (dev).

## 3. APIs

**Internal REST** — auth via **HttpOnly cookie** `opspilot_jwt` (SameSite=strict,
Secure unless DEBUG). Every request decodes the JWT *and* checks a server-side
`session` row by `jti` (revocable). `require_admin` dep gates admin routes.

| Group   | Endpoints |
|---------|-----------|
| Setup   | `GET /api/setup/status`, `POST /api/setup/register` (first admin) |
| Auth    | `POST /api/auth/login` `/logout`, `GET /api/auth/me`, `PATCH /api/auth/password`, `GET /api/ws-ticket` |
| Invites | `GET /api/invite/{token}`, `POST /api/invite/{token}/accept` |
| Orgs    | `GET/POST /api/organizations`, `GET/PATCH/DELETE /api/organizations/{id}`, `GET …/stats` |
| Servers | `GET/POST /api/organizations/{org_id}/servers`, `GET /api/servers`, `GET/PATCH/DELETE /api/servers/{id}`, `POST …/onboard`, `…/redeploy`, `…/ssh-test`, `GET …/onboarding` |
| Health  | `GET /api/health`; Swagger at `/api/docs` **only when DEBUG** |

**Ingestion API** (machine-to-machine) — `POST /api/ingest/metrics` (Telegraf,
Line Protocol → `server_metrics`, also bumps `Server.last_seen_at`) and
`POST /api/ingest/logs` (Fluent Bit, JSON → `server_logs`). Auth:
`Authorization: Bearer <ingestion_token>`, one UUID per server, compared in
**constant time** (`hmac.compare_digest`) across active servers.

**WebSocket** — `GET /api/ws-ticket` (cookie auth) issues a single-use ticket →
client connects `wss://…/ws?ticket=…` (nginx `proxy_read_timeout 3600s`). Client
actions: `subscribe_org`, `subscribe` (server), `subscribe_onboarding`,
`subscribe_rotation` (admin-only) + `unsubscribe*`. Server fanout channels: per-org,
per-server, per-onboarding, global rotation. **Live today:** onboarding step updates.

## 4. Queues / async work

No external broker (no Redis/RabbitMQ/Celery). Async work via:
1. **APScheduler** (`AsyncIOScheduler`, **SQLAlchemy job store** → jobs persist across
   restarts), started/stopped in FastAPI `lifespan`. Registered jobs: `session_cleanup`
   (daily 03:00), `ticket_sweep` (every 60s). *Planned: service checks, SSL/domain
   expiry, alert evaluation, cron/backup grace sweeps, retention.*
2. **Fire-and-forget asyncio** — onboarding runs as a background coroutine
   (`POST …/onboard` → 202), streaming over WS.
3. **In-memory single-instance state** — `WSManager._connections`, `TicketStore._store`
   (not shared across replicas — backend is single-instance by design).

## 5. Databases — one Postgres 16 + TimescaleDB

- **App access:** `postgresql+asyncpg` (async, pool 10+20) for API;
  `postgresql+psycopg2` (sync) for Alembic and the APScheduler job store.
- **Agent write role:** `opspilot_writer` (`LOGIN NOINHERIT`, **INSERT-only** on the
  three hypertables), provisioned in migration `0001` for direct-write agent configs.

**Relational tables (ORM, `models/`):** user, user_organization, organization, server,
onboarding_log, session, invite, service, incident, domain, ssl_cert, alert, alert_rule,
log_alert_rule, maintenance_window, cron_job, cron_job_run, backup_job, backup_run,
db_credential, app_settings.

**TimescaleDB hypertables (raw SQL, not ORM-mapped):**
- `server_metrics` (time, server_id, metric_name, value, labels JSONB) — 1-day chunks, 30-day retention
- `server_logs` (time, server_id, source, severity, message, raw JSONB) — 30-day retention, GIN FTS on `message`
- `service_checks` (time, service_id, …) — 90-day retention
- Continuous aggregates: `server_metrics_hourly`, `server_metrics_daily` (back the charts)

**Key relationships:** org *1─\** user_organization *\*─1* user (global role admin/member;
org role operator/viewer); org *1─\** server *1─\** service *1─\** incident; org *1─\**
domain *1─\** ssl_cert; server *1─\** {alert_rule, log_alert_rule, maintenance_window,
cron_job, backup_job, db_credential, onboarding_log}; `alert` has polymorphic FKs to
server/service/domain/ssl_cert/cron_job/backup_job.

## 6. Deployment & onboarding flow

1. Copy `.env.example`→`.env`, generate secrets (`OPSPILOT_JWT_SECRET` ≥32 chars,
   `OPSPILOT_ENCRYPTION_KEY` = base64 32-byte AES key, DB + writer passwords).
   `config.py` hard-validates at boot, exits with guidance if invalid.
2. `docker compose up`: postgres → migrate (enables TimescaleDB, creates tables +
   hypertables + continuous aggregates + retention policies + `opspilot_writer`) →
   backend (runs scheduler) → frontend build → edge nginx (TLS, certs at
   `/etc/nginx/certs`).
3. First run: `/setup/status` reports no users → SPA SetupView → `POST /api/setup/register`
   creates first **admin**.

**Onboarding (core runtime workflow):** Admin adds server (SSH key/password, AES-encrypted
at rest) → `POST /api/servers/{id}/onboard` (202) → `onboarding.py` SSHes in, installs
Telegraf + Fluent Bit, renders/uploads Jinja2 configs pointed at `/api/ingest/*` with the
server's token, starts services, verifies data flow → each step streams to the browser on
the `onboarding:{server_id}` WS channel → agents push metrics/logs → hypertables →
dashboard + live WS.

**Security posture:** TLS-only (HTTP→HTTPS 301), HSTS+CSP+anti-clickjacking at both nginx
and FastAPI middleware, HttpOnly/SameSite cookie + server-side revocable sessions, AES-256
for stored SSH/DB secrets, INSERT-only DB role for agents, constant-time ingestion-token
compare, slowapi + nginx `/ping` rate limiting, all non-nginx host ports bound to localhost.

## 7. As-built vs. planned

| Area | Built | Reserved in schema/nginx, logic pending |
|------|-------|------------------------------------------|
| Auth, sessions, invites, orgs | ✅ | — |
| Server CRUD + SSH onboarding + agent config | ✅ | redeploy / arbitrary remote actions |
| Metric/log ingestion → hypertables | ✅ | — |
| WebSocket (onboarding live push) | ✅ | metrics/alert live push |
| Scheduler (session cleanup, ticket sweep) | ✅ | service checks, SSL/domain expiry, alert eval, cron/backup sweeps |
| Alerts, services/uptime, SSL/domains, cron & backup dead-man-switch, DB monitoring, settings/SMTP, public status page | — | tables/routes reserved (`models/other.py`, `/ping`, `/status`) |

