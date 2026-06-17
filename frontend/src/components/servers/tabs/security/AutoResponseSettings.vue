<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useSecurityActionsStore } from '@/stores/securityActions'
import { useAuthStore } from '@/stores/auth'
import { useNotify } from '@/composables/useNotify'

const props = defineProps<{ serverId: string }>()
const store = useSecurityActionsStore()
const auth = useAuthStore()
const notify = useNotify()
const ttl = ref(24)

onMounted(async () => {
  await store.fetchSettings(props.serverId)
  ttl.value = store.settings?.block_ttl_hours ?? 24
})

async function save(enabled: boolean) {
  try {
    await store.updateSettings(props.serverId, { auto_response_enabled: enabled, block_ttl_hours: ttl.value })
    notify.success(enabled ? 'Auto-response enabled for this server' : 'Auto-response disabled')
  } catch (e) { notify.error(e as Error) }
}
</script>

<template>
  <section class="ar-settings">
    <div class="ar-settings__row">
      <div>
        <h4>Auto-response</h4>
        <p class="muted">When ON, OpsPilot may block IPs, quarantine webshells, and kill malicious
          processes automatically on this server. High-impact actions still wait for your approval.</p>
      </div>
      <VaSwitch
        :model-value="store.settings?.auto_response_enabled ?? false"
        :disabled="!auth.isAdmin"
        @update:model-value="save($event)"
        size="small" />
    </div>
    <div v-if="store.settings?.auto_response_enabled" class="ar-settings__ttl">
      <label>Auto-block expires after</label>
      <VaInput v-model="ttl" type="number" :min="1" :max="720" :disabled="!auth.isAdmin"
               @blur="save(true)" class="ttl-input" /> <span class="muted">hours</span>
    </div>
  </section>
</template>

<style scoped>
.ar-settings { border: 1px solid var(--border, #2a3040); border-radius: 10px; padding: 14px 16px; }
.ar-settings__row { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.ar-settings h4 { margin: 0 0 4px; font-size: 0.95rem; }
.muted { color: var(--va-text-secondary, #9aa4b2); font-size: 0.8rem; margin: 0; }
.ar-settings__ttl { display: flex; align-items: center; gap: 8px; margin-top: 12px; }
.ttl-input { max-width: 90px; }
</style>
