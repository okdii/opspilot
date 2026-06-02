<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useOrgStore } from '@/stores/org'
import { getApiError } from '@/services/api'
import type { Organization, OrgStats } from '@/types'

const orgStore = useOrgStore()
const stats = ref<Record<string, OrgStats>>({})
const showModal = ref(false)
const modalMode = ref<'create' | 'edit'>('create')
const editingOrg = ref<Organization | null>(null)
const deletingOrg = ref<Organization | null>(null)
const deleteBlocked = ref<{ servers: number; domains: number } | null>(null)
const deleteConfirmName = ref('')

const form = ref({ name: '', slug: '', description: '' })
const errors = ref<Record<string, string>>({})
const submitting = ref(false)

onMounted(async () => {
  await orgStore.fetchOrgs()
  for (const o of orgStore.orgs) {
    try {
      stats.value[o.id] = await orgStore.fetchStats(o.id)
    } catch { /* ignore */ }
  }
})

function autoSlug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9\s-]/g, '').replace(/\s+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '').slice(0, 50)
}

function openCreate() {
  modalMode.value = 'create'
  editingOrg.value = null
  form.value = { name: '', slug: '', description: '' }
  errors.value = {}
  showModal.value = true
}

function openEdit(org: Organization) {
  modalMode.value = 'edit'
  editingOrg.value = org
  form.value = { name: org.name, slug: org.slug, description: org.description ?? '' }
  errors.value = {}
  showModal.value = true
}

function validateForm(): boolean {
  errors.value = {}
  if (!form.value.name.trim()) errors.value.name = 'Organization name is required'
  else if (form.value.name.trim().length < 2) errors.value.name = 'Name must be at least 2 characters'
  if (!form.value.slug.trim()) errors.value.slug = 'Slug is required'
  else if (!/^[a-z0-9-]+$/.test(form.value.slug)) errors.value.slug = 'Slug can only contain lowercase letters, numbers, and hyphens'
  return Object.keys(errors.value).length === 0
}

let slugTouched = false
function onNameInput() {
  if (modalMode.value === 'create' && !slugTouched) {
    form.value.slug = autoSlug(form.value.name)
  }
}
function onSlugInput() { slugTouched = true }

async function submit() {
  if (!validateForm()) return
  submitting.value = true
  try {
    if (modalMode.value === 'create') {
      const created = await orgStore.createOrg({
        name: form.value.name.trim(),
        slug: form.value.slug.trim(),
        description: form.value.description.trim() || undefined,
      })
      stats.value[created.id] = { server_count: 0, domain_count: 0, member_count: 0 }
    } else if (editingOrg.value) {
      await orgStore.updateOrg(editingOrg.value.id, {
        name: form.value.name.trim(),
        description: form.value.description.trim() || undefined,
      })
    }
    showModal.value = false
  } catch (err) {
    const api = getApiError(err)
    if (api?.error === 'slug_taken') errors.value.slug = 'This slug is already taken'
    else errors.value._form = 'Unable to save. Please try again.'
  } finally {
    submitting.value = false
  }
}

async function attemptDelete(org: Organization) {
  const s = stats.value[org.id]
  if (s && (s.server_count > 0 || s.domain_count > 0)) {
    deleteBlocked.value = { servers: s.server_count, domains: s.domain_count }
    deletingOrg.value = org
  } else {
    deletingOrg.value = org
    deleteBlocked.value = null
    deleteConfirmName.value = ''
  }
}

async function confirmDelete() {
  if (!deletingOrg.value) return
  try {
    await orgStore.deleteOrg(deletingOrg.value.id)
    delete stats.value[deletingOrg.value.id]
    deletingOrg.value = null
  } catch (err) {
    const api = getApiError(err)
    if (api?.error === 'has_resources') {
      deleteBlocked.value = { servers: Number(api.servers) || 0, domains: Number(api.domains) || 0 }
    }
  }
}
</script>

