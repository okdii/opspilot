# SSL Certificate Tracking in HTTP Service Probes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically extract and track SSL certificate expiry for every HTTPS service probe, eliminating the need to register the same domain twice.

**Architecture:** Add 8 SSL columns to the `service` table. After each HTTP probe run, if `ssl_enabled=true` and the last SSL check was >6 hours ago, open a TLS socket (reusing `ssl_checker._fetch_ssl_cert`), persist the cert state, and fire/resolve `ssl_expiry` alerts keyed to `service_id`. The SSL & Domain page is unchanged; it continues to manage domain WHOIS + non-standard-port SSL certs.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async / Alembic — Vue 3 / Pinia / TypeScript

**Spec:** `docs/superpowers/specs/2026-06-04-ssl-in-http-probe-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/migrations/versions/0008_service_ssl_columns.py` | CREATE | Alembic migration — 8 new columns on `service` |
| `backend/app/models/other.py` | MODIFY | Add SSL mapped columns to `Service` class |
| `backend/app/schemas/service.py` | MODIFY | SSL fields in `ServiceCreate`, `ServiceUpdate`, `ServiceOut` |
| `backend/app/routers/services.py` | MODIFY | Auto-set `ssl_enabled`; include SSL in response; handle URL scheme change |
| `backend/app/services/probe.py` | MODIFY | `_maybe_check_ssl()` + call from `probe_service` |
| `frontend/src/stores/services.ts` | MODIFY | SSL fields in `Service` interface + `ServiceCreatePayload` |
| `frontend/src/components/services/ServiceModal.vue` | MODIFY | SSL Thresholds section for HTTPS URLs |
| `frontend/src/components/services/ServiceRow.vue` | MODIFY | SSL status pill in service list rows |
| `frontend/src/views/services/ServiceDetail.vue` | MODIFY | SSL Certificate card with ExpiryBar |
| `frontend/src/views/ssl-domains/SslDomainsView.vue` | MODIFY | Hint text pointing users to Services for HTTPS SSL |

---

## Task 1: Alembic Migration — Add SSL Columns to `service` Table

**Files:**
- Create: `backend/migrations/versions/0008_service_ssl_columns.py`

- [ ] **Step 1.1: Create migration file**

```python
# backend/migrations/versions/0008_service_ssl_columns.py
"""Add SSL tracking columns to service table."""
from alembic import op
import sqlalchemy as sa

revision = "0008_service_ssl_columns"
down_revision = "0007_server_service_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service", sa.Column("ssl_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("service", sa.Column("ssl_warn_days", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("service", sa.Column("ssl_critical_days", sa.Integer(), nullable=False, server_default="7"))
    op.add_column("service", sa.Column("ssl_expiry_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("service", sa.Column("ssl_days_remaining", sa.Integer(), nullable=True))
    op.add_column("service", sa.Column("ssl_status", sa.String(30), nullable=True))
    op.add_column("service", sa.Column("ssl_issuer", sa.String(255), nullable=True))
    op.add_column("service", sa.Column("ssl_last_checked", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in ("ssl_enabled", "ssl_warn_days", "ssl_critical_days",
                "ssl_expiry_date", "ssl_days_remaining", "ssl_status",
                "ssl_issuer", "ssl_last_checked"):
        op.drop_column("service", col)
```

- [ ] **Step 1.2: Apply migration**

```bash
docker compose exec backend alembic upgrade head
```

Expected output ends with: `Running upgrade 0007_server_service_metrics -> 0008_service_ssl_columns`

- [ ] **Step 1.3: Verify columns exist**

```bash
docker compose exec postgres psql -U opspilot -d opspilot -c "\d service" | grep ssl
```

Expected: 8 rows starting with `ssl_`

- [ ] **Step 1.4: Commit**

```bash
git add backend/migrations/versions/0008_service_ssl_columns.py
git commit -m "feat(db): add ssl tracking columns to service table"
```

---

## Task 2: Service Model + Schema + Router

**Files:**
- Modify: `backend/app/models/other.py` (Service class, after `last_status` line)
- Modify: `backend/app/schemas/service.py` (ServiceCreate, ServiceUpdate, ServiceOut)
- Modify: `backend/app/routers/services.py` (_service_to_out, create_service, update_service)

