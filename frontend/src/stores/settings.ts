import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'
import type { Session, TeamMember, PendingInvite, RotationServer } from '@/types'

export const useSettingsStore = defineStore('settings', () => {
  const general = ref({ instanceName: 'OpsPilot', baseUrl: '', timezone: 'UTC' })
  const smtp = ref({
    host: '',
    port: 587,
    encryption: 'tls' as 'none' | 'tls' | 'ssl',
    username: '',
    fromAddress: '',
    recipients: '',
    hasPassword: false,
  })
  const retention = ref({
    metricsRetentionDays: 30,
    logsRetentionDays: 30,
    serviceChecksRetentionDays: 90,
    alertsRetentionDays: 90,
  })
  const discord = ref({
    webhookUrl: '',
    enabled: false,
  })
  const sessions = ref<Session[]>([])
  const team = ref<{ members: TeamMember[]; pendingInvites: PendingInvite[] }>({
    members: [],
    pendingInvites: [],
  })
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  async function fetchSettings() {
    const { data } = await api.get('/api/settings')
    general.value = {
      instanceName: data.instance_name,
      baseUrl: data.base_url ?? '',
      timezone: data.timezone ?? 'UTC',
    }
    smtp.value = {
      host: data.smtp_host ?? '',
      port: data.smtp_port ?? 587,
      encryption: data.smtp_encryption,
      username: data.smtp_username ?? '',
      fromAddress: data.smtp_from_address ?? '',
      recipients: data.smtp_recipients ?? '',
      hasPassword: data.smtp_has_password,
    }
    retention.value = {
      metricsRetentionDays: data.metrics_retention_days,
      logsRetentionDays: data.logs_retention_days,
      serviceChecksRetentionDays: data.service_checks_retention_days,
      alertsRetentionDays: data.alerts_retention_days,
    }
    discord.value = {
      webhookUrl: data.discord_webhook_url ?? '',
      enabled: data.discord_enabled ?? false,
    }
  }

  async function saveGeneral(p: { instance_name: string; base_url: string; timezone: string }) {
    await api.patch('/api/settings', p)
    await fetchSettings()
  }
  async function saveSmtp(p: Record<string, unknown>) {
    await api.patch('/api/settings', p)
    await fetchSettings()
  }
  async function testSmtp() {
    const { data } = await api.post('/api/settings/smtp/test')
    return data as { ok: boolean; sent_to: string }
  }
  async function saveRetention(p: Record<string, number>) {
    await api.patch('/api/settings', p)
    await fetchSettings()
  }
  async function saveDiscord(p: { discord_webhook_url: string; discord_enabled: boolean }) {
    await api.patch('/api/settings', p)
    await fetchSettings()
  }

  async function fetchSessions() {
    const { data } = await api.get('/api/sessions')
    sessions.value = data
  }
  async function revokeSession(jti: string) {
    await api.patch(`/api/sessions/${jti}/revoke`)
    await fetchSessions()
  }
  async function revokeAllOtherSessions() {
    await api.post('/api/sessions/revoke-others')
    await fetchSessions()
  }

  async function fetchTeam() {
    const { data } = await api.get('/api/team')
    team.value = { members: data.members, pendingInvites: data.pending_invites }
  }
  async function inviteMember(p: { email: string; org_id: string; role: string }) {
    await api.post('/api/invites', p)
    await fetchTeam()
  }
  async function addOrgAssignment(userId: string, p: { org_id: string; role: string }) {
    await api.post(`/api/users/${userId}/org-assignments`, p)
    await fetchTeam()
  }
  async function removeOrgAssignment(userId: string, orgId: string) {
    await api.delete(`/api/users/${userId}/org-assignments/${orgId}`)
    await fetchTeam()
  }
  async function removeMember(userId: string) {
    await api.delete(`/api/users/${userId}`)
    await fetchTeam()
  }
  async function resendInvite(inviteId: string) {
    await api.post(`/api/invites/${inviteId}/resend`)
    await fetchTeam()
  }
  async function revokeInvite(inviteId: string) {
    await api.delete(`/api/invites/${inviteId}`)
    await fetchTeam()
  }

  async function changePassword(p: { current_password: string; new_password: string }) {
    await api.patch('/api/auth/password', p)
  }

  // Option B: rotation progress via polling. Swap to WS subscribe in Phase 2 — callers unchanged.
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

  return {
    general,
    smtp,
    retention,
    discord,
    sessions,
    team,
    isLoading,
    error,
    fetchSettings,
    saveGeneral,
    saveSmtp,
    testSmtp,
    saveRetention,
    saveDiscord,
    fetchSessions,
    revokeSession,
    revokeAllOtherSessions,
    fetchTeam,
    inviteMember,
    addOrgAssignment,
    removeOrgAssignment,
    removeMember,
    resendInvite,
    revokeInvite,
    changePassword,
    rotateWriterPassword,
    pollRotation,
    retryRotationServer,
  }
})
