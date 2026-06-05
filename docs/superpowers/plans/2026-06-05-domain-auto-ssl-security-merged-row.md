# Domain Auto-SSL, Security Audit & Merged Row Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a domain is registered, automatically create its SSL:443 cert and run a security audit; display WHOIS + SSL + security grade merged in one domain row; restore service rows as read-only cross-reference.

**Architecture:** Backend adds 4 security columns to `ssl_cert` table and a new `run_ssl_cert_security_check()` function in `security_checker.py`; `create_domain` auto-creates the port-443 cert; `check_ssl_cert_by_id` triggers the security audit after the first successful SSL check. Frontend store merges domain + SSL cert data into one `CombinedRow` with worst-expiry logic; the view renders a two-line expiry cell and restores the Security column and service rows.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy (async) + Alembic; Vue 3 + Pinia + TypeScript

---

## File Map

| File | Change |
|------|--------|
| `backend/migrations/versions/0011_ssl_cert_security.py` | Create — add 4 security columns to `ssl_cert` |
| `backend/app/models/other.py` | Modify — add 4 fields to `SSLCert` model |
| `backend/app/schemas/ssl_domains.py` | Modify — add `security_grade`, `security_score` to `SSLCertOut` + update `_ssl_out` |
| `backend/app/services/security_checker.py` | Modify — add `run_ssl_cert_security_check()` |
| `backend/app/services/ssl_checker.py` | Modify — trigger security audit after first SSL check |
| `backend/app/routers/ssl_domains.py` | Modify — auto-create SSL cert in `create_domain`; remove 409 check from `delete_domain` |
| `frontend/src/stores/sslDomains.ts` | Modify — update `SslCert` interface, `CombinedRow` type, `combinedRows` computed |
| `frontend/src/views/ssl-domains/SslDomainsView.vue` | Modify — expiry subtitle, Security column, sort key, type filter, kebab, delete confirm |

---

## Task 1: Migration — add security columns to ssl_cert

**Files:**
- Create: `backend/migrations/versions/0011_ssl_cert_security.py`

- [ ] **Step 1: Create the migration file**

```python
# backend/migrations/versions/0011_ssl_cert_security.py
"""Add security audit columns to ssl_cert table.

Revision ID: 0011_ssl_cert_security
Revises: 0010_security_scans
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_ssl_cert_security"
down_revision = "0010_security_scans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ssl_cert", sa.Column("security_grade", sa.String(2), nullable=True))
    op.add_column("ssl_cert", sa.Column("security_score", sa.Integer, nullable=True))
    op.add_column("ssl_cert", sa.Column("security_scanned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ssl_cert", sa.Column("security_findings", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("ssl_cert", "security_findings")
    op.drop_column("ssl_cert", "security_scanned_at")
    op.drop_column("ssl_cert", "security_score")
    op.drop_column("ssl_cert", "security_grade")
```

- [ ] **Step 2: Run the migration**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend alembic upgrade head
```

Expected output ends with: `Running upgrade 0010_security_scans -> 0011_ssl_cert_security`

- [ ] **Step 3: Verify columns exist**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres psql -U opspilot -d opspilot -c "\d ssl_cert"
```

Expected: table description shows `security_grade`, `security_score`, `security_scanned_at`, `security_findings` columns.

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/versions/0011_ssl_cert_security.py
git commit -m "feat(db): add security audit columns to ssl_cert table"
```

---

## Task 2: Backend model + schema

**Files:**
- Modify: `backend/app/models/other.py` (SSLCert class, around line 79)
- Modify: `backend/app/schemas/ssl_domains.py` (SSLCertOut class + `_ssl_out` in router)
- Modify: `backend/app/routers/ssl_domains.py` (`_ssl_out` function, line 77)

- [ ] **Step 1: Add 4 fields to SSLCert model**

In `backend/app/models/other.py`, find the `SSLCert` class. After `status: Mapped[str | None]` (line ~91), add:

```python
    security_grade: Mapped[str | None] = mapped_column(String(2), nullable=True)
    security_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    security_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    security_findings: Mapped[list | None] = mapped_column(JSONB(astext_type=Text()), nullable=True)
