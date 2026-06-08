# GitHub Actions Deploy Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up a GitHub Actions pipeline that lints, builds Docker images, pushes to GHCR, and deploys to the VPS on every push to `main` (and via manual trigger).

**Architecture:** Three jobs run in sequence with parallelism: `lint` blocks both `build-backend` and `build-frontend` (which run in parallel), then `deploy` waits for both builds before SSHing into the server to pull and restart containers. Images are tagged `latest` + `sha-<7-char>` and pushed to GHCR (`ghcr.io/okdii/opspilot-*`). The `docker-compose.yml` `image:` fields point to GHCR so `docker compose pull` works on the server.

**Tech Stack:** GitHub Actions, GHCR (ghcr.io), docker/build-push-action v5, docker/login-action v3, appleboy/ssh-action v1, ruff (Python lint), vue-tsc (frontend type-check, used instead of eslint which is not configured)

---

## Files

| File | Action |
|---|---|
| `backend/.dockerignore` | Create — exclude `__pycache__`, `.pyc`, `.env` from build context |
| `frontend/.dockerignore` | Create — exclude `node_modules`, `dist` from build context |
| `docker-compose.yml` | Modify — add `image:` to `backend`, `migrate`, `frontend` services |
| `.github/workflows/deploy.yml` | Create — full CI/CD pipeline |

---

## Task 1: Add `.dockerignore` files

Prevents `node_modules` (300 MB+) and Python cache from being sent to Docker build context. Without these, CI builds will be very slow.

**Files:**
- Create: `backend/.dockerignore`
- Create: `frontend/.dockerignore`

- [ ] **Step 1: Create `backend/.dockerignore`**

Create file `backend/.dockerignore` with content:
```
__pycache__
*.pyc
*.pyo
*.pyd
.Python
.env
.env.*
*.egg-info
.pytest_cache
.ruff_cache
```

- [ ] **Step 2: Create `frontend/.dockerignore`**

Create file `frontend/.dockerignore` with content:
```
node_modules
dist
.env
.env.*
*.local
```

- [ ] **Step 3: Commit**

```bash
git add backend/.dockerignore frontend/.dockerignore
git commit -m "build: add .dockerignore for backend and frontend"
```

---

## Task 2: Add `image:` fields to `docker-compose.yml`

When `image:` and `build:` are both set, Docker Compose uses `build:` locally and `image:` for `docker compose pull`. This lets the server pull pre-built images from GHCR without rebuilding.

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add `image:` to `migrate` service**

In `docker-compose.yml`, the `migrate` service currently has:
```yaml
  migrate:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: alembic upgrade head
```

Change to:
```yaml
  migrate:
    image: ghcr.io/okdii/opspilot-backend:latest
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: alembic upgrade head
```

- [ ] **Step 2: Add `image:` to `backend` service**

In `docker-compose.yml`, the `backend` service currently has:
```yaml
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: opspilot-backend
```

Change to:
```yaml
  backend:
    image: ghcr.io/okdii/opspilot-backend:latest
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: opspilot-backend
```

- [ ] **Step 3: Add `image:` to `frontend` service**

In `docker-compose.yml`, the `frontend` service currently has:
```yaml
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: opspilot-frontend
```

Change to:
```yaml
  frontend:
    image: ghcr.io/okdii/opspilot-frontend:latest
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: opspilot-frontend
```

- [ ] **Step 4: Verify the file is valid**

```bash
docker compose config --quiet && echo "Valid"
```

Expected output: `Valid` (no errors)

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "build: add GHCR image references to docker-compose.yml"
```

---

## Task 3: Create GitHub Actions workflow

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Create the workflows directory**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Create `.github/workflows/deploy.yml`**

Create file `.github/workflows/deploy.yml` with the following content:

```yaml
name: Deploy

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install ruff
        run: pip install ruff

      - name: Lint backend
        run: ruff check backend/

      - name: Set up Node 20
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install frontend dependencies
        run: npm ci
        working-directory: frontend

      - name: Type-check frontend
        run: npx vue-tsc --noEmit
        working-directory: frontend

  build-backend:
    needs: lint
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Short SHA
        id: sha
        run: echo "short=$(echo ${{ github.sha }} | cut -c1-7)" >> $GITHUB_OUTPUT

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build and push backend image
        uses: docker/build-push-action@v5
        with:
          context: ./backend
          push: true
          tags: |
            ghcr.io/okdii/opspilot-backend:latest
            ghcr.io/okdii/opspilot-backend:sha-${{ steps.sha.outputs.short }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  build-frontend:
    needs: lint
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Short SHA
        id: sha
        run: echo "short=$(echo ${{ github.sha }} | cut -c1-7)" >> $GITHUB_OUTPUT

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build and push frontend image
        uses: docker/build-push-action@v5
        with:
          context: ./frontend
          push: true
          tags: |
            ghcr.io/okdii/opspilot-frontend:latest
            ghcr.io/okdii/opspilot-frontend:sha-${{ steps.sha.outputs.short }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  deploy:
    needs: [build-backend, build-frontend]
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to server
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.SSH_HOST }}
          username: ${{ secrets.SSH_USER }}
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd /opt/opspilot
            docker compose pull
            docker compose up -d
            docker image prune -f
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add GitHub Actions deploy pipeline"
```

- [ ] **Step 4: Push and verify the workflow appears in GitHub**

```bash
git push origin main
```

Then open `https://github.com/okdii/opspilot/actions` — the "Deploy" workflow should appear. On first push to main it will trigger automatically.

---

## Pre-Flight Checklist (Before First Run)

These must be done before the workflow runs successfully:

- [ ] **Add GitHub Secrets** — in `https://github.com/okdii/opspilot/settings/secrets/actions`:
  - `SSH_HOST` — VPS IP or hostname
  - `SSH_USER` — Linux user that owns `/opt/opspilot`
  - `SSH_PRIVATE_KEY` — full content of the ed25519 private key (including `-----BEGIN...` and `-----END...` lines)

- [ ] **Generate deploy key** (on local machine if not done):
  ```bash
  ssh-keygen -t ed25519 -C "opspilot-deploy" -f ~/.ssh/opspilot_deploy
  ssh-copy-id -i ~/.ssh/opspilot_deploy.pub <SSH_USER>@<SSH_HOST>
  cat ~/.ssh/opspilot_deploy   # paste this into SSH_PRIVATE_KEY secret
  ```

- [ ] **Ensure SSH_USER is in docker group** (on server):
  ```bash
  sudo usermod -aG docker $SSH_USER
  # Log out and back in for the group to take effect
  ```

- [ ] **Authenticate server to GHCR** (on server, one-time):
  ```bash
  # Create a GitHub PAT at https://github.com/settings/tokens
  # Classic token, read:packages scope only
  echo <PAT> | docker login ghcr.io -u okdii --password-stdin
  ```

- [ ] **Make GHCR packages public** (optional but simpler — avoids PAT on server):
  After the first successful build, go to `https://github.com/okdii?tab=packages`, open each package, go to Package Settings → Change visibility → Public.
