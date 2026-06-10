<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useOrgStore } from '@/stores/org'
import { useServerStore } from '@/stores/server'
import { useOnboardingStore, TOTAL_STEPS } from '@/stores/onboarding'
import { getApiError } from '@/services/api'
import OnboardingPanel from '@/components/servers/OnboardingPanel.vue'
import { PageHeader, StatusBadge } from '@/components/ui'
import type { Server } from '@/types'

const auth = useAuthStore()
const orgStore = useOrgStore()
const serverStore = useServerStore()
const onboarding = useOnboardingStore()
const route = useRoute()
const router = useRouter()

const showAddModal = ref(false)
const submitting = ref(false)
const errors = ref<Record<string, string>>({})
const editMode = ref(false)
const editingId = ref<string | null>(null)

const form = ref({
  name: '',
  host: '',
  ssh_port: 22,
  ssh_user: '',
  ssh_auth_type: 'password' as 'key' | 'password',
  ssh_key: '',
  ssh_password: '',
  tags: [] as string[],
})
const tagInput = ref('')
const showKey = ref(false)
const showManualInstall = ref(false)

const manualCmds = {
  repos: [
    'sudo install -d -m 0755 /etc/apt/keyrings',
    'curl -fsSL https://repos.influxdata.com/influxdata-archive.key | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/influxdata-archive.gpg',
    'echo "deb [signed-by=/etc/apt/keyrings/influxdata-archive.gpg] https://repos.influxdata.com/debian stable main" | sudo tee /etc/apt/sources.list.d/influxdata.list',
    'sudo apt-get update -y',
  ].join('\n'),
  telegraf: 'sudo apt-get install -y telegraf',
  telegrafDirect: [
    '# If apt-get update is slow (e.g. Debian 9 / many repos), install directly:',
    'curl -LO https://dl.influxdata.com/telegraf/releases/telegraf_1.33.1-1_amd64.deb',
    'sudo dpkg -i telegraf_1.33.1-1_amd64.deb',
  ].join('\n'),
  fluentbit: [
    'curl -fsSL https://packages.fluentbit.io/fluentbit.key | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/fluentbit.gpg',
    '. /etc/os-release',
    'echo "deb [signed-by=/etc/apt/keyrings/fluentbit.gpg] https://packages.fluentbit.io/${ID}/${VERSION_CODENAME} ${VERSION_CODENAME} main" | sudo tee /etc/apt/sources.list.d/fluent-bit.list',
    'sudo apt-get update -y && sudo apt-get install -y fluent-bit',
  ].join('\n'),
}

function copyCmd(text: string) {
  navigator.clipboard.writeText(text)
}

// ── Onboarding panel + per-card action menu ──────────────────────────────────
const panelServerId = ref<string | null>(null)
const panelServer = computed<Server | null>(
  () => serverStore.servers.find((s) => s.id === panelServerId.value) ?? null,
)
const openMenuId = ref<string | null>(null)
const subscribed = new Set<string>()

const filteredServers = computed(() => serverStore.servers)

interface OrgGroup {
  orgId: string
  orgName: string
  servers: Server[]
}

const groupedServers = computed<OrgGroup[]>(() => {
  if (orgStore.activeOrgId) return []
  const map = new Map<string, OrgGroup>()
  for (const s of serverStore.servers) {
    if (!map.has(s.org_id)) {
      const org = orgStore.orgs.find((o) => o.id === s.org_id)
      map.set(s.org_id, { orgId: s.org_id, orgName: org?.name ?? s.org_id, servers: [] })
    }
    map.get(s.org_id)!.servers.push(s)
  }
  return Array.from(map.values()).sort((a, b) => a.orgName.localeCompare(b.orgName))
})

const statusCounts = computed(() => {
  const counts = { online: 0, offline: 0, maintenance: 0, pending: 0 }
  for (const s of serverStore.servers) counts[s.status]++
  return counts
})