<template>
  <div class="page">
    <header class="hdr">
      <div>
        <h1>Organizations</h1>
        <p>Manage your client and team workspaces</p>
      </div>
      <button class="primary" @click="openCreate">+ New Organization</button>
    </header>

    <div v-if="orgStore.orgs.length === 0" class="empty">
      <div class="icon">🏢</div>
      <h2>No organizations yet</h2>
      <p>Create one to start adding servers.</p>
      <button class="primary" @click="openCreate">+ Create Organization</button>
    </div>

    <div v-else class="grid">
      <div v-for="o in orgStore.orgs" :key="o.id" class="card">
        <h3>{{ o.name }}</h3>
        <code class="slug">{{ o.slug }}</code>
        <div v-if="o.description" class="desc">{{ o.description }}</div>

        <div class="stats">
          <div><strong>{{ stats[o.id]?.server_count ?? '—' }}</strong> servers</div>
          <div><strong>{{ stats[o.id]?.domain_count ?? '—' }}</strong> domains</div>
          <div><strong>{{ stats[o.id]?.member_count ?? '—' }}</strong> members</div>
        </div>

        <div class="actions">
          <button class="btn ghost" @click="openEdit(o)">Edit</button>
          <button class="btn danger" @click="attemptDelete(o)">Delete</button>
        </div>
      </div>
    </div>

    <!-- Create/Edit Modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
      <div class="modal">
        <div class="modal-hdr">
          <h2>{{ modalMode === 'create' ? 'Create Organization' : 'Edit Organization' }}</h2>
          <button class="close" @click="showModal = false">✕</button>
        </div>

        <form @submit.prevent="submit">
          <label>Name *</label>
          <input v-model="form.name" placeholder="e.g. Acme Corp" :class="{ invalid: errors.name }" @input="onNameInput" />
          <div v-if="errors.name" class="err">{{ errors.name }}</div>

          <label>Slug *</label>
          <input v-model="form.slug" :disabled="modalMode === 'edit'" placeholder="acme-corp" :class="{ invalid: errors.slug }" @input="onSlugInput" />
          <small class="hint">{{ modalMode === 'edit' ? '🔒 Slug cannot be changed after creation' : 'Auto-generated. Locked after creation.' }}</small>
          <div v-if="errors.slug" class="err">{{ errors.slug }}</div>

          <label>Description</label>
          <textarea v-model="form.description" rows="3" placeholder="(optional)"></textarea>

          <div v-if="errors._form" class="err">{{ errors._form }}</div>

          <div class="actions">
            <button type="button" class="btn ghost" @click="showModal = false">Cancel</button>
            <button type="submit" class="primary" :disabled="submitting">
              <span v-if="submitting" class="spin"></span>
              <span v-else>{{ modalMode === 'create' ? 'Create Organization' : 'Save Changes' }}</span>
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Delete Modal -->
    <div v-if="deletingOrg" class="modal-overlay" @click.self="deletingOrg = null">
      <div class="modal">
        <div class="modal-hdr">
          <h2 v-if="deleteBlocked">Cannot delete "{{ deletingOrg.name }}"</h2>
          <h2 v-else>Delete "{{ deletingOrg.name }}"?</h2>
          <button class="close" @click="deletingOrg = null">✕</button>
        </div>

        <div v-if="deleteBlocked" class="modal-body">
          <div class="alert warning">
            ⚠ This organization still has:
            <ul>
              <li v-if="deleteBlocked.servers">{{ deleteBlocked.servers }} servers</li>
              <li v-if="deleteBlocked.domains">{{ deleteBlocked.domains }} domains</li>
            </ul>
            Remove or reassign all servers and domains before deleting.
          </div>
          <div class="actions">
            <button class="primary" @click="deletingOrg = null">OK</button>
          </div>
        </div>

        <div v-else class="modal-body">
          <p>This will also remove all team member assignments for this organization. This action cannot be undone.</p>
          <label>Type the organization name to confirm:</label>
          <input v-model="deleteConfirmName" />
          <div class="actions">
            <button class="btn ghost" @click="deletingOrg = null">Cancel</button>
            <button class="btn danger" :disabled="deleteConfirmName !== deletingOrg.name" @click="confirmDelete">Delete Organization</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 28px; }
.hdr { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }
.hdr h1 { font-size: 22px; color: #fff; letter-spacing: -0.3px; }
.hdr p { color: var(--muted); font-size: 13px; margin-top: 4px; }
.empty { text-align: center; padding: 80px 20px; }
.empty .icon { font-size: 48px; margin-bottom: 12px; }
.empty h2 { font-size: 18px; color: #fff; margin-bottom: 6px; }
.empty p { color: var(--muted); margin-bottom: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; transition: border-color 0.15s; }
.card:hover { border-color: var(--accent); }
.card h3 { font-size: 15px; color: #fff; margin-bottom: 6px; }
.slug { font-size: 11px; color: var(--muted); background: var(--surface-2); padding: 2px 8px; border-radius: 4px; font-family: monospace; }
.desc { font-size: 12px; color: var(--muted); margin-top: 10px; line-height: 1.5; }
.stats { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.stats strong { color: var(--text); font-weight: 600; }
.actions { display: flex; gap: 8px; margin-top: 14px; }
.btn { padding: 7px 14px; border-radius: 6px; font-size: 12px; cursor: pointer; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); font-weight: 500; }
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
.btn.danger { color: var(--red); border-color: rgba(239,68,68,0.4); background: rgba(239,68,68,0.08); }
.btn.danger:hover:not(:disabled) { background: rgba(239,68,68,0.18); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.primary { padding: 9px 18px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; min-height: 38px; gap: 8px; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
.modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; width: 100%; max-width: 480px; max-height: 90vh; overflow-y: auto; }
.modal-hdr { padding: 18px 22px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
.modal-hdr h2 { font-size: 15px; color: #fff; }
.close { background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; }
form, .modal-body { padding: 20px 22px; }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; margin-top: 14px; }
label:first-child { margin-top: 0; }
input, textarea { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 13px; outline: none; font-family: inherit; }
input:focus, textarea:focus { border-color: var(--accent); }
input:disabled { opacity: 0.6; cursor: not-allowed; }
input.invalid { border-color: var(--red); }
.hint { font-size: 11px; color: var(--muted); margin-top: 4px; display: block; }
.err { color: var(--red); font-size: 11px; margin-top: 6px; }
.alert.warning { background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.3); color: #fde68a; padding: 14px; border-radius: 8px; font-size: 13px; margin-bottom: 18px; }
.alert.warning ul { margin-top: 8px; padding-left: 18px; }
.alert.warning li { margin: 2px 0; }
.modal-body p { color: var(--muted); font-size: 13px; line-height: 1.5; margin-bottom: 8px; }
.modal-body .actions { justify-content: flex-end; margin-top: 18px; }
.spin { width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
