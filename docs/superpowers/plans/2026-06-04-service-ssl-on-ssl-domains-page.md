# Service SSL on SSL & Domains Page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show HTTPS service SSL certs on the SSL & Domains page alongside manually-tracked domains and SSL certs, eliminating the need to register the same domain twice.

**Architecture:** Backend extends the existing `/api/organizations/:org_id/ssl-domains` endpoint to include a `service_ssl` list (HTTPS services with `ssl_enabled=true`). Frontend store adds `ServiceSslRec` type and merges service rows into `combinedRows` with `type: 'service'`. The view renders a read-only "SERVICE" badge row with a single "View in Services →" kebab action.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async — Vue 3 / Pinia / TypeScript

**Spec:** `docs/superpowers/specs/2026-06-04-ssl-in-http-probe-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/app/schemas/ssl_domains.py` | MODIFY | Add `ServiceSslOut` model; add `service_ssl` field to `SSLDomainsResponse` |
| `backend/app/routers/ssl_domains.py` | MODIFY | Query HTTPS services for org; include in response |
| `frontend/src/stores/sslDomains.ts` | MODIFY | `ServiceSslRec` type; `type: 'service'` on `CombinedRow`/`TimelineDot`; populate from fetch |
| `frontend/src/components/ssl-domains/ExpiryTimeline.vue` | MODIFY | Handle `type === 'service'` in tooltip label |
| `frontend/src/views/ssl-domains/SslDomainsView.vue` | MODIFY | SERVICE badge, filter option, read-only kebab, type guards |

---

## Task 1: Backend — Schema + Router

**Files:**
- Modify: `backend/app/schemas/ssl_domains.py`
- Modify: `backend/app/routers/ssl_domains.py`

- [ ] **Step 1.1: Add `ServiceSslOut` to `backend/app/schemas/ssl_domains.py`**

After the `SSLCertOut` class, add:

```python
class ServiceSslOut(BaseModel):
    id: UUID
    name: str
    url: str
    ssl_status: str | None
    ssl_expiry_date: datetime | None
    ssl_days_remaining: int | None
    ssl_issuer: str | None
    ssl_last_checked: datetime | None
    ssl_warn_days: int
    ssl_critical_days: int

    model_config = {"from_attributes": True}
```

- [ ] **Step 1.2: Add `service_ssl` field to `SSLDomainsResponse`**

Replace:
```python
class SSLDomainsResponse(BaseModel):
    domains: list[DomainOut]
    ssl_certs: list[SSLCertOut]
```

With:
```python
class SSLDomainsResponse(BaseModel):
    domains: list[DomainOut]
    ssl_certs: list[SSLCertOut]
    service_ssl: list[ServiceSslOut]
```

- [ ] **Step 1.3: Update imports in `backend/app/routers/ssl_domains.py`**

Change:
```python
from app.models.other import Alert, Domain, SSLCert
```

To:
```python
from app.models.other import Alert, Domain, Service, SSLCert
from app.models.server import Server
```

Also update the schema import to include `ServiceSslOut`:
```python
from app.schemas.ssl_domains import (
    DomainCreate,
    DomainOut,
    DomainUpdate,
    ServiceSslOut,
    SSLCertCreate,
    SSLCertOut,
    SSLCertUpdate,
    SSLDomainsResponse,
)
```

- [ ] **Step 1.4: Extend `list_ssl_domains` to include service SSL**

Replace the existing return block:
```python
    return SSLDomainsResponse(
        domains=[_domain_out(d) for d in domains],
        ssl_certs=[_ssl_out(c, domain_name_by_id.get(c.domain_id)) for c in ssl_certs],
    )
```

With:
```python
    # Fetch HTTPS services for this org
    server_ids_result = await db.execute(
        select(Server.id).where(Server.org_id == org_id)
    )
    server_ids = [str(sid) for sid in server_ids_result.scalars().all()]
    service_ssl_rows: list[Service] = []
    if server_ids:
        service_ssl_rows = (
            await db.execute(
                select(Service).where(
                    Service.server_id.in_(server_ids),
                    Service.ssl_enabled == True,  # noqa: E712
                )
            )
        ).scalars().all()

    return SSLDomainsResponse(
        domains=[_domain_out(d) for d in domains],
        ssl_certs=[_ssl_out(c, domain_name_by_id.get(c.domain_id)) for c in ssl_certs],
        service_ssl=[ServiceSslOut.model_validate(s) for s in service_ssl_rows],
    )
```

- [ ] **Step 1.5: Smoke test backend**

```bash
docker compose restart backend
# Get a session cookie first, then:
curl -s http://localhost:8000/api/organizations/<org-id>/ssl-domains \
  -H "Cookie: session=<session-token>" | python3 -m json.tool | grep -A5 "service_ssl"
```

