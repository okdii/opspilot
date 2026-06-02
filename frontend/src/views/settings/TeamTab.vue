<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '@/stores/settings'
import { useOrgStore } from '@/stores/org'
import { useNotify } from '@/composables/useNotify'
import { getApiError } from '@/services/api'
import { relativeFuture } from '@/utils/time'
import { EmptyState } from '@/components/ui'
import type { TeamMember } from '@/types'

const settings = useSettingsStore()
const orgStore = useOrgStore()
const notify = useNotify()
const { team } = storeToRefs(settings)

const loading = ref(true)
const openMenu = ref<string | null>(null)

onMounted(async () => {
  try {
    await Promise.all([settings.fetchTeam(), orgStore.fetchOrgs()])
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to load team.')
  } finally {
    loading.value = false
  }
})

function orgSummary(m: TeamMember): string {
  if (m.role === 'admin') return 'All organizations'
  if (!m.org_assignments.length) return '—'
  return m.org_assignments.map((a) => `${a.org_name} (${a.role})`).join(', ')
}

function toggleMenu(id: string) {
  openMenu.value = openMenu.value === id ? null : id
}

// ── Invite modal ─────────────────────────────────────────────────────────────
const showInvite = ref(false)
const inviteEmail = ref('')
const inviteOrg = ref('')
const inviteRole = ref<'operator' | 'viewer'>('operator')
const inviteError = ref('')
const inviteSubmitting = ref(false)

function openInvite() {
  inviteEmail.value = ''
  inviteOrg.value = orgStore.orgs[0]?.id ?? ''
  inviteRole.value = 'operator'
  inviteError.value = ''
  showInvite.value = true
}

async function submitInvite() {
  inviteError.value = ''
  if (!inviteEmail.value.includes('@')) {
    inviteError.value = 'Enter a valid email address.'
    return
  }
  if (!inviteOrg.value) {
    inviteError.value = 'Select an organisation.'
    return
  }
  inviteSubmitting.value = true
  try {
    await settings.inviteMember({ email: inviteEmail.value.trim(), org_id: inviteOrg.value, role: inviteRole.value })
    notify.success(`Invite sent to ${inviteEmail.value.trim()}.`)
    showInvite.value = false
  } catch (err) {
    inviteError.value = getApiError(err)?.message ?? 'Unable to send invite.'
  } finally {
    inviteSubmitting.value = false
  }
}

// ── Add to organisation modal ────────────────────────────────────────────────
const showAddOrg = ref(false)
const addOrgMember = ref<TeamMember | null>(null)
const addOrgId = ref('')
const addOrgRole = ref<'operator' | 'viewer'>('operator')
const addOrgError = ref('')
const addOrgSubmitting = ref(false)

const availableOrgs = computed(() => {
  if (!addOrgMember.value) return orgStore.orgs
  const taken = new Set(addOrgMember.value.org_assignments.map((a) => a.org_id))
  return orgStore.orgs.filter((o) => !taken.has(o.id))
})

function openAddOrg(m: TeamMember) {
  openMenu.value = null
  addOrgMember.value = m
  addOrgId.value = ''
  addOrgRole.value = 'operator'
  addOrgError.value = ''
  showAddOrg.value = true
}

async function submitAddOrg() {
  addOrgError.value = ''
  if (!addOrgId.value) {
    addOrgError.value = 'Select an organisation.'
    return
  }
  addOrgSubmitting.value = true
  try {
    await settings.addOrgAssignment(addOrgMember.value!.id, { org_id: addOrgId.value, role: addOrgRole.value })
    const orgName = orgStore.orgs.find((o) => o.id === addOrgId.value)?.name ?? 'organisation'
    notify.success(`${addOrgMember.value!.username} added to ${orgName} as ${addOrgRole.value}.`)
    showAddOrg.value = false
  } catch (err) {
    addOrgError.value = getApiError(err)?.message ?? 'Unable to add to organisation.'
  } finally {
    addOrgSubmitting.value = false
  }
}

// ── Remove from organisation modal ───────────────────────────────────────────
const showRemoveOrg = ref(false)
const removeOrgMember = ref<TeamMember | null>(null)
const removeOrgId = ref('')

function openRemoveOrg(m: TeamMember) {
  openMenu.value = null
  removeOrgMember.value = m
  removeOrgId.value = m.org_assignments[0]?.org_id ?? ''
  showRemoveOrg.value = true
}

async function submitRemoveOrg() {
  if (!removeOrgId.value) return
  try {
    await settings.removeOrgAssignment(removeOrgMember.value!.id, removeOrgId.value)
    notify.success('Removed from organisation.')
    showRemoveOrg.value = false
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to remove from organisation.')
  }
}

// ── Remove from team ─────────────────────────────────────────────────────────
async function removeFromTeam(m: TeamMember) {
  openMenu.value = null
  if (!window.confirm(`Remove ${m.username} from the team? This deletes their account and all org assignments.`)) return
  try {
    await settings.removeMember(m.id)
    notify.success(`${m.username} removed from the team.`)
  } catch (err) {
    const api = getApiError(err)
    if (api?.error === 'sole_operator') {
      notify.error(api.message ?? 'This member is the only Operator for an organisation.')
    } else {
      notify.error(api ?? 'Unable to remove member.')
    }
  }
}

