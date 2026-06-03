# Phase 8 — Alerting Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Slices A–E can be split across subagents *after* Slice A (the shared `fire_alert` + email helpers) lands; Slice A is the gate everything else codes against.

**Goal:** Build the OpsPilot alerting engine per `specs/10-alerting.md`: a shared `fire_alert` helper (dedup + cooldown + WS push) that Phases 4/5/6/7 call, a 30s metric evaluator, a 60s log evaluator, auto-resolve at 2 consecutive clean ticks, plain-text SMTP fire/resolve emails, ack/snooze actions, alert/rules read + CRUD endpoints, WS `alert_fired`/`alert_updated`/`alert_resolved` events, default-rule auto-creation at onboarding, and the full `/alerts` + `/alerts/rules` UI with a notification bell, toast, frequency chart, and detail slide-over.

**Architecture:** A new `app/services/alerting.py` owns the single `fire_alert()` / `resolve_alert()` core: it enforces one-open-alert-per-`(type, relevant_fk)` dedup, per-rule (or hardcoded-1h) cooldown, maintenance suppression, persists the row, sends email, and broadcasts the WS event. Two APScheduler jobs (`metric_alert_evaluator` @30s, `log_alert_evaluator` @60s) read rolling windows from `server_metrics` / `server_logs` and drive fire/resolve through that core. Alerts are pushed org-scoped over the **existing** `ws_manager.broadcast_org` seam (alerts are not buffered through `live_bus` — they fire immediately). The frontend gains a `useAlertStore` Pinia store, a top-bar bell + toast in `AppLayout.vue`, and two routed views.

**Tech Stack:** FastAPI + SQLAlchemy async + raw SQL (`text()`) for window aggregates; APScheduler (`AsyncIOScheduler`, SQLAlchemy jobstore); existing `app.services.email.send_email`; existing `ws_manager`; Vue 3 + Pinia + Vuestic + ApexCharts (frequency bar chart); existing `ui/` kit (`DataGrid`, `SlideOver`, `StatusBadge`, `EmptyState`), `useNotify`, `wsClient`.

> **Verification model:** No unit-test harness in this repo → every unit is **smoke-verified** against live data. Backend `http://127.0.0.1:8765` (Docker, postgres `opspilot-postgres`, migrations run via the compose `migrate` service: `docker compose run --rm migrate` i.e. `alembic upgrade head`). Cookie auth: login `smoketest_admin` / `SmokeTest!2026` against `POST /api/auth/login` to get the `opspilot_jwt` cookie, reuse via `curl -c/-b cookiejar`. Live org `e7067c5f-1e52-4255-9f78-d6f6047576f7`, server `fd772547-2f05-4d93-9ed2-9ddbe3e3646c`. UI smokes use host Playwright + login above. Email smoke requires SMTP pointed at a **mailpit** instance (set via `PATCH /api/settings` smtp_host/port/from/recipients; mailpit HTTP UI for assertion). **Headline smoke (Slice B):** lower the CPU rule threshold to ~1%, wait one 30s tick → alert fires + email lands in mailpit; raise threshold back → 2 clean ticks → alert resolves + resolve email.

---

## Already done in earlier phases — DO NOT rebuild

