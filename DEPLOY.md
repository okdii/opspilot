# OpsPilot — Deployment Runbook

This document covers a production deployment of OpsPilot on a single Linux VPS using Docker Compose with Caddy for TLS termination.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Ubuntu 22.04 LTS (or Debian 12) | Other distros work; adjust package commands |
| Docker Engine 24+ | [Install guide](https://docs.docker.com/engine/install/ubuntu/) |
| Docker Compose v2 | Bundled with Docker Desktop; `docker compose` (no hyphen) |
| Domain name | DNS A record pointing to your server's IP |
| Caddy 2 | Installed on the host for TLS termination |
| 2 GB RAM minimum | 4 GB recommended for comfortable operation |

---

## Architecture

```
Internet :443 ──▶ Caddy (host, TLS via Let's Encrypt)
                     │
                     ▼
               nginx :8080  (Docker container, HTTP only)
               ├─ /api, /ws ──▶ backend :8000
               ├─ /ping      ──▶ backend :8000  (rate-limited)
               └─ /          ──▶ frontend :80   (Vue SPA)
                                    │
                                    ▼
                             postgres :5432  (localhost-only)
                                    ▲
                 Monitored servers ─┘  (Telegraf + Fluent Bit push metrics/logs)
```

All containers except nginx bind their ports to `127.0.0.1` only. Caddy is the only process listening on public ports 80/443.

---

## Step 1 — Firewall Setup

```bash
# Allow SSH, HTTP (Caddy redirect), HTTPS
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Allow monitored servers to push metrics/logs to TimescaleDB on port 5432.
# IMPORTANT: restrict to your monitored server IPs — never open to the internet.
# Add one rule per monitored server:
sudo ufw allow from <MONITORED_SERVER_IP> to any port 5432

# Enable firewall
sudo ufw --force enable
sudo ufw status
```

> **Why port 5432 is open:** Telegraf and Fluent Bit agents push metrics and logs directly to PostgreSQL using the INSERT-only `opspilot_writer` user. They do NOT go through the OpsPilot backend — only the `opspilot_writer` password grants them access, and that password is scoped to INSERT only. Never expose port 5432 to the public internet.

---

## Step 2 — Install Caddy

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy
```

Create `/etc/caddy/Caddyfile`:

```caddyfile
yourdomain.com {
    # TLS via Let's Encrypt (automatic)
    reverse_proxy localhost:8080

    # HSTS (Caddy sets this; nginx.conf intentionally omits it)
    header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"

    # Logging
    log {
        output file /var/log/caddy/opspilot.log
        format json
    }
}
```

Replace `yourdomain.com` with your actual domain, then:

```bash
sudo systemctl reload caddy
sudo systemctl enable caddy
```

Caddy automatically obtains and renews a Let's Encrypt certificate. Verify with `sudo caddy validate --config /etc/caddy/Caddyfile`.

---

## Step 3 — Clone and Configure

```bash
git clone <your-repo-url> /opt/opspilot
cd /opt/opspilot
cp .env.example .env
```

Edit `.env` and fill in every value:

```bash
# Generate JWT secret
echo "OPSPILOT_JWT_SECRET=$(openssl rand -hex 32)" >> /dev/stdout

# Generate AES-256 encryption key
echo "OPSPILOT_ENCRYPTION_KEY=$(openssl rand -base64 32)" >> /dev/stdout

# Generate writer password
echo "OPSPILOT_WRITER_PASSWORD=$(openssl rand -base64 24)" >> /dev/stdout
```

Set `OPSPILOT_BASE_URL` to your public domain (used in alert emails and ping URLs):

```
OPSPILOT_BASE_URL=https://yourdomain.com
```

> **Warning:** Back up the `OPSPILOT_ENCRYPTION_KEY` immediately in a password manager. If lost, all stored SSH credentials and database passwords become permanently unrecoverable.

---

## Step 4 — First Deploy (Migrate-First Pattern)

The stack enforces a strict startup order via Docker Compose healthchecks:

```
postgres (healthy) → migrate (completed) → backend → frontend → nginx
```

```bash
cd /opt/opspilot

# Pull / build all images
docker compose pull
docker compose build

# Start in detached mode
docker compose up -d

# Watch startup (ctrl+C to stop watching, containers keep running)
docker compose logs -f
```

Verify all containers are healthy:

```bash
docker compose ps
```

Expected output — all containers should show `running` or `exited (0)` for `migrate`:

```
NAME                STATUS
opspilot-postgres   running (healthy)
opspilot-migrate    exited (0)
opspilot-backend    running (healthy)
opspilot-frontend   running
opspilot-nginx      running
```

---

## Step 5 — First-Run Admin Setup

Open `https://yourdomain.com` in your browser. On first visit, OpsPilot displays a setup screen to create the initial admin account. Fill in a username and password, submit — the account is created and you are logged in.

After login:
1. Go to **Settings → General** and configure SMTP (for alert emails)
2. Set the instance name (shown in emails and the public status page)
3. Go to **Servers → Add Server** to onboard your first monitored machine

---

## Step 6 — Onboarding a Server

OpsPilot installs and configures Telegraf (metrics) and Fluent Bit (logs) automatically over SSH.

**Before adding a server:**
- Ensure port 5432 is open from that server's IP (Step 1)
- Have SSH credentials ready (password or private key)

**Add server:**
1. Click **Servers → + Add Server**
2. Fill in the hostname/IP, SSH user, and credentials
3. OpsPilot SSHes in, installs agents, renders configs, starts agents, and verifies data flow — all streamed live to the browser
4. After onboarding completes, the server appears in the Servers list with live metrics within 30 seconds

---

## Deploying Your Own Instance

Anyone can run their own OpsPilot instance using the pre-built images from GitHub Container Registry (GHCR). You do not need to build anything — just pull and run.

### How it works

```
GitHub Container Registry (ghcr.io/okdii/opspilot-*)
        │
        ▼
  Your VPS (docker compose pull + up -d)
```

All images are built automatically by the CI/CD pipeline on every push to `main`.

### Prerequisites

- Ubuntu 22.04 LTS (or Debian 12) VPS
- Docker Engine 24+ and Docker Compose v2
- A GitHub account (free) with a Personal Access Token — needed to pull images from GHCR

### Step 1 — Create a GitHub PAT

Go to `github.com/settings/tokens` → **Generate new token (classic)**

Scopes required: check **`read:packages`** only. Copy the token.

### Step 2 — Clone the repo (one time)

```bash
git clone https://github.com/okdii/opspilot.git /home/opspilot
cd /home/opspilot
```

### Step 3 — Create your `.env` file

```bash
nano /home/opspilot/.env
```

```env
POSTGRES_PASSWORD=your_strong_password
OPSPILOT_WRITER_PASSWORD=your_writer_password
OPSPILOT_JWT_SECRET=your_jwt_secret_min_32_chars
OPSPILOT_ENCRYPTION_KEY=your_encryption_key_min_32_chars
OPSPILOT_BASE_URL=https://yourdomain.com
```

Generate secure random values with:
```bash
openssl rand -hex 32
```

### Step 4 — Authenticate to GHCR

```bash
echo YOUR_PAT_HERE | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

Expected output: `Login Succeeded`

### Step 5 — Pull images and start

```bash
cd /home/opspilot
docker compose pull
docker compose up -d
```

Migrations run automatically before the backend starts. All services should be up within ~30 seconds.

### Step 6 — Verify

```bash
docker compose ps
```

All services (`postgres`, `backend`, `frontend`, `nginx`) should show `running`.

### Staying up to date

When a new version is released, pull the latest compose file and images:

```bash
cd /home/opspilot
git pull origin main
docker compose pull
docker compose up -d
docker image prune -f
```

---

## Upgrade Procedure

```bash
cd /opt/opspilot

# Pull latest code
git pull origin main

# Rebuild and restart (migrate runs automatically as part of compose up)
docker compose build
docker compose up -d

# Verify
docker compose ps
docker compose logs backend --tail=20
```

Alembic migrations run automatically via the `migrate` one-shot container before the backend starts. Downtime is typically under 30 seconds.

---

## Backup and Restore

### Backup PostgreSQL data

```bash
# Dump to compressed file
docker exec opspilot-postgres pg_dump -U opspilot opspilot | gzip > /opt/backups/opspilot-$(date +%Y%m%d).sql.gz
```

Schedule with cron:

```bash
# /etc/cron.d/opspilot-backup
0 3 * * * root docker exec opspilot-postgres pg_dump -U opspilot opspilot | gzip > /opt/backups/opspilot-$(date +\%Y\%m\%d).sql.gz && find /opt/backups -name "opspilot-*.sql.gz" -mtime +30 -delete
```

### Restore

```bash
# Stop backend (prevent writes during restore)
docker compose stop backend

# Restore
gunzip -c /opt/backups/opspilot-YYYYMMDD.sql.gz | docker exec -i opspilot-postgres psql -U opspilot opspilot

# Restart
docker compose start backend
```

---

## Log Retention

By default OpsPilot retains:
- Raw metrics: 30 days (TimescaleDB retention policy)
- Logs: 30 days
- Alert history: 90 days

Adjust in **Settings → Retention**.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Backend fails to start | `docker compose logs backend` — usually a missing env var or failed migration |
| Metrics not arriving | Verify port 5432 firewall rule for the agent server's IP |
| No alert emails | Settings → General → SMTP — test connection; check spam folder |
| `migrate` exits non-zero | `docker compose logs migrate` — usually a DB connection issue |
| Agents not installing | SSH credentials wrong, or target server firewalls SSH from OpsPilot VPS |
| `OPSPILOT_ENCRYPTION_KEY` error | Key is wrong length or not base64 — regenerate with `openssl rand -base64 32` |

---

## Environment Variable Reference

| Variable | Required | Description |
|---|---|---|
| `POSTGRES_DB` | Yes | Database name (default: `opspilot`) |
| `POSTGRES_USER` | Yes | Superuser name (default: `opspilot`) |
| `POSTGRES_PASSWORD` | Yes | Superuser password — use a strong random value |
| `OPSPILOT_WRITER_PASSWORD` | Yes | INSERT-only user for Telegraf/Fluent Bit agents |
| `OPSPILOT_JWT_SECRET` | Yes | Min 32 chars — signs session tokens |
| `OPSPILOT_ENCRYPTION_KEY` | Yes | Base64-encoded 32-byte AES-256 key — encrypts SSH creds and DB passwords |
| `OPSPILOT_BASE_URL` | Recommended | Public URL (`https://yourdomain.com`) — used in emails and ping URLs |
| `DEBUG` | No | `true` enables Swagger UI at `/api/docs`. Never enable in production. |