async function loadServers() {
  if (auth.isAdmin && !orgStore.activeOrgId) {
    await serverStore.fetchAll()
  } else if (orgStore.activeOrgId) {
    await serverStore.fetchByOrg(orgStore.activeOrgId)
  } else {
    serverStore.servers = []
  }
  syncSubscriptions()
}

/** Subscribe + hydrate onboarding state for every pending server on screen. */
function syncSubscriptions() {
  for (const s of serverStore.servers) {
    if (s.status === 'pending' && !subscribed.has(s.id)) {
      subscribed.add(s.id)
      onboarding.subscribe(s.id)
      void onboarding.hydrate(s.id)
    }
  }
}

onMounted(async () => {
  await loadServers()
  // Deep-link: /servers?onboarding=:server_id opens the panel directly.
  const deepLink = route.query.onboarding
  if (typeof deepLink === 'string') openPanel(deepLink)
})

watch(() => orgStore.activeOrgId, loadServers)
watch(() => serverStore.servers.length, syncSubscriptions)

onUnmounted(() => {
  for (const id of subscribed) onboarding.unsubscribe(id)
  subscribed.clear()
})

// When a server finishes onboarding, refresh the list so its status flips.
watch(
  () => serverStore.servers.map((s) => onboarding.states[s.id]?.outcome).join(','),
  (val, old) => {
    if (val !== old && val.includes('success')) void loadServers()
  },
)

// ── Onboarding panel controls ─────────────────────────────────────────────────
function openPanel(serverId: string) {
  panelServerId.value = serverId
  openMenuId.value = null
  if (!subscribed.has(serverId)) {
    subscribed.add(serverId)
    onboarding.subscribe(serverId)
  }
  void onboarding.hydrate(serverId)
  if (route.query.onboarding !== serverId) {
    router.replace({ query: { ...route.query, onboarding: serverId } })
  }
}

function closePanel() {
  panelServerId.value = null
  const q = { ...route.query }
  delete q.onboarding
  router.replace({ query: q })
}

async function retryOnboarding(serverId: string) {
  onboarding.reset(serverId)
  try {
    await serverStore.onboard(serverId)
  } catch {
    // 409 "in_progress" — a job is already running; live state will stream in.
  }
}

async function redeployAgents(serverId: string) {
  openMenuId.value = null
  try {
    await serverStore.redeploy(serverId)
    openPanel(serverId)
  } catch {
    /* 409 if already running */
  }
}

async function deleteServer(serverId: string) {
  const s = serverStore.servers.find((x) => x.id === serverId)
  if (!s) return
  if (!window.confirm(`Delete server "${s.name}"? This removes all its services, alerts, and metrics.`)) return
  openMenuId.value = null
  await serverStore.remove(serverId)
  if (panelServerId.value === serverId) closePanel()
}

// ── Add / Edit server form ────────────────────────────────────────────────────
function addTag() {
  const t = tagInput.value.trim()
  if (t && !form.value.tags.includes(t) && form.value.tags.length < 10) {
    form.value.tags.push(t.slice(0, 30))
  }
  tagInput.value = ''
}
function removeTag(t: string) { form.value.tags = form.value.tags.filter((x) => x !== t) }

function validate(): boolean {
  errors.value = {}
  if (!form.value.name.trim()) errors.value.name = 'Server name is required'
  if (!form.value.host.trim()) errors.value.host = 'IP address or hostname is required'
  else if (/\s/.test(form.value.host)) errors.value.host = 'Enter a valid IP address or hostname'
  if (form.value.ssh_port < 1 || form.value.ssh_port > 65535) errors.value.ssh_port = 'Enter a valid port number'
  if (!form.value.ssh_user.trim()) errors.value.ssh_user = 'SSH username is required'
  // On edit, credentials are optional (only re-validated if the admin enters new ones).
  const credRequired = !editMode.value
  if (form.value.ssh_auth_type === 'key') {
    if (form.value.ssh_key.trim()) {
      if (!form.value.ssh_key.trim().startsWith('-----BEGIN')) errors.value.ssh_key = 'Enter a valid PEM private key'
    } else if (credRequired) {
      errors.value.ssh_key = 'SSH private key is required'
    }
  } else {
    if (!form.value.ssh_password && credRequired) errors.value.ssh_password = 'SSH password is required'
  }
  return Object.keys(errors.value).length === 0
}

