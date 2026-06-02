# OpsPilot

Self-hosted server and infrastructure monitoring platform. OpsPilot onboards Linux
servers over SSH, auto-deploys metric and log agents, and surfaces live dashboards,
alerting, uptime monitoring, and a public status page — all from a single Docker
Compose stack.

> **Status:** Phase 1 (Foundation) is implemented and verified — auth, organizations,
> server management, SSH onboarding, metric/log ingestion, and WebSocket infrastructure.
> Phases 2–11 (dashboards, log viewer, service/SSL/DB/cron monitoring, alerting,
> status page, settings) are in progress. See [`pm/PROGRESS.md`](pm/PROGRESS.md).

---

## Features

- **Server onboarding over SSH** — add a server, OpsPilot installs and configures
  [Telegraf](https://www.influxdata.com/time-series-platform/telegraf/) (metrics) and
  [Fluent Bit](https://fluentbit.io/) (logs) automatically, streaming progress live.
- **Live metrics & dashboards** — CPU, memory, disk, network, and process data pushed
  over WebSocket and stored in TimescaleDB hypertables.
- **Log viewer** — full-text search, severity/source filters, and live tail.
- **Service & uptime monitoring** — HTTP/TCP/DB probes with incident tracking and a
  public status page.
- **SSL & domain expiry monitoring** — daily certificate and WHOIS checks with
  threshold alerts.
- **Database monitoring** — MySQL/MariaDB health metrics, replication, and deadlocks.
- **Cron & backup dead-man-switch** — heartbeat ping endpoints with missed-run detection.
- **Alerting engine** — metric and log-pattern rules, auto-resolve, acknowledge/snooze,
  maintenance windows, and plain-text email notifications.
- **Multi-tenant** — organizations, role-based access (admin/member), invites.

---

## Architecture

| Layer        | Technology |
|--------------|------------|
| Backend      | Python 3.11 · FastAPI · SQLAlchemy (async, asyncpg) · APScheduler |
| Frontend     | Vue 3 · Vite · TypeScript · Pinia · Vuestic Admin (dark) · ApexCharts |
| Database     | PostgreSQL 16 + TimescaleDB (hypertables + continuous aggregates) |
| Edge         | Nginx (TLS termination, reverse proxy, rate limiting) |
| Agents       | Telegraf + Fluent Bit (auto-deployed to monitored servers) |
| Orchestration| Docker Compose |

```
Internet ──:80/:443──▶ nginx (TLS, CSP/HSTS)
   ├─ /            ──▶ frontend  (Vue SPA)
   ├─ /api, /ws    ──▶ backend   (FastAPI / uvicorn)
   └─ /ping,/status──▶ backend
                          │
                          ▼
                postgres + TimescaleDB
                          ▲
   Monitored servers ─────┘  (Telegraf → /api/ingest/metrics, Fluent Bit → /api/ingest/logs)
```

Full layout and runtime details: [`STRUCTURE.md`](STRUCTURE.md).
Product requirements: [`PRD.md`](PRD.md) · Module specs: [`specs/`](specs/).

---

## Quick start

**Prerequisites:** Docker and Docker Compose.

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env and set the required secrets:
#   OPSPILOT_JWT_SECRET       (>= 32 chars)
#   OPSPILOT_ENCRYPTION_KEY   (base64-encoded 32-byte AES key)
#   database + writer passwords
# config.py hard-validates these at boot and exits with guidance if invalid.

# 2. Bring up the stack (postgres → migrate → backend → frontend → nginx)
docker compose up -d

# 3. First-run setup
# Open the app in your browser; the setup screen creates the first admin account.
```

Compose start order is enforced via healthchecks: `postgres` → `migrate`
(`alembic upgrade head`, one-shot) → `backend` → `frontend` → `nginx`. All host
ports except nginx bind to `127.0.0.1` only.

| Container          | Host port             |
|--------------------|-----------------------|
| nginx              | `80`, `443`           |
| frontend           | `127.0.0.1:8766`      |
| backend            | `127.0.0.1:8765`      |
| postgres           | `127.0.0.1:5433`      |

---

## Development

```bash
# Hot-reload stack: backend uvicorn --reload, frontend Vite HMR
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

- Backend source is mounted for live reload; frontend serves Vite HMR on `:5173`
  proxying the backend.
- API docs (Swagger) are available at `/api/docs` **only when `DEBUG` is enabled**.

### Onboarding a server

Admin adds a server (SSH key or password, stored AES-256 encrypted) → OpsPilot SSHes
in, installs Telegraf + Fluent Bit, renders configs pointed at `/api/ingest/*` with the
server's ingestion token, starts the agents, and verifies data flow — each step streams
to the browser over the `onboarding:{server_id}` WebSocket channel.

---

## Security

- TLS-only (HTTP → HTTPS redirect), HSTS + CSP + anti-clickjacking headers
- HttpOnly / SameSite session cookie backed by server-side revocable sessions (JTI)
- AES-256 encryption for stored SSH keys and database credentials
- Dedicated `opspilot_writer` DB role with **INSERT-only** grants for agents
- Constant-time ingestion-token comparison; rate limiting on auth and `/ping`
- All non-nginx host ports bound to localhost

Secrets (`.env`, `*.pem`, `*.key`) are git-ignored — never commit them.

---

## License

Proprietary — internal project.
