import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/services/api'

// ── Types (co-located — spec 07 §12 / §13) ───────────────────────────────────

export interface DomainRec {
  id: string
  domain: string
  registrar: string | null
  expiry_date: string | null
  days_remaining: number | null
  warn_days: number
  critical_days: number
  last_checked: string | null
  status: string | null
}

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

export interface ServiceSslRec {
  id: string
  name: string
  url: string | null
  ssl_status: string | null
  ssl_expiry_date: string | null
  ssl_days_remaining: number | null
  ssl_issuer: string | null
  ssl_last_checked: string | null
  ssl_warn_days: number
  ssl_critical_days: number
  security_grade: string | null
  security_score: number | null
}

interface SslDomainsResponse {
  domains: DomainRec[]
  ssl_certs: SslCert[]
  service_ssl: ServiceSslRec[]
}

export interface CreateDomainPayload {
  org_id: string
  domain: string
  warn_days: number
  critical_days: number
}


export type ThresholdPayload = { warn_days?: number; critical_days?: number; port?: number }

/** A merged, table-ready row (spec 07 §12 CombinedRow). */
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
  // The threshold the bar/colour are measured against (warn_days).
  warnThreshold: number
  securityGrade?: string | null
  securityScore?: number | null
  // Subtitle data for merged domain rows (WHOIS + SSL)
  whoisExpiry?: string | null
  whoisDaysRemaining?: number | null
  sslExpiry?: string | null
  sslDaysRemaining?: number | null
}

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

// Status ranking so critical/expired float to top of the default sort.
const STATUS_RANK: Record<string, number> = {
  expired: 0,
  critical: 1,
  expiring_soon: 2,
  unreachable: 3,
  checking: 4,
  valid: 5,
}

export const useSslDomainStore = defineStore('sslDomains', () => {
  const domains = ref<DomainRec[]>([])
  const sslCerts = ref<SslCert[]>([])
  const serviceSsl = ref<ServiceSslRec[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // ── Getters ─────────────────────────────────────────────────────────────
  const domainNameById = computed<Record<string, string>>(() => {
    const m: Record<string, string> = {}
    for (const d of domains.value) m[d.id] = d.domain
    return m
  })

  /** Domains + certs merged, grouped by domain, default-sorted by expiry. */
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

  const criticalCount = computed(
    () => combinedRows.value.filter((r) => r.status === 'critical' || r.status === 'expired').length,
  )
  const expiringCount = computed(
    () => combinedRows.value.filter((r) => r.status === 'expiring_soon').length,
  )

  /** Dots for the scatter timeline — only items with a known expiry date. */
  const timelineDots = computed<TimelineDot[]>(() =>
    combinedRows.value
      .filter((r) => r.expiryDate)
      .map((r) => ({
        id: r.id,
        type: r.type,
        label: r.type === 'ssl' ? `${r.domainName}:${r.port}` : r.domainName,
        expiryDate: r.expiryDate as string,
        daysRemaining: r.daysRemaining,
        status: r.status,
        issuer: r.issuer,
        registrar: r.registrar,
      })),
  )

  /** Set of domain ids that already have an SSL cert (for "Add SSL" affordance). */
  const domainIdsWithCert = computed<Set<string>>(() => {
    const s = new Set<string>()
    for (const c of sslCerts.value) s.add(c.domain_id)
    return s
  })

  function statusRank(status: string): number {
    return STATUS_RANK[status] ?? 6
  }

  // ── Actions ─────────────────────────────────────────────────────────────
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

  async function addDomain(payload: CreateDomainPayload): Promise<DomainRec> {
    const { data } = await api.post<DomainRec>('/api/domains', payload)
    domains.value.push(data)
    return data
  }

async function updateDomain(id: string, payload: ThresholdPayload): Promise<DomainRec> {
    const { data } = await api.patch<DomainRec>(`/api/domains/${id}`, payload)
    const idx = domains.value.findIndex((d) => d.id === id)
    if (idx >= 0) domains.value[idx] = data
    return data
  }

  async function updateCert(id: string, payload: ThresholdPayload): Promise<SslCert> {
    const { data } = await api.patch<SslCert>(`/api/ssl-certs/${id}`, payload)
    const idx = sslCerts.value.findIndex((c) => c.id === id)
    if (idx >= 0) sslCerts.value[idx] = data
    return data
  }

  async function deleteDomain(id: string): Promise<void> {
    await api.delete(`/api/domains/${id}`)
    domains.value = domains.value.filter((d) => d.id !== id)
  }

  async function deleteCert(id: string): Promise<void> {
    await api.delete(`/api/ssl-certs/${id}`)
    sslCerts.value = sslCerts.value.filter((c) => c.id !== id)
  }

  /** Trigger an immediate background re-check. Throws on 429 (rate limited). */
  async function checkDomain(id: string): Promise<void> {
    await api.post(`/api/domains/${id}/check`)
  }

  async function checkCert(id: string): Promise<void> {
    await api.post(`/api/ssl-certs/${id}/check`)
  }

  /**
   * Poll the combined endpoint until the target record's last_checked is
   * non-null (spec 07 §6.3 — 10s interval, max 5 polls). Resolves either way.
   */
  async function pollUntilChecked(
    orgId: string,
    type: 'domain' | 'ssl',
    id: string,
    maxPolls = 5,
  ): Promise<boolean> {
    for (let i = 0; i < maxPolls; i++) {
      await new Promise((r) => setTimeout(r, 10_000))
      await fetchAll(orgId)
      const rec =
        type === 'domain'
          ? domains.value.find((d) => d.id === id)
          : sslCerts.value.find((c) => c.id === id)
      if (rec && rec.last_checked) return true
    }
    return false
  }

  function reset(): void {
    domains.value = []
    sslCerts.value = []
    serviceSsl.value = []
    isLoading.value = false
    error.value = null
  }

  return {
    domains,
    sslCerts,
    serviceSsl,
    isLoading,
    error,
    combinedRows,
    criticalCount,
    expiringCount,
    timelineDots,
    domainIdsWithCert,
    statusRank,
    fetchAll,
    addDomain,
    updateDomain,
    updateCert,
    deleteDomain,
    deleteCert,
    checkDomain,
    checkCert,
    pollUntilChecked,
    reset,
  }
})