function resetForm() {
  form.value = { name: '', host: '', ssh_port: 22, ssh_user: '', ssh_auth_type: 'password', ssh_key: '', ssh_password: '', tags: [] }
  tagInput.value = ''
  errors.value = {}
}

function openAdd() {
  editMode.value = false
  editingId.value = null
  resetForm()
  showAddModal.value = true
}

function openEdit(s: Server) {
  editMode.value = true
  editingId.value = s.id
  resetForm()
  form.value.name = s.name
  form.value.host = s.host
  form.value.ssh_port = s.ssh_port
  form.value.ssh_user = s.ssh_user
  form.value.ssh_auth_type = s.ssh_auth_type
  form.value.tags = [...(s.tags ?? [])]
  openMenuId.value = null
  showAddModal.value = true
}

async function submit() {
  addTag() // flush any text still in the tag input before submitting
  if (!validate()) return
  submitting.value = true
  try {
    const payload: Record<string, unknown> = {
      name: form.value.name.trim(),
      host: form.value.host.trim(),
      ssh_port: form.value.ssh_port,
      ssh_user: form.value.ssh_user.trim(),
      ssh_auth_type: form.value.ssh_auth_type,
      tags: form.value.tags,
    }
    if (form.value.ssh_auth_type === 'key') {
      if (form.value.ssh_key.trim()) payload.ssh_key = form.value.ssh_key
    } else if (form.value.ssh_password) {
      payload.ssh_password = form.value.ssh_password
    }

    if (editMode.value && editingId.value) {
      await serverStore.update(editingId.value, payload)
      showAddModal.value = false
    } else {
      const targetOrg = orgStore.activeOrgId ?? orgStore.orgs[0]?.id
      if (!targetOrg) return
      const created = await serverStore.create(targetOrg, payload)
      showAddModal.value = false
      // Onboarding auto-starts on the backend — open the live panel.
      openPanel(created.id)
    }
  } catch (err) {
    errors.value._form = getApiError(err)?.message ?? 'Unable to save server.'
  } finally {
    submitting.value = false
  }
}

function handleFileUpload(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 16 * 1024) {
    errors.value.ssh_key = 'File too large (max 16 KB)'
    return
  }
  const reader = new FileReader()
  reader.onload = () => { form.value.ssh_key = String(reader.result ?? '') }
  reader.readAsText(file)
}