Expected: `"service_ssl": [...]` containing HTTPS services with ssl_* fields populated.

- [ ] **Step 1.6: Commit**

```bash
git add backend/app/schemas/ssl_domains.py backend/app/routers/ssl_domains.py
git commit -m "feat(ssl-domains): include https service ssl certs in ssl-domains api response"
```

---

## Task 2: Frontend Store

**Files:**
- Modify: `frontend/src/stores/sslDomains.ts`

- [ ] **Step 2.1: Add `ServiceSslRec` interface**

After the `SslCert` interface, add:

```typescript
export interface ServiceSslRec {
  id: string
  name: string
  url: string
  ssl_status: string | null
  ssl_expiry_date: string | null
  ssl_days_remaining: number | null
  ssl_issuer: string | null
  ssl_last_checked: string | null
  ssl_warn_days: number
  ssl_critical_days: number
}
```

- [ ] **Step 2.2: Update `SslDomainsResponse` interface**

```typescript
interface SslDomainsResponse {
  domains: DomainRec[]
  ssl_certs: SslCert[]
  service_ssl: ServiceSslRec[]
}
```

- [ ] **Step 2.3: Add `type: 'service'` to `CombinedRow` and add `serviceId` field**

```typescript
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
  serviceId?: string       // set for type === 'service'
  warnThreshold: number
}
```

- [ ] **Step 2.4: Add `type: 'service'` to `TimelineDot`**

```typescript
export interface TimelineDot {
  id: string
  type: 'domain' | 'ssl' | 'service'
  label: string
  expiryDate: string
  daysRemaining: number | null
  status: string
  issuer?: string | null
  registrar?: string | null
}
```

- [ ] **Step 2.5: Add `serviceSsl` state ref**

Inside `useSslDomainStore`, after `const sslCerts = ref<SslCert[]>([])`, add:

```typescript
const serviceSsl = ref<ServiceSslRec[]>([])
```

- [ ] **Step 2.6: Add service SSL rows to `combinedRows` computed**

After the `for (const c of sslCerts.value)` loop, add:

```typescript
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
      })
    }
```

- [ ] **Step 2.7: Populate `serviceSsl` in `fetchAll`**

```typescript
  async function fetchAll(orgId: string): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      const { data } = await api.get<SslDomainsResponse>(
        `/api/organizations/${orgId}/ssl-domains`,
      )
      domains.value = data.domains
      sslCerts.value = data.ssl_certs
      serviceSsl.value = data.service_ssl ?? []
    } catch {
      error.value = 'Could not load SSL & domain data.'
    } finally {
      isLoading.value = false
    }
  }
```

- [ ] **Step 2.8: Verify TypeScript build passes**

```bash
cd frontend && npm run build 2>&1 | tail -5
```

Expected: `✓ built in ...s` with no errors.

- [ ] **Step 2.9: Commit**

```bash
git add frontend/src/stores/sslDomains.ts
git commit -m "feat(store): add service ssl rows to ssl-domains combined view"
```

---

## Task 3: Frontend — ExpiryTimeline + SslDomainsView

**Files:**
- Modify: `frontend/src/components/ssl-domains/ExpiryTimeline.vue`
- Modify: `frontend/src/views/ssl-domains/SslDomainsView.vue`

- [ ] **Step 3.1: Handle `type === 'service'` in `ExpiryTimeline.vue` tooltip**

Find:
```typescript
const kind = m.type === 'ssl' ? 'SSL Certificate' : 'Domain Registration'
```

Replace with:
```typescript
const kind = m.type === 'ssl' ? 'SSL Certificate' : m.type === 'service' ? 'Service SSL' : 'Domain Registration'
```

Find:
```typescript
const issuerLine = m.type === 'ssl'
  ? `<div class="tl-row">Issuer: ${escapeHtml(m.issuer ?? '—')}</div>`
  : `<div class="tl-row">Registrar: ${escapeHtml(m.registrar ?? '—')}</div>`
```

Replace with:
```typescript
const issuerLine = m.type === 'ssl' || m.type === 'service'
  ? `<div class="tl-row">Issuer: ${escapeHtml(m.issuer ?? '—')}</div>`
  : `<div class="tl-row">Registrar: ${escapeHtml(m.registrar ?? '—')}</div>`
```

- [ ] **Step 3.2: Add `useRouter` import to `SslDomainsView.vue`**

Find the existing import from `vue-router`:
```typescript
import { useRoute, useRouter } from 'vue-router'
```

If only `useRoute` is imported, add `useRouter`. Then add after the existing `const route = useRoute()` line:
```typescript
const router = useRouter()
```

