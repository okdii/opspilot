# Phase 10 — Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the five-tab Admin Settings area (General, Team, Retention, Security, Infrastructure) plus the all-roles `/profile` password change, per `specs/11-settings.md`.

**Architecture:** A new backend slice (`settings`, `team`, `sessions` routers + `email`/`retention` services) on top of the existing single-row `app_settings` model and Phase 1 auth/session/onboarding code. Frontend adds a `SettingsLayout` with tabbed child routes, a `useSettingsStore`, and five tab views built from existing shared components. Writer-password rotation reports progress via short **polling** (Option B) — WebSocket fan-out is deferred to Phase 2 and isolated behind one store action.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy (async) + Alembic; Vue 3 + Vuestic Admin + Pinia + axios; PostgreSQL + TimescaleDB.

**Verification idiom (per CLAUDE.md Rule 1):** This project has **no automated test harness** and verifies every unit by **smoke test** (curl the endpoint + walk the browser happy path). Each task ends with a concrete smoke test, then the Rule 0 dashboard update, then the Rule 4 commit + push. Do **not** introduce pytest/vitest — follow the established pattern.

**Frontend idiom (per CLAUDE.md Rules 2 & 3):** Before building any tab's markup, invoke `/ui-ux-pro-max` for the modern dark-dashboard treatment, and reuse existing components first: `PageHeader`, `DataGrid`, `EmptyState`, `SlideOver`, `StatCard`, `StatusBadge` (`frontend/src/components/ui`), plus `AppLayout`/`OrgSwitcher` (`common`). This plan specifies exact files, store actions, API calls, and payloads (deterministic); the tab template markup is produced via the UI/UX skill at execution time, not hardcoded here.

**Reference design:** `docs/superpowers/specs/2026-06-02-phase10-settings-design.md` and `specs/11-settings.md`.

---

## File Structure

**Backend — create:**
- `backend/migrations/versions/0003_settings_columns.py` — extend `app_settings`
- `backend/app/schemas/settings.py` — settings/sessions/team Pydantic schemas
- `backend/app/routers/settings.py` — `/api/settings`, SMTP test, rotation
- `backend/app/routers/sessions.py` — `/api/sessions`
- `backend/app/routers/team.py` — `/api/team`, invites, org-assignments, user delete
- `backend/app/services/email.py` — SMTP sender (shared; Phase 8 reuses)
- `backend/app/services/retention.py` — TimescaleDB retention policy updates
- `backend/app/services/rotation.py` — writer-password rotation state + per-server runner

**Backend — modify:**
- `backend/app/models/other.py` — add columns to `Settings`
- `backend/app/routers/auth.py` — `change_password` revokes other sessions
- `backend/app/main.py` — register the three new routers

**Frontend — create:**
- `frontend/src/stores/settings.ts` — `useSettingsStore`
- `frontend/src/views/settings/SettingsLayout.vue` — tab shell
- `frontend/src/views/settings/SecurityTab.vue`
- `frontend/src/views/settings/GeneralTab.vue`
- `frontend/src/views/settings/RetentionTab.vue`
- `frontend/src/views/settings/TeamTab.vue`
- `frontend/src/views/settings/InfrastructureTab.vue`

**Frontend — modify:**
- `frontend/src/router/index.ts` (or the file holding routes) — add `/settings/*` children
- `frontend/src/views/auth/ProfileView.vue` — confirm password-change wiring
- `frontend/src/types/index.ts` — add `Session`, `TeamMember`, `Invite`, settings types

---

## Task 1: DB migration — extend `app_settings`

**Files:**
- Modify: `backend/app/models/other.py` (`Settings` class, ~line 238)
- Create: `backend/migrations/versions/0003_settings_columns.py`

- [ ] **Step 1: Update the `Settings` model**

In `backend/app/models/other.py`, replace the `Settings` class body so columns match spec §10. Rename `smtp_user`→`smtp_username`, `smtp_from`→`smtp_from_address`; add the new columns:

```python
class Settings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    instance_name: Mapped[str] = mapped_column(String(255), nullable=False, server_default="OpsPilot")
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_encryption: Mapped[str] = mapped_column(String(10), nullable=False, server_default="tls")
    smtp_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_from_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_recipients: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    logs_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    service_checks_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    alerts_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    writer_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: Find the current migration head**

Run: `cd backend && python -m alembic heads`
Expected: prints one revision id (the `0002_ingestion_token` revision). Note it as `<down_revision>`.

- [ ] **Step 3: Write the migration**

Create `backend/migrations/versions/0003_settings_columns.py`. Use `0002_ingestion_token` as `down_revision` (confirm with Step 2). The migration renames two columns and adds the rest, then seeds `writer_password_encrypted` from the env var so existing agents keep working:

```python
"""extend app_settings for Phase 10 settings

Revision ID: 0003_settings_columns
Revises: 0002_ingestion_token
"""
import os
import base64
import sqlalchemy as sa
from alembic import op
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

revision = "0003_settings_columns"
down_revision = "0002_ingestion_token"
branch_labels = None
depends_on = None


def _encrypt(plaintext: str) -> str:
    key = base64.b64decode(os.environ["OPSPILOT_ENCRYPTION_KEY"])
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def upgrade() -> None:
    op.alter_column("app_settings", "smtp_user", new_column_name="smtp_username")
    op.alter_column("app_settings", "smtp_from", new_column_name="smtp_from_address")
    op.add_column("app_settings", sa.Column("instance_name", sa.String(255), nullable=False, server_default="OpsPilot"))
    op.add_column("app_settings", sa.Column("smtp_encryption", sa.String(10), nullable=False, server_default="tls"))
    op.add_column("app_settings", sa.Column("smtp_recipients", sa.Text(), nullable=True))
    op.add_column("app_settings", sa.Column("alerts_retention_days", sa.Integer(), nullable=False, server_default="90"))
    op.add_column("app_settings", sa.Column("writer_password_encrypted", sa.Text(), nullable=True))

    # Seed writer password (encrypted) from env so existing agents keep authenticating
    writer_pw = os.environ.get("OPSPILOT_WRITER_PASSWORD")
    if writer_pw:
        op.execute(
            sa.text("UPDATE app_settings SET writer_password_encrypted = :v WHERE id = 1").bindparams(
                v=_encrypt(writer_pw)
            )
        )


def downgrade() -> None:
    op.drop_column("app_settings", "writer_password_encrypted")
    op.drop_column("app_settings", "alerts_retention_days")
    op.drop_column("app_settings", "smtp_recipients")
    op.drop_column("app_settings", "smtp_encryption")
    op.drop_column("app_settings", "instance_name")
    op.alter_column("app_settings", "smtp_from_address", new_column_name="smtp_from")
    op.alter_column("app_settings", "smtp_username", new_column_name="smtp_user")
```

- [ ] **Step 4: Smoke test — run the migration**

Run: `cd backend && python -m alembic upgrade head`
Expected: `Running upgrade 0002_ingestion_token -> 0003_settings_columns`. No error.

Run: `psql "$DATABASE_URL" -c "\d app_settings"` (or `docker compose exec postgres psql -U opspilot -c "\d app_settings"`)
Expected: columns `instance_name, smtp_username, smtp_from_address, smtp_encryption, smtp_recipients, alerts_retention_days, writer_password_encrypted` present.

Run: `psql "$DATABASE_URL" -c "SELECT writer_password_encrypted IS NOT NULL AS seeded FROM app_settings WHERE id=1;"`
Expected: `seeded = t`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/other.py backend/migrations/versions/0003_settings_columns.py
git commit -m "Phase 10: extend app_settings (identity, smtp_encryption, recipients, alerts retention, writer password)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Settings schemas + `GET/PATCH /api/settings` router

**Files:**
- Create: `backend/app/schemas/settings.py`
- Create: `backend/app/routers/settings.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the schemas**