function relativeTime(iso: string | null): string {
  if (!iso) return 'never'
  const diff = Date.now() - new Date(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

// Onboarding outcome for a pending server's inline card.
function cardOutcome(serverId: string) {
  return onboarding.states[serverId]?.outcome ?? 'pending'
}

const pageTitle = computed(() =>
  orgStore.activeOrg
    ? `Servers — ${orgStore.activeOrg.name}`
    : auth.isAdmin
      ? 'Servers — All Organizations'
      : 'Servers',
)
const summaryText = computed(() => {
  const c = statusCounts.value
  const parts = [`${serverStore.servers.length} servers`]
  if (c.online) parts.push(`${c.online} online`)
  if (c.offline) parts.push(`${c.offline} offline`)
  if (c.maintenance) parts.push(`${c.maintenance} maintenance`)
  if (c.pending) parts.push(`${c.pending} pending`)
  return parts.join(' • ')
})
</script>

<template>
  <div class="page" @click="openMenuId = null">
    <PageHeader :title="pageTitle" :subtitle="summaryText">
      <template #actions>
        <button v-if="auth.isAdmin && orgStore.orgs.length > 0" class="primary" @click="openAdd">+ Add Server</button>
      </template>
    </PageHeader>

    <div v-if="orgStore.orgs.length === 0 && auth.isAdmin" class="empty">
      <div class="icon">🏢</div>
      <h2>Create an organization first</h2>
      <p>You need at least one organization before adding servers.</p>
      <router-link to="/organizations" class="primary">+ Create Organization</router-link>
    </div>

    <div v-else-if="serverStore.servers.length === 0" class="empty">
      <div class="icon">🖥</div>
      <h2 v-if="auth.isAdmin">No servers in {{ orgStore.activeOrg?.name ?? 'this view' }}</h2>
      <h2 v-else>No servers in this organization yet</h2>
      <p v-if="auth.isAdmin">Add your first server to start monitoring.</p>
      <p v-else>Ask your admin to add servers.</p>
      <button v-if="auth.isAdmin" class="primary" @click="openAdd">+ Add Server</button>
    </div>

    <template v-else-if="!orgStore.activeOrgId && auth.isAdmin">
      <div v-if="serverStore.servers.length === 0" class="empty">
        <div class="icon">🖥</div>
        <h2>No servers registered yet</h2>
        <p>Add a server inside an organization to get started.</p>
      </div>
      <template v-else>
        <div v-for="group in groupedServers" :key="group.orgId" class="org-section">
          <div class="org-section-head">
            <span class="org-section-name">{{ group.orgName }}</span>
            <span class="org-section-count">{{ group.servers.length }} server{{ group.servers.length !== 1 ? 's' : '' }}</span>
          </div>
          <div class="grid">
            <div v-for="s in group.servers" :key="s.id" class="card" :class="`status-${s.status}`" @click="router.push({ name: 'server-detail', params: { id: s.id } })">
              <div class="card-hd">
                <span v-if="s.status === 'pending' && cardOutcome(s.id) === 'failed'" class="hd-ico fail">✕</span>
                <span v-else-if="s.status === 'pending'" class="spinner"></span>
                <span v-else class="dot" :class="`dot-${s.status}`"></span>
                <span class="name">{{ s.name }}</span>
                <div v-if="auth.isAdmin" class="menu-wrap" @click.stop>
                  <button class="kebab" aria-label="Server actions" @click="openMenuId = openMenuId === s.id ? null : s.id">⋮</button>
                  <div v-if="openMenuId === s.id" class="kebab-menu">
                    <button class="kmi" @click="openPanel(s.id)">View Onboarding Log</button>
                    <button class="kmi" @click="redeployAgents(s.id)">Re-deploy Agents</button>
                    <button class="kmi" @click="openEdit(s)">Edit Server</button>
                    <div class="kmi-div"></div>
                    <button class="kmi danger" @click="deleteServer(s.id)">Delete</button>
                  </div>
                </div>
              </div>
              <div class="host">{{ s.host }}</div>
              <template v-if="s.status === 'pending'">
                <div v-if="cardOutcome(s.id) === 'failed'" class="ob ob-fail">
                  <div class="ob-row"><span class="ob-label">ONBOARDING FAILED</span></div>
                  <button class="ob-link fail" @click.stop="openPanel(s.id)">View Error →</button>
                </div>
                <div v-else class="ob">
                  <div class="ob-row">
                    <span class="ob-label">ONBOARDING</span>
                    <span class="ob-step mono">Step {{ onboarding.currentStepNumber(s.id) }} of {{ TOTAL_STEPS }}</span>
                  </div>
                  <div class="ob-running">{{ onboarding.runningLabel(s.id) || 'Starting…' }}</div>
                  <div class="bar"><div class="bar-fill" :style="{ width: onboarding.progressPct(s.id) + '%' }"></div></div>
                  <button class="ob-link" @click.stop="openPanel(s.id)">View Progress →</button>
                </div>
              </template>
              <template v-else>
                <div class="meta">{{ s.os_distro ?? '—' }}</div>
                <div class="footer">
                  <StatusBadge kind="server" :status="s.status" />
                  <span class="time">{{ relativeTime(s.last_seen_at) }}</span>
                </div>
              </template>
              <div v-if="s.tags && s.tags.length" class="tags">
                <span v-for="t in s.tags" :key="t" class="tag">{{ t }}</span>
              </div>
            </div>
          </div>
        </div>
      </template>
    </template>

    <div v-else class="grid">
      <div v-for="s in filteredServers" :key="s.id" class="card" :class="`status-${s.status}`" @click="router.push({ name: 'server-detail', params: { id: s.id } })">
        <div class="card-hd">
          <span v-if="s.status === 'pending' && cardOutcome(s.id) === 'failed'" class="hd-ico fail">✕</span>
          <span v-else-if="s.status === 'pending'" class="spinner"></span>
          <span v-else class="dot" :class="`dot-${s.status}`"></span>
          <span class="name">{{ s.name }}</span>
          <div v-if="auth.isAdmin" class="menu-wrap" @click.stop>
            <button class="kebab" aria-label="Server actions" @click="openMenuId = openMenuId === s.id ? null : s.id">⋮</button>
            <div v-if="openMenuId === s.id" class="kebab-menu">
              <button class="kmi" @click="openPanel(s.id)">View Onboarding Log</button>
              <button class="kmi" @click="redeployAgents(s.id)">Re-deploy Agents</button>
              <button class="kmi" @click="openEdit(s)">Edit Server</button>
              <div class="kmi-div"></div>
              <button class="kmi danger" @click="deleteServer(s.id)">Delete</button>
            </div>
          </div>
        </div>
        <div class="host">{{ s.host }}</div>

        <!-- Onboarding inline state (pending servers) -->
        <template v-if="s.status === 'pending'">
          <div v-if="cardOutcome(s.id) === 'failed'" class="ob ob-fail">
            <div class="ob-row"><span class="ob-label">ONBOARDING FAILED</span></div>
            <button class="ob-link fail" @click.stop="openPanel(s.id)">View Error →</button>
          </div>
          <div v-else class="ob">
            <div class="ob-row">
              <span class="ob-label">ONBOARDING</span>
              <span class="ob-step mono">Step {{ onboarding.currentStepNumber(s.id) }} of {{ TOTAL_STEPS }}</span>
            </div>
            <div class="ob-running">{{ onboarding.runningLabel(s.id) || 'Starting…' }}</div>
            <div class="bar"><div class="bar-fill" :style="{ width: onboarding.progressPct(s.id) + '%' }"></div></div>
            <button class="ob-link" @click.stop="openPanel(s.id)">View Progress →</button>
          </div>
        </template>

        <!-- Normal footer (active servers) -->
        <template v-else>
          <div class="meta">{{ s.os_distro ?? '—' }}</div>
          <div class="footer">
            <StatusBadge kind="server" :status="s.status" />
            <span class="time">{{ relativeTime(s.last_seen_at) }}</span>
          </div>
        </template>

        <div v-if="s.tags && s.tags.length" class="tags">
          <span v-for="t in s.tags" :key="t" class="tag">{{ t }}</span>
        </div>
      </div>
    </div>

    <!-- Onboarding Panel -->
    <OnboardingPanel
      v-if="panelServer"
      :server="panelServer"
      @close="closePanel"
      @retry="retryOnboarding(panelServer.id)"
      @edit="openEdit(panelServer)"
      @delete="deleteServer(panelServer.id)"
      @view-dashboard="closePanel"
    />

    <!-- Add / Edit Server Modal -->
    <div v-if="showAddModal" class="modal-overlay" @click.self="showAddModal = false">
      <div class="modal">
        <div class="modal-hdr">
          <h2>{{ editMode ? 'Edit Server' : 'Add Server' }}</h2>
          <button class="close" @click="showAddModal = false">✕</button>
        </div>

        <form @submit.prevent="submit">
          <label>Display Name *</label>
          <input v-model="form.name" placeholder="e.g. web-01" :class="{ invalid: errors.name }" />
          <div v-if="errors.name" class="err">{{ errors.name }}</div>

          <label>IP Address / Hostname *</label>
          <input v-model="form.host" placeholder="e.g. 192.168.1.10" :class="{ invalid: errors.host }" />
          <div v-if="errors.host" class="err">{{ errors.host }}</div>

          <div class="form-row">
            <div class="col">
              <label>SSH Port *</label>
              <input v-model.number="form.ssh_port" type="number" :class="{ invalid: errors.ssh_port }" />
              <div v-if="errors.ssh_port" class="err">{{ errors.ssh_port }}</div>
            </div>
            <div class="col" style="flex: 2">
              <label>SSH Username *</label>
              <input v-model="form.ssh_user" placeholder="e.g. ubuntu" :class="{ invalid: errors.ssh_user }" />
              <small class="hint">Must have passwordless sudo (NOPASSWD)</small>
              <div v-if="errors.ssh_user" class="err">{{ errors.ssh_user }}</div>
            </div>
          </div>

          <label>SSH Authentication {{ editMode ? '' : '*' }}</label>
          <div class="radio-group">
            <label class="radio"><input v-model="form.ssh_auth_type" type="radio" value="key" /> Private Key</label>
            <label class="radio"><input v-model="form.ssh_auth_type" type="radio" value="password" /> Password</label>
          </div>

          <template v-if="form.ssh_auth_type === 'key'">
            <label>Private Key (PEM) {{ editMode ? '' : '*' }}</label>
            <textarea v-model="form.ssh_key" rows="5" :placeholder="editMode ? 'Leave blank to keep existing key' : '-----BEGIN OPENSSH PRIVATE KEY-----'" :class="{ invalid: errors.ssh_key }"></textarea>
            <input type="file" accept=".pem,.key,.txt" @change="handleFileUpload" class="file-input" />
            <div v-if="errors.ssh_key" class="err">{{ errors.ssh_key }}</div>
          </template>

          <template v-else>
            <label>SSH Password {{ editMode ? '' : '*' }}</label>
            <div class="pw-wrap">
              <input v-model="form.ssh_password" :type="showKey ? 'text' : 'password'" :placeholder="editMode ? 'Leave blank to keep existing password' : ''" :class="{ invalid: errors.ssh_password }" />
              <button type="button" class="eye" @click="showKey = !showKey">{{ showKey ? '🙈' : '👁' }}</button>
            </div>
            <div v-if="errors.ssh_password" class="err">{{ errors.ssh_password }}</div>
          </template>

          <label>Tags</label>
          <div class="tag-input">
            <span v-for="t in form.tags" :key="t" class="tag">
              {{ t }}<button type="button" @click="removeTag(t)">✕</button>
            </span>
            <input v-model="tagInput" placeholder="+ tag" @keydown.enter.prevent="addTag" @keydown.,.prevent="addTag" />
          </div>
          <small class="hint">Press Enter or comma to add a tag · Max 10 tags</small>

          <div v-if="errors._form" class="err">{{ errors._form }}</div>

          <!-- Manual installation guide (add mode only) -->
          <div v-if="!editMode" class="manual-install">
            <button type="button" class="manual-toggle" @click="showManualInstall = !showManualInstall">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
              Need to install packages manually?
              <span class="chev-sm">{{ showManualInstall ? '▲' : '▼' }}</span>
            </button>
            <div v-if="showManualInstall" class="manual-body">
              <p class="manual-note">Run these commands on the server before registering. OpsPilot will detect them and skip those steps automatically.</p>

              <div class="cmd-group">
                <div class="cmd-label">1. Add InfluxData repository <span class="os-badge">Debian / Ubuntu</span></div>
                <div class="cmd-block">
                  <pre>{{ manualCmds.repos }}</pre>
                  <button type="button" class="copy-btn" @click="copyCmd(manualCmds.repos)">Copy</button>
                </div>
              </div>

              <div class="cmd-group">
                <div class="cmd-label">2. Install Telegraf <span class="os-badge">via apt</span></div>
                <div class="cmd-block">
                  <pre>{{ manualCmds.telegraf }}</pre>
                  <button type="button" class="copy-btn" @click="copyCmd(manualCmds.telegraf)">Copy</button>
                </div>
              </div>

              <div class="cmd-group">
                <div class="cmd-label">2b. Install Telegraf <span class="os-badge">direct download — if apt is slow</span></div>
                <div class="cmd-block">
                  <pre>{{ manualCmds.telegrafDirect }}</pre>
                  <button type="button" class="copy-btn" @click="copyCmd(manualCmds.telegrafDirect)">Copy</button>
                </div>
              </div>

              <div class="cmd-group">
                <div class="cmd-label">3. Install Fluent Bit <span class="os-badge">Debian 10+ / Ubuntu 18+ only</span></div>
                <div class="cmd-block">
                  <pre>{{ manualCmds.fluentbit }}</pre>
                  <button type="button" class="copy-btn" @click="copyCmd(manualCmds.fluentbit)">Copy</button>
                </div>
              </div>
            </div>
          </div>

          <div class="actions">
            <button type="button" class="btn ghost" @click="showAddModal = false">Cancel</button>
            <button type="submit" class="primary" :disabled="submitting">
              <span v-if="submitting" class="spin"></span>
              <span v-else>{{ editMode ? 'Save Changes' : 'Add Server' }}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 28px; }
@media (max-width: 1023px) { .page { padding: 20px; } }
@media (max-width: 767px)  { .page { padding: 14px; } }
.empty { text-align: center; padding: 80px 20px; }
.empty .icon { font-size: 48px; margin-bottom: 12px; }
.empty h2 { font-size: 18px; color: #fff; margin-bottom: 6px; }
.empty p { color: var(--muted); margin-bottom: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px; transition: border-color 0.15s; cursor: pointer; }
.card:hover { border-color: var(--accent); }
.card.status-online { border-color: rgba(34,197,94,0.3); }
.card.status-offline { border-color: rgba(239,68,68,0.3); }
.card-hd { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot-online { background: var(--green); box-shadow: 0 0 8px rgba(34,197,94,0.6); }
.dot-offline { background: var(--red); }
.dot-maintenance { background: var(--amber); }
.dot-pending { background: var(--grey); }
.hd-ico { width: 14px; flex-shrink: 0; text-align: center; font-weight: 700; }
.hd-ico.fail { color: var(--red); }
.spinner { width: 12px; height: 12px; border: 2px solid rgba(99,102,241,0.25); border-top-color: var(--accent-2); border-radius: 50%; animation: spin 0.7s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }
.name { font-weight: 600; color: #fff; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.host { font-size: 12px; color: var(--muted); font-family: ui-monospace, monospace; }
.meta { font-size: 11px; color: var(--muted); margin-top: 6px; }
.footer { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); }
.time { font-size: 11px; color: var(--muted); }
.mono { font-family: ui-monospace, monospace; }

/* Onboarding inline */
.ob { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); }
.ob-row { display: flex; justify-content: space-between; align-items: baseline; }
.ob-label { font-size: 10px; font-weight: 700; letter-spacing: 0.08em; color: var(--accent-2); }
.ob-fail .ob-label { color: var(--red); }
.ob-step { font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }
.ob-running { font-size: 12px; color: var(--text); margin: 6px 0 8px; }
.bar { height: 6px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }
.bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); border-radius: 3px; transition: width 0.3s ease-out; }

