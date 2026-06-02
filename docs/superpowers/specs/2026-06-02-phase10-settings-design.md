# Phase 10 — Settings: Implementation Design

**Date:** 2026-06-02
**Status:** Approved (design)
**Authoritative spec:** `specs/11-settings.md` (v1.0, Approved)
**PRD refs:** §5.1, §5.19, §9

This document is the *implementation design* for Phase 10. The full functional
spec lives in `specs/11-settings.md`; this doc maps that spec onto the existing
codebase, records build order, names the components to reuse, and ratifies the
two deviations from the spec.

---

## 1. Scope & Approach

Phase 10 delivers the five Settings tabs plus the `/profile` password change:

1. **General** — instance identity (name, base URL) + SMTP config
2. **Team** — invites, members, org assignments, removal
3. **Retention** — TimescaleDB retention policy overrides
4. **Security** — active session management + admin password change
5. **Infrastructure** — `opspilot_writer` agent DB password rotation

`/settings/*` is Admin-only. `/profile` is all-roles.

### Build order (value-first)

Built and shipped tab-by-tab (each tab is one functional unit → smoke test →
dashboard update → commit + push, per CLAUDE.md Rules 0/1/4):

1. **Security** — endpoints/model mostly exist from Phase 1; fastest win.
2. **General / SMTP** — builds the shared `email` service that **unblocks Phase 8** alert emails.
3. **Retention** — TimescaleDB policy updates.
4. **Team** — invites, members, org assignments.
5. **Infrastructure** — writer password rotation (poll-based progress).

### Dependency note

Four of five tabs depend only on Phase 1 (complete). The **only** cross-phase
coupling is the Infrastructure tab's *live rotation progress*, which the spec
describes over the Phase 2 WebSocket fan-out (`subscribe_rotation` /
`writer_rotation_progress`). Phase 2's WS fan-out is not yet built, so we use
**Option B — short polling** (see §5, Deviation 1).

---

## 2. What Already Exists (Reuse First — CLAUDE.md Rule 3)

| Asset | Location | Used by |
|---|---|---|
| AES-256 encrypt/decrypt | `backend/app/core/crypto.py` | SMTP password, writer password |
| Password change endpoint | `auth.py` `PATCH /api/auth/password` | Security tab, `/profile` (needs session-revoke fix) |
| Session model + jti revocation | `models/session.py` | Security tab |
| Invite accept flow | `auth.py` `/{token}` + `/{token}/accept` | Team tab (admin-initiated invite is new) |
| Agent re-deploy | `routers/servers.py` `redeploy_agents` + `onboarding_service.schedule(redeploy_only=True)` | Infrastructure rotation |
| `app_settings` single-row model | `models/other.py` `Settings` | All settings reads/writes (needs new columns) |
| `adminOnly` route guard meta | `frontend/src/router/*` | `/settings/*` guard |
| Shared UI: `PageHeader`, `DataGrid`, `EmptyState`, `SlideOver`, `StatCard`, `StatusBadge`, `AppLayout`, `OrgSwitcher` | `frontend/src/components/ui` + `common` | All tabs |
| Existing `ProfileView.vue` | `frontend/src/views/auth/` | `/profile` password change |

---

## 3. Backend Design

### 3.1 New routers

**`routers/settings.py`** (Admin)
- `GET /api/settings` — returns all settings, no sensitive values; `smtp_has_password: bool` flag only (spec §12.1)
- `PATCH /api/settings` — partial update; applies only keys present in body (identity / SMTP / retention all route here)
- `POST /api/settings/smtp/test` — send test email to first recipient (spec §4.2)
- `POST /api/settings/rotate-writer-password` — start rotation; returns `{ ok, rotation_id, total_servers }`
- `GET /api/settings/rotation/:id` — **poll** endpoint returning per-server status array (Option B; replaces WS channel)

Retention saves go through `PATCH /api/settings`; the handler detects changed
retention keys and calls the retention service (§3.3).

**`routers/team.py`** (Admin)
- `GET /api/team` — members (with `org_assignments`) + `pending_invites` (spec §12.2)
- `POST /api/invites` — admin-initiated invite (distinct from the existing accept flow); 48h token; sends email; rejects already-member / already-pending email
- `POST /api/invites/:id/resend` — new token, new email, old token invalidated
- `DELETE /api/invites/:id` — revoke pending invite
- `POST /api/users/:id/org-assignments` — add `UserOrganization`
- `DELETE /api/users/:id/org-assignments/:org_id` — remove assignment
- `DELETE /api/users/:id` — remove member; **sole-operator guard** returns `409 { error: "sole_operator", orgs: [...] }` (spec §12)

**`routers/sessions.py`** (Admin)
- `GET /api/sessions` — active sessions (`revoked=false AND expires_at > now()`); each row labelled current vs other by matching the request's jti
- `PATCH /api/sessions/:jti/revoke` — set `revoked=true`
- `POST /api/sessions/revoke-others` — revoke all except current jti

### 3.2 New services

**`services/email.py`** — SMTP sender. text/plain; charset=utf-8; supports
encryption `none` / `tls` (STARTTLS) / `ssl`. Reads config from `app_settings`,
decrypts password via `crypto.py`. Pure component (one job: send an email given
settings + subject + body + recipients). **Phase 8 alerting reuses this.**

**`services/retention.py`** — given a hypertable + day count, calls
`alter_retention_policy()` (or `add_retention_policy()` if absent). One function
per hypertable mapping; invoked from the settings PATCH handler for changed keys.

### 3.3 Existing-code change: password change revokes other sessions

`auth.change_password` currently only updates the hash. Spec §7.2/§9.3 require
auto-revoking **all other** sessions on password change. Change:
- Thread the current request's session jti into the handler (from the auth
  dependency / cookie claims).