Create `backend/app/schemas/settings.py`:

```python
from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    instance_name: str
    base_url: str | None
    smtp_host: str | None
    smtp_port: int | None
    smtp_encryption: str
    smtp_username: str | None
    smtp_from_address: str | None
    smtp_recipients: str | None
    smtp_has_password: bool
    metrics_retention_days: int
    logs_retention_days: int
    service_checks_retention_days: int
    alerts_retention_days: int


class SettingsPatch(BaseModel):
    instance_name: str | None = None
    base_url: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_encryption: str | None = None  # none | tls | ssl
    smtp_username: str | None = None
    smtp_password: str | None = None  # plaintext in; encrypted at rest; blank/None keeps existing
    smtp_from_address: str | None = None
    smtp_recipients: str | None = None
    metrics_retention_days: int | None = Field(default=None, ge=7, le=365)
    logs_retention_days: int | None = Field(default=None, ge=7, le=365)
    service_checks_retention_days: int | None = Field(default=None, ge=30, le=365)
    alerts_retention_days: int | None = Field(default=None, ge=30, le=730)
```

- [ ] **Step 2: Write the router (GET + PATCH)**

Create `backend/app/routers/settings.py`. PATCH applies only keys present in the body; `smtp_password` is encrypted via `crypto.encrypt`; blank password preserved. Retention-key changes call the retention service (added in Task 8 — import is safe to add now as the service file is created there; if executing strictly in order, add the retention call in Task 8 and leave a clear marker here).

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.database import get_db
from app.deps import AdminUser
from app.models.other import Settings
from app.schemas.settings import SettingsResponse, SettingsPatch

router = APIRouter(prefix="/api/settings", tags=["settings"])

RETENTION_KEYS = {
    "metrics_retention_days",
    "logs_retention_days",
    "service_checks_retention_days",
    "alerts_retention_days",
}


async def _get_settings_row(db: AsyncSession) -> Settings:
    row = await db.scalar(select(Settings).where(Settings.id == 1))
    if row is None:
        row = Settings(id=1)
        db.add(row)
        await db.flush()
    return row


@router.get("", response_model=SettingsResponse)
async def get_settings(_: AdminUser, db: AsyncSession = Depends(get_db)) -> SettingsResponse:
    s = await _get_settings_row(db)
    return SettingsResponse(
        instance_name=s.instance_name,
        base_url=s.base_url,
        smtp_host=s.smtp_host,
        smtp_port=s.smtp_port,
        smtp_encryption=s.smtp_encryption,
        smtp_username=s.smtp_username,
        smtp_from_address=s.smtp_from_address,
        smtp_recipients=s.smtp_recipients,
        smtp_has_password=s.smtp_password_encrypted is not None,
        metrics_retention_days=s.metrics_retention_days,
        logs_retention_days=s.logs_retention_days,
        service_checks_retention_days=s.service_checks_retention_days,
        alerts_retention_days=s.alerts_retention_days,
    )


@router.patch("", response_model=SettingsResponse)
async def patch_settings(body: SettingsPatch, _: AdminUser, db: AsyncSession = Depends(get_db)) -> SettingsResponse:
    s = await _get_settings_row(db)
    data = body.model_dump(exclude_unset=True)

    # SMTP password: blank/None keeps existing; non-empty is encrypted
    pw = data.pop("smtp_password", None)
    if pw:
        s.smtp_password_encrypted = crypto.encrypt(pw)

    changed_retention = {}
    for key, value in data.items():
        setattr(s, key, value)
        if key in RETENTION_KEYS:
            changed_retention[key] = value

    await db.commit()

    # Task 8 wires changed_retention -> retention service here.

    return await get_settings(_, db)
```

- [ ] **Step 3: Register the router**

In `backend/app/main.py`, import and include it alongside the existing routers:

```python
from app.routers.settings import router as settings_router
# ...
app.include_router(settings_router)
```

- [ ] **Step 4: Smoke test — GET then PATCH**

Start the backend (`cd backend && uvicorn app.main:app --reload` or the project's run command). Log in as admin to get the cookie (reuse the Phase 1 login curl), saving cookies to `/tmp/c.txt`.

```bash
curl -s -b /tmp/c.txt http://localhost:8000/api/settings | jq
```
Expected: JSON with `instance_name: "OpsPilot"`, `smtp_has_password: false`, retention defaults `30/30/90/90`.

```bash
curl -s -b /tmp/c.txt -X PATCH http://localhost:8000/api/settings \
  -H 'Content-Type: application/json' \
  -d '{"instance_name":"Acme Ops","base_url":"https://monitor.acme.com"}' | jq '.instance_name, .base_url'
```
Expected: `"Acme Ops"` and `"https://monitor.acme.com"`. Re-GET confirms persistence. Confirm a non-admin cookie gets `403`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/settings.py backend/app/routers/settings.py backend/app/main.py
git commit -m "Phase 10: GET/PATCH /api/settings (partial update, encrypted SMTP password)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Frontend foundation — store, layout, routes, guard

**Files:**
- Create: `frontend/src/stores/settings.ts`
- Create: `frontend/src/views/settings/SettingsLayout.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: Add types**

In `frontend/src/types/index.ts`, add:

```ts
export interface Session {
  jti: string
  is_current: boolean
  ip_address: string | null
  user_agent: string | null
  issued_at: string
  expires_at: string
}

export interface OrgAssignment { org_id: string; org_name: string; role: 'operator' | 'viewer' }
export interface TeamMember {
  id: string; username: string; role: 'admin' | 'member'; created_at: string
  org_assignments: OrgAssignment[]
}
export interface PendingInvite {
  id: string; email: string; org_id: string; org_name: string
  role: 'operator' | 'viewer'; expires_at: string
}
export interface RotationServer {
  server_id: string; server_name: string
  status: 'pending' | 'deploying' | 'ok' | 'error'; message: string
}
```

- [ ] **Step 2: Write the store**

Create `frontend/src/stores/settings.ts` implementing the spec §11 shape. Actions hit the endpoints built in later tasks; methods referencing not-yet-built endpoints are still defined now (they fail gracefully until their backend lands, and each tab task verifies its own action).

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'
import type { Session, TeamMember, PendingInvite, RotationServer } from '@/types'