/* Manual install panel */
.manual-install { margin: 16px 0 4px; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.manual-toggle { width: 100%; display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: var(--surface-2); border: none; color: var(--muted); font-size: 12px; cursor: pointer; text-align: left; }
.manual-toggle:hover { color: var(--text); }
.manual-toggle .chev-sm { margin-left: auto; font-size: 9px; }
.manual-body { padding: 14px; display: flex; flex-direction: column; gap: 12px; background: var(--surface); }
.manual-note { font-size: 12px; color: var(--muted); margin: 0; line-height: 1.5; }
.cmd-group { display: flex; flex-direction: column; gap: 6px; }
.cmd-label { font-size: 11px; font-weight: 600; color: var(--text); display: flex; align-items: center; gap: 8px; }
.os-badge { font-size: 10px; font-weight: 400; color: var(--muted); background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 1px 6px; }
.cmd-block { position: relative; background: #0d0d0d; border: 1px solid var(--border); border-radius: 6px; }
.cmd-block pre { margin: 0; padding: 10px 70px 10px 12px; font-size: 11px; font-family: ui-monospace, monospace; color: #a8d8a8; white-space: pre-wrap; word-break: break-all; line-height: 1.6; }
.copy-btn { position: absolute; top: 6px; right: 6px; padding: 3px 10px; font-size: 11px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; color: var(--muted); cursor: pointer; }
.copy-btn:hover { color: var(--text); border-color: var(--accent); }
.ob-link { margin-top: 10px; background: none; border: none; color: var(--accent-2); font-size: 12px; cursor: pointer; padding: 0; font-weight: 600; }
.ob-link:hover { text-decoration: underline; }
.ob-link.fail { color: var(--red); }

/* Kebab menu */
.menu-wrap { position: relative; }
.kebab { background: none; border: none; color: var(--muted); font-size: 16px; cursor: pointer; padding: 2px 6px; border-radius: 6px; line-height: 1; }
.kebab:hover { background: var(--surface-2); color: var(--text); }
.kebab-menu { position: absolute; top: 100%; right: 0; margin-top: 4px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 4px 0; min-width: 180px; z-index: 50; box-shadow: 0 12px 30px rgba(0,0,0,0.4); }
.kmi { display: block; width: 100%; text-align: left; background: none; border: none; color: var(--text); font-size: 12px; padding: 8px 14px; cursor: pointer; }
.kmi:hover { background: rgba(99,102,241,0.1); color: var(--accent-2); }
.kmi.danger { color: #fca5a5; }
.kmi.danger:hover { background: rgba(239,68,68,0.1); color: var(--red); }
.kmi-div { height: 1px; background: var(--border); margin: 2px 0; }

.tags { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 4px; }
.tag { background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 2px 8px; font-size: 10px; color: var(--muted); }
.primary { padding: 9px 18px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 38px; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.btn { padding: 8px 16px; border-radius: 8px; font-size: 12px; cursor: pointer; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); }
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
.modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; width: 100%; max-width: 520px; max-height: 90vh; overflow-y: auto; }
.modal-hdr { padding: 18px 22px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
.modal-hdr h2 { font-size: 15px; color: #fff; }
.close { background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; }
form { padding: 20px 22px; }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; margin-top: 14px; }
input, textarea { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 13px; outline: none; font-family: inherit; }
textarea { font-family: monospace; font-size: 11px; }
input:focus, textarea:focus { border-color: var(--accent); }
input.invalid, textarea.invalid { border-color: var(--red); }
.form-row { display: flex; gap: 12px; align-items: flex-start; }
.col { flex: 1; }
.radio-group { display: flex; gap: 16px; padding: 6px 0; }
.radio { display: flex; align-items: center; gap: 6px; color: var(--text); font-size: 13px; cursor: pointer; }
.pw-wrap { position: relative; }
.pw-wrap input { padding-right: 40px; }
.eye { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); background: none; border: none; color: var(--muted); cursor: pointer; font-size: 14px; padding: 4px; }
.tag-input { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.tag-input .tag { display: flex; align-items: center; gap: 6px; }
.tag-input .tag button { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 10px; padding: 0; }
.tag-input input { flex: 1; min-width: 80px; background: none; border: none; padding: 4px; color: var(--text); font-size: 12px; outline: none; }
.file-input { margin-top: 8px; font-size: 12px; color: var(--muted); }
.hint { font-size: 11px; color: var(--muted); margin-top: 4px; display: block; }
.err { color: var(--red); font-size: 11px; margin-top: 6px; }
.actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 22px; padding-top: 14px; border-top: 1px solid var(--border); }
.spin { width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }

.org-section { margin-bottom: 28px; }
.org-section-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}
.org-section-name { font-size: 14px; font-weight: 600; color: #fff; }
.org-section-count { font-size: 12px; color: var(--muted); }
</style>