- [ ] **Step 3.3: Update `typeFilter` type and dropdown**

Change:
```typescript
const typeFilter = ref<'all' | 'domain' | 'ssl'>('all')
```

To:
```typescript
const typeFilter = ref<'all' | 'domain' | 'ssl' | 'service'>('all')
```

In the template, find the type filter select:
```html
        <select v-model="typeFilter">
          <option value="all">All Types</option>
          <option value="domain">Domain</option>
          <option value="ssl">SSL</option>
        </select>
```

Replace with:
```html
        <select v-model="typeFilter">
          <option value="all">All Types</option>
          <option value="domain">Domain</option>
          <option value="ssl">SSL</option>
          <option value="service">Service</option>
        </select>
```

- [ ] **Step 3.4: Update `rowName` to handle service type**

```typescript
function rowName(r: CombinedRow): string {
  if (r.type === 'ssl') return `${r.domainName}:${r.port}`
  return r.domainName
}
```

(Service rows already use `name` as `domainName` — no change needed to the function body, but verify it handles service correctly.)

- [ ] **Step 3.5: Update type badge in template**

Find:
```html
<span class="type-badge" :class="r.type">{{ r.type === 'ssl' ? 'SSL' : 'Domain' }}</span>
```

Replace with:
```html
<span class="type-badge" :class="r.type">
  {{ r.type === 'ssl' ? 'SSL' : r.type === 'service' ? 'Service' : 'Domain' }}
</span>
```

- [ ] **Step 3.6: Update row highlight class**

Find:
```html
:class="{ highlight: highlightId === r.id, 'is-ssl': r.type === 'ssl' }"
```

Replace with:
```html
:class="{ highlight: highlightId === r.id, 'is-ssl': r.type === 'ssl' || r.type === 'service' }"
```

- [ ] **Step 3.7: Update kebab menu for service rows**

Find the kebab menu block:
```html
                <div v-if="openMenuId === r.id" class="kebab-menu">
                  <button class="kmi" @click="checkNow(r)">Check Now</button>
                  <button v-if="r.type === 'domain' && !store.domainIdsWithCert.has(r.id)" class="kmi" @click="openAddSsl(r)">Add SSL Cert</button>
                  <button class="kmi" @click="r.type === 'domain' ? openEditDomain(r) : openEditSsl(r)">Edit</button>
                  <div class="kmi-div"></div>
                  <button class="kmi danger" @click="askDelete(r)">Delete</button>
                </div>
```

Replace with:
```html
                <div v-if="openMenuId === r.id" class="kebab-menu">
                  <template v-if="r.type === 'service'">
                    <button class="kmi" @click="router.push(`/services/${r.serviceId}`)">View in Services →</button>
                  </template>
                  <template v-else>
                    <button class="kmi" @click="checkNow(r)">Check Now</button>
                    <button v-if="r.type === 'domain' && !store.domainIdsWithCert.has(r.id)" class="kmi" @click="openAddSsl(r)">Add SSL Cert</button>
                    <button class="kmi" @click="r.type === 'domain' ? openEditDomain(r) : openEditSsl(r)">Edit</button>
                    <div class="kmi-div"></div>
                    <button class="kmi danger" @click="askDelete(r)">Delete</button>
                  </template>
                </div>
```

- [ ] **Step 3.8: Add SERVICE type badge CSS**

In `<style scoped>`, after `.type-badge.ssl { ... }`, add:

```css
.type-badge.service { background: rgba(168,85,247,0.15); color: #c084fc; }
```

- [ ] **Step 3.9: Verify TypeScript build passes**

```bash
cd frontend && npm run build 2>&1 | tail -5
```

Expected: `✓ built in ...s` with no errors.

- [ ] **Step 3.10: Rebuild Docker container and smoke test in browser**

```bash
docker compose build frontend && docker compose up -d frontend
```

1. Open `http://localhost:9090/ssl-domains`
2. Confirm HTTPS services appear in the table with a purple "SERVICE" badge
3. Confirm expiry date, days left, issuer, status, and ExpiryBar show correctly
4. Confirm clicking ⋮ → "View in Services →" navigates to the service detail page
5. Confirm "Domain" and "SSL" rows still work (no regressions)
6. Confirm filter dropdown has "Service" option and filters correctly
7. Confirm timeline dots include service SSL dots (hover to see "Service SSL" tooltip kind)

- [ ] **Step 3.11: Commit**

```bash
git add \
  frontend/src/components/ssl-domains/ExpiryTimeline.vue \
  frontend/src/views/ssl-domains/SslDomainsView.vue
git commit -m "feat(ssl-domains): show https service ssl certs as read-only service rows"
git push origin main
```