// ── Invite actions ───────────────────────────────────────────────────────────
async function resendInvite(id: string, email: string) {
  openMenu.value = null
  try {
    await settings.resendInvite(id)
    notify.success(`Invite resent to ${email}.`)
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to resend invite.')
  }
}

async function revokeInvite(id: string) {
  openMenu.value = null
  if (!window.confirm('Revoke this invite? The invite link will stop working.')) return
  try {
    await settings.revokeInvite(id)
    notify.success('Invite revoked.')
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to revoke invite.')
  }
}

function isExpired(iso: string): boolean {
  return new Date(iso).getTime() <= Date.now()
}
</script>

<template>
  <div class="team" @click="openMenu = null">
    <!-- Members -->
    <section class="card">
      <header class="card-head">
        <h2>Members</h2>
        <button class="primary sm" @click="openInvite">+ Invite Member</button>
      </header>

      <div v-if="loading" class="muted-row">Loading team…</div>
      <table v-else class="grid">
        <thead>
          <tr><th>Username</th><th>Role</th><th>Organisations</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="m in team.members" :key="m.id">
            <td class="strong">{{ m.username }}</td>
            <td><span class="badge" :class="m.role">{{ m.role === 'admin' ? 'Admin' : 'Member' }}</span></td>
            <td class="muted">{{ orgSummary(m) }}</td>
            <td class="right">
              <span v-if="m.role === 'admin'" class="dash">—</span>
              <div v-else class="menu-wrap" @click.stop>
                <button class="kebab" @click="toggleMenu(m.id)" aria-label="Actions">⋮</button>
                <div v-if="openMenu === m.id" class="menu">
                  <button @click="openAddOrg(m)">Add to Organisation</button>
                  <button :disabled="!m.org_assignments.length" @click="openRemoveOrg(m)">Remove from Organisation</button>
                  <button class="danger" @click="removeFromTeam(m)">Remove from Team</button>
                </div>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- Pending invites -->
    <section class="card">
      <h2>Pending Invites</h2>
      <div v-if="loading" class="muted-row">Loading…</div>
      <table v-else-if="team.pendingInvites.length" class="grid">
        <thead>
          <tr><th>Email</th><th>Organisation</th><th>Role</th><th>Expires</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="i in team.pendingInvites" :key="i.id">
            <td class="strong">{{ i.email }}</td>
            <td class="muted">{{ i.org_name }}</td>
            <td><span class="badge">{{ i.role }}</span></td>
            <td :class="isExpired(i.expires_at) ? 'expired' : 'muted'">{{ relativeFuture(i.expires_at) }}</td>
            <td class="right">
              <div class="menu-wrap" @click.stop>
                <button class="kebab" @click="toggleMenu('inv-' + i.id)" aria-label="Actions">⋮</button>
                <div v-if="openMenu === 'inv-' + i.id" class="menu">
                  <button @click="resendInvite(i.id, i.email)">Resend</button>
                  <button v-if="!isExpired(i.expires_at)" class="danger" @click="revokeInvite(i.id)">Revoke</button>
                </div>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-else title="No pending invites" message="Invite a teammate to get started." />
    </section>

    <!-- Invite modal -->
    <div v-if="showInvite" class="modal-overlay" @click.self="showInvite = false">
      <div class="modal">
        <div class="modal-hdr"><h2>Invite Member</h2><button class="x" @click="showInvite = false">✕</button></div>
        <div class="modal-body">
          <label>Email Address</label>
          <input v-model="inviteEmail" type="email" placeholder="teammate@example.com" />
          <label>Organisation</label>
          <select v-model="inviteOrg">
            <option v-for="o in orgStore.orgs" :key="o.id" :value="o.id">{{ o.name }}</option>
          </select>
          <label>Role</label>
          <div class="radios">
            <label class="radio"><input type="radio" value="operator" v-model="inviteRole" /> Operator</label>
            <label class="radio"><input type="radio" value="viewer" v-model="inviteRole" /> Viewer</label>
          </div>
          <div v-if="inviteError" class="err">{{ inviteError }}</div>
        </div>
        <div class="modal-ftr">
          <button class="ghost" @click="showInvite = false">Cancel</button>
          <button class="primary" :disabled="inviteSubmitting" @click="submitInvite">
            <span v-if="inviteSubmitting" class="spin"></span><span v-else>Send Invite</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Add to org modal -->
    <div v-if="showAddOrg" class="modal-overlay" @click.self="showAddOrg = false">
      <div class="modal">
        <div class="modal-hdr"><h2>Add to Organisation</h2><button class="x" @click="showAddOrg = false">✕</button></div>
        <div class="modal-body">
          <label>Organisation</label>
          <select v-model="addOrgId">
            <option value="" disabled>Select an organisation</option>
            <option v-for="o in availableOrgs" :key="o.id" :value="o.id">{{ o.name }}</option>
          </select>
          <p v-if="!availableOrgs.length" class="hint">This member is already in every organisation.</p>
          <label>Role</label>
          <div class="radios">
            <label class="radio"><input type="radio" value="operator" v-model="addOrgRole" /> Operator</label>
            <label class="radio"><input type="radio" value="viewer" v-model="addOrgRole" /> Viewer</label>
          </div>
          <div v-if="addOrgError" class="err">{{ addOrgError }}</div>
        </div>
        <div class="modal-ftr">
          <button class="ghost" @click="showAddOrg = false">Cancel</button>
          <button class="primary" :disabled="addOrgSubmitting || !availableOrgs.length" @click="submitAddOrg">
            <span v-if="addOrgSubmitting" class="spin"></span><span v-else>Add</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Remove from org modal -->
    <div v-if="showRemoveOrg" class="modal-overlay" @click.self="showRemoveOrg = false">
      <div class="modal">
        <div class="modal-hdr"><h2>Remove from Organisation</h2><button class="x" @click="showRemoveOrg = false">✕</button></div>
        <div class="modal-body">
          <label>Organisation</label>
          <select v-model="removeOrgId">
            <option v-for="a in removeOrgMember?.org_assignments ?? []" :key="a.org_id" :value="a.org_id">
              {{ a.org_name }} ({{ a.role }})
            </option>
          </select>
        </div>
        <div class="modal-ftr">
          <button class="ghost" @click="showRemoveOrg = false">Cancel</button>
          <button class="primary danger-btn" @click="submitRemoveOrg">Remove</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.team { display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 22px; }