- [ ] **Step 2.1: Add SSL columns to Service model in `backend/app/models/other.py`**

After `last_status` in the `Service` class, add:

```python
    ssl_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    ssl_warn_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    ssl_critical_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7, server_default="7")
    ssl_expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ssl_days_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ssl_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ssl_issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssl_last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 2.2: Add SSL fields to `ServiceCreate` in `backend/app/schemas/service.py`**

After `ignore_ssl_errors: bool = False`, add:

```python
    ssl_warn_days: int = 30
    ssl_critical_days: int = 7
```

- [ ] **Step 2.3: Add SSL fields to `ServiceUpdate` in `backend/app/schemas/service.py`**

After `ignore_ssl_errors: bool | None = None`, add:

```python
    ssl_warn_days: int | None = None
    ssl_critical_days: int | None = None
```

- [ ] **Step 2.4: Add SSL fields to `ServiceOut` in `backend/app/schemas/service.py`**

After `open_incident_id: str | None`, add:

```python
    ssl_enabled: bool
    ssl_warn_days: int
    ssl_critical_days: int
    ssl_expiry_date: datetime | None
    ssl_days_remaining: int | None
    ssl_status: str | None
    ssl_issuer: str | None
    ssl_last_checked: datetime | None
```

- [ ] **Step 2.5: Update `_service_to_out` in `backend/app/routers/services.py`**

After `open_incident_id=await _open_incident_id(db, sid),`, add:

```python
        ssl_enabled=service.ssl_enabled,
        ssl_warn_days=service.ssl_warn_days,
        ssl_critical_days=service.ssl_critical_days,
        ssl_expiry_date=service.ssl_expiry_date,
        ssl_days_remaining=service.ssl_days_remaining,
        ssl_status=service.ssl_status,
        ssl_issuer=service.ssl_issuer,
        ssl_last_checked=service.ssl_last_checked,
```

- [ ] **Step 2.6: Update `create_service` in `backend/app/routers/services.py`**

Add import at top of file (alongside existing `from app.services import probe`):

```python
from app.services import alerting, probe
```

In the `if body.type == "http":` block, after `url = body.url`, add:

```python
        ssl_enabled = url.lower().startswith("https://")
```

In the `Service(...)` constructor call, after `ignore_ssl_errors=body.ignore_ssl_errors,`, add:

```python
        ssl_enabled=ssl_enabled,
        ssl_warn_days=body.ssl_warn_days,
        ssl_critical_days=body.ssl_critical_days,
```

In the `else:` (tcp/db) branch, before `url = body.url.strip()`, add:

```python
        ssl_enabled = False
```

Then in the shared `Service(...)` constructor (called after both branches), add:

```python
        ssl_enabled=ssl_enabled,
        ssl_warn_days=body.ssl_warn_days,
        ssl_critical_days=body.ssl_critical_days,
```

- [ ] **Step 2.7: Update `update_service` in `backend/app/routers/services.py`**

Replace the `if body.url is not None: service.url = body.url` block with:

```python
    if body.url is not None:
        old_url = service.url or ""
        was_https = old_url.lower().startswith("https://")
        is_https = body.url.lower().startswith("https://")
        service.url = body.url
        if was_https and not is_https:
            service.ssl_enabled = False
            service.ssl_expiry_date = None
            service.ssl_days_remaining = None
            service.ssl_status = None
            service.ssl_issuer = None
            service.ssl_last_checked = None
            open_ssl = (
                await db.execute(
                    select(Alert).where(
                        Alert.service_id == service.id,
                        Alert.type == "ssl_expiry",
                        Alert.state.in_(alerting.OPEN_STATES),
                    )
                )
            ).scalars().all()
            for a in open_ssl:
                await alerting.resolve_alert(db, a, commit=False)
        elif not was_https and is_https:
            service.ssl_enabled = True