export const useSettingsStore = defineStore('settings', () => {
  const general = ref({ instanceName: 'OpsPilot', baseUrl: '' })
  const smtp = ref({ host: '', port: 587, encryption: 'tls' as 'none' | 'tls' | 'ssl', username: '', fromAddress: '', recipients: '', hasPassword: false })
  const retention = ref({ metricsRetentionDays: 30, logsRetentionDays: 30, serviceChecksRetentionDays: 90, alertsRetentionDays: 90 })
  const sessions = ref<Session[]>([])
  const team = ref<{ members: TeamMember[]; pendingInvites: PendingInvite[] }>({ members: [], pendingInvites: [] })
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  async function fetchSettings() {
    const { data } = await api.get('/api/settings')
    general.value = { instanceName: data.instance_name, baseUrl: data.base_url ?? '' }
    smtp.value = { host: data.smtp_host ?? '', port: data.smtp_port ?? 587, encryption: data.smtp_encryption, username: data.smtp_username ?? '', fromAddress: data.smtp_from_address ?? '', recipients: data.smtp_recipients ?? '', hasPassword: data.smtp_has_password }
    retention.value = { metricsRetentionDays: data.metrics_retention_days, logsRetentionDays: data.logs_retention_days, serviceChecksRetentionDays: data.service_checks_retention_days, alertsRetentionDays: data.alerts_retention_days }
  }
  async function saveGeneral(p: { instance_name: string; base_url: string }) { await api.patch('/api/settings', p); await fetchSettings() }
  async function saveSmtp(p: Record<string, unknown>) { await api.patch('/api/settings', p); await fetchSettings() }
  async function testSmtp() { await api.post('/api/settings/smtp/test') }
  async function saveRetention(p: Record<string, number>) { await api.patch('/api/settings', p); await fetchSettings() }
  async function fetchSessions() { const { data } = await api.get('/api/sessions'); sessions.value = data }
  async function revokeSession(jti: string) { await api.patch(`/api/sessions/${jti}/revoke`); await fetchSessions() }
  async function revokeAllOtherSessions() { await api.post('/api/sessions/revoke-others'); await fetchSessions() }
  async function fetchTeam() { const { data } = await api.get('/api/team'); team.value = { members: data.members, pendingInvites: data.pending_invites } }
  async function inviteMember(p: { email: string; org_id: string; role: string }) { await api.post('/api/invites', p); await fetchTeam() }
  async function addOrgAssignment(userId: string, p: { org_id: string; role: string }) { await api.post(`/api/users/${userId}/org-assignments`, p); await fetchTeam() }
  async function removeOrgAssignment(userId: string, orgId: string) { await api.delete(`/api/users/${userId}/org-assignments/${orgId}`); await fetchTeam() }
  async function removeMember(userId: string) { await api.delete(`/api/users/${userId}`); await fetchTeam() }
  async function resendInvite(inviteId: string) { await api.post(`/api/invites/${inviteId}/resend`); await fetchTeam() }
  async function revokeInvite(inviteId: string) { await api.delete(`/api/invites/${inviteId}`); await fetchTeam() }
  async function changePassword(p: { current_password: string; new_password: string }) { await api.patch('/api/auth/password', p) }

  // Option B: rotation via polling. Swap body to WS subscribe in Phase 2 — callers unchanged.
  async function rotateWriterPassword(p: { new_password: string }) {
    const { data } = await api.post('/api/settings/rotate-writer-password', p)
    return data as { rotation_id: string; total_servers: number }
  }
  async function pollRotation(rotationId: string) {
    const { data } = await api.get(`/api/settings/rotation/${rotationId}`)
    return data as { servers: RotationServer[]; done: boolean }
  }
  async function retryRotationServer(rotationId: string, serverId: string) {
    await api.post(`/api/settings/rotation/${rotationId}/retry/${serverId}`)
  }

  return { general, smtp, retention, sessions, team, isLoading, error,
    fetchSettings, saveGeneral, saveSmtp, testSmtp, saveRetention,
    fetchSessions, revokeSession, revokeAllOtherSessions,
    fetchTeam, inviteMember, addOrgAssignment, removeOrgAssignment, removeMember, resendInvite, revokeInvite,
    changePassword, rotateWriterPassword, pollRotation, retryRotationServer }
})
```

- [ ] **Step 3: Build the layout shell (via UI/UX skill)**

Invoke `/ui-ux-pro-max` (Rule 2) for a modern dark tabbed settings shell, reusing `PageHeader`. Create `frontend/src/views/settings/SettingsLayout.vue`:
- `PageHeader` titled "Settings".
- A tab bar (VaTabs) with General / Team / Retention / Security / Infrastructure; selecting a tab does `router.push('/settings/<name>')`; active tab follows `route.path`.
- `<router-view />` below the tabs.
- Keyboard shortcuts: keys `1`–`5` switch tabs, `r` re-fetches the active tab's data, `Escape` closes any open modal. Register/cleanup listeners in `onMounted`/`onUnmounted`.

- [ ] **Step 4: Add routes + admin guard**

In the router, add children under the authenticated shell (sibling to `servers`/`profile`), all `meta: { adminOnly: true }`:

```ts
{
  path: 'settings',
  component: () => import('@/views/settings/SettingsLayout.vue'),
  meta: { adminOnly: true },
  children: [
    { path: '', redirect: '/settings/general' },
    { path: 'general', name: 'settings-general', component: () => import('@/views/settings/GeneralTab.vue') },
    { path: 'team', name: 'settings-team', component: () => import('@/views/settings/TeamTab.vue') },
    { path: 'retention', name: 'settings-retention', component: () => import('@/views/settings/RetentionTab.vue') },
    { path: 'security', name: 'settings-security', component: () => import('@/views/settings/SecurityTab.vue') },
    { path: 'infrastructure', name: 'settings-infrastructure', component: () => import('@/views/settings/InfrastructureTab.vue') },
  ],
},
```

Confirm the existing global `beforeEach` guard already honours `meta.adminOnly` (it does for `organizations`). If a non-admin hits `/settings/*`, it redirects to `/` with the toast "This area requires admin access." If the guard does not yet emit that specific toast, add it.

- [ ] **Step 5: Create placeholder tab files**

To keep routing resolvable before each tab is built, create the five tab `.vue` files with a minimal `<template><div /></template><script setup lang="ts"></script>`. Each later task replaces its file with the real implementation.

- [ ] **Step 6: Smoke test — navigation + guard**

`cd frontend && npm run dev`. As admin, open `/settings` → redirects to `/settings/general`; clicking each tab updates the URL and renders the (empty) view; pressing `1`–`5` switches tabs. Log in as a non-admin member → visiting `/settings` redirects to `/` with the toast.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/stores/settings.ts frontend/src/views/settings frontend/src/router frontend/src/types/index.ts
git commit -m "Phase 10: settings store, tabbed layout, admin-guarded routes (foundation)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Security backend — sessions router + password-change revokes others

**Files:**
- Create: `backend/app/routers/sessions.py`
- Modify: `backend/app/routers/auth.py` (`change_password`)
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas/settings.py` (add `SessionResponse`)

- [ ] **Step 1: Add the session schema**

Append to `backend/app/schemas/settings.py`:

```python
from datetime import datetime

class SessionResponse(BaseModel):
    jti: str
    is_current: bool
    ip_address: str | None
    user_agent: str | None
    issued_at: datetime
    expires_at: datetime
```

- [ ] **Step 2: Write the sessions router**

Create `backend/app/routers/sessions.py`. The current session is on `request.state.current_session` (set by `get_current_user` in `deps.py`). List active sessions for the current user; flag the current one; revoke by jti; revoke all others.

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser
from app.models.session import Session
from app.schemas.settings import SessionResponse

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionResponse])
async def list_sessions(user: AdminUser, request: Request, db: AsyncSession = Depends(get_db)):
    current_jti = str(request.state.current_session.jti)
    now = datetime.now(timezone.utc)
    rows = (await db.scalars(
        select(Session).where(Session.user_id == user.id, Session.revoked == False)  # noqa: E712
    )).all()
    rows = [r for r in rows if r.expires_at.replace(tzinfo=timezone.utc) > now]
    return [
        SessionResponse(
            jti=str(r.jti), is_current=(str(r.jti) == current_jti),
            ip_address=r.ip_address, user_agent=r.user_agent,
            issued_at=r.issued_at, expires_at=r.expires_at,
        ) for r in rows
    ]


@router.patch("/{jti}/revoke", status_code=204)
async def revoke_session(jti: str, user: AdminUser, request: Request, db: AsyncSession = Depends(get_db)):
    if jti == str(request.state.current_session.jti):
        raise HTTPException(400, detail={"error": "cannot_revoke_current", "message": "Cannot revoke the current session."})
    await db.execute(update(Session).where(Session.jti == jti, Session.user_id == user.id).values(revoked=True))
    await db.commit()


@router.post("/revoke-others", status_code=204)
async def revoke_others(user: AdminUser, request: Request, db: AsyncSession = Depends(get_db)):
    current_jti = str(request.state.current_session.jti)
    await db.execute(update(Session).where(Session.user_id == user.id, Session.jti != current_jti).values(revoked=True))
    await db.commit()
```

- [ ] **Step 3: Make `change_password` revoke other sessions**

In `backend/app/routers/auth.py`, update `change_password` to accept `Request` and revoke every other session for the user after the hash changes (spec §7.2/§9.3):

```python
from sqlalchemy import update
from app.models.session import Session

@router.patch("/password", status_code=204)
async def change_password(body: ChangePasswordRequest, request: Request, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, detail={"error": "wrong_password", "message": "Current password is incorrect."})
    user.password_hash = hash_password(body.new_password)
    current_jti = str(request.state.current_session.jti)
    await db.execute(update(Session).where(Session.user_id == user.id, Session.jti != current_jti).values(revoked=True))
    await db.commit()
    return None
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`:

```python
from app.routers.sessions import router as sessions_router
app.include_router(sessions_router)
```

- [ ] **Step 5: Smoke test — sessions list, revoke, password revoke**

Log in twice (two cookie jars `/tmp/c1.txt`, `/tmp/c2.txt`) as the same admin.
```bash
curl -s -b /tmp/c1.txt http://localhost:8000/api/sessions | jq
```
Expected: two entries; exactly one `is_current: true` (the c1 one).

```bash
JTI=$(curl -s -b /tmp/c1.txt http://localhost:8000/api/sessions | jq -r '.[] | select(.is_current==false) | .jti')
curl -s -b /tmp/c1.txt -X PATCH http://localhost:8000/api/sessions/$JTI/revoke -o /dev/null -w '%{http_code}\n'
curl -s -b /tmp/c2.txt http://localhost:8000/api/auth/me -o /dev/null -w '%{http_code}\n'
```
Expected: `204` then `401` (c2's session now revoked).

Password revoke: log in twice again; change password with c1; confirm c2 → `401` and c1 still `200` on `/api/auth/me`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/sessions.py backend/app/routers/auth.py backend/app/main.py backend/app/schemas/settings.py
git commit -m "Phase 10: sessions router + password change revokes all other sessions

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Security tab (frontend) + dashboard update

**Files:**
- Modify: `frontend/src/views/settings/SecurityTab.vue`
- Modify: `pm/PROGRESS.md`, `DASHBOARD.html`

- [ ] **Step 1: Build the tab (via UI/UX skill)**

Invoke `/ui-ux-pro-max`. Build `SecurityTab.vue` reusing `DataGrid` and `EmptyState`:
- On mount: `settings.fetchSessions()`.
- Active Sessions `DataGrid`: columns Label ("This device" italic if `is_current`, else "Other device"), Browser/OS (parse `user_agent` best-effort; fall back to raw UA), IP, Issued (relative from `issued_at`), Expires (relative to `expires_at`), and a `[Revoke]` action shown only when `!is_current` → `settings.revokeSession(jti)`.
- `[Revoke All Other Sessions]` button top-right → confirm modal "This will sign out all other devices. Continue?" → `settings.revokeAllOtherSessions()`.
- If only the current session exists: show "No other active sessions" via `EmptyState` below the current row.
- Below: admin Change Password form (Current / New (min 8) / Confirm match) → `settings.changePassword({ current_password, new_password })`; on success toast "Password changed. All other sessions have been revoked."; on `401` show "Current password is incorrect" under the Current field (use `getApiError`).

- [ ] **Step 2: Smoke test (browser)**

Open `/settings/security` as admin with a second browser/incognito session active. Verify: both sessions listed, current one labelled + no revoke button; revoke the other → it disappears and the other browser is bounced to login on its next action. Change password with a wrong current password → inline error; with a correct one → toast, and the second session (re-logged-in) is signed out.

- [ ] **Step 3: Update dashboard (Rule 0)**

In `pm/PROGRESS.md` under Phase 10, change the Security-related lines to ✅:
`GET/PATCH /api/sessions/:jti/revoke + revoke-others`, `/settings/security (active sessions table, password change)`.
In `DASHBOARD.html`, set the matching Phase 10 tasks `status: 'pending'` → `'done'` and bump `LAST_UPDATED` to `2026-06-02`.

- [ ] **Step 4: Commit + push (Rule 4)**

```bash
git add frontend/src/views/settings/SecurityTab.vue pm/PROGRESS.md DASHBOARD.html
git commit -m "Phase 10: Security tab — active sessions + admin password change (smoke tested)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin main
```

---

## Task 6: General backend — email service + SMTP test endpoint

**Files:**
- Create: `backend/app/services/email.py`
- Modify: `backend/app/routers/settings.py` (add `/smtp/test`)

- [ ] **Step 1: Write the email service (shared; Phase 8 reuses)**

Create `backend/app/services/email.py`. One responsibility: send a text/plain email given the persisted SMTP settings. Encryption `none`/`tls` (STARTTLS)/`ssl`.

```python
import smtplib
from email.message import EmailMessage

from app.core import crypto
from app.models.other import Settings


class EmailNotConfigured(Exception):
    pass


def send_email(s: Settings, subject: str, body: str, recipients: list[str]) -> None:
    if not s.smtp_host or not s.smtp_from_address:
        raise EmailNotConfigured("SMTP is not configured.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = s.smtp_from_address
    msg["To"] = ", ".join(recipients)
    msg.set_content(body, subtype="plain", charset="utf-8")

    port = s.smtp_port or 587
    password = crypto.decrypt(s.smtp_password_encrypted) if s.smtp_password_encrypted else None

    if s.smtp_encryption == "ssl":
        server = smtplib.SMTP_SSL(s.smtp_host, port, timeout=15)
    else:
        server = smtplib.SMTP(s.smtp_host, port, timeout=15)
    try:
        if s.smtp_encryption == "tls":
            server.starttls()
        if s.smtp_username and password:
            server.login(s.smtp_username, password)
        server.send_message(msg)
    finally:
        server.quit()


def parse_recipients(raw: str | None) -> list[str]:
    return [e.strip() for e in (raw or "").split(",") if e.strip()]
```

- [ ] **Step 2: Add the SMTP test endpoint**

In `backend/app/routers/settings.py`, add (reusing `_get_settings_row`):

```python
from fastapi import HTTPException
from app.services.email import send_email, parse_recipients, EmailNotConfigured

@router.post("/smtp/test", status_code=200)
async def smtp_test(_: AdminUser, db: AsyncSession = Depends(get_db)):
    s = await _get_settings_row(db)
    recipients = parse_recipients(s.smtp_recipients)
    if not recipients:
        raise HTTPException(400, detail={"error": "no_recipients", "message": "Add at least one alert recipient first."})
    subject = f"[OpsPilot] Test Email — {s.instance_name}"
    base = s.base_url or "your OpsPilot instance"
    body = (
        "This is a test email from OpsPilot.\n"
        "If you received this, your SMTP configuration is working correctly.\n\n"
        f"Sent by: {s.instance_name} ({base})\n"
    )
    try:
        send_email(s, subject, body, [recipients[0]])
    except EmailNotConfigured as e:
        raise HTTPException(400, detail={"error": "not_configured", "message": str(e)})
    except Exception as e:  # SMTP errors surfaced verbatim to the admin
        raise HTTPException(502, detail={"error": "smtp_error", "message": str(e)})
    return {"ok": True, "sent_to": recipients[0]}
```

- [ ] **Step 3: Smoke test**

Configure SMTP via PATCH (use a real or Mailtrap/MailHog account):
```bash
curl -s -b /tmp/c.txt -X PATCH http://localhost:8000/api/settings -H 'Content-Type: application/json' \
  -d '{"smtp_host":"sandbox.smtp.mailtrap.io","smtp_port":2525,"smtp_encryption":"tls","smtp_username":"<u>","smtp_password":"<p>","smtp_from_address":"alerts@acme.com","smtp_recipients":"admin@acme.com"}' >/dev/null
curl -s -b /tmp/c.txt -X POST http://localhost:8000/api/settings/smtp/test | jq
```
Expected: `{ "ok": true, "sent_to": "admin@acme.com" }` and the email visible in the inbox. With a bad host, expect `502` and the SMTP error string in `detail.message`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/email.py backend/app/routers/settings.py
git commit -m "Phase 10: SMTP email service + POST /api/settings/smtp/test (shared with Phase 8)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: General tab (frontend) + dashboard update

**Files:**
- Modify: `frontend/src/views/settings/GeneralTab.vue`
- Modify: `pm/PROGRESS.md`, `DASHBOARD.html`

- [ ] **Step 1: Build the tab (via UI/UX skill)**

Invoke `/ui-ux-pro-max`. `GeneralTab.vue`, on mount `settings.fetchSettings()`:
- **Identity section** (own `[Save]` → `settings.saveGeneral({ instance_name, base_url })`): Instance Name, Base URL (strip trailing slash). If `general.baseUrl` is empty show the amber banner: "Base URL is not configured — links will use the request Host header as fallback."
- **SMTP section** (own `[Save]` → `settings.saveSmtp({...})`): Host, Port (1–65535), Encryption select (None/TLS/SSL), Username, Password (placeholder `••••••••` when `smtp.hasPassword`; blank = keep — only send `smtp_password` when the field is non-empty), From Address, Alert Recipients (comma-separated). If `!smtp.host` show amber banner "Email notifications are disabled — configure SMTP to receive alerts." and disable the test button.
- `[Send Test Email]` → spinner → `settings.testSmtp()`; success toast "Test email sent to &lt;recipient&gt;."; failure inline error from `getApiError(err)?.message`.
- Toast "Settings saved." after each successful save.

- [ ] **Step 2: Smoke test (browser)**

Open `/settings/general`. Save a new instance name + base URL → toast, persists on reload, banner disappears once base URL set. Enter SMTP creds, Save, then Send Test Email → success toast + inbox receives it. Clear the host → amber banner returns and test button disables.

- [ ] **Step 3: Update dashboard (Rule 0)**

PROGRESS.md → ✅ for `GET/PATCH /api/settings`, `POST /api/settings/smtp/test`, `/settings/general (instance name, base URL, SMTP)`. DASHBOARD.html matching tasks → `done`; bump `LAST_UPDATED`.

- [ ] **Step 4: Commit + push (Rule 4)**

```bash
git add frontend/src/views/settings/GeneralTab.vue pm/PROGRESS.md DASHBOARD.html
git commit -m "Phase 10: General tab — identity + SMTP config with test email (smoke tested)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin main
```

---

## Task 8: Retention backend — service + wire into PATCH

**Files:**
- Create: `backend/app/services/retention.py`
- Modify: `backend/app/routers/settings.py` (call service on retention changes)

- [ ] **Step 1: Write the retention service**

Create `backend/app/services/retention.py`. Maps each retention setting to its hypertable and applies the TimescaleDB policy. Uses the async engine; `add_retention_policy(..., if_not_exists => true)` is idempotent and updates the interval.

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# setting key -> hypertable name
HYPERTABLES = {
    "metrics_retention_days": "server_metrics",
    "logs_retention_days": "server_logs",
    "service_checks_retention_days": "service_checks",
    "alerts_retention_days": "alert",  # relational table; retention applied by the alerts cleanup job, not a hypertable
}


async def apply_retention(db: AsyncSession, key: str, days: int) -> None:
    table = HYPERTABLES.get(key)
    if table is None or table == "alert":
        # alerts_retention_days is consumed by the Phase 8 alert-history cleanup job; nothing to do on a hypertable here.
        return
    await db.execute(
        text("SELECT remove_retention_policy(:t, if_exists => true)").bindparams(t=table)
    )
    await db.execute(
        text("SELECT add_retention_policy(:t, INTERVAL ':d days', if_not_exists => true)".replace(":d days", f"{days} days")).bindparams(t=table)
    )
    await db.commit()
```

Note: TimescaleDB does not accept a bound parameter inside an `INTERVAL` literal, so `days` is interpolated as an integer (already validated `7–730` by the schema) while the table name stays a bound param.

- [ ] **Step 2: Wire into the PATCH handler**

In `backend/app/routers/settings.py` `patch_settings`, replace the Task 2 marker comment with the call:

```python
from app.services.retention import apply_retention
# ... after await db.commit():
for key, value in changed_retention.items():
    await apply_retention(db, key, value)
```

- [ ] **Step 3: Smoke test**

```bash
curl -s -b /tmp/c.txt -X PATCH http://localhost:8000/api/settings -H 'Content-Type: application/json' \
  -d '{"metrics_retention_days":14}' | jq '.metrics_retention_days'
```
Expected: `14`. Verify the policy in the DB:
```bash
psql "$DATABASE_URL" -c "SELECT config FROM timescaledb_information.jobs WHERE proc_name='policy_retention' AND hypertable_name='server_metrics';"
```
Expected: `drop_after` shows `14 days`. Out-of-range (e.g. `5`) → `422` from schema validation.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/retention.py backend/app/routers/settings.py
git commit -m "Phase 10: retention service — apply TimescaleDB policies on settings change

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Retention tab (frontend) + dashboard update

**Files:**
- Modify: `frontend/src/views/settings/RetentionTab.vue`
- Modify: `pm/PROGRESS.md`, `DASHBOARD.html`

- [ ] **Step 1: Build the tab (via UI/UX skill)**

Invoke `/ui-ux-pro-max`. `RetentionTab.vue`, on mount `settings.fetchSettings()`:
- Always-visible warning block (spec §6.2 text about immediate deletion).
- Four number fields with min/max: metrics (7–365), logs (7–365), service checks (30–365), alerts (30–730).
- Single `[Save Retention Settings]` → `settings.saveRetention({ metrics_retention_days, logs_retention_days, service_checks_retention_days, alerts_retention_days })`.
- Toast "Retention settings saved. Changes will take effect shortly."

- [ ] **Step 2: Smoke test (browser)**

Open `/settings/retention`. Change metrics to 14, save → toast; reload shows 14 persisted. Enter an out-of-range value → field validation blocks save.

- [ ] **Step 3: Update dashboard (Rule 0)**

PROGRESS.md → ✅ for `/settings/retention (retention fields, TimescaleDB policy update)`. DASHBOARD.html → `done`; bump `LAST_UPDATED`.

- [ ] **Step 4: Commit + push (Rule 4)**

```bash
git add frontend/src/views/settings/RetentionTab.vue pm/PROGRESS.md DASHBOARD.html
git commit -m "Phase 10: Retention tab — policy editor (smoke tested)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin main
```

---

## Task 10: Team backend — team router

**Files:**
- Create: `backend/app/routers/team.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas/settings.py` (team schemas)

Reuse: `Invite`, `User`, `UserOrganization`, `Organization` models; `email.send_email` for invite emails; token + 48h expiry pattern from the existing invite-accept flow in `auth.py`.

- [ ] **Step 1: Add team schemas**

Append to `backend/app/schemas/settings.py`:

```python
from pydantic import EmailStr

class InviteCreate(BaseModel):
    email: EmailStr
    org_id: str
    role: str  # operator | viewer

class OrgAssignmentCreate(BaseModel):
    org_id: str
    role: str  # operator | viewer
```

- [ ] **Step 2: Write the router**

Create `backend/app/routers/team.py`. Endpoints per spec §12. Invite token generation mirrors the existing flow (`secrets.token_urlsafe`, 48h expiry). Invite email body links to `{base_url}/invite/{token}`. The `DELETE /api/users/:id` sole-operator guard returns `409` with the org list.

```python
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser
from app.models.user import User
from app.models.organization import Organization, UserOrganization
from app.models.invite import Invite
from app.models.other import Settings
from app.schemas.settings import InviteCreate, OrgAssignmentCreate
from app.services.email import send_email

router = APIRouter(prefix="/api", tags=["team"])


def _invite_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=48)


async def _org_name(db: AsyncSession, org_id) -> str:
    return await db.scalar(select(Organization.name).where(Organization.id == org_id))


@router.get("/team")
async def get_team(_: AdminUser, db: AsyncSession = Depends(get_db)):
    users = (await db.scalars(select(User))).all()
    members = []
    for u in users:
        assigns = (await db.scalars(select(UserOrganization).where(UserOrganization.user_id == u.id))).all()
        members.append({
            "id": str(u.id), "username": u.username, "role": u.role,
            "created_at": u.created_at,
            "org_assignments": [
                {"org_id": str(a.org_id), "org_name": await _org_name(db, a.org_id), "role": a.role}
                for a in assigns
            ],
        })
    now = datetime.now(timezone.utc)
    invites = (await db.scalars(select(Invite).where(Invite.accepted_at.is_(None)))).all()
    pending = [{
        "id": str(i.id), "email": i.email, "org_id": str(i.org_id),
        "org_name": await _org_name(db, i.org_id), "role": i.role, "expires_at": i.expires_at,
    } for i in invites]
    return {"members": members, "pending_invites": pending}


@router.post("/invites")
async def create_invite(body: InviteCreate, _: AdminUser, db: AsyncSession = Depends(get_db)):
    if await db.scalar(select(User).where(User.username == body.email)):
        raise HTTPException(409, detail={"error": "already_member", "message": "This email is already a member."})
    if await db.scalar(select(Invite).where(Invite.email == body.email, Invite.accepted_at.is_(None))):
        raise HTTPException(409, detail={"error": "already_pending", "message": "An invite is already pending for this email."})
    token = secrets.token_urlsafe(32)
    invite = Invite(email=body.email, org_id=body.org_id, role=body.role, token=token, expires_at=_invite_expiry())
    db.add(invite)
    await db.commit()
    await _send_invite_email(db, invite)
    return {"ok": True, "invite_id": str(invite.id)}


@router.post("/invites/{invite_id}/resend")
async def resend_invite(invite_id: str, _: AdminUser, db: AsyncSession = Depends(get_db)):
    invite = await db.scalar(select(Invite).where(Invite.id == invite_id))
    if not invite or invite.accepted_at is not None:
        raise HTTPException(404, detail={"error": "not_found", "message": "Invite not found."})
    invite.token = secrets.token_urlsafe(32)
    invite.expires_at = _invite_expiry()
    await db.commit()
    await _send_invite_email(db, invite)
    return {"ok": True}


@router.delete("/invites/{invite_id}", status_code=204)
async def revoke_invite(invite_id: str, _: AdminUser, db: AsyncSession = Depends(get_db)):
    invite = await db.scalar(select(Invite).where(Invite.id == invite_id))
    if invite:
        await db.delete(invite)
        await db.commit()


@router.post("/users/{user_id}/org-assignments")
async def add_org_assignment(user_id: str, body: OrgAssignmentCreate, _: AdminUser, db: AsyncSession = Depends(get_db)):
    exists = await db.scalar(select(UserOrganization).where(
        UserOrganization.user_id == user_id, UserOrganization.org_id == body.org_id))
    if exists:
        raise HTTPException(409, detail={"error": "already_assigned", "message": "User already in this organisation."})
    db.add(UserOrganization(user_id=user_id, org_id=body.org_id, role=body.role))
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}/org-assignments/{org_id}", status_code=204)
async def remove_org_assignment(user_id: str, org_id: str, _: AdminUser, db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(UserOrganization).where(
        UserOrganization.user_id == user_id, UserOrganization.org_id == org_id))
    if row:
        await db.delete(row)
        await db.commit()


@router.delete("/users/{user_id}", status_code=204)
async def remove_member(user_id: str, _: AdminUser, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        return
    if user.role == "admin":
        raise HTTPException(400, detail={"error": "cannot_remove_admin", "message": "Admins cannot be removed."})
    # Sole-operator guard
    assigns = (await db.scalars(select(UserOrganization).where(
        UserOrganization.user_id == user_id, UserOrganization.role == "operator"))).all()
    sole = []
    for a in assigns:
        other = await db.scalar(select(func.count()).select_from(UserOrganization).where(
            UserOrganization.org_id == a.org_id, UserOrganization.role == "operator",
            UserOrganization.user_id != user_id))
        if not other:
            sole.append({"org_id": str(a.org_id), "org_name": await _org_name(db, a.org_id)})
    if sole:
        raise HTTPException(409, detail={
            "error": "sole_operator", "orgs": sole,
            "message": f"This user is the only Operator for {len(sole)} organisation(s). Assign another Operator before removing.",
        })
    await db.delete(user)  # UserOrganization rows cascade (ondelete=CASCADE)
    await db.commit()


async def _send_invite_email(db: AsyncSession, invite: Invite) -> None:
    s = await db.scalar(select(Settings).where(Settings.id == 1))
    if not s or not s.smtp_host:
        return  # email disabled; invite still valid via link
    base = (s.base_url or "").rstrip("/")
    link = f"{base}/invite/{invite.token}"
    org_name = await _org_name(db, invite.org_id)
    body = (
        f"You have been invited to OpsPilot ({s.instance_name}) for {org_name} as {invite.role}.\n\n"
        f"Accept your invite:\n{link}\n\n"
        "This link expires in 48 hours.\n"
    )
    from app.services.email import send_email as _send
    try:
        _send(s, f"[OpsPilot] You're invited to {s.instance_name}", body, [invite.email])
    except Exception:
        pass  # invite persists even if email send fails; admin can resend
```

Before implementing, confirm the actual `UserOrganization` model location/columns and `Invite` columns (`token`, `expires_at`, `accepted_at`, `role`, `org_id`, `email`) — adjust imports to the real module (the accept flow in `auth.py` imports them; mirror those imports).

- [ ] **Step 3: Register the router**

In `backend/app/main.py`:
```python
from app.routers.team import router as team_router
app.include_router(team_router)
```

- [ ] **Step 4: Smoke test**

```bash
# list
curl -s -b /tmp/c.txt http://localhost:8000/api/team | jq '.members[0].username, (.pending_invites|length)'
# invite (use a real org_id from /api/organizations)
ORG=$(curl -s -b /tmp/c.txt http://localhost:8000/api/organizations | jq -r '.[0].id')
curl -s -b /tmp/c.txt -X POST http://localhost:8000/api/invites -H 'Content-Type: application/json' \
  -d "{\"email\":\"charlie@example.com\",\"org_id\":\"$ORG\",\"role\":\"operator\"}" | jq
```
Expected: invite created, appears in `/api/team` `pending_invites`. Re-invite same email → `409 already_pending`. Accept the invite via the Phase 1 `/api/invite/{token}/accept` flow, then `DELETE /api/users/{id}` for that new member when they are the only operator of the org → `409 sole_operator` with the org listed. Add a second operator, retry delete → `204`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/team.py backend/app/main.py backend/app/schemas/settings.py
git commit -m "Phase 10: team router — invites, org assignments, member removal (sole-operator guard)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Team tab (frontend) + dashboard update

**Files:**
- Modify: `frontend/src/views/settings/TeamTab.vue`
- Modify: `pm/PROGRESS.md`, `DASHBOARD.html`

- [ ] **Step 1: Build the tab (via UI/UX skill)**

Invoke `/ui-ux-pro-max`. `TeamTab.vue`, on mount `settings.fetchTeam()` (also needs the org list — reuse `useOrgStore`):
- **Members** `DataGrid`: Username, Role (Admin/Member), Orgs (`org_name (role)` comma-joined), `[⋮]`. Admin rows show `—` (no menu). Member rows menu: Add to Organisation (modal: org dropdown limited to orgs the member is NOT in + role radio → `addOrgAssignment`), Remove from Organisation (dropdown of assigned orgs → `removeOrgAssignment`), Remove from Team (confirm modal → `removeMember`; on `409 sole_operator` show the returned message + listed orgs and block).
- **Pending Invites** `DataGrid`: Email, Org, Role, Expires (relative or "Expired" amber), `[⋮]` (Resend always; Revoke only when not expired) → `resendInvite` / `revokeInvite`.
- `[+ Invite Member]` → modal (Email, Org dropdown, Role radio Operator/Viewer) → `inviteMember`; inline error on `409` (already member/pending) via `getApiError`.
- Use `SlideOver` or VaModal for the modals; `EmptyState` when no members beyond admin / no pending invites.

- [ ] **Step 2: Smoke test (browser)**

Open `/settings/team`. Invite a new email → row appears under Pending. Resend → toast. Revoke → row removed. For an accepted member: Add to Organisation, Remove from Organisation, and attempt Remove from Team while sole operator → blocked with the sole-operator message; add another operator then remove → succeeds.

- [ ] **Step 3: Update dashboard (Rule 0)**

PROGRESS.md → ✅ for `GET /api/team`, `POST /api/invites + resend + revoke`, `POST /api/users/:id/org-assignments + DELETE`, `DELETE /api/users/:id (sole-operator guard → 409)`, `/settings/team (...)`. DASHBOARD.html → `done`; bump `LAST_UPDATED`.

- [ ] **Step 4: Commit + push (Rule 4)**

```bash
git add frontend/src/views/settings/TeamTab.vue pm/PROGRESS.md DASHBOARD.html
git commit -m "Phase 10: Team tab — members, org assignments, invites (smoke tested)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin main
```

---

## Task 12: Infrastructure backend — writer-password rotation (Option B polling)

**Files:**
- Create: `backend/app/services/rotation.py`
- Modify: `backend/app/routers/settings.py` (rotation endpoints)
- Modify: `backend/app/schemas/settings.py` (rotation schema)

Reuse: `onboarding_service.schedule(server_id, redeploy_only=True)` (re-renders agent configs + restarts services — steps 6–10) and `crypto.encrypt`. The agent config templates read the writer password from `app_settings.writer_password_encrypted`; confirm the telegraf/fluent-bit template render path reads the rotated value (it must, for re-deploy to pick up the new password) — if it currently reads the env var, update the template context to prefer the DB value.

- [ ] **Step 1: Rotation schema**

Append to `backend/app/schemas/settings.py`:

```python
class RotateWriterPassword(BaseModel):
    new_password: str = Field(min_length=16)

    @classmethod
    def _no_spaces(cls, v: str) -> str:
        if " " in v:
            raise ValueError("Password must not contain spaces.")
        return v
```

(Use a Pydantic `field_validator` to enforce no-spaces; match the validator style already used in `config.py`.)

- [ ] **Step 2: Rotation state + runner**

Create `backend/app/services/rotation.py`. In-memory rotation registry keyed by `rotation_id`; each server entry tracks status/message. The runner updates PostgreSQL, persists the new password, then re-deploys each active server via the onboarding service.

```python
import asyncio
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.database import AsyncSessionLocal, engine
from app.models.server import Server
from app.models.other import Settings
from app.services import onboarding as onboarding_service


@dataclass
class ServerProgress:
    server_id: str
    server_name: str
    status: str = "pending"   # pending | deploying | ok | error
    message: str = "Waiting"


@dataclass
class Rotation:
    rotation_id: str
    servers: dict[str, ServerProgress] = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return all(s.status in ("ok", "error") for s in self.servers.values())


_rotations: dict[str, Rotation] = {}


def get(rotation_id: str) -> Rotation | None:
    return _rotations.get(rotation_id)


async def start(new_password: str) -> tuple[str, int]:
    rotation_id = str(uuid.uuid4())

    async with AsyncSessionLocal() as db:
        active = (await db.scalars(select(Server).where(Server.status == "online"))).all()
        rotation = Rotation(rotation_id=rotation_id, servers={
            str(s.id): ServerProgress(str(s.id), s.name) for s in active
        })
        _rotations[rotation_id] = rotation

        # 1) ALTER USER on PostgreSQL (autocommit — DDL outside a txn)
        async with engine.connect() as conn:
            await conn.execute(text(f"ALTER USER opspilot_writer PASSWORD '{new_password}'")
                               .execution_options(isolation_level="AUTOCOMMIT"))
        # 2) Persist encrypted password
        s = await db.scalar(select(Settings).where(Settings.id == 1))
        s.writer_password_encrypted = crypto.encrypt(new_password)
        await db.commit()

    asyncio.create_task(_run(rotation_id))
    return rotation_id, len(rotation.servers)


async def _run(rotation_id: str) -> None:
    rotation = _rotations[rotation_id]
    for sid, prog in rotation.servers.items():
        await _redeploy_one(rotation, sid)


async def _redeploy_one(rotation: Rotation, server_id: str) -> None:
    prog = rotation.servers[server_id]
    prog.status, prog.message = "deploying", "Re-deploying..."
    try:
        ok = onboarding_service.schedule(server_id, redeploy_only=True)
        # schedule() returns False if a job is already running for this server
        if not ok:
            prog.status, prog.message = "error", "A deploy is already running for this server."
            return
        # Poll the server's onboarding outcome via its status flip back to online.
        await _await_redeploy(server_id)
        prog.status, prog.message = "ok", "Updated successfully"
    except Exception as e:
        prog.status, prog.message = "error", str(e)


async def _await_redeploy(server_id: str, timeout: float = 90.0) -> None:
    # The onboarding service writes OnboardingLog rows and flips server.status.
    # Wait until the scheduled task completes (no in-flight job) or timeout.
    elapsed = 0.0
    while elapsed < timeout:
        if not onboarding_service.is_running(server_id):
            return
        await asyncio.sleep(2.0)
        elapsed += 2.0
    raise TimeoutError("Re-deploy timed out.")


async def retry(rotation_id: str, server_id: str) -> None:
    rotation = _rotations.get(rotation_id)
    if rotation and server_id in rotation.servers:
        await _redeploy_one(rotation, server_id)
```

Before implementing, verify the onboarding service exposes a way to tell whether a server's job is in flight. `schedule()` already guards against concurrent jobs (returns `False`); add a small `is_running(server_id) -> bool` helper to `onboarding.py` if one does not exist (it tracks tasks in a dict per the Phase 1 implementation). Adjust `_await_redeploy` to whatever completion signal the service exposes (task done, or final OnboardingLog row).

- [ ] **Step 3: Rotation endpoints**

In `backend/app/routers/settings.py`:

```python
from app.schemas.settings import RotateWriterPassword
from app.services import rotation as rotation_service

@router.post("/rotate-writer-password")
async def rotate_writer_password(body: RotateWriterPassword, _: AdminUser):
    rotation_id, total = await rotation_service.start(body.new_password)
    return {"ok": True, "rotation_id": rotation_id, "total_servers": total}

@router.get("/rotation/{rotation_id}")
async def rotation_status(rotation_id: str, _: AdminUser):
    r = rotation_service.get(rotation_id)
    if not r:
        raise HTTPException(404, detail={"error": "not_found", "message": "Rotation not found."})
    return {"done": r.done, "servers": [
        {"server_id": p.server_id, "server_name": p.server_name, "status": p.status, "message": p.message}
        for p in r.servers.values()
    ]}

@router.post("/rotation/{rotation_id}/retry/{server_id}", status_code=204)
async def rotation_retry(rotation_id: str, server_id: str, _: AdminUser):
    await rotation_service.retry(rotation_id, server_id)
```

- [ ] **Step 4: Smoke test**

With the Lima Ubuntu VM server `online`:
```bash
curl -s -b /tmp/c.txt -X POST http://localhost:8000/api/settings/rotate-writer-password \
  -H 'Content-Type: application/json' -d '{"new_password":"S3cretWriterPwLong"}' | jq
```
Expected: `{ ok:true, rotation_id:"...", total_servers:1 }`. Poll:
```bash
RID=<rotation_id>
curl -s -b /tmp/c.txt http://localhost:8000/api/settings/rotation/$RID | jq
```
Expected: server transitions `deploying` → `ok`. Verify metrics resume flowing after the agent restart:
```bash
psql "$DATABASE_URL" -c "SELECT count(*) FROM server_metrics WHERE time > now() - interval '2 minutes';"
```
Expected: non-zero (agents reconnected with the new password). Short password (<16) → `422`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rotation.py backend/app/routers/settings.py backend/app/schemas/settings.py backend/app/services/onboarding.py
git commit -m "Phase 10: writer-password rotation (ALTER USER + per-server re-deploy, poll status)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 13: Infrastructure tab (frontend) + dashboard update

**Files:**
- Modify: `frontend/src/views/settings/InfrastructureTab.vue`
- Modify: `pm/PROGRESS.md`, `DASHBOARD.html`

- [ ] **Step 1: Build the tab (via UI/UX skill)**

Invoke `/ui-ux-pro-max`. `InfrastructureTab.vue`:
- Rotate section (spec §8.1 copy): New Password (min 16, no spaces), Confirm (must match).
- `[Rotate Password]` → confirm modal "This will restart Telegraf and Fluent Bit on all X active servers..." → `const { rotation_id } = await settings.rotateWriterPassword({ new_password })`.
- Progress panel: `setInterval` ~2s calling `settings.pollRotation(rotation_id)`; render each server with icon by status (`ok`→✓, `deploying`→⟳ spinner, `pending`→○, `error`→✕) + message; `error` rows show `[Retry]` → `settings.retryRotationServer(rotation_id, server_id)`. Stop polling when `done`; show "Rotation complete. N of M servers updated." Clear the interval in `onUnmounted`.
- Collapsed env-var reference block (spec §8.2 text), read-only.

This is the only Option-B (polling) screen; a comment should note the swap point to WS for Phase 2.

- [ ] **Step 2: Smoke test (browser)**

Open `/settings/infrastructure` with the Lima VM online. Enter a 16+ char password, confirm, rotate → confirm modal → progress panel shows the server going ⟳ → ✓ and "Rotation complete. 1 of 1 servers updated." Confirm the metrics chart resumes after the brief gap. Mismatched confirm / <16 chars → client-side validation blocks submit.

- [ ] **Step 3: Update dashboard (Rule 0)**

PROGRESS.md → ✅ for `POST /api/settings/rotate-writer-password (...)` and `/settings/infrastructure (...)`. DASHBOARD.html → `done`; bump `LAST_UPDATED`.

- [ ] **Step 4: Commit + push (Rule 4)**

```bash
git add frontend/src/views/settings/InfrastructureTab.vue pm/PROGRESS.md DASHBOARD.html
git commit -m "Phase 10: Infrastructure tab — writer password rotation with poll progress (smoke tested)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin main
```

---

## Task 14: Profile page password change + final dashboard reconcile

**Files:**
- Modify: `frontend/src/views/auth/ProfileView.vue`
- Modify: `pm/PROGRESS.md`, `DASHBOARD.html`

- [ ] **Step 1: Verify/complete the profile password form**

Confirm `ProfileView.vue` (already routed at `/profile`) renders: read-only Username, Role (Admin → "Admin — Global Access"; member → "Operator in X, Viewer in Y" from `/api/auth/me`), Member since (`created_at` as `YYYY-MM-DD`), and the Change Password form (Current / New min 8 / Confirm match) → `PATCH /api/auth/password`. On success toast "Password changed. You have been signed out of all other devices."; on `401` inline "Current password is incorrect." If any piece is missing, add it (reuse the same form approach as `SecurityTab`). Optionally factor the shared password form into a `PasswordChangeForm.vue` component used by both (Rule 3 — promote on second use).

- [ ] **Step 2: Smoke test (browser)**

As a non-admin member, open `/profile` → fields correct, password change works, other sessions signed out. As admin, Role shows "Admin — Global Access".

- [ ] **Step 3: Final dashboard reconcile (Rule 0)**

Ensure every Phase 10 line in `pm/PROGRESS.md` is ✅ and the Phase 10 summary row reads `✅ Complete | 16 / 16`; update the Total count. Set all Phase 10 `DASHBOARD.html` tasks to `done` and `LAST_UPDATED` to today.

- [ ] **Step 4: Commit + push (Rule 4)**

```bash
git add frontend/src/views/auth/ProfileView.vue frontend/src/components pm/PROGRESS.md DASHBOARD.html
git commit -m "Phase 10 complete: profile password change + dashboard reconcile (16/16)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin main
```

---

## Self-Review

**Spec coverage (spec 11 → task):**
- §4 General/SMTP → Tasks 2, 6, 7 ✅
- §5 Team (members, invites, org-assignments, sole-operator guard) → Tasks 10, 11 ✅
- §6 Retention → Tasks 8, 9 ✅
- §7 Security (sessions, password change revokes others) → Tasks 4, 5 ✅
- §8 Infrastructure rotation → Tasks 12, 13 (Option B polling per ratified deviation) ✅
- §9 Profile → Task 14 ✅
- §10 Settings storage (single-row, ratified) → Task 1 ✅
- §11 store shape → Task 3 ✅
- §12 endpoints → Tasks 2/4/6/10/12 ✅
- §13 edge states → covered in the relevant tab build steps (banners, 409s, empty states) ✅
- §14 keyboard shortcuts → Task 3 Step 3 ✅

**Placeholder scan:** No "TBD"/"handle edge cases" left; the two "before implementing, confirm…" notes point at specific existing modules to mirror (`UserOrganization`/`Invite` imports; onboarding completion signal) — these are verification instructions, not deferred work.

**Type consistency:** Store action names match spec §11 and the endpoints they call (`rotateWriterPassword`/`pollRotation`/`retryRotationServer` ↔ `/rotate-writer-password`, `/rotation/:id`, `/rotation/:id/retry/:server_id`); schema field names (`smtp_username`, `smtp_from_address`, `alerts_retention_days`) consistent across migration, model, schema, and store.

**Known integration points to verify at execution (flagged in-task):** (a) the global router guard already emits the admin-only toast; (b) agent config templates read `writer_password_encrypted` from the DB, not the env var, so re-deploy applies the rotated password; (c) onboarding service completion signal for `_await_redeploy`.