- **`Alert.consecutive_clear_count`** column + **`suppressed`** state value: already present in `backend/app/models/other.py` (lines 104–105). The `StatusBadge` `alert` kind already maps `suppressed` (grey). **However** verify a migration actually added the column to the live DB (model may be ahead of schema) — see Task A0.
- **`maintenance_expiry`** APScheduler job: registered in `main.py` (line 37) + `scheduler.py` (no-op body). Spec checkbox "maintenance_expiry job" is **satisfied structurally**; Phase 8 only adds the *un-suppress / re-fire on window end* logic inside it (Task B4).
- **Maintenance enter suppression**: `routers/maintenance.py` `start_maintenance` already runs the `UPDATE alert SET state='suppressed' …` (lines 64–68). Checkbox "Maintenance enter: immediately suppress" is **done**. Do not duplicate.
- **`send_email` + `parse_recipients` + `EmailNotConfigured`**: live in `app/services/email.py` and proven by Phase 10's `/api/settings/smtp/test`. Reuse — do **not** write a new SMTP client. Phase 8 adds only a thin `alert_email.py` that *formats* fire/resolve bodies and calls `send_email`.
- **`base_url` fallback**: `Settings.base_url` exists; emails use it with a hardcoded fallback string. (Per-request `request.base_url` is unavailable inside scheduler jobs, so jobs fall back to `Settings.base_url or "http://localhost"`; the test endpoint already does `s.base_url or "your OpsPilot instance"`.)
- **`GET /api/organizations/:org_id/alerts/recent`**: already in `routers/dashboard.py` (used by `RecentAlertsPanel`). Keep it; Slice F only wires its `[Ack]` button to the new ack endpoint.
- **`Alert` open→resolved on server delete**: `routers/servers.py` `delete_server` already resolves a server's open alerts. Leave as-is.

> **Coordinator-owned shared-wiring files** (edit once, sequence carefully — flag to the orchestrator; do not let parallel subagents both touch these): `backend/app/main.py` (lifespan job registration), `backend/app/jobs/scheduler.py` (job bodies), `frontend/src/router/index.ts` (routes), `frontend/src/components/common/AppLayout.vue` (bell + toast mount + WS dispatch), `frontend/src/services/api.ts`, `frontend/src/types/index.ts`, `frontend/src/components/ui/index.ts`.

---

## fire_alert — the shared signature other phases code against

Define in `backend/app/services/alerting.py`. **Lock this signature now**; Phases 4 (services/SSL/domain), 5 (logs), 6 (DB), 7 (cron/backup) all import and call it.

```python
# backend/app/services/alerting.py
from datetime import datetime
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.other import Alert

async def fire_alert(
    db: AsyncSession,
    *,
    type: str,                       # spec §15 type key, e.g. "cpu", "service_down", "php_fatal"
    severity: str,                   # "critical" | "warning"
    message: str,                    # human-readable; goes to row + email body + WS
    server_id: UUID | str | None = None,
    service_id: UUID | str | None = None,
    domain_id: UUID | str | None = None,
    ssl_cert_id: UUID | str | None = None,
    cron_job_id: UUID | str | None = None,
    backup_job_id: UUID | str | None = None,
    cooldown_min: int = 60,          # callers without an AlertRule pass the hardcoded 1h default
    email_meta: dict | None = None,  # optional {"condition","value","threshold"} → richer email body; falls back to message
    commit: bool = True,             # evaluators batch many rules then commit once → pass False
) -> Alert | None:
    """
    Idempotent fire. Returns the new Alert, or None if suppressed by:
      (1) active maintenance window on server_id,
      (2) cooldown: an alert with same (type, relevant_fk) fired < cooldown_min ago AND still open,
      (3) dedup: an open (firing|acknowledged|snoozed|suppressed) alert with same (type, relevant_fk) exists.
    On success: INSERT Alert(state='firing', sent_at=now), send fire email (best-effort,
    never raises into caller), and broadcast 'alert_fired' to the org. Resolves org_id from
    server_id (or the subject's server) for the WS fan-out.
    """

async def resolve_alert(
    db: AsyncSession,
    alert: Alert,
    *,
    send_email: bool = True,
    commit: bool = True,
) -> None:
    """Set state='resolved', resolved_at=now, consecutive_clear_count=0; send resolve email
    (best-effort); broadcast 'alert_resolved'. No-op if already resolved."""
```

**Dedup/cooldown key resolution** (`_relevant_fk(type, **fks)`): maps each `type` to its governing FK column per spec §11.3 — `service_down→service_id`, `ssl_expiry→ssl_cert_id`, `domain_expiry→domain_id`, `cron_missing→cron_job_id`, `backup_*→backup_job_id`, everything else (cpu/ram/disk/disk_inode/db_*/agent_offline/log types)→`server_id`. The "one open alert" query filters `Alert.type == type AND <fk_col> == <fk_val> AND state IN ('firing','acknowledged','snoozed','suppressed')`.

