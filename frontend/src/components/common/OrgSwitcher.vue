<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useOrgStore } from '@/stores/org'
import { useAuthStore } from '@/stores/auth'

const orgStore = useOrgStore()
const auth = useAuthStore()
const open = ref(false)
const search = ref('')
const wrapper = ref<HTMLElement | null>(null)

const showSearch = computed(() => orgStore.orgs.length > 5)

const filtered = computed(() => {
  if (!search.value) return orgStore.orgs
  const q = search.value.toLowerCase()
  return orgStore.orgs.filter((o) => o.name.toLowerCase().includes(q))
})

function getRoleLabel(orgId: string): string {
  if (auth.isAdmin) return 'Admin'
  const r = auth.user?.orgs.find((o) => o.id === orgId)?.my_role
  return r ? r.charAt(0).toUpperCase() + r.slice(1) : ''
}

function pick(orgId: string | null) {
  orgStore.setActiveOrg(orgId)
  open.value = false
  search.value = ''
}

function handleClickOutside(e: MouseEvent) {
  if (wrapper.value && !wrapper.value.contains(e.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))
</script>

<template>
  <div ref="wrapper" class="org-switcher" :class="{ open }">
    <button class="trigger" @click="open = !open">
      <span class="icon">🏢</span>
      <span class="name">{{ orgStore.activeOrg?.name ?? (auth.isAdmin && !orgStore.activeOrgId ? 'All Organizations' : 'No organization') }}</span>
      <span class="chev">▾</span>
    </button>

    <div v-if="open" class="dropdown">
      <div v-if="showSearch" class="search">
        <input v-model="search" placeholder="🔍 Search organizations…" />
      </div>

      <div v-if="auth.isAdmin" class="item all" :class="{ active: !orgStore.activeOrgId }" @click="pick(null)">
        <span class="check">{{ !orgStore.activeOrgId ? '✓' : '' }}</span>
        <span>☁ All Organizations</span>
      </div>
      <div v-if="auth.isAdmin" class="divider"></div>

      <div
        v-for="o in filtered"
        :key="o.id"
        class="item"
        :class="{ active: orgStore.activeOrgId === o.id }"
        @click="pick(o.id)"
      >
        <span class="check">{{ orgStore.activeOrgId === o.id ? '✓' : '' }}</span>
        <span class="org-name">{{ o.name }}</span>
        <span class="role-badge">{{ getRoleLabel(o.id) }}</span>
      </div>

      <div v-if="auth.isAdmin" class="divider"></div>
      <router-link v-if="auth.isAdmin" to="/organizations" class="item create" @click="open = false">
        <span class="check">+</span><span>Manage Organizations</span>
      </router-link>
    </div>
  </div>
</template>

<style scoped>
.org-switcher { position: relative; padding: 0 12px; }
.trigger { width: 100%; display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; color: var(--text); cursor: pointer; font-size: 13px; transition: border-color 0.15s; }
.trigger:hover, .open .trigger { border-color: var(--accent); }
.icon { font-size: 14px; }
.name { flex: 1; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 500; }
.chev { color: var(--muted); font-size: 10px; }
.dropdown { position: absolute; top: calc(100% + 4px); left: 12px; right: 12px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 12px 30px rgba(0,0,0,0.4); z-index: 100; padding: 4px 0; max-height: 360px; overflow-y: auto; }
.search { padding: 8px; border-bottom: 1px solid var(--border); }
.search input { width: 100%; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; color: var(--text); font-size: 12px; outline: none; }
.item { display: flex; align-items: center; gap: 8px; padding: 8px 12px; cursor: pointer; font-size: 13px; color: var(--text); text-decoration: none; transition: background 0.1s; }
.item:hover { background: rgba(99,102,241,0.1); }
.item.active { color: var(--accent-2); }
.check { width: 14px; color: var(--accent-2); font-size: 12px; }
.org-name { flex: 1; }
.role-badge { font-size: 10px; color: var(--muted); background: var(--surface); padding: 2px 8px; border-radius: 999px; }
.divider { height: 1px; background: var(--border); margin: 2px 0; }
.create { color: var(--accent-2); }
.create .check { color: var(--accent-2); }
</style>