```

After `if body.ignore_ssl_errors is not None: service.ignore_ssl_errors = body.ignore_ssl_errors`, add:

```python
    if body.ssl_warn_days is not None:
        service.ssl_warn_days = body.ssl_warn_days
    if body.ssl_critical_days is not None:
        service.ssl_critical_days = body.ssl_critical_days
```

- [ ] **Step 2.8: Smoke test backend**

```bash
docker compose restart backend
curl -s -X POST http://localhost:8000/api/services \
  -H "Content-Type: application/json" \
  -H "Cookie: <admin-session>" \
  -d '{"server_id":"<any-server-id>","name":"test-ssl","type":"http","url":"https://example.com","interval_sec":60,"timeout_sec":5,"is_active":false,"is_public":false,"ignore_ssl_errors":false}' \
  | python3 -m json.tool | grep ssl
```

Expected: `"ssl_enabled": true`, `"ssl_warn_days": 30`, `"ssl_critical_days": 7`, rest null.

- [ ] **Step 2.9: Commit**

```bash
git add backend/app/models/other.py backend/app/schemas/service.py backend/app/routers/services.py
git commit -m "feat(services): add ssl tracking fields to model, schema, and router"
```

---

## Task 3: SSL Extraction in `probe.py`

**Files:**
- Modify: `backend/app/services/probe.py`

- [ ] **Step 3.1: Add imports to `backend/app/services/probe.py`**

Add to the existing imports at the top:

```python
from datetime import timedelta
from urllib.parse import urlparse
```

- [ ] **Step 3.2: Add `_parse_ssl_target` helper after the existing `_aware` function**

```python
def _parse_ssl_target(url: str) -> tuple[str, int]:
    """Return (hostname, port) from an https:// URL for TLS socket connection."""
    parsed = urlparse(url)
    return parsed.hostname or "", parsed.port or 443
```

- [ ] **Step 3.3: Add `_maybe_check_ssl` after `_parse_ssl_target`**

```python
async def _maybe_check_ssl(service_id: str) -> None:
    """Read the TLS cert for an HTTPS service if last check was >6 h ago.

    Uses a fresh DB session so it never delays the uptime write path.
    On socket/TLS failure sets ssl_status='unreachable' and updates ssl_last_checked.
    Unreachable does not change alert state (preserve last known state).
    """
    from app.models.other import Alert
    from app.services import alerting
    from app.services.ssl_checker import _compute_status, _fetch_ssl_cert

    async with AsyncSessionLocal() as db:
        service = await db.get(Service, service_id)
        if service is None or not service.ssl_enabled:
            return

        now = _now()
        last = _aware(service.ssl_last_checked)
        if last is not None and (now - last) < timedelta(hours=6):
            return

        hostname, port = _parse_ssl_target(service.url or "")
        if not hostname:
            return

        try:
            expiry, issuer = await asyncio.to_thread(_fetch_ssl_cert, hostname, port)
            expiry = _aware(expiry)
            days = (expiry - now).days
            ssl_status = _compute_status(days, service.ssl_warn_days, service.ssl_critical_days)

            service.ssl_expiry_date = expiry
            service.ssl_days_remaining = days
            service.ssl_issuer = issuer
            service.ssl_status = ssl_status
            service.ssl_last_checked = now
            await db.flush()

            if ssl_status in ("expiring_soon", "critical", "expired"):
                severity = "warning" if ssl_status == "expiring_soon" else "critical"
                msg = (
                    f"SSL certificate for {hostname} has expired."
                    if ssl_status == "expired"
                    else f"SSL certificate for {hostname} expires in {days} day(s) ({expiry.date()})."
                )
                await alerting.fire_alert(
                    db,
                    type="ssl_expiry",
                    severity=severity,
                    message=msg,
                    service_id=service.id,
                    commit=False,
                )
            elif ssl_status == "valid":
                open_alerts = (
                    await db.execute(
                        select(Alert).where(
                            Alert.service_id == service.id,
                            Alert.type == "ssl_expiry",
                            Alert.state.in_(alerting.OPEN_STATES),
                        )
                    )
                ).scalars().all()
                for alert in open_alerts:
                    await alerting.resolve_alert(db, alert, commit=False)

            await db.commit()

        except Exception:  # noqa: BLE001
            logger.info(
                "SSL check failed for service %s (%s:%s)", service_id, hostname, port, exc_info=True
            )
            service.ssl_status = "unreachable"
            service.ssl_last_checked = now
            await db.commit()