**Email best-effort contract:** `fire_alert`/`resolve_alert` wrap `send_email` in try/except (catch `EmailNotConfigured` + any SMTP error), log, and continue — a missing SMTP config must never stop an alert from being recorded or pushed.

---

## File Structure

**Backend — new**
- `backend/app/services/alerting.py` — `fire_alert`, `resolve_alert`, `_relevant_fk`, `_active_maintenance(server_id)`, `_broadcast(event, alert, org_id)`.
- `backend/app/services/alert_email.py` — `format_fire_body(...)`, `format_resolve_body(...)`, `fire_subject(...)`, `resolve_subject(...)` (spec §12) + `send_alert_email(db, alert, kind)` thin wrapper over `email.send_email`.
- `backend/app/services/alert_defaults.py` — `create_default_rules(db, server_id)`: 4 `AlertRule` + 5 `LogAlertRule` rows (spec checkbox line 231).
- `backend/app/jobs/metric_evaluator.py` — `async def metric_alert_evaluator()` (30s).
- `backend/app/jobs/log_evaluator.py` — `async def log_alert_evaluator()` (60s).
- `backend/app/routers/alerts.py` — read endpoints + ack/snooze (spec §14).
- `backend/app/routers/alert_rules.py` — metric + log rule CRUD (spec §14, §9).
- `backend/app/schemas/alerts.py` — `AlertOut`, `SnoozeIn`, `FrequencyBucket`.
- `backend/app/schemas/alert_rules.py` — `MetricRuleIn/Out`, `LogRuleIn/Out`.
- `backend/migrations/versions/0006_alert_state_consecutive.py` — guard migration: ensure `alert.consecutive_clear_count` exists + widen `alert.state` usage (string col already 20-wide; just confirm). Down-rev `0005_server_metrics_compression`.

**Backend — modify (coordinator-owned)**
- `backend/app/main.py` — register `metric_alert_evaluator` (30s) + `log_alert_evaluator` (60s); `include_router(alerts_router, alert_rules_router)`.
- `backend/app/jobs/scheduler.py` — flesh out `maintenance_expiry` un-suppress/re-fire (Task B4) OR keep evaluators in their own modules and only import here.
- `backend/app/routers/servers.py` — call `alert_defaults.create_default_rules` after server insert (Task E4).

**Frontend — new**
- `frontend/src/stores/alerts.ts` — `useAlertStore` (spec §13).
- `frontend/src/views/alerts/AlertsView.vue` — Active + History tabs + frequency chart (`/alerts`).
- `frontend/src/views/alerts/AlertRulesView.vue` — Metric + Log rule tables (`/alerts/rules`, admin).
- `frontend/src/components/alerts/AlertRow.vue`, `AlertDetailSlideOver.vue`, `SnoozePicker.vue`, `AlertFrequencyChart.vue`, `NotificationBell.vue`, `AlertToast.vue`, `MetricRuleModal.vue`, `LogRuleModal.vue`.

**Frontend — modify (coordinator-owned)**
- `frontend/src/router/index.ts` — `/alerts`, `/alerts/rules` (latter `meta:{adminOnly:true}`).
- `frontend/src/components/common/AppLayout.vue` — mount `NotificationBell` in top bar, `AlertToast` container, dispatch `alert_*` WS events to `useAlertStore`, add Alerts nav item.
- `frontend/src/services/api.ts` + `frontend/src/types/index.ts` — alert + rule API funcs and types.
- `frontend/src/components/ui/index.ts` — (only if new shared primitives are extracted).
- `frontend/src/components/dashboard/RecentAlertsPanel.vue` — wire `[Ack]` (Task F7).

---

## SLICE A — Alerting core: fire_alert + resolve_alert + email formatting

