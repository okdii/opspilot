# GitHub Actions Deploy Pipeline — Design Spec

**Date:** 2026-06-08  
**Status:** Approved

---

## Overview

A CI/CD pipeline using GitHub Actions that lints, builds Docker images, pushes them to GitHub Container Registry (GHCR), and deploys to the production VPS via SSH. Triggers on every push to `main` and via manual `workflow_dispatch`.

---

## Workflow File

**Path:** `.github/workflows/deploy.yml`

---

## Job Graph

```
[push to main / workflow_dispatch]
         │
       lint
     (ruff + eslint)
         │
    ┌────┴────┐
build-backend  build-frontend   ← parallel
    └────┬────┘
       deploy
    (SSH → pull → up -d)
```

### Job: `lint`

- **Runner:** `ubuntu-latest`
- **Steps:**
  1. Checkout code
  2. Set up Python 3.11, install `ruff`, run `ruff check backend/`
  3. Set up Node 20, run `npm ci` in `frontend/`, run `npx eslint frontend/src/`
- **On failure:** Blocks `build-backend` and `build-frontend` from starting

### Job: `build-backend`

- **Runner:** `ubuntu-latest`
- **Needs:** `lint`
- **Steps:**
  1. Checkout code
  2. Log in to GHCR using `GITHUB_TOKEN`
  3. Build `./backend/Dockerfile`
  4. Push as `ghcr.io/okdii/opspilot-backend:sha-<7-char-sha>` and `ghcr.io/okdii/opspilot-backend:latest`
- **Used by:** both `backend` and `migrate` services (same Dockerfile, different `command`)

### Job: `build-frontend`

- **Runner:** `ubuntu-latest`
- **Needs:** `lint`
- **Steps:**
  1. Checkout code
  2. Log in to GHCR using `GITHUB_TOKEN`
  3. Build `./frontend/Dockerfile`
  4. Push as `ghcr.io/okdii/opspilot-frontend:sha-<7-char-sha>` and `ghcr.io/okdii/opspilot-frontend:latest`

### Job: `deploy`

- **Runner:** `ubuntu-latest`
- **Needs:** `build-backend`, `build-frontend`
- **Steps:**
  1. SSH into server using `SSH_PRIVATE_KEY`, `SSH_HOST`, `SSH_USER`
  2. Run:
     ```bash
     cd /opt/opspilot
     docker compose pull
     docker compose up -d
     docker image prune -f
     ```
- **Downtime:** ~30 seconds (migrate runs, then backend restarts)
- **Failure safety:** If SSH step fails, existing containers keep running — no unplanned downtime

---

## Image Naming

| Service | GHCR Image |
|---|---|
| `backend` | `ghcr.io/okdii/opspilot-backend:latest` |
| `migrate` | `ghcr.io/okdii/opspilot-backend:latest` (same image, different command) |
| `frontend` | `ghcr.io/okdii/opspilot-frontend:latest` |

---

## docker-compose.yml Changes

Add `image:` fields to `backend`, `migrate`, and `frontend` services. Docker Compose uses the `image:` name when pulling from a registry, while `build:` continues to work for local development.

```yaml
# backend and migrate
image: ghcr.io/okdii/opspilot-backend:latest

# frontend
image: ghcr.io/okdii/opspilot-frontend:latest
```

---

## Secrets Required

| GitHub Secret | Description |
|---|---|
| `SSH_HOST` | VPS IP address or hostname |
| `SSH_USER` | Linux user that owns `/opt/opspilot` |
| `SSH_PRIVATE_KEY` | Ed25519 private key content (no passphrase) |

`GITHUB_TOKEN` is built-in to GitHub Actions — no manual secret needed for GHCR access.

---

## One-Time Server Setup

```bash
# Generate deploy key (local machine)
ssh-keygen -t ed25519 -C "opspilot-deploy" -f ~/.ssh/opspilot_deploy

# Install public key on server
ssh-copy-id -i ~/.ssh/opspilot_deploy.pub <SSH_USER>@<SSH_HOST>

# Add SSH_PRIVATE_KEY secret to GitHub (paste output of):
cat ~/.ssh/opspilot_deploy

# Ensure SSH_USER can run docker without sudo
sudo usermod -aG docker $USER  # re-login after
```

---

## GHCR Package Visibility

GHCR packages are private by default. The server's Docker daemon must authenticate to pull them. The deploy step handles this by running `docker compose pull` while already authenticated via SSH — but the server itself needs a one-time `docker login`:

```bash
# On the server — one-time
echo <GITHUB_PAT> | docker login ghcr.io -u <github_username> --password-stdin
```

Use a GitHub Personal Access Token (classic) with `read:packages` scope.

---

## Estimated Pipeline Time

| Stage | Time |
|---|---|
| Lint | ~1 min |
| Build backend + frontend (parallel) | ~4-5 min |
| Deploy (pull + up -d) | ~1 min |
| **Total** | **~6-8 min** |

---

## Files Created / Modified

| File | Change |
|---|---|
| `.github/workflows/deploy.yml` | New — full pipeline workflow |
| `docker-compose.yml` | Add `image:` to `backend`, `migrate`, `frontend` |
