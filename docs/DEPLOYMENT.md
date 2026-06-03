# OpsPilot — Deployment Runbook

Production deployment of OpsPilot via Docker Compose. Five services:
`postgres` (TimescaleDB) → `migrate` (one-shot Alembic) → `backend` (FastAPI) +
`frontend` (Vue build) behind `nginx` (TLS termination + reverse proxy).

---

## 1. Prerequisites

- A Linux host with Docker Engine + Docker Compose v2.
- DNS A record pointing your domain at the host.
- TLS certificate + key (Let's Encrypt or commercial).
- Outbound SMTP relay (optional — configured later in the UI, not via env).

---

## 2. Configure environment

```bash
cp .env.example .env
```

Fill in `.env` (never commit it — `.gitignore` already excludes it):

| Var | How to generate | Notes |
|---|---|---|
| `POSTGRES_PASSWORD` | `openssl rand -base64 24` | DB superuser password |
| `OPSPILOT_WRITER_PASSWORD` | `openssl rand -base64 24` | INSERT-only Telegraf user; baked into agent configs |
| `OPSPILOT_JWT_SECRET` | `openssl rand -hex 32` | min 32 chars; rotating it logs everyone out |
| `OPSPILOT_ENCRYPTION_KEY` | `openssl rand -base64 32` | AES-256 master key. **If lost, all stored SSH keys + DB passwords are unrecoverable.** Back it up securely. |
| `OPSPILOT_BASE_URL` | e.g. `https://ops.example.com` | used in outbound emails + cron/backup ping URLs |
| `DEBUG` | `false` | MUST be `false` in prod (keeps the `Secure` cookie flag) |

SMTP (for alert emails) is configured **after first run** in Settings → General, not via env.

---

## 3. TLS certificates

nginx expects:

```
nginx/certs/fullchain.pem
nginx/certs/privkey.pem
```

```bash
mkdir -p nginx/certs
# Let's Encrypt example:
cp /etc/letsencrypt/live/ops.example.com/fullchain.pem nginx/certs/fullchain.pem
cp /etc/letsencrypt/live/ops.example.com/privkey.pem  nginx/certs/privkey.pem
```

nginx redirects all `:80` → `:443`, terminates TLS (TLSv1.2/1.3), and reverse-proxies
`/api`, `/ws` (WebSocket), `/ping/` (rate-limited dead-man switch), `/status` (public
status SPA), and `/` (frontend).

---

## 4. Firewall (important)

Expose **only 80 and 443** publicly. In particular:

- **Do NOT expose PostgreSQL (5432).** The compose file binds Postgres to
  `127.0.0.1:5433` on the host (loopback only) — keep it that way; never publish it.
- The backend (`127.0.0.1:8765`) and frontend (`127.0.0.1:8766`) host ports are
  loopback-only too; public traffic goes through nginx.

```bash
# ufw example
ufw default deny incoming
ufw allow 22/tcp      # SSH (restrict to your admin IPs if possible)
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

**Monitored servers** must allow inbound SSH from the OpsPilot host (for agent
onboarding) and outbound HTTPS to `OPSPILOT_BASE_URL` (Telegraf/Fluent Bit ship
metrics/logs to `/api/ingest/*`).

---

## 5. First run

```bash
docker compose build          # builds backend (incl. python-whois) + frontend images
docker compose up -d
```

Startup order is enforced: `postgres` (healthcheck) → `migrate` (runs
`alembic upgrade head`, exits 0) → `backend` (waits for migrate success) +
`frontend` → `nginx`.

Then:

1. Open `https://<your-domain>` → you'll be redirected to **/setup**.
2. Create the first admin account.
3. Settings → General: set instance name, base URL, and SMTP (send a test email).
4. Add your first server (Servers → Add) — onboarding installs Telegraf + Fluent Bit
   over SSH and you'll see the first metrics within ~10s.

---

## 6. Verify

```bash
docker compose ps                       # all services healthy/up; migrate Exited (0)
curl -sk https://<domain>/api/health    # {"ok":true}
docker compose logs -f backend          # confirm scheduler jobs registered, no errors
```

End-to-end check: add a server, watch onboarding complete + metrics flow on the
dashboard; create a low-threshold CPU alert rule, confirm an alert fires on the
/alerts page (and email arrives if SMTP is configured).

---

## 7. Upgrades

```bash
git pull
docker compose build
docker compose up -d            # migrate re-runs alembic upgrade head idempotently
```

Migrations are linear (`0001` → `0006`); the `migrate` service applies any new
revisions before the backend starts.

---

## 8. Backups

- **Database:** `docker compose exec postgres pg_dump -U opspilot opspilot | gzip > backup.sql.gz`
  (TimescaleDB hypertables included). Restore into a fresh DB before `migrate` if recovering.
- **`OPSPILOT_ENCRYPTION_KEY`:** back this up out-of-band — without it, restored SSH/DB
  credentials cannot be decrypted.

---

## 9. Notes / known operational items

- The backend image bundles `python-whois` (domain expiry checks) — a plain
  `docker compose build` includes it; no manual install needed in production.
- TimescaleDB retention: metrics 30d, logs 30d, service_checks 90d; a compression
  policy compresses `server_metrics` chunks older than 2 days.
- Background jobs (APScheduler, SQLAlchemy job store) persist across restarts:
  metric/log alert evaluators, ssl/domain daily checkers, cron/backup watchdog,
  snooze/maintenance expiry, session cleanup.