### Task A0: Verify/guard the DB schema
**Files:** Create `backend/migrations/versions/0006_alert_state_consecutive.py`
- [ ] Confirm against live DB whether `alert.consecutive_clear_count` exists: `docker exec opspilot-postgres psql -U opspilot -c "\d alert"`. The model has it but it may post-date the last migration.
- [ ] If missing, the migration `op.add_column('alert', sa.Column('consecutive_clear_count', sa.Integer(), server_default='0', nullable=False))`. If present, make the migration a no-op stamp (still create it so `down_revision` chain stays linear: `0006` ← `0005`).
- [ ] **SMOKE:** `docker compose run --rm migrate` exits 0; `\d alert` shows the column.

### Task A1: alert_email.py — fire/resolve subject + body (spec §12)
**Files:** Create `backend/app/services/alert_email.py`
- [ ] `TYPE_DISPLAY: dict` = the full spec §15 map. `fire_subject(s, alert, server_name)` → `"[OpsPilot] {SEVERITY}: {server} — {Display}"`. `resolve_subject(...)` → `"[OpsPilot] RESOLVED: {server} — {Display} returned to normal"`.
- [ ] `format_fire_body(...)` reproduces the §12 block (Severity/Server/Condition/Value/Threshold/Fired at/Message/View dashboard/manage/edit links). Use `base_url = settings_row.base_url or "http://localhost"`. Omit Value/Threshold lines when `email_meta` is None.
- [ ] `async def send_alert_email(db, alert, *, kind, server_name, email_meta)` → loads `Settings` row + `parse_recipients`, builds subject/body, calls `email.send_email`; swallow `EmailNotConfigured`/SMTP errors with `logger.warning`.
- [ ] **SMOKE:** unit-call from a Python REPL in the backend container with a fake Alert dataclass; print body; eyeball §12 layout. (No DB write yet.)

### Task A2: alerting.py — fire_alert + resolve_alert core
**Files:** Create `backend/app/services/alerting.py`
- [ ] Implement signature above. `_relevant_fk` map per spec §11.3. `_active_maintenance(db, server_id)` reuses the maintenance `_active_window` logic (query `MaintenanceWindow` for server, check `starts<=now<ends`); return bool.
- [ ] `_resolve_org_id(db, alert)`: if `server_id` → `Server.org_id`; if `domain_id` → `Domain.org_id`; if `service_id` → service.server.org_id; else None.
- [ ] `_broadcast(event, alert, org_id, server_name)`: `await ws_manager.broadcast_org(org_id, {"event": event, "data": {...}})` with the §10.2 shapes (`alert_fired` full row, `alert_updated`/`alert_resolved` partial).
- [ ] fire flow: maintenance check → dedup/cooldown query → INSERT → `flush` (need PK/sent_at) → `send_alert_email(kind="fire")` → `_broadcast("alert_fired")` → `commit` if `commit`.
- [ ] resolve flow: set fields → flush → `send_alert_email(kind="resolve")` if `send_email` → `_broadcast("alert_resolved")` → commit.
- [ ] **SMOKE:** REPL in container: `await fire_alert(db, type="cpu", severity="critical", message="test", server_id=<live server>)` → row appears (`psql SELECT * FROM alert ORDER BY sent_at DESC LIMIT 1`); calling again immediately returns `None` (dedup); mailpit shows the fire email; an open WS client subscribed to the org receives `alert_fired`.

---

## SLICE B — Metric evaluator + maintenance re-fire (spec §11.1, §11.3 DB/replication)