- After updating the hash, set `revoked=true` on all the user's sessions whose
  jti ≠ current.
- Response unchanged (204); frontend shows the "signed out of other devices" toast.

### 3.4 Migration — extend `app_settings`

Current columns: `smtp_host, smtp_port, smtp_user, smtp_password_encrypted,
smtp_from, base_url, metrics_retention_days, logs_retention_days,
service_checks_retention_days`.

Add / rename to match spec §10:
- **Add:** `instance_name` (default `OpsPilot`), `smtp_encryption` (default `tls`),
  `smtp_recipients`, `alerts_retention_days` (default 90), `writer_password_encrypted`.
- **Rename:** `smtp_user` → `smtp_username`, `smtp_from` → `smtp_from_address`.

`writer_password_encrypted` holds the post-rotation writer password; on first
boot it is seeded from the `OPSPILOT_WRITER_PASSWORD` env var. `crypto.py`
handles encryption. Env-only secrets (`OPSPILOT_ENCRYPTION_KEY`,
`OPSPILOT_JWT_SECRET`) are never stored in the DB.

### 3.5 Writer password rotation flow (Option B)

1. Validate new password (min 16, no spaces).
2. `ALTER USER opspilot_writer PASSWORD '<new>'` on PostgreSQL.
3. Update `app_settings.writer_password_encrypted` (encrypted).
4. Create an in-memory (or DB-backed) rotation record keyed by `rotation_id`
   with one entry per active server (status `pending`).
5. For each active server, enqueue the existing `redeploy_only=True` onboarding
   job; update that server's rotation entry to `deploying` → `ok`/`error`.
6. Frontend polls `GET /api/settings/rotation/:id` every ~2s; renders the
   progress panel; stops when all entries terminal. `[Retry]` re-enqueues one server.

Rotation state store is isolated behind a small module so swapping poll → WS in
Phase 2 touches only the transport, not the rotation logic.

---

## 4. Frontend Design

### 4.1 Routing & layout

- Add child routes under the authenticated shell: `/settings` (redirect →
  `/settings/general`), `/settings/general|team|retention|security|infrastructure`,
  all with `meta.adminOnly`. Non-admin → `/` with toast "This area requires admin access."
- **`SettingsLayout.vue`** — `PageHeader` + VaTabs tab bar (updates URL) +
  `<router-view>`. Keyboard shortcuts: `1`–`5` switch tabs, `Esc` close modal,
  `r` refresh current tab. Unsaved-changes discard warning on navigate-away.

### 4.2 Tab views (`views/settings/`)

Each reuses shared components and is designed via the UI/UX Pro Max skill
(CLAUDE.md Rule 2) before coding:

- **`SecurityTab.vue`** — `DataGrid` of active sessions (label, browser/OS from UA,
  IP, issued, expires, `[Revoke]`); `[Revoke All Other Sessions]`; current row no
  revoke + italic "This device"; below it the admin password-change form.
  Empty state ("No other active sessions") via `EmptyState`.
- **`GeneralTab.vue`** — Identity section (instance name, base URL) + SMTP section,
  each with its own `[Save]` (both → `PATCH /api/settings`). `[Send Test Email]`
  with spinner + inline result. Amber banners for no-SMTP and no-base-url states.
  Password field placeholder `••••••••`, blank = keep existing.
- **`RetentionTab.vue`** — four day fields (with min/max), always-visible warning
  block, single `[Save Retention Settings]`.
- **`TeamTab.vue`** — Members `DataGrid` (kebab per member row: add/remove org,
  remove from team) + Pending Invites `DataGrid` (resend/revoke). Invite modal,
  Add-to-Org modal (`SlideOver` or VaModal). Sole-operator 409 surfaced in the
  remove confirmation.
- **`InfrastructureTab.vue`** — rotate form (new + confirm password), confirmation
  modal, poll-driven progress panel (`✓/⟳/○/✕` per server) with `[Retry]`,
  collapsed env-var reference block.

### 4.3 Store — `stores/settings.ts`

Implements the exact `useSettingsStore` state + actions in spec §11
(`general`, `smtp`, `retention`, `sessions`, `team`, plus the actions list).
`rotateWriterPassword` + a `pollRotation(rotationId)` helper encapsulate Option B.

### 4.4 `/profile`

Wire the existing `ProfileView.vue` password form to `PATCH /api/auth/password`;
show "Password changed. You have been signed out of all other devices." on success
(backed by §3.3). Username read-only; role/member-since from `/api/auth/me`.

---

## 5. Deviations from Spec 11 (Ratified)

1. **Rotation progress uses short polling (Option B), not WebSocket.** Spec §8.1
   describes a `subscribe_rotation` WS channel; that depends on Phase 2's WS
   fan-out, which is not yet built. We expose `GET /api/settings/rotation/:id`
   and poll every ~2s. The rotation transport is isolated so a later swap to WS
   is a small, contained change.
2. **`app_settings` stays a single-row table**, not the key-value store the spec
   §10 prose describes. The Phase 1 model is already single-row; functionally
   identical and simpler. We add the missing columns (§3.4).

---

## 6. Per-Unit Definition of Done

For each tab (functional unit), in order, per CLAUDE.md:
1. Smoke test the happy path (backend curl + browser walk-through; sessions/email/
   rotation verified live where applicable) — Rule 1.
2. Update `pm/PROGRESS.md` (⬜→✅) **and** `DASHBOARD.html` (status + LAST_UPDATED) — Rule 0.
3. Commit + push (`git push origin main`), dashboard update in the same commit — Rule 4.

Out of scope for Phase 10: Phase 2 WS fan-out, Phase 8 alert evaluators (though
the `email` service built here is the dependency Phase 8 will consume).