```

Make sure `JSONB` and `Text` are in the imports at the top of the file — they already are (used by `ServiceSecurityScan`).

- [ ] **Step 2: Add security fields to SSLCertOut schema**

In `backend/app/schemas/ssl_domains.py`, find the `SSLCertOut` class (line ~99). Add two optional fields after `status`:

```python
class SSLCertOut(BaseModel):
    id: UUID
    domain_id: UUID
    domain: str | None = None
    port: int
    issuer: str | None
    expiry_date: datetime | None
    days_remaining: int | None
    warn_days: int
    critical_days: int
    last_checked: datetime | None
    status: str | None
    security_grade: str | None = None
    security_score: int | None = None

    model_config = {"from_attributes": True}
```

- [ ] **Step 3: Update `_ssl_out` helper to include security fields**

In `backend/app/routers/ssl_domains.py`, replace the `_ssl_out` function (line ~77):

```python
def _ssl_out(c: SSLCert, domain_name: str | None) -> SSLCertOut:
    return SSLCertOut(
        id=c.id,
        domain_id=c.domain_id,
        domain=domain_name,
        port=c.port,
        issuer=c.issuer,
        expiry_date=c.expiry_date,
        days_remaining=c.days_remaining,
        warn_days=c.warn_days,
        critical_days=c.critical_days,
        last_checked=c.last_checked,
        status=c.status,
        security_grade=c.security_grade,
        security_score=c.security_score,
    )
```

- [ ] **Step 4: Smoke test — verify endpoint returns security fields**

```bash
# Get org ID first
curl -s http://localhost:9090/api/organizations -H "Authorization: Bearer $(curl -s -X POST http://localhost:9090/api/auth/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')" | python3 -m json.tool | grep '"id"' | head -1
```

Then hit the ssl-domains endpoint and confirm `ssl_certs` items have `security_grade` and `security_score` keys (values will be `null` — that's correct).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/other.py backend/app/schemas/ssl_domains.py backend/app/routers/ssl_domains.py
git commit -m "feat(ssl-domains): add security grade/score fields to SSLCert model and schema"
```

---

## Task 3: Domain security audit function

**Files:**
- Modify: `backend/app/services/security_checker.py` (add function at the end of file)

- [ ] **Step 1: Add `run_ssl_cert_security_check` to security_checker.py**

Add these imports at the top of `backend/app/services/security_checker.py` if not already present:
```python
from app.models.other import Domain, SSLCert
```

Then append at the end of the file (after `run_security_check`):

```python
async def run_ssl_cert_security_check(ssl_cert_id: str) -> None:
    """Run a full security audit for a domain's SSL:443 cert. Never raises.

    Reuses the same TLS + HTTP header audit as run_security_check() but stores
    results on the SSLCert record instead of creating a ServiceSecurityScan row.
    Respects a 24-hour throttle.
    """
    try:
        async with AsyncSessionLocal() as db:
            cert = await db.get(SSLCert, ssl_cert_id)
            if cert is None or cert.port != 443:
                return
            domain = await db.get(Domain, cert.domain_id)
            if domain is None:
                return

            now = _now()
            if (
                cert.security_scanned_at is not None
                and (now - _aware(cert.security_scanned_at)).total_seconds() < 86400
            ):
                return  # scanned within last 24 h

            hostname = domain.domain
            url = f"https://{hostname}"

            tls = await asyncio.to_thread(_audit_tls_sync, hostname, 443)
            hdr = await _audit_headers(url)
            score, grade, findings = _compute_score(tls, hdr)

            cert.security_grade = grade
            cert.security_score = score
            cert.security_scanned_at = now
            cert.security_findings = findings
            await db.commit()
            logger.info("Security audit complete for domain %s: grade=%s score=%d", domain.domain, grade, score)
    except Exception:
        logger.exception("run_ssl_cert_security_check failed for cert %s", ssl_cert_id)
```

- [ ] **Step 2: Verify the function signature and imports are correct**