```

- [ ] **Step 3.4: Update `probe_service` to call `_maybe_check_ssl` after uptime check**

Replace the body of `probe_service` with:

```python
async def probe_service(service_id: str) -> None:
    """Entry point invoked by APScheduler (one job per service). Loads the
    service, runs the check under the concurrency semaphore, and applies the
    result. Skips paused services. Never raises into the scheduler."""
    async with _semaphore:
        try:
            needs_ssl = False
            async with AsyncSessionLocal() as db:
                service = await db.scalar(select(Service).where(Service.id == service_id))
                if service is None or not service.is_active:
                    return
                server = await db.get(Server, service.server_id)
                org_id = str(server.org_id) if server else None
                needs_ssl = service.type == "http" and service.ssl_enabled
                status, rt, cause = await _run_check(service)
                await evaluate_result(db, service, status, rt, cause, org_id)
            if needs_ssl:
                await _maybe_check_ssl(service_id)
        except Exception:  # noqa: BLE001
            logger.exception("probe_service failed for %s", service_id)
```

- [ ] **Step 3.5: Smoke test SSL extraction**

```bash
docker compose restart backend
```

Trigger an immediate check on an HTTPS service (use the UI "Check Now" or patch it active). Then query:

```bash
docker compose exec postgres psql -U opspilot -d opspilot \
  -c "SELECT name, ssl_enabled, ssl_status, ssl_days_remaining, ssl_issuer, ssl_last_checked FROM service WHERE ssl_enabled = true LIMIT 5;"
```

Expected: `ssl_status` is `valid`, `ssl_days_remaining` is a positive integer, `ssl_issuer` is populated.

- [ ] **Step 3.6: Commit**

```bash
git add backend/app/services/probe.py
git commit -m "feat(probe): extract ssl cert info during https service probes (6h throttle)"
```

---

## Task 4: Frontend Type Definitions

**Files:**
- Modify: `frontend/src/stores/services.ts`

- [ ] **Step 4.1: Add SSL fields to `Service` interface**

In `frontend/src/stores/services.ts`, after `open_incident_id: string | null` in the `Service` interface, add:

```typescript
  ssl_enabled: boolean
  ssl_warn_days: number
  ssl_critical_days: number
  ssl_expiry_date: string | null
  ssl_days_remaining: number | null
  ssl_status: string | null
  ssl_issuer: string | null
  ssl_last_checked: string | null
```

- [ ] **Step 4.2: Add SSL threshold fields to `ServiceCreatePayload`**

After `ignore_ssl_errors: boolean` in `ServiceCreatePayload`, add:

```typescript
  ssl_warn_days?: number
  ssl_critical_days?: number
```

`ServiceUpdatePayload` is `Partial<Omit<ServiceCreatePayload, 'server_id' | 'type'>>` so it automatically picks up the new optional fields — no change needed there.

- [ ] **Step 4.3: Verify TypeScript build passes**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: no TypeScript errors.

- [ ] **Step 4.4: Commit**

```bash
git add frontend/src/stores/services.ts
git commit -m "feat(types): add ssl fields to Service interface and ServiceCreatePayload"
```

---

## Task 5: ServiceModal — SSL Threshold Section

**Files:**
- Modify: `frontend/src/components/services/ServiceModal.vue`

- [ ] **Step 5.1: Add SSL fields to `FormState` interface**

In `frontend/src/components/services/ServiceModal.vue`, in the `FormState` type (which has fields like `ignore_ssl_errors: boolean`), add:

```typescript
  ssl_warn_days: number
  ssl_critical_days: number
```

- [ ] **Step 5.2: Add defaults to `blank()`**

Inside `blank()`, after `ignore_ssl_errors: false,`, add:

```typescript
    ssl_warn_days: 30,
    ssl_critical_days: 7,