### Task B1: metric_alert_evaluator job
**Files:** Create `backend/app/jobs/metric_evaluator.py`
- [ ] `async def metric_alert_evaluator()`: open `AsyncSessionLocal`; `SELECT * FROM alert_rule` (no `enabled` column exists → all rules are active; spec's "enabled" maps to row existence + the *log* rules; metric rules have no enabled flag in the model, so "disable" = delete, OR add an `enabled` bool — **decision: reuse delete-as-disable for v1 metric rules** unless model changes; note this divergence in the rule UI). For each rule: rolling-avg query:
  ```sql
  SELECT AVG(value) FROM server_metrics
  WHERE server_id=:sid AND metric_name=:m
    AND time > now() - (:win || ' minutes')::interval
  ```
  Metric-name mapping: rule.metric stores spec keys; translate to stored Telegraf names (`cpu`→`cpu.usage_active`, `ram`→`mem.used_percent`, `disk`→`disk.used_percent` path='/', `disk_inode`→`disk.inodes_used_percent`). Keep this map in `metric_catalog.py` or local `RULE_METRIC`.
- [ ] If `avg > threshold`: `await fire_alert(db, type=<rule.metric key>, severity="critical", message=f"… reached {avg:.1f}% — threshold {threshold}%", server_id=rule.server_id, cooldown_min=rule.cooldown_min, email_meta={...}, commit=False)`; on non-None result set `rule.last_fired_at=now`.
- [ ] If `avg <= threshold`: find open alerts for `(type, server_id)`; `consecutive_clear_count += 1`; if `>= 2` → `resolve_alert(commit=False)`.
- [ ] Replication: special rule — when latest `mariadb.replication_running == 0` fire `db_replication_stopped` immediately (spec §11.3 last bullet). DB connection/lag/deadlock ride the same `server_metrics` path via their own AlertRule rows (`db_connections`, `db_replication_lag`).
- [ ] One `await db.commit()` at the end.
- [ ] **SMOKE (headline):** ensure a `cpu` AlertRule exists for the live server; `PATCH /api/alert-rules/:id {threshold:1}` → within ~30s `GET /api/organizations/:org/alerts` shows a firing cpu alert + mailpit fire email. `PATCH {threshold:95}` → after 2 ticks (~60s) alert resolves + resolve email. Confirm dedup: it never double-fires while open.

### Task B2: register job in main.py
**Files:** Modify `backend/app/main.py` (coordinator)
- [ ] `scheduler.add_job(metric_alert_evaluator, "interval", seconds=30, id="metric_alert_evaluator", replace_existing=True)`.
- [ ] **SMOKE:** backend logs show the job ticking; `GET /api/docs` healthy.

### Task B4: maintenance_expiry un-suppress / re-fire on window end
**Files:** Modify `backend/app/jobs/scheduler.py` `maintenance_expiry`
- [ ] For each server whose newest window just ended (ends_at passed, no active window now) that still has `state='suppressed'` alerts: leave them suppressed for the evaluator to handle — i.e. set suppressed alerts back so the next evaluator tick re-evaluates. Per spec §16: "suppressed alerts whose condition has cleared are auto-resolved; those still breaching fire a new alert (subject to cooldown)." Simplest correct impl: on window-end, `resolve_alert(send_email=False)` all `suppressed` alerts for that server (clearing the slate) → the metric/log evaluator re-fires fresh if still breaching. Document this as the chosen semantics.
- [ ] **SMOKE:** start maintenance (alert suppresses), set ends_at in the past or `DELETE maintenance`, wait a tick → suppressed alert resolves; if CPU still spiked, a new alert fires after the next evaluator tick.

---

## SLICE C — Log evaluator (spec §11.2)

### Task C1: log_alert_evaluator job
**Files:** Create `backend/app/jobs/log_evaluator.py`
- [ ] For each `LogAlertRule` (these *do* conceptually have enabled — model has no `enabled` col either; same v1 decision: existence = enabled): general count query using **`ILIKE`** for user patterns:
  ```sql
  SELECT COUNT(*) FROM server_logs
  WHERE server_id=:sid AND source LIKE :source
    AND message ILIKE :pattern
    AND time > now() - (:win || ' seconds')::interval
  ```
- [ ] SSH brute-force special case (source='auth', per-IP group, **case-sensitive `LIKE '%Failed password%'`**, `GROUP BY source_ip HAVING COUNT(*) >= threshold`).
- [ ] On threshold breach → `fire_alert(type=<rule-derived, e.g. php_fatal/nginx_5xx/ssh_brute_force/mariadb_error/slow_query_spike>, severity=rule.severity, message=…count…, server_id=rule.server_id, cooldown_min=rule.cooldown_min, commit=False)`; set `rule.last_fired_at`.
- [ ] Auto-resolve: below threshold for 2 consecutive ticks → `resolve_alert`. (Track via the alert's `consecutive_clear_count`, same mechanism.)
- [ ] **SMOKE:** create a log rule `source=php_app pattern=%fatal error% threshold=1 window=300`; insert a matching `server_logs` row via psql; wait 60s → alert fires; stop matching → 2 ticks → resolves.

### Task C2: register in main.py (coordinator)
- [ ] `add_job(log_alert_evaluator, "interval", seconds=60, id="log_alert_evaluator", replace_existing=True)`.

---

## SLICE D — Alert read/ack/snooze endpoints + WS events (spec §14, §10)

### Task D1: schemas
**Files:** Create `backend/app/schemas/alerts.py`
- [ ] `AlertOut` (full §14.1 shape incl. joined `server_name`/`service_name`/`domain_name`). `SnoozeIn{minutes:int|None, until:datetime|None}` with a validator: at least one set; `until` precedence; reject past `until` (spec §16).

### Task D2: alerts router — list/history/frequency
**Files:** Create `backend/app/routers/alerts.py` (`prefix="/api"`)
- [ ] `GET /organizations/{org_id}/alerts` → `_assert_org_access`; states firing+acked+snoozed (+suppressed visible per spec §6.1 "everything not resolved"); join server/service/domain names; sort firing→acked→snoozed then sent_at desc.
- [ ] `GET /organizations/{org_id}/alerts/history` → resolved, cursor-paginated (50/page, cursor=`sent_at`+`id`); filters: server_id, type, date range, search (`message ILIKE`).
- [ ] `GET /organizations/{org_id}/alerts/frequency` → last-30-day daily `critical`/`warning` counts (`date_trunc('day', sent_at)` GROUP BY), zero-filled.
- [ ] **SMOKE:** curl all three against live org; shapes match §14.1/§14.3.

### Task D3: ack + snooze (Admin/Operator)
**Files:** add to `backend/app/routers/alerts.py`
- [ ] `POST /alerts/{id}/acknowledge` → guard role ∈ {admin,operator}; set `acknowledged_at`, `state='acknowledged'`; `_broadcast("alert_updated")`.
- [ ] `POST /alerts/{id}/snooze` (`SnoozeIn`) → compute `snoozed_until` (until || now+minutes); `state='snoozed'`; broadcast `alert_updated`.
- [ ] Snooze-expiry re-fire: handled by evaluators — when `snoozed_until` passes and condition persists, the open alert is still deduped; add to the evaluator: if an open alert is `snoozed` and `snoozed_until < now` and still breaching → flip back to `firing` + send email + broadcast (spec §16). Implement this flip inside `fire_alert`'s dedup branch (if the only open alert is an expired snooze, re-fire it rather than skip).
- [ ] **SMOKE:** fire an alert, `POST …/acknowledge` → WS `alert_updated`, badge logic unaffected; `POST …/snooze {minutes:1}` → state snoozed; after 1 min + evaluator tick while breaching → returns to firing + new email.

### Task D4: role guard helper
**Files:** `backend/app/deps.py` (add `OperatorOrAdmin` dep) — coordinator-light
- [ ] `require_operator_or_admin` (role in {admin,operator}); export `WriteUser` annotated dep. Reuse existing `AdminUser` for rule CRUD.

---

## SLICE E — Alert-rule CRUD + default-rule auto-creation (spec §9, §14)

### Task E1: rule schemas
**Files:** Create `backend/app/schemas/alert_rules.py`
- [ ] `MetricRuleIn{server_id, metric, threshold>0, rolling_window_min∈{1,3,5,10,15}, cooldown_min∈{15,30,60,120,240}}`, `MetricRuleOut` (+`is_auto` flag — derive by default values, or add column; v1: compute `is_auto = metric in DEFAULT_METRICS and threshold==default`).
- [ ] `LogRuleIn{server_id, source, pattern(max 500), threshold>=1, window_sec 10..3600, severity, cooldown_min}`, `LogRuleOut`.

### Task E2: alert_rules router
**Files:** Create `backend/app/routers/alert_rules.py`
- [ ] `GET /api/organizations/{org_id}/alert-rules` → both metric + log rules for org's servers, with `server_name`.
- [ ] `POST/PATCH/DELETE /api/alert-rules[/{id}]` (Admin). POST rejects duplicate `(server_id, metric)` → 409 with spec §9.4 message. PATCH: server+metric read-only.
- [ ] `POST/PATCH/DELETE /api/log-alert-rules[/{id}]` (Admin).
- [ ] **SMOKE:** curl create/list/patch/delete; duplicate metric → 409.

### Task E3: default-rule factory
**Files:** Create `backend/app/services/alert_defaults.py`
- [ ] `create_default_rules(db, server_id)`: 4 `AlertRule` (`cpu` >85, `ram` >90, `disk` >85, `disk_inode` >90; window 5, cooldown 60) + 5 `LogAlertRule` (e.g. `php_app %Fatal error% crit`, `nginx_access %" 5__ % warn`, `auth %Failed password% crit` (ssh brute), `mariadb_error %ERROR% crit`, `mariadb_slow %Query_time% warn`; thresholds/windows per spec defaults). Idempotent: skip if rules already exist for the server.
- [ ] **SMOKE:** call in REPL for a server with no rules → 4+5 rows; re-call → no dupes.

### Task E4: wire into onboarding/server-create (coordinator)
**Files:** Modify `backend/app/routers/servers.py` `add_server` (after commit) — call `await create_default_rules(db, server.id)`. (Onboarding runs async via SSH; rules belong at server-create so they exist immediately.)
- [ ] **SMOKE:** `POST /api/organizations/:org/servers` → `GET …/alert-rules` shows the 9 defaults.

---

## SLICE F — Frontend: /alerts, /alerts/rules, bell, toast, detail (spec §3–10, §13, §17)

### Task F1: types + api funcs (coordinator)
**Files:** `frontend/src/types/index.ts`, `frontend/src/services/api.ts`
- [ ] `Alert`, `FrequencyBucket`, `MetricRule`, `LogRule` types; `getActiveAlerts/getAlertHistory/getAlertFrequency/acknowledgeAlert/snoozeAlert/getAlertRules/create*/patch*/delete*` funcs.

### Task F2: useAlertStore (spec §13)
**Files:** Create `frontend/src/stores/alerts.ts`
- [ ] State/getters/actions per §13 incl. `firingCount`, `handleAlertFired/Updated/Resolved` WS handlers (insert/patch/move row + maintain `firingCount`).
- [ ] **SMOKE (Playwright):** after fire, `firingCount` increments without a page refresh.

### Task F3: NotificationBell + AlertToast (spec §3, §10.4)
**Files:** Create `frontend/src/components/alerts/NotificationBell.vue`, `AlertToast.vue`
- [ ] Bell badge = `firingCount` (>99 → "99+"); dropdown top-5 firing; empty → "No active alerts". Toast on `alert_fired` (≤3, 8s auto-dismiss, red/amber border, View→ `/alerts`). Reuse `useNotify` for toast OR a dedicated toast stack — spec wants severity-colored border + View link, so a small custom `AlertToast` stack is cleaner.

### Task F4: mount bell + WS dispatch in AppLayout (coordinator)
**Files:** Modify `frontend/src/components/common/AppLayout.vue`
- [ ] In `startWs()` handler, branch on `msg.event` ∈ {alert_fired,alert_updated,alert_resolved} → call the store handler (events arrive flat, not channel-wrapped — `_broadcast` sends `{event,data}`). Add bell to top bar, toast container, `Alerts` nav item.
- [ ] **SMOKE (Playwright):** trigger a fire via curl → toast appears + badge ticks live.

### Task F5: AlertsView + AlertRow + SnoozePicker + FrequencyChart (spec §4–7)
**Files:** Create `frontend/src/views/alerts/AlertsView.vue` + components
- [ ] Active/History tabs, filter bars, `AlertFrequencyChart` (ApexCharts stacked bar, clickable day filter), `AlertRow` (severity dot, subject, message, state badge via `StatusBadge`, relative time, Ack/Snooze), `SnoozePicker` (15m/30m/1h/4h/Custom modal, past-time validation). History via `DataGrid` + cursor pagination. Empty state via `EmptyState`.
- [ ] **SMOKE (Playwright):** `/alerts` renders firing alert; Ack button clears badge; History tab shows resolved rows; frequency chart renders bars.

### Task F6: AlertDetailSlideOver (spec §8)
**Files:** Create `frontend/src/components/alerts/AlertDetailSlideOver.vue`
- [ ] `SlideOver` (520px): header, message, timeline (Fired/Ack/Snooze/Resolved), Rule section (metric rule → Edit Rule link; log rule → View in Log Viewer; service/ssl/etc → hardcoded condition, "Rule deleted" when none), Ack/Snooze actions. Toast "View →" deep-links open this.
- [ ] **SMOKE (Playwright):** row click opens slide-over with timeline populated.

### Task F7: AlertRulesView + modals + wire RecentAlertsPanel Ack (coordinator for router + panel)
**Files:** Create `AlertRulesView.vue`, `MetricRuleModal.vue`, `LogRuleModal.vue`; modify `router/index.ts` (`/alerts`, `/alerts/rules` adminOnly), `RecentAlertsPanel.vue`.
- [ ] Two tabs (Metric/Log), server filter, "Auto" chip, enabled toggle (v1: toggle = delete/recreate or no-op note since model lacks `enabled`), edit/add modals with §9.2/§9.3 validation + duplicate inline error. Wire `RecentAlertsPanel` `[Ack]` → `acknowledgeAlert`.
- [ ] **SMOKE (Playwright):** admin opens `/alerts/rules`, edits cpu threshold, sees it persist; non-admin redirected. Dashboard `[Ack]` acknowledges and badge drops.

### Task F8: keyboard shortcuts (spec §17)
**Files:** `AlertsView.vue` / `AppLayout.vue`
- [ ] `b` bell, `a` ack focused, `Esc` close, `r` refresh, `/` focus search, `1`/`2` tab switch. (Lower priority; implement after core flows pass.)

---

## Cross-slice smoke (acceptance — must pass before Phase 8 is "done")
- [ ] **Headline:** spike CPU (lower rule threshold) → alert fires within 30s + fire email in mailpit + WS toast/badge in UI → restore threshold → 2 clean ticks → alert resolves + resolve email + row moves to History.
- [ ] Maintenance suppress→un-suppress re-fire works.
- [ ] Log rule (php_fatal) fires + resolves.
- [ ] Ack/Snooze (incl. snooze-expiry re-fire) work and broadcast.
- [ ] Default rules auto-created on new server.
- [ ] Update `pm/PROGRESS.md` Phase 8 checkboxes.

---

## Risks / decisions to confirm with the orchestrator
1. **No `enabled` column** on `AlertRule`/`LogAlertRule` in the current model, but spec §9.2/§9.3 and §11.1 require an Enabled toggle + "evaluator skips disabled". **Recommend adding `enabled BOOLEAN DEFAULT true` to both tables in migration `0006`** rather than the delete-as-disable hack — it's the spec-faithful path and cheap. If added, the evaluators filter `WHERE enabled = true` and the UI toggle is a real PATCH.
2. **WS broadcast scope:** alerts fan out by org via `broadcast_org`; the dashboard already subscribes by org, so the bell works app-wide as long as `AppLayout` issues a `subscribe_org` for the active org (verify it does, else add it).
3. **base_url in jobs:** no `Request` in scheduler context → `Settings.base_url or "http://localhost"`. Spec §12's per-request fallback only applies to request-scoped sends; document this.