Run a quick syntax check:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend python -c "from app.services.security_checker import run_ssl_cert_security_check; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/security_checker.py
git commit -m "feat(ssl-domains): add run_ssl_cert_security_check for domain security audit"
```

---

## Task 4: Auto-SSL on domain creation + security trigger + delete fix

**Files:**
- Modify: `backend/app/routers/ssl_domains.py` (`create_domain` and `delete_domain`)
- Modify: `backend/app/services/ssl_checker.py` (`check_ssl_cert_by_id`)

- [ ] **Step 1: Add security_checker import to ssl_checker.py**

In `backend/app/services/ssl_checker.py`, add to the imports at the top:

```python
from app.services import security_checker
```

Also add `scheduler` import since we'll schedule a job from within `check_ssl_cert_by_id`:

```python
from app.jobs.scheduler import scheduler
```

- [ ] **Step 2: Update `check_ssl_cert_by_id` to trigger security audit**

In `backend/app/services/ssl_checker.py`, replace the `check_ssl_cert_by_id` function (line ~275):

```python
async def check_ssl_cert_by_id(ssl_cert_id: str) -> None:
    async with AsyncSessionLocal() as db:
        cert = await db.get(SSLCert, ssl_cert_id)
        if cert is None:
            return
        was_first_check = cert.last_checked is None
        await check_ssl_cert(db, cert)
        # After the first successful check on a port-443 cert, schedule security audit
        if was_first_check and cert.port == 443 and cert.status != "unreachable":
            scheduler.add_job(
                security_checker.run_ssl_cert_security_check,
                "date",
                run_date=_now() + timedelta(seconds=2),
                args=[ssl_cert_id],
                id=f"ssl_security_once:{ssl_cert_id}",
                replace_existing=True,
            )
```

Also add `timedelta` to the imports at the top if not already there:
```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 3: Update `create_domain` to auto-create SSL:443 cert**

In `backend/app/routers/ssl_domains.py`, replace the `create_domain` function (line ~182):

```python
@router.post("/api/domains", status_code=201, response_model=DomainOut)
async def create_domain(body: DomainCreate, user: AdminUser, db: AsyncSession = Depends(get_db)):
    await _assert_org_access(str(body.org_id), user, db)

    existing = await db.scalar(
        select(Domain).where(Domain.org_id == body.org_id, Domain.domain == body.domain)
    )
    if existing:
        raise HTTPException(
            409,
            detail={"error": "duplicate", "message": f"{body.domain} is already tracked in this organisation."},
        )

    domain = Domain(
        org_id=body.org_id,
        domain=body.domain,
        warn_days=body.warn_days,
        critical_days=body.critical_days,
        status="checking",
    )
    db.add(domain)
    await db.commit()
    await db.refresh(domain)

    _schedule_once(f"domain_check_once:{domain.id}", ssl_checker.check_domain_by_id, str(domain.id))

    # Auto-create SSL cert for port 443 — security audit fires automatically after first check
    ssl_cert = SSLCert(
        domain_id=domain.id,
        port=443,
        warn_days=body.warn_days,
        critical_days=body.critical_days,
        status="checking",
    )
    db.add(ssl_cert)
    await db.commit()
    await db.refresh(ssl_cert)
    _schedule_once(f"ssl_check_once:{ssl_cert.id}", ssl_checker.check_ssl_cert_by_id, str(ssl_cert.id))

    return _domain_out(domain)
```

- [ ] **Step 4: Update `delete_domain` to remove the 409 check**

In `backend/app/routers/ssl_domains.py`, replace `delete_domain` (line ~228):

```python
@router.delete("/api/domains/{domain_id}", status_code=204)
async def delete_domain(domain_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    domain = await _get_domain_for_admin(domain_id, db)
    await db.delete(domain)
    await db.commit()
    return None
```

The FK `ondelete="CASCADE"` on `SSLCert.domain_id` handles deletion of linked SSL certs automatically.