```

- [ ] **Step 5.3: Hydrate SSL fields in `hydrate()`**

Inside the `if (s.type === 'http') {` block in `hydrate()`, after `form.ignore_ssl_errors = s.ignore_ssl_errors`, add:

```typescript
    form.ssl_warn_days = s.ssl_warn_days ?? 30
    form.ssl_critical_days = s.ssl_critical_days ?? 7
```

- [ ] **Step 5.4: Add `isHttps` computed**

After the existing `intervalAdvisory` computed, add:

```typescript
const isHttps = computed(() => /^https:\/\//i.test(form.url.trim()))
```

- [ ] **Step 5.5: Add SSL validation in `validate()`**

Inside the `if (form.type === 'http') {` block, after the `expected_status` validation, add:

```typescript
    if (isHttps.value) {
      if (form.ssl_warn_days < 1 || form.ssl_warn_days > 365)
        errors.ssl_warn_days = 'Must be 1–365'
      if (form.ssl_critical_days < 1 || form.ssl_critical_days >= form.ssl_warn_days)
        errors.ssl_critical_days = 'Must be ≥ 1 and less than warn threshold'
    }
```

- [ ] **Step 5.6: Add SSL fields to create payload in `submit()`**

Inside the create path's `if (form.type === 'http') {` block, after `payload.ignore_ssl_errors = form.ignore_ssl_errors`, add:

```typescript
        if (isHttps.value) {
          payload.ssl_warn_days = form.ssl_warn_days
          payload.ssl_critical_days = form.ssl_critical_days
        }
```

Inside the update path's `if (form.type === 'http') {` block, after `payload.ignore_ssl_errors = form.ignore_ssl_errors`, add:

```typescript
        payload.ssl_warn_days = form.ssl_warn_days
        payload.ssl_critical_days = form.ssl_critical_days
```

- [ ] **Step 5.7: Add SSL Thresholds section to template**

Inside `<template v-if="form.type === 'http'">`, after the `ignore_ssl_errors` checkbox block, add:

```html
        <!-- SSL thresholds — shown only for https:// URLs -->
        <template v-if="isHttps">
          <div class="section-divider"></div>
          <p class="ssl-hint">SSL certificate expiry will be tracked automatically for this HTTPS service.</p>
          <div class="form-row">
            <label class="form-label">
              Warn at (days)
              <input
                v-model.number="form.ssl_warn_days"
                type="number"
                min="1"
                max="365"
                class="form-input"
                :class="{ invalid: errors.ssl_warn_days }"
              />
              <span v-if="errors.ssl_warn_days" class="err">{{ errors.ssl_warn_days }}</span>
            </label>
            <label class="form-label">
              Critical at (days)
              <input
                v-model.number="form.ssl_critical_days"
                type="number"
                min="1"
                class="form-input"
                :class="{ invalid: errors.ssl_critical_days }"
              />
              <span v-if="errors.ssl_critical_days" class="err">{{ errors.ssl_critical_days }}</span>
            </label>
          </div>
        </template>
```

- [ ] **Step 5.8: Add styles for new elements**

In the `<style scoped>` block, add:

```css
.section-divider { height: 1px; background: var(--border); margin: 12px 0; }
.ssl-hint { font-size: 12px; color: var(--muted); margin-bottom: 10px; }
```

- [ ] **Step 5.9: Smoke test in browser**

1. Open `http://localhost:9090/services`
2. Click "+ Add Service", choose HTTP, type `https://example.com` in URL field
3. Confirm "SSL certificate expiry will be tracked automatically" hint appears with warn/critical inputs
4. Change URL to `http://example.com` — confirm SSL section disappears
5. Submit the form and confirm the service appears without errors

- [ ] **Step 5.10: Commit**

```bash
git add frontend/src/components/services/ServiceModal.vue
git commit -m "feat(modal): add ssl threshold fields for https service creation and editing"
```

---

## Task 6: ServiceRow — SSL Status Pill

**Files:**
- Modify: `frontend/src/components/services/ServiceRow.vue`

- [ ] **Step 6.1: Add SSL pill to template**

In `frontend/src/components/services/ServiceRow.vue`, find the row template. After the `StatusBadge` for uptime status (around line 89 where `StatusBadge kind="service"` is used in the down banner, or wherever the main status badge sits in the row), add the SSL pill alongside the type badge or status area:

Look for the row's status cell (it uses `dotClass`, `last_status`, and `StatusBadge`). After the status badge, add:

```html
<span
  v-if="s.ssl_enabled && ['expiring_soon', 'critical', 'expired'].includes(s.ssl_status ?? '')"
  class="ssl-pill"
  :class="`ssl-pill--${s.ssl_status}`"
  :title="`SSL ${s.ssl_status === 'expiring_soon' ? 'expiring soon' : s.ssl_status} · ${s.ssl_days_remaining ?? '?'} days left`"
>SSL {{ s.ssl_status === 'expiring_soon' ? 'expiring' : s.ssl_status }}</span>
```

- [ ] **Step 6.2: Add SSL pill styles**

In `<style scoped>`, add:

```css
.ssl-pill {
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 2px 6px;
  border-radius: 4px;
  margin-left: 6px;
  vertical-align: middle;
}
.ssl-pill--expiring_soon { background: rgba(245,158,11,0.15); color: #f59e0b; }
.ssl-pill--critical      { background: rgba(239,68,68,0.15);  color: #ef4444; }
.ssl-pill--expired       { background: rgba(239,68,68,0.2);   color: #fca5a5; }
```

- [ ] **Step 6.3: Smoke test in browser**

1. Open `http://localhost:9090/services`
2. For an HTTPS service with a valid cert, confirm no SSL pill appears
3. To test the pill: temporarily set a service's `ssl_status = 'expiring_soon'` in the DB and `ssl_enabled = true`, then refresh the page
   ```bash
   docker compose exec postgres psql -U opspilot -d opspilot \
     -c "UPDATE service SET ssl_status='expiring_soon', ssl_days_remaining=12, ssl_enabled=true WHERE type='http' LIMIT 1;"
   ```
4. Confirm amber "SSL expiring" pill appears next to that service
5. Revert: `UPDATE service SET ssl_status='valid', ssl_days_remaining=NULL WHERE ...`

- [ ] **Step 6.4: Commit**

```bash
git add frontend/src/components/services/ServiceRow.vue
git commit -m "feat(service-row): add ssl expiry status pill for https services"
```

---

## Task 7: ServiceDetail — SSL Certificate Card

**Files:**
- Modify: `frontend/src/views/services/ServiceDetail.vue`

- [ ] **Step 7.1: Import ExpiryBar**

In `frontend/src/views/services/ServiceDetail.vue`, add to the imports at the top of `<script setup>`:

```typescript
import ExpiryBar from '@/components/ssl-domains/ExpiryBar.vue'
```

- [ ] **Step 7.2: Add SSL card to template**

Find a suitable location after the stat cards section (the `StatCard` grid) but before the `MetricChart` / `UptimeTimeline` section. Add:

```html
<!-- SSL Certificate Card — HTTPS services only -->
<section v-if="service?.ssl_enabled" class="ssl-section panel">
  <div class="ssl-section-header">
    <h2 class="ssl-section-title">SSL Certificate</h2>
    <StatusBadge kind="ssl" :status="service.ssl_status ?? 'unreachable'" />
  </div>
  <div class="ssl-meta-grid">
    <div class="ssl-meta-item">
      <span class="ssl-label">Expiry Date</span>
      <span class="ssl-value mono">{{ service.ssl_expiry_date ? service.ssl_expiry_date.slice(0, 10) : '—' }}</span>
    </div>
    <div class="ssl-meta-item">
      <span class="ssl-label">Days Left</span>
      <span
        class="ssl-value mono"
        :class="{
          'ssl-warn': (service.ssl_days_remaining ?? 999) <= service.ssl_warn_days && (service.ssl_days_remaining ?? 999) > service.ssl_critical_days,
          'ssl-crit': (service.ssl_days_remaining ?? 999) <= service.ssl_critical_days
        }"
      >{{ service.ssl_days_remaining ?? '—' }}</span>
    </div>
    <div class="ssl-meta-item">
      <span class="ssl-label">Issuer</span>
      <span class="ssl-value">{{ service.ssl_issuer ?? '—' }}</span>
    </div>
    <div class="ssl-meta-item">
      <span class="ssl-label">Last Checked</span>
      <span class="ssl-value muted">{{ service.ssl_last_checked ? relativeTime(service.ssl_last_checked) : 'never' }}</span>
    </div>
  </div>
  <ExpiryBar
    class="ssl-expiry-bar"
    :days-remaining="service.ssl_days_remaining"
    :warn-threshold="service.ssl_warn_days"
    :status="service.ssl_status ?? 'unreachable'"
  />
</section>
```

- [ ] **Step 7.3: Add styles**

In `<style scoped>`, add:

```css
.ssl-section { margin-bottom: 20px; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.ssl-section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.ssl-section-title { font-size: 13px; font-weight: 600; color: var(--text); }
.ssl-meta-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px 20px; margin-bottom: 14px; }
.ssl-meta-item { display: flex; flex-direction: column; gap: 3px; }
.ssl-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
.ssl-value { font-size: 14px; color: var(--text); }
.ssl-value.mono { font-family: ui-monospace, monospace; }
.ssl-value.muted { color: var(--muted); }
.ssl-warn { color: #f59e0b; }
.ssl-crit { color: #ef4444; }
.ssl-expiry-bar { margin-top: 4px; }
```

- [ ] **Step 7.4: Smoke test in browser**

1. Open `http://localhost:9090/services` and click on an HTTPS service
2. Confirm the SSL Certificate card appears below the stat cards, showing expiry date, days left, issuer, last checked, and ExpiryBar
3. For an HTTP (non-HTTPS) service, confirm the SSL section is absent

- [ ] **Step 7.5: Commit**

```bash
git add frontend/src/views/services/ServiceDetail.vue
git commit -m "feat(service-detail): add ssl certificate card for https services"
```

---

## Task 8: SSL & Domain Page Hint + Progress Update

**Files:**
- Modify: `frontend/src/views/ssl-domains/SslDomainsView.vue`
- Modify: `pm/PROGRESS.md`
- Modify: `pm/DASHBOARD.html`

- [ ] **Step 8.1: Add hint text to `SslDomainsView.vue`**

In `frontend/src/views/ssl-domains/SslDomainsView.vue`, update the `EmptyState` message:

Find:
```html
      message="Add your domains to get notified before SSL certificates or domain registrations expire and cause outages."
```

Replace with:
```html
      message="Add domains to track WHOIS registration expiry and non-standard SSL certs (e.g. IMAPS:993). SSL for your HTTPS services is tracked automatically on the Services page."
```

Also add a hint line after the `</section>` closing tag of the timeline panel (i.e., just before `<!-- Filter bar -->`):

```html
      <p class="page-hint">SSL for your HTTPS services is tracked automatically — add non-HTTP certs (e.g. IMAPS, SMTPS) here.</p>
```

And in `<style scoped>`, add:

```css
.page-hint { font-size: 12px; color: var(--muted); margin-bottom: 10px; }
```

- [ ] **Step 8.2: Update PROGRESS.md**

Find the SSL-in-HTTP-probe task entry (or add it) and mark it `✅`.

- [ ] **Step 8.3: Update DASHBOARD.html**

Find the matching task in the `phases` data array and change `status: 'pending'` to `status: 'done'`. Update `LAST_UPDATED` to `2026-06-04`.

- [ ] **Step 8.4: Final end-to-end smoke test**

1. Add an HTTPS service (e.g. `https://example.com`) via the Services UI — confirm SSL fields appear in the response
2. Trigger a probe (`probe_now`) — wait 10 seconds — check the DB for ssl_status, ssl_days_remaining
3. Confirm no ssl_expiry alert fires for a valid cert
4. Open `http://localhost:9090/ssl-domains` — confirm hint text appears
5. Confirm the Services Detail page shows the SSL card

- [ ] **Step 8.5: Commit and push**

```bash
git add frontend/src/views/ssl-domains/SslDomainsView.vue pm/PROGRESS.md pm/DASHBOARD.html
git commit -m "feat(ssl-domains): add hint for https ssl tracking; mark ssl-in-http-probe complete"
git push origin main
```