.card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.card h2 { font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
.card-head h2 { margin: 0; }

.grid { width: 100%; border-collapse: collapse; font-size: 13px; }
.grid th { text-align: left; color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; padding: 8px 12px; border-bottom: 1px solid var(--border); }
.grid td { padding: 11px 12px; border-bottom: 1px solid rgba(255,255,255,0.04); color: var(--text); vertical-align: middle; }
.grid tr:last-child td { border-bottom: none; }
.grid .right { text-align: right; }
.strong { color: var(--text); font-weight: 500; }
.muted { color: var(--muted); }
.expired { color: var(--amber); }
.dash { color: var(--muted); }
.muted-row { color: var(--muted); font-size: 13px; padding: 8px 0; }

.badge { background: var(--surface-2); border: 1px solid var(--border); padding: 3px 10px; border-radius: 999px; font-size: 11px; text-transform: capitalize; color: var(--muted); }
.badge.admin { color: var(--accent-2); border-color: rgba(99,102,241,0.4); }

.menu-wrap { position: relative; display: inline-block; }
.kebab { background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; padding: 2px 8px; border-radius: 6px; line-height: 1; }
.kebab:hover { background: var(--surface-2); color: var(--text); }
.menu { position: absolute; right: 0; top: calc(100% + 4px); background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 4px 0; min-width: 190px; z-index: 50; box-shadow: 0 12px 30px rgba(0,0,0,0.4); }
.menu button { display: block; width: 100%; text-align: left; background: none; border: none; color: var(--text); font-size: 13px; padding: 8px 14px; cursor: pointer; }
.menu button:hover { background: rgba(99,102,241,0.1); color: var(--accent-2); }
.menu button:disabled { opacity: 0.4; cursor: not-allowed; }
.menu button.danger { color: #fca5a5; }
.menu button.danger:hover { background: rgba(239,68,68,0.12); color: #fca5a5; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
.modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; width: 100%; max-width: 460px; }
.modal-hdr { padding: 18px 22px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
.modal-hdr h2 { font-size: 15px; color: #fff; }
.x { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 14px; }
.modal-body { padding: 20px 22px; }
.modal-ftr { padding: 16px 22px; border-top: 1px solid var(--border); display: flex; justify-content: flex-end; gap: 10px; }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; margin-top: 14px; }
.modal-body label:first-child { margin-top: 0; }
input, select { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 14px; outline: none; }
input:focus, select:focus { border-color: var(--accent); }
.radios { display: flex; gap: 18px; }
.radio { display: flex; align-items: center; gap: 6px; margin: 0; color: var(--text); font-size: 13px; }
.radio input { width: auto; }
.hint { color: var(--muted); font-size: 12px; margin-top: 6px; }
.err { color: var(--red); font-size: 12px; margin-top: 12px; }
.primary { background: linear-gradient(90deg, var(--accent), var(--accent-2)); border: none; color: #fff; padding: 10px 20px; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; min-height: 40px; min-width: 110px; }
.primary.sm { padding: 8px 14px; min-height: 36px; min-width: 0; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.primary.danger-btn { background: var(--red); }
.ghost { background: var(--surface-2); border: 1px solid var(--border); color: var(--text); padding: 10px 18px; border-radius: 8px; font-size: 13px; cursor: pointer; }
.spin { width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