- [ ] **Step 5: Restart backend and smoke test**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
```

Wait 5 seconds, then test adding a domain:

```bash
TOKEN=$(curl -s -X POST http://localhost:9090/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

# Get org ID
ORG=$(curl -s http://localhost:9090/api/organizations \
  -H "Authorization: Bearer $TOKEN" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[0]["id"])')

# Add a domain
curl -s -X POST http://localhost:9090/api/domains \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"org_id\":\"$ORG\",\"domain\":\"example.com\",\"warn_days\":60,\"critical_days\":30}" | python3 -m json.tool
```

Expected: domain created with `status: "checking"`.

Then verify an SSL cert was auto-created:

```bash
curl -s "http://localhost:9090/api/organizations/$ORG/ssl-domains" \
  -H "Authorization: Bearer $TOKEN" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("ssl_certs:", [(c["domain"], c["port"]) for c in d["ssl_certs"]])'
```

Expected: `ssl_certs: [('example.com', 443)]`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ssl_checker.py backend/app/routers/ssl_domains.py
git commit -m "feat(ssl-domains): auto-create SSL:443 cert on domain registration, trigger security audit after first check"
```

---

## Task 5: Frontend store — merged domain rows

**Files:**
- Modify: `frontend/src/stores/sslDomains.ts`

- [ ] **Step 1: Update `SslCert` interface to include security fields**

In `frontend/src/stores/sslDomains.ts`, find the `SslCert` interface (line ~19). Add two fields:

```ts
export interface SslCert {
  id: string
  domain_id: string
  domain: string | null
  port: number
  issuer: string | null
  expiry_date: string | null
  days_remaining: number | null
  warn_days: number
  critical_days: number
  last_checked: string | null
  status: string | null
  security_grade: string | null
  security_score: number | null
}
```

- [ ] **Step 2: Update `CombinedRow` interface to add subtitle fields**

In `frontend/src/stores/sslDomains.ts`, find the `CombinedRow` interface (line ~71). Add 4 optional fields after the existing `securityScore` field:

```ts
export interface CombinedRow {
  id: string
  domainName: string
  type: 'domain' | 'ssl' | 'service'
  port?: number
  expiryDate: string | null
  daysRemaining: number | null
  status: string
  lastChecked: string | null
  registrar?: string | null
  warnDays: number
  criticalDays: number
  issuer?: string | null
  domainId?: string
  serviceId?: string
  warnThreshold: number
  securityGrade?: string | null
  securityScore?: number | null
  // Subtitle data for merged domain rows (WHOIS + SSL)
  whoisExpiry?: string | null
  whoisDaysRemaining?: number | null
  sslExpiry?: string | null
  sslDaysRemaining?: number | null
}
```

- [ ] **Step 3: Replace `combinedRows` computed with merged domain logic**

In `frontend/src/stores/sslDomains.ts`, replace the entire `combinedRows` computed (line ~128 to ~182):

```ts
const combinedRows = computed<CombinedRow[]>(() => {
  const rows: CombinedRow[] = []

  // Map domain_id → port-443 cert for merging into domain rows
  const auto443: Record<string, SslCert> = {}
  for (const c of sslCerts.value) {
    if (c.port === 443) auto443[c.domain_id] = c
  }

  for (const d of domains.value) {
    const cert = auto443[d.id] ?? null

    // Worst expiry: pick sooner-expiring date (null = unknown, sorts last)
    const dMs = d.expiry_date ? new Date(d.expiry_date).getTime() : Infinity
    const cMs = cert?.expiry_date ? new Date(cert.expiry_date).getTime() : Infinity
    const expiryDate: string | null =
      !d.expiry_date && !cert?.expiry_date ? null
      : !d.expiry_date ? (cert?.expiry_date ?? null)
      : !cert?.expiry_date ? d.expiry_date
      : dMs <= cMs ? d.expiry_date : cert!.expiry_date

    // Worst days remaining
    const dDays = d.days_remaining ?? Infinity
    const cDays = cert?.days_remaining ?? Infinity
    const minDays = Math.min(dDays, cDays)
    const daysRemaining = minDays === Infinity ? null : minDays

    // Worst status (lowest rank = most severe)
    const worstStatus =
      statusRank(d.status ?? 'checking') <= statusRank(cert?.status ?? 'valid')
        ? (d.status ?? 'checking')
        : (cert?.status ?? 'checking')

    // Last checked: most recent of the two
    const dChecked = d.last_checked ? new Date(d.last_checked).getTime() : 0
    const cChecked = cert?.last_checked ? new Date(cert.last_checked).getTime() : 0
    const lastChecked = dChecked >= cChecked ? d.last_checked : (cert?.last_checked ?? d.last_checked)

    // Warn threshold: sooner threshold (more sensitive)
    const warnThreshold = Math.min(d.warn_days, cert?.warn_days ?? d.warn_days)

    rows.push({
      id: d.id,
      domainName: d.domain,
      type: 'domain',
      expiryDate,
      daysRemaining,
      status: worstStatus,
      lastChecked,
      registrar: d.registrar,
      warnDays: d.warn_days,
      criticalDays: d.critical_days,
      warnThreshold,
      securityGrade: cert?.security_grade ?? null,
      securityScore: cert?.security_score ?? null,
      whoisExpiry: d.expiry_date,
      whoisDaysRemaining: d.days_remaining,
      sslExpiry: cert?.expiry_date ?? null,
      sslDaysRemaining: cert?.days_remaining ?? null,
    })
  }

  // SSL rows: only non-443 ports (port-443 are merged into domain rows above)
  for (const c of sslCerts.value) {
    if (c.port === 443) continue
    const name = c.domain ?? domainNameById.value[c.domain_id] ?? '—'
    rows.push({
      id: c.id,
      domainName: name,
      type: 'ssl',
      port: c.port,
      expiryDate: c.expiry_date,
      daysRemaining: c.days_remaining,
      status: c.status ?? 'checking',
      lastChecked: c.last_checked,
      issuer: c.issuer,
      domainId: c.domain_id,
      warnDays: c.warn_days,
      criticalDays: c.critical_days,
      warnThreshold: c.warn_days,
    })
  }

  // Service rows (read-only cross-reference)
  for (const s of serviceSsl.value) {
    rows.push({
      id: s.id,
      domainName: s.name,
      type: 'service',
      expiryDate: s.ssl_expiry_date,
      daysRemaining: s.ssl_days_remaining,
      status: s.ssl_status ?? 'checking',
      lastChecked: s.ssl_last_checked,
      issuer: s.ssl_issuer,
      serviceId: s.id,
      warnDays: s.ssl_warn_days,
      criticalDays: s.ssl_critical_days,
      warnThreshold: s.ssl_warn_days,
      securityGrade: s.security_grade ?? null,
      securityScore: s.security_score ?? null,
    })
  }

  return rows
})
```

Note: `statusRank` is defined later in the store (line ~214). Vue's `computed` resolves closures at runtime, so forward references within the store function body are fine.

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend && npx vue-tsc --noEmit 2>&1 | head -20
```

Expected: no output (no errors).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/sslDomains.ts
git commit -m "feat(ssl-domains): merge domain+SSL rows in store, restore service rows"
```

---

## Task 6: Frontend view — expiry subtitle, Security column, type filter, delete fix

**Files:**
- Modify: `frontend/src/views/ssl-domains/SslDomainsView.vue`

- [ ] **Step 1: Restore `useRouter` import and `router` instance**

In the script setup, restore:
```ts
import { useRouter } from 'vue-router'
// ...
const router = useRouter()
```

And restore `SecurityGrade` import:
```ts
import SecurityGrade from '@/components/SecurityGrade.vue'
```

- [ ] **Step 2: Update `trackedRows` to include all row types**

Replace:
```ts
const trackedRows = computed(() =>
  store.combinedRows.filter(r => r.type !== 'service')
)
```
With:
```ts
const trackedRows = computed(() => store.combinedRows)
```

- [ ] **Step 3: Update `summary` computed to use store-level counts**

Replace the `summary` computed body so it stays consistent with `trackedRows`:
```ts
const summary = computed(() => {
  const parts = [`${statTotal.value} items`]
  if (statCritical.value) parts.push(`${statCritical.value} critical`)
  if (statExpiring.value) parts.push(`${statExpiring.value} expiring`)
  return parts.join(' • ')
})
```

- [ ] **Step 4: Update `trackedTimelineDots` to include all row types**

Replace:
```ts
const trackedTimelineDots = computed(() =>
  store.timelineDots.filter(d => d.type !== 'service')
)
```
With:
```ts
const trackedTimelineDots = computed(() => store.timelineDots)
```

- [ ] **Step 5: Restore `security` sort key**

In the `sortKey` ref type union, add `'security'` back:
```ts
const sortKey = ref<'name' | 'type' | 'expiry' | 'days' | 'status' | 'security'>('expiry')
```

In the `sorted` computed switch-case, add back the security case:
```ts
case 'security':
  cmp = (b.securityScore ?? -1) - (a.securityScore ?? -1)
  break
```

- [ ] **Step 6: Restore Service option in type filter**

In the `typeFilter` type union:
```ts
const typeFilter = ref<'all' | 'domain' | 'ssl' | 'service'>('all')
```

In the template, add back the Service option:
```html
<option value="service">Service</option>
```

- [ ] **Step 7: Update expiry cell to show two-line subtitle for domain rows**

Find the expiry `<td>` in the table body. Replace:
```html
<td class="mono">{{ formatDate(r.expiryDate) }}</td>
```
With:
```html
<td class="mono">
  <template v-if="r.type === 'domain'">
    <div>{{ formatDate(r.expiryDate) }}</div>
    <div class="expiry-sub">
      <span v-if="r.sslDaysRemaining != null">SSL: {{ r.sslDaysRemaining }}d</span>
      <span v-else>SSL: pending</span>
      <span v-if="r.whoisDaysRemaining != null"> · WHOIS: {{ r.whoisDaysRemaining }}d</span>
    </div>
  </template>
  <template v-else>{{ formatDate(r.expiryDate) }}</template>
</td>
```

- [ ] **Step 8: Restore Security column header and cell**

In `<thead>`, add back after the Status column:
```html
<th class="col-security sortable" @click="toggleSort('security')">
  Security
  <span v-if="sortKey === 'security'" class="sort-arrow">{{ sortDir === 'asc' ? '↑' : '↓' }}</span>
</th>
```

In `<tbody>` rows, add the security cell after the status cell:
```html
<td class="col-security">
  <SecurityGrade
    v-if="r.type !== 'ssl'"
    :grade="r.securityGrade ?? null"
    :score="r.securityScore ?? null"
    size="sm"
  />
  <span v-else class="muted-dash">—</span>
</td>
```

- [ ] **Step 9: Update kebab menu for domain rows**

Find the kebab menu item for "Add SSL Cert". Change:
```html
<button v-if="r.type === 'domain' && !store.domainIdsWithCert.has(r.id)" class="kmi" @click="openAddSsl(r)">Add SSL Cert</button>
```
To (always visible for domain rows, renamed for clarity):
```html
<button v-if="r.type === 'domain'" class="kmi" @click="openAddSsl(r)">Add SSL (non-standard port)</button>
```

Also restore the service row kebab:
```html
<template v-if="r.type === 'service'">
  <button class="kmi" @click="router.push({ name: 'service-detail', params: { id: r.id } })">View in Services →</button>
</template>
```

- [ ] **Step 10: Update delete confirm message for domains**

Find the delete confirm modal for domains. Update the message to mention SSL cert cascade:
```html
<p class="mb-msg">This will permanently remove {{ confirm.name }} and its linked SSL certificate and check history.</p>
```

Also remove the `'blocked'` kind from the confirm state type and the `'blocked'` template block — domains now always delete cleanly:

In the reactive confirm state, change:
```ts
const confirm = reactive<{
  open: boolean
  kind: 'domain' | 'ssl'
  id: string
  name: string
}>({ open: false, kind: 'domain', id: '', name: '' })
```

In `askDelete`, remove:
```ts
if (r.type === 'domain') {
  if (store.domainIdsWithCert.has(r.id)) {
    confirm.kind = 'blocked'
  } else {
    confirm.kind = 'domain'
  }
```
Replace with:
```ts
if (r.type === 'domain') {
  confirm.kind = 'domain'
```

Remove the `<template v-if="confirm.kind === 'blocked'">` block from the modal.

- [ ] **Step 11: Add CSS for expiry subtitle and Security column**

In `<style scoped>`, add:
```css
.expiry-sub { font-size: 11px; color: var(--muted); margin-top: 2px; }
.col-security { width: 100px; text-align: center; cursor: pointer; }
.muted-dash { color: var(--muted); font-size: 13px; }
.sort-arrow { font-size: 10px; margin-left: 2px; }
```

- [ ] **Step 12: TypeScript check**

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend && npx vue-tsc --noEmit 2>&1 | head -20
```

Expected: no output.

- [ ] **Step 13: Smoke test in browser**

Open http://localhost:9090/ssl-domains. Verify:
1. Service rows appear with SSL expiry + security grade (read-only)
2. Domain rows show two-line expiry: primary date + `SSL: Xd · WHOIS: Yd` subtitle (once SSL check completes)
3. Security column visible with grade badge for domain/service rows, `—` for non-HTTP SSL
4. Type filter has Domain / SSL / Service options
5. Sorting by Security column works
6. "Add SSL (non-standard port)" appears in domain kebab
7. "View in Services →" appears in service kebab
8. Deleting a domain works without "SSL cert exists" error

- [ ] **Step 14: Commit**

```bash
git add frontend/src/views/ssl-domains/SslDomainsView.vue
git commit -m "feat(ssl-domains): merged domain row with expiry subtitle, security column, service rows restored"
```
